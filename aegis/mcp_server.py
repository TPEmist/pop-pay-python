import os
import json
import asyncio
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
from aegis.core.models import PaymentIntent, GuardrailPolicy
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.providers.stripe_real import StripeIssuingProvider
from aegis.providers.byoc_local import LocalVaultProvider
from aegis.client import AegisClient

mcp = FastMCP("Aegis-Vault")

# ---------------------------------------------------------------------------
# Load configuration from environment
# ---------------------------------------------------------------------------
allowed_categories = json.loads(os.getenv("AEGIS_ALLOWED_CATEGORIES", '["aws", "cloudflare"]'))
max_per_tx   = float(os.getenv("AEGIS_MAX_PER_TX", "100.0"))
max_daily    = float(os.getenv("AEGIS_MAX_DAILY", "500.0"))
block_loops  = os.getenv("AEGIS_BLOCK_LOOPS", "true").lower() == "true"
stripe_key   = os.getenv("AEGIS_STRIPE_KEY")
cdp_url      = os.getenv("AEGIS_CDP_URL", "http://localhost:9222")
auto_inject  = os.getenv("AEGIS_AUTO_INJECT", "false").lower() == "true"
engine_type  = os.getenv("AEGIS_GUARDRAIL_ENGINE", "keyword").lower()
llm_api_key  = os.getenv("AEGIS_LLM_API_KEY", "")
llm_base_url = os.getenv("AEGIS_LLM_BASE_URL", None)
llm_model    = os.getenv("AEGIS_LLM_MODEL", "gpt-4o-mini")

policy = GuardrailPolicy(
    allowed_categories=allowed_categories,
    max_amount_per_tx=max_per_tx,
    max_daily_budget=max_daily,
    block_hallucination_loops=block_loops
)

if stripe_key:
    provider = StripeIssuingProvider(api_key=stripe_key)
elif os.getenv("AEGIS_BYOC_NUMBER"):
    provider = LocalVaultProvider()
else:
    provider = MockStripeProvider()

engine = None
if engine_type == "llm":
    from aegis.engine.llm_guardrails import LLMGuardrailEngine
    engine = LLMGuardrailEngine(
        api_key=llm_api_key,
        base_url=llm_base_url,
        model=llm_model,
        use_json_mode=True
    )

client = AegisClient(provider, policy, engine=engine)

# ---------------------------------------------------------------------------
# Optional: browser injector (only loaded when AEGIS_AUTO_INJECT=true)
# ---------------------------------------------------------------------------
injector = None
if auto_inject:
    try:
        from aegis.injector import AegisBrowserInjector
        injector = AegisBrowserInjector(client.state_tracker)
    except ImportError:
        pass  # playwright not installed — injector disabled silently


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------
@mcp.tool()
async def request_virtual_card(requested_amount: float, target_vendor: str, reasoning: str) -> str:
    """Request a one-time virtual credit card for an automated purchase.

    IMPORTANT USAGE RULES:
    - ONLY call this tool when you are currently on the FINAL checkout page
      and can visually see the credit card input fields in the browser.
    - DO NOT call this if you have not yet navigated to the checkout form.
    - DO NOT retry with a different reasoning if this tool returns a rejection.
    - If auto-injection is enabled (AEGIS_AUTO_INJECT=true), the card will be
      securely filled into the browser form automatically after approval —
      you only need to click the submit/pay button.
    """
    intent = PaymentIntent(
        agent_id="mcp-agent",
        requested_amount=requested_amount,
        target_vendor=target_vendor,
        reasoning=reasoning,
    )
    seal = await client.process_payment(intent)

    if seal.status.lower() == "rejected":
        return f"Payment rejected by guardrails. Reason: {seal.rejection_reason}"

    masked_card = f"****-****-****-{seal.card_number[-4:]}"

    # -------------------------------------------------------------------
    # Auto-injection path: if enabled, inject into the active browser tab
    # -------------------------------------------------------------------
    if injector is not None:
        injection_result = await injector.inject_payment_info(
            seal_id=seal.seal_id,
            cdp_url=cdp_url,
        )

        # inject_payment_info now returns a dict; support both dict and legacy bool
        if isinstance(injection_result, dict):
            card_filled    = injection_result.get("card_filled", False)
            billing_filled = injection_result.get("billing_filled", False)
        else:
            # backwards-compatible fallback if a custom injector returns a bool
            card_filled    = bool(injection_result)
            billing_filled = False

        if not card_filled:
            # Undo the seal — cancel the budget reservation
            client.state_tracker.mark_used(seal.seal_id)
            return (
                "Payment rejected. Error: Aegis could not find credit card input "
                "fields on your active browser tab. Please ensure you have navigated "
                "to the FINAL checkout form and the card fields are visible, then retry."
            )

        billing_note = (
            " Billing fields (name, address, email) were also filled automatically."
            if billing_filled
            else ""
        )
        return (
            f"Payment approved and securely auto-injected into the browser form."
            f"{billing_note} "
            f"Please proceed to click the submit/pay button. "
            f"Masked card: {masked_card}"
        )

    # -------------------------------------------------------------------
    # Standard path: return masked card details only
    # -------------------------------------------------------------------
    return (
        f"Payment approved. Card Issued: {masked_card}, "
        f"Expiry: {seal.expiration_date}, Amount: {seal.authorized_amount}"
    )


if __name__ == "__main__":
    mcp.run()
