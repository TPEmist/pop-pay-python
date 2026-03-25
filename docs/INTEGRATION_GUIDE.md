[English](./INTEGRATION_GUIDE.md) | [中文](./INTEGRATION_GUIDE.zh-TW.md)

# Aegis Integration Guide

> **For developers** who want to embed Aegis as the financial middleware in their agentic workflows.
> This guide covers four integration patterns: **Claude Code (BYOC + CDP injection)**, **Python SDK / gemini-cli**, **browser-agent middleware (Playwright / browser-use / Skyvern)**, and **OpenClaw/NemoClaw System Prompts**.

---

## 1. Claude Code — Full Setup with CDP Injection

This section covers the complete three-component setup for using Aegis with **Claude Code** (Hacker Edition / BYOC). Both MCPs share the same Chrome instance: Playwright MCP handles navigation while Aegis MCP injects card credentials directly into the DOM via CDP. The user can watch the entire flow live in the browser — the raw card number never enters Claude's context.

### Architecture

```
Chrome (--remote-debugging-port=9222)
├── Playwright MCP  ──→ agent uses for navigation
└── Aegis MCP       ──→ injects real card via CDP
         │
         └── Claude Code Agent (only sees ****-****-****-4242)
```

### Step 0 — Launch Chrome with CDP (must be done first, every session)

```bash
# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-aegis-profile

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-aegis-profile
```

> **Why `--user-data-dir`?** If Chrome is already running, a separate profile is required to open a new instance with CDP enabled. Without this flag, Chrome silently reuses the existing instance and CDP will not be available.

Verify that CDP is active:

```bash
curl http://localhost:9222/json/version
# Should return a JSON object with "Browser", "webSocketDebuggerUrl", etc.
```

**Recommended shell alias** (add to `~/.zshrc` or `~/.bashrc`):

```bash
# macOS
alias chrome-cdp='"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-aegis-profile'

# Linux
alias chrome-cdp='google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-aegis-profile'
```

> **Shortcut:** `aegis-launch` (included with `aegis-pay`) automates Step 0 and prints the exact `claude mcp add` commands for your machine. Run `aegis-launch --help` for options.

### Step 1 — Configure `.env`

Copy the provided example and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
AEGIS_BYOC_NUMBER=4111111111111111   # Your real card number
AEGIS_BYOC_CVV=123
AEGIS_BYOC_EXPIRY=12/27
AEGIS_BYOC_NAME=Your Name

# Policy settings
AEGIS_ALLOWED_CATEGORIES=["aws", "cloudflare", "openai"]
AEGIS_MAX_PER_TX=100.0
AEGIS_MAX_DAILY=500.0
AEGIS_BLOCK_LOOPS=true

# Optional: Billing fields for auto-fill (name, address, email)
# AEGIS_BILLING_FIRST_NAME=John
# AEGIS_BILLING_LAST_NAME=Doe
# AEGIS_BILLING_STREET=123 Main St
# AEGIS_BILLING_ZIP=10001
# AEGIS_BILLING_EMAIL=john@example.com

# Guardrail mode: "keyword" (default, zero-cost) or "llm" (deep semantic analysis)
# See "Guardrail Mode Configuration" below for the full comparison and LLM config options.
# AEGIS_GUARDRAIL_ENGINE=keyword
```

### Guardrail Mode Configuration

By default, Aegis uses the `keyword` engine — a zero-cost, zero-dependency check that blocks obvious hallucination loops and prompt injection phrases. For production or high-value workflows, switch to `llm` mode for deep semantic analysis of each payment reasoning.

| | `keyword` (default) | `llm` |
|---|---|---|
| **How it works** | Blocks requests whose `reasoning` string contains suspicious keywords (e.g. "retry", "failed again", "ignore previous instructions") | Sends the agent's `reasoning` to an LLM for deep semantic analysis |
| **What it catches** | Obvious loops, hallucination phrases, prompt injection attempts | Subtle off-topic purchases, logical inconsistencies, policy violations that keyword matching misses |
| **Cost** | Zero — no API calls, instant | One LLM call per `request_virtual_card` invocation |
| **Dependencies** | None | Any OpenAI-compatible endpoint |
| **Best for** | Development, low-risk workflows, cost-sensitive setups | Production, high-value transactions, untrusted agent pipelines |

**LLM mode:**

```bash
export AEGIS_GUARDRAIL_ENGINE=llm

# Option A: OpenAI
export AEGIS_LLM_API_KEY=sk-...
export AEGIS_LLM_MODEL=gpt-4o-mini          # default

# Option B: Local model via Ollama (free, private)
export AEGIS_LLM_BASE_URL=http://localhost:11434/v1
export AEGIS_LLM_MODEL=llama3.2
# AEGIS_LLM_API_KEY can be set to any non-empty string for Ollama

# Option C: Any OpenAI-compatible endpoint (OpenRouter, vLLM, LM Studio...)
export AEGIS_LLM_BASE_URL=https://openrouter.ai/api/v1
export AEGIS_LLM_API_KEY=sk-or-...
export AEGIS_LLM_MODEL=anthropic/claude-3-haiku
```

> **Tip:** Start with `keyword` during development. Switch to `llm` when moving to production or when the agent pipeline is handling real money or untrusted inputs.

### Step 2 — Add Aegis MCP to Claude Code

```bash
claude mcp add aegis -- uv run --project /path/to/Project-Aegis python -m aegis.mcp_server
```

> The `--project` flag tells `uv` which project directory to use, so the `.env` file and `aegis_state.db` are resolved relative to the correct location.

### Step 3 — Add Playwright MCP to Claude Code

```bash
claude mcp add playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> This connects Playwright MCP to the **same Chrome instance** you launched in Step 0. Both MCPs now share one browser window.

### Recommended System Prompt Addition

Add the following block to your Claude Code system prompt (or project `CLAUDE.md`):

```
Payment rules:
- Only call request_virtual_card when you can see credit card input fields on the current page
- After approval, the system auto-fills the card — just click submit
- Never manually type any card number or CVV
- If request_virtual_card is rejected, do not retry — report to user
```

### Full Session Checklist

1. `chrome-cdp` — launch Chrome with CDP
2. `curl http://localhost:9222/json/version` — verify CDP is up
3. Start Claude Code — both MCPs connect automatically
4. Give your agent a task involving a checkout page
5. Agent navigates via Playwright MCP, calls `request_virtual_card` via Aegis MCP
6. `AegisBrowserInjector` injects real card via CDP — agent only sees the masked number
7. Agent clicks submit; card is burned after use

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

### Pattern: LLM Guardrail Engine

To use the LLM guardrail engine directly in a Python script (e.g. for local Ollama inference), pass an `LLMGuardrailEngine` instance when constructing `AegisClient`:

```python
from aegis.engine.llm_guardrails import LLMGuardrailEngine

llm_engine = LLMGuardrailEngine(
    base_url="http://localhost:11434/v1",  # Ollama endpoint
    model="llama3.2",
    use_json_mode=False
)
client = AegisClient(
    provider=MockStripeProvider(),
    policy=policy,
    engine=llm_engine
)
```

Supported LLM providers:

| Provider | `base_url` | `model` |
|---|---|---|
| OpenAI (default) | *(not needed)* | `gpt-4o-mini` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.2` |
| vLLM / LM Studio | `http://localhost:8000/v1` | Your model name |
| OpenRouter | `https://openrouter.ai/api/v1` | `anthropic/claude-3-haiku` |
| Any OpenAI-compatible | Your endpoint URL | Your model name |

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
│  4. AegisBrowserInjector attaches to Chrome via CDP  │
│     (--remote-debugging-port=9222)                   │
│  5. Traverses cross-origin iframes (e.g. Stripe Elm.) │
│  6. Injects real card into DOM — NOT via page.fill()  │
│     (raw PAN handled only by trusted local process)   │
│  7. Agent clicks submit (only sees masked card number)│
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

## 4. OpenClaw / NemoClaw — System Prompt Configuration

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
      "AEGIS_BLOCK_LOOPS": "true",
      "AEGIS_GUARDRAIL_ENGINE": "llm",
      "AEGIS_LLM_API_KEY": "sk-your-openai-api-key"
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
# Guardrail mode: "keyword" (default) or "llm" — see §1 "Guardrail Mode Configuration" for options
export AEGIS_GUARDRAIL_ENGINE=llm
export AEGIS_LLM_API_KEY=sk-your-openai-api-key
```

> **NemoClaw tip:** The System Prompt fragment above is particularly critical in the NemoClaw context, since the agent has broader system-level permissions. Aegis becomes the last financial line of defense inside the sandbox.

---

## See Also

- [README.md](../README.md) — Main project overview and quick start
- [§1 Claude Code](#1-claude-code--full-setup-with-cdp-injection) — Full BYOC + CDP injection setup (most common)
- [§2 Python SDK / gemini-cli](#2-gemini-cli--python-script-integration) — Direct SDK embedding and LangChain tool pattern
- [§3 Browser Agents](#3-browser-agent-middleware-playwright--browser-use--skyvern) — Playwright / browser-use / Skyvern integration
- [§4 OpenClaw / NemoClaw](#4-openclaw--nemoclaw--system-prompt-configuration) — System prompt configuration for OpenClaw and NemoClaw
- [examples/agent_vault_flow.py](../examples/agent_vault_flow.py) — Full Playwright browser injection example
- [examples/e2e_demo.py](../examples/e2e_demo.py) — SDK-only end-to-end demo (no browser)
- [CONTRIBUTING.md](../CONTRIBUTING.md) — How to add new payment providers or guardrail engines
