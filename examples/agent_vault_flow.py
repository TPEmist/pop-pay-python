"""
Point One Percent — Browser Agent + Vault Flow Example
========================================================
Demonstrates the full agent payment lifecycle using the Python SDK:

  1. Agent requests a virtual card via PopClient
  2. Point One Percent evaluates the intent against the guardrail policy
  3. On approval, the trusted local process injects real credentials
     into the browser form via Playwright — the agent only ever sees
     the masked card number

This example uses MockStripeProvider (no real money involved) and a
local HTML form to ensure the injection step always succeeds in demos.
For a real checkout page, replace `page.set_content(...)` with
`page.goto("https://checkout.example.com")` and adjust the selectors.

Run:
    uv run python examples/agent_vault_flow.py
"""

import asyncio

from playwright.async_api import async_playwright

from pop_pay.client import PopClient
from pop_pay.core.models import GuardrailPolicy, PaymentIntent
from pop_pay.providers.stripe_mock import MockStripeProvider

DIVIDER = "-" * 60


async def agent_workflow() -> None:
    # ------------------------------------------------------------------ #
    # 1. Initialise Point One Percent
    # ------------------------------------------------------------------ #
    policy = GuardrailPolicy(
        allowed_categories=["Donation", "SaaS", "Wikipedia"],
        max_amount_per_tx=30.0,
        max_daily_budget=50.0,
    )
    client = PopClient(
        provider=MockStripeProvider(),
        policy=policy,
        db_path="pop_state.db",
    )

    # ------------------------------------------------------------------ #
    # 2. Agent requests a virtual card
    # ------------------------------------------------------------------ #
    intent = PaymentIntent(
        agent_id="claude-agent-007",
        requested_amount=25.0,
        target_vendor="Wikipedia",
        reasoning="Support open knowledge via a one-time $25 donation.",
    )

    print(DIVIDER)
    print(f"[Agent]  Requesting ${intent.requested_amount:.2f} for {intent.target_vendor}")
    seal = await client.process_payment(intent)

    if seal.status.lower() == "rejected":
        print(f"[POP]    Rejected — {seal.rejection_reason}")
        return

    # The agent's context only ever sees the masked number, never the raw PAN
    print(f"[POP]    Approved  — Seal: {seal.seal_id}")
    print(f"[Agent]  Card in log : ****-****-****-{seal.card_number[-4:]}  (raw PAN protected)")

    # ------------------------------------------------------------------ #
    # 3. Trusted local process injects real credentials via Playwright
    #    This block runs outside the LLM context — the raw PAN is
    #    retrieved from the local DB and injected directly into the DOM.
    # ------------------------------------------------------------------ #
    print(f"\n[POP]    Launching secure browser session for credential injection...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Local test form — replace with page.goto(...) for a real checkout
        await page.set_content("""
            <html><body style="font-family:sans-serif;padding:2em">
              <h3>Checkout Form (local test)</h3>
              <input id="card_num" placeholder="Card Number" style="display:block;margin:8px 0">
              <input id="cvv"      placeholder="CVV"         style="display:block;margin:8px 0">
            </body></html>
        """)

        # Retrieve real credentials from the local vault (never from LLM output)
        details = client.state_tracker.get_seal_details(seal.seal_id)

        await page.fill("#card_num", details["card_number"])
        await page.fill("#cvv",      details["cvv"])

        screenshot_path = "agent_injection_proof.png"
        await page.screenshot(path=screenshot_path)
        print(f"[POP]    Injection complete. Screenshot saved: {screenshot_path}")

        # ---------------------------------------------------------------- #
        # 4. Vault audit
        # ---------------------------------------------------------------- #
        spent = client.state_tracker.daily_spend_total
        print(f"\n[Vault]  Daily spend : ${spent:.2f} / ${policy.max_daily_budget:.2f}")

        await asyncio.sleep(2)
        await browser.close()

    print(f"\n[Done]   Workflow complete. Raw card credentials never left the local process.")
    print(DIVIDER)


if __name__ == "__main__":
    asyncio.run(agent_workflow())
