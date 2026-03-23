# Aegis Integration Guide

> **For developers** who want to embed Aegis as the financial middleware in their agentic workflows.  
> This guide covers three integration patterns: **OpenClaw/NemoClaw System Prompts**, **direct Python SDK / gemini-cli**, and **browser-agent middleware (Playwright / browser-use / Skyvern)**.

---

## 1. OpenClaw / NemoClaw — System Prompt Configuration

The most important guardrail you can add is at the **System Prompt level**: instructing the agent that it *must* call Aegis before any payment action, rather than attempting to fill forms directly with real credentials.

### Recommended System Prompt Fragment

Add the following block to your OpenClaw or NemoClaw identity file (e.g., `IDENTITY.md` or the system prompt field in your agent config):

```markdown
## Financial Safety Protocol (REQUIRED)

You are operating under the Aegis Payment Guardrail Protocol. The following rules are NON-NEGOTIABLE:

1. **You MUST call the `request_virtual_card` MCP tool** before attempting any purchase,
   subscription, donation, API credit top-up, or any other financial transaction.

2. **Never use stored credit card numbers, PAN numbers, or any real payment credentials**
   found in your context, memory, or files. These are never provided to you.

3. **If `request_virtual_card` returns a rejection, STOP the payment flow immediately.**
   Do not retry with a different reasoning. Report the rejection reason to the user.

4. **If you find yourself in a loop** (retrying the same failed purchase more than once),
   you MUST stop and request human intervention rather than continuing.

5. The card number returned by Aegis will be masked (e.g., `****-****-****-4242`).
   Do NOT attempt to look up or reconstruct the full card number.
```

### OpenClaw: Registering Aegis as an MCP Tool

```bash
openclaw mcp add aegis -- uv run python -m aegis.mcp_server
```

Or add to `~/.openclaw/mcp_servers.json`:

```json
{
  "aegis": {
    "command": "uv",
    "args": ["run", "python", "-m", "aegis.mcp_server"],
    "cwd": "/path/to/Project-Aegis",
    "env": {
      "AEGIS_ALLOWED_CATEGORIES": "[\"aws\", \"cloudflare\", \"openai\", \"github\"]",
      "AEGIS_MAX_PER_TX": "100.0",
      "AEGIS_MAX_DAILY": "500.0",
      "AEGIS_BLOCK_LOOPS": "true"
    }
  }
}
```

### NemoClaw (NVIDIA Sandboxed): Additional Notes

NemoClaw's `OpenShell` runtime restricts write access to `/sandbox/` and `/tmp/`.

```bash
# Step 1: Clone Aegis inside the sandbox
nemoclaw my-assistant connect
cd /sandbox
git clone https://github.com/TPEmist/Project-Aegis.git
cd Project-Aegis && uv sync --all-extras

# Step 2: Register MCP server (while connected to sandbox)
openclaw mcp add aegis -- uv run python -m aegis.mcp_server

# Step 3: Set env vars (aegis_state.db will write to /sandbox/Project-Aegis/)
export AEGIS_ALLOWED_CATEGORIES='["aws", "openai"]'
export AEGIS_MAX_PER_TX=50.0
export AEGIS_MAX_DAILY=200.0
```

> **NemoClaw tip:** The System Prompt fragment above is particularly critical in the NemoClaw context, since the agent has broader system-level permissions. Aegis becomes the last financial line of defense inside the sandbox.

---

## 2. gemini-cli / Python Script Integration

For automation scripts that use `gemini-cli` or a raw Python agent loop, embed `AegisClient` directly as the payment middleware.

### Pattern: AegisClient as Script Middleware

```python
import asyncio
from aegis.client import AegisClient
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.core.models import GuardrailPolicy, PaymentIntent

async def run_automated_workflow():
    # 1. Initialize Aegis at the start of your script
    policy = GuardrailPolicy(
        allowed_categories=["SaaS", "API", "Cloud"],
        max_amount_per_tx=50.0,
        max_daily_budget=200.0,
        block_hallucination_loops=True
    )
    client = AegisClient(
        provider=MockStripeProvider(),  # swap for StripeIssuingProvider in prod
        policy=policy,
        db_path="aegis_state.db"
    )

    # 2. When your script needs to make a purchase, go through Aegis
    intent = PaymentIntent(
        agent_id="gemini-script-001",
        requested_amount=15.0,
        target_vendor="openai",
        reasoning="Topping up API credits to continue the data pipeline run."
    )

    seal = await client.process_payment(intent)

    if seal.status == "Rejected":
        print(f"🛑 Payment blocked: {seal.rejection_reason}")
        return  # halt script — do NOT proceed with a fallback

    print(f"✅ Approved. Seal: {seal.seal_id} | Card: ****-****-****-{seal.card_number[-4:]}")

    # 3. Use the seal_id to execute (burn-after-use enforced)
    result = await client.execute_payment(seal.seal_id, 15.0)
    print(f"Execution result: {result['status']}")

asyncio.run(run_automated_workflow())
```

### Pattern: LangChain Tool Call (for gemini-cli tool integration)

If your `gemini-cli` prompt uses tools, wrap Aegis as a LangChain `BaseTool`:

```python
from aegis.tools.langchain import AegisPaymentTool
from aegis.client import AegisClient
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.core.models import GuardrailPolicy

policy = GuardrailPolicy(
    allowed_categories=["SaaS", "API"],
    max_amount_per_tx=50.0,
    max_daily_budget=200.0,
    block_hallucination_loops=True
)
client = AegisClient(MockStripeProvider(), policy)

# Register as a tool in your agent's tool list
aegis_tool = AegisPaymentTool(client=client, agent_id="gemini-agent")

# The tool accepts: requested_amount, target_vendor, reasoning
result = await aegis_tool._arun(
    requested_amount=15.0,
    target_vendor="openai",
    reasoning="Need API credits to continue processing user request."
)
print(result)
# → "Payment approved. Card Issued: ****-****-****-4242, Expiry: 03/27, ..."
```

---

## 3. Browser Agent Middleware (Playwright / browser-use / Skyvern)

Browser agents that navigate real websites need to intercept the checkout flow and request a virtual card from Aegis *before* filling in any payment form.

### Architecture

```
┌──────────────────────────────────────────────────────┐
│                  Agent Orchestrator                   │
│  (OpenClaw / NemoClaw / custom asyncio loop)         │
└───────────────────────┬──────────────────────────────┘
                        │
          Navigates, finds checkout page
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│              Browser Agent Layer                      │
│  (Playwright, browser-use, Skyvern)                  │
│                                                       │
│  1. Detect payment form / paywall                     │
│  2. Extract: amount, vendor, context                  │
│  3. ─── PAUSE navigation ───────────────────────────►│
└───────────────────────┬──────────────────────────────┘
                        │  request_virtual_card(amount, vendor, reasoning)
                        ▼
┌──────────────────────────────────────────────────────┐
│                 Aegis (This library)                  │
│                                                       │
│  • GuardrailEngine: keyword + optional LLM check      │
│  • Budget enforcement: daily cap + per-tx limit       │
│  • VirtualSeal issued: one-time card, burn-after-use  │
│  • Returns: masked card number + seal_id             │
└───────────────────────┬──────────────────────────────┘
                        │  seal approved
                        ▼
┌──────────────────────────────────────────────────────┐
│              Browser Agent Layer (resumed)            │
│                                                       │
│  4. Trusted local process retrieves real card details │
│     (via state_tracker.get_seal_details — NOT the LLM)│
│  5. page.fill("#card_number", real_pan)               │
│  6. page.fill("#cvv", real_cvv)                       │
│  7. page.click("#submit")                             │
│  8. execute_payment(seal_id) → card burned            │
└──────────────────────────────────────────────────────┘
```

### Real Implementation Example (Playwright)

The following is a working implementation from [`examples/agent_vault_flow.py`](../examples/agent_vault_flow.py):

```python
import asyncio
from playwright.async_api import async_playwright
from aegis.client import AegisClient
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.core.models import PaymentIntent, GuardrailPolicy

async def browser_agent_with_aegis():
    # 1. Initialize Aegis
    policy = GuardrailPolicy(
        allowed_categories=["Donation", "SaaS", "Wikipedia"],
        max_amount_per_tx=30.0,
        max_daily_budget=50.0
    )
    client = AegisClient(MockStripeProvider(), policy, db_path="aegis_state.db")

    # 2. Browser agent detects a checkout form and requests authorization
    intent = PaymentIntent(
        agent_id="playwright-agent-001",
        requested_amount=25.0,
        target_vendor="Wikipedia",
        reasoning="I need to support open knowledge via a $25 donation."
    )
    seal = await client.process_payment(intent)

    if seal.status.lower() == "rejected":
        print(f"🛑 Aegis blocked payment: {seal.rejection_reason}")
        return  # browser agent stops — does NOT attempt to fill the form

    print(f"✅ Aegis approved. Seal: {seal.seal_id}")
    # The agent's context only sees the masked number — never the real PAN
    print(f"   Card in agent log: ****-****-****-{seal.card_number[-4:]}")

    # 3. Trusted local process fills the real credentials into the browser
    #    (This code runs in the local execution env, NOT inside the LLM context)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://donate.wikimedia.org/")

        # CRITICAL: Real card details retrieved from DB, never from LLM output
        details = client.state_tracker.get_seal_details(seal.seal_id)

        await page.fill("#card_number", details["card_number"])
        await page.fill("#cvv", details["cvv"])
        await page.fill("#expiry", details["expiration_date"])
        await page.click("#submit-donation")

    # 4. Mark seal as used (burn-after-use)
    await client.execute_payment(seal.seal_id, 25.0)
    print("🔥 Card burned. Transaction complete.")

asyncio.run(browser_agent_with_aegis())
```

### Adapting for browser-use / Skyvern

If you're using `browser-use` or Skyvern (which operate with higher-level visual reasoning), the pattern is identical — intercept before form submission:

```python
# Pseudo-code for browser-use integration
class AegisCheckoutInterceptor:
    def __init__(self, aegis_client: AegisClient):
        self.client = aegis_client

    async def on_checkout_detected(self, amount: float, vendor: str, context: str):
        """Called by browser-use when a payment form is detected."""
        intent = PaymentIntent(
            agent_id="browser-use-agent",
            requested_amount=amount,
            target_vendor=vendor,
            reasoning=context  # browser-use's visual description of why it's paying
        )
        seal = await self.client.process_payment(intent)

        if seal.status == "Rejected":
            raise PaymentBlockedError(f"Aegis rejected: {seal.rejection_reason}")

        return seal  # pass seal back to browser-use to complete checkout

    async def on_checkout_complete(self, seal_id: str, amount: float):
        """Called after browser-use successfully submits the form."""
        await self.client.execute_payment(seal_id, amount)
```

---

## See Also

- [README.md](../README.md) — Main project overview and quick start
- [examples/agent_vault_flow.py](../examples/agent_vault_flow.py) — Full Playwright browser injection example
- [examples/e2e_demo.py](../examples/e2e_demo.py) — SDK-only end-to-end demo (no browser)
- [CONTRIBUTING.md](../CONTRIBUTING.md) — How to add new payment providers or guardrail engines
