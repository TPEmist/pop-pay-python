# Point One Percent Integration Guide

> **For developers** who want to embed Point One Percent as the financial middleware in their agentic workflows.
> This guide covers four integration patterns: **Claude Code (BYOC + CDP injection)**, **Python SDK / gemini-cli**, **browser-agent middleware (Playwright / browser-use / Skyvern)**, and **OpenClaw/NemoClaw System Prompts**.

---

## 1. Claude Code — Full Setup with CDP Injection

This section covers the complete three-component setup for using Point One Percent with **Claude Code** (Hacker Edition / BYOC). Both MCPs share the same Chrome instance: Playwright MCP handles navigation while Point One Percent MCP injects card credentials directly into the DOM via CDP. The user can watch the entire flow live in the browser — the raw card number never enters Claude's context.

### Architecture

```
Chrome (--remote-debugging-port=9222)
├── Playwright MCP  ──→ agent uses for navigation
└── POP MCP         ──→ injects real card via CDP
         │
         └── Claude Code Agent (only sees ****-****-****-4242)
```

### Step 0 — Launch Chrome with CDP (must be done first, every session)

**Recommended — use `pop-launch`:**

```bash
pop-launch
```

`pop-launch` is included with `pop-pay`. It auto-discovers Chrome on your system, launches it with the correct CDP flags, waits until the port is ready, and then prints the exact `claude mcp add` commands for your machine. Run `pop-launch --help` for options (`--port`, `--url`, `--print-mcp`).

<details>
<summary>Manual alternative (if you prefer to launch Chrome yourself)</summary>

```bash
# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-pop-profile

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-pop-profile
```

> **Why `--user-data-dir`?** If Chrome is already running, a separate profile is required to open a new instance with CDP enabled. Without this flag, Chrome silently reuses the existing instance and CDP will not be available.

Verify that CDP is active:

```bash
curl http://localhost:9222/json/version
# Should return a JSON object with "Browser", "webSocketDebuggerUrl", etc.
```

**Shell alias** (add to `~/.zshrc` or `~/.bashrc`):

```bash
# macOS
alias chrome-cdp='"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-pop-profile'

# Linux
alias chrome-cdp='google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-pop-profile'
```

</details>

### Step 1a — Initialize the Credential Vault

Card credentials are stored in an **AES-256-GCM encrypted vault**, not in a plaintext file. Run once to set up:

```bash
pop-init-vault
```

You'll be prompted for your card number, CVV, expiry, and billing info (all input is hidden). Credentials are encrypted into `~/.config/pop-pay/vault.enc` and the MCP server decrypts them automatically at startup — nothing else to do per session.

**Passphrase mode** (stronger — protects against agents with shell execution):

```bash
pop-init-vault --passphrase   # one-time setup: derives key from your passphrase
pop-unlock                     # run once before each MCP server session
```

`pop-unlock` stores the derived key in the OS keyring. The MCP server reads it at startup — you never type your passphrase again until the next session.

> **Security levels (lowest → highest):**
> plaintext `.env` < vault, machine key, OSS source < vault, machine key, `pip install pop-pay` < vault + passphrase < Stripe Issuing (commercial, no local credentials)

### Step 1b — Configure Policy (`.env`)

Create `~/.config/pop-pay/.env` for **policy and non-sensitive config only** — no card credentials here:

```bash
# ── Spending policy ──
POP_ALLOWED_CATEGORIES='["aws", "cloudflare", "openai", "github", "wikipedia", "donation"]'
POP_MAX_PER_TX=100.0
POP_MAX_DAILY=500.0
POP_BLOCK_LOOPS=true

# ── CDP injection ──
POP_AUTO_INJECT=true
POP_CDP_URL=http://localhost:9222

# ── Guardrail mode: "keyword" (default) or "llm" ──
# POP_GUARDRAIL_ENGINE=keyword

# ── Billing info for auto-filling name/address/contact fields on checkout pages ──
# POP_BILLING_FIRST_NAME=Bob
# POP_BILLING_LAST_NAME=Smith
# POP_BILLING_EMAIL=bob@example.com
# POP_BILLING_PHONE_COUNTRY_CODE=US     # Optional: fills country code dropdown; national number auto-derived
# POP_BILLING_PHONE=+14155551234        # E.164 format
# POP_BILLING_STREET="123 Main St"
# POP_BILLING_CITY="Redwood City"
# POP_BILLING_STATE=CA                  # Full name or abbreviation, matched fuzzily
# POP_BILLING_COUNTRY=US                # ISO code or full name, matched fuzzily
# POP_BILLING_ZIP=94043

# ── Extra payment processors to trust (built-in list covers Stripe, Zoho, Square, etc.) ──
# POP_ALLOWED_PAYMENT_PROCESSORS='["checkout.myprocessor.com"]'

# ── Custom block keywords (extends built-in list) ──
# POP_EXTRA_BLOCK_KEYWORDS=
```

> **After editing `.env`, restart your agent session** (e.g. close and reopen Claude Code). The MCP server loads configuration once at startup and does not hot-reload.

### Guardrail Mode Configuration

By default, Point One Percent uses the `keyword` engine — a zero-cost, zero-dependency check that blocks obvious hallucination loops and prompt injection phrases. For production or high-value workflows, switch to `llm` mode: it runs Layer 1 keyword check first (fast, no API cost), then Layer 2 LLM semantic evaluation — only use if you need semantic reasoning checks beyond keyword matching.

| | `keyword` (default) | `llm` |
|---|---|---|
| **How it works** | Blocks requests whose `reasoning` string contains suspicious keywords (e.g. "retry", "failed again", "ignore previous instructions") | Hybrid mode: Layer 1 keyword engine runs first (fast, no API cost), then Layer 2 LLM semantic evaluation |
| **What it catches** | Obvious loops, hallucination phrases, prompt injection attempts | Subtle off-topic purchases, logical inconsistencies, policy violations that keyword matching misses |
| **Cost** | Zero — no API calls, instant | Layer 1 is free; one LLM call per `request_virtual_card` invocation only if Layer 1 passes |
| **Dependencies** | None | Any OpenAI-compatible endpoint |
| **Best for** | Development, low-risk workflows, cost-sensitive setups | Production, high-value transactions, untrusted agent pipelines |

**LLM mode:**

```bash
export POP_GUARDRAIL_ENGINE=llm

# Option A: OpenAI
export POP_LLM_API_KEY=sk-...
export POP_LLM_MODEL=gpt-4o-mini          # default

# Option B: Local model via Ollama (free, private)
export POP_LLM_BASE_URL=http://localhost:11434/v1
export POP_LLM_MODEL=llama3.2
# POP_LLM_API_KEY can be set to any non-empty string for Ollama

# Option C: Any OpenAI-compatible endpoint (OpenRouter, vLLM, LM Studio...)
export POP_LLM_BASE_URL=https://openrouter.ai/api/v1
export POP_LLM_API_KEY=sk-or-...
export POP_LLM_MODEL=anthropic/claude-3-haiku
```

> **Tip:** Start with `keyword` during development. Switch to `llm` when moving to production or when the agent pipeline is handling real money or untrusted inputs.

### Step 2 — Add Point One Percent MCP to Claude Code

```bash
pop-launch --print-mcp
```

Copy the printed `claude mcp add pop-pay -- ...` command and run it. The command uses `sys.executable` from your venv, so it works correctly regardless of how you installed pop-pay.

```bash
claude mcp add pop-pay ... #Result from pop-launch --print-mcp
```

> `--scope user` (optional) stores the registration in `~/.claude.json` — available in every Claude Code session. Without it, the registration is scoped to the current project.

### Step 3 — Add Playwright MCP to Claude Code

```bash
claude mcp add --scope user playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> **`--cdp-endpoint` is required.** It connects Playwright MCP to the **same Chrome** that Point One Percent uses for injection. Without it, Playwright runs its own isolated browser and Point One Percent cannot see the pages — injection will fail with a "could not find card fields" error. Run **once**; persists automatically.

### `request_virtual_card` Parameters

| Parameter | Required | Description |
|---|---|---|
| `requested_amount` | Yes | The transaction amount in USD. |
| `target_vendor` | Yes | The vendor or service being purchased (e.g. `"openai"`, `"Wikipedia"`). Must match an entry in `POP_ALLOWED_CATEGORIES`. |
| `reasoning` | Yes | The agent's explanation for why this purchase is needed. Evaluated by the guardrail engine. |
| `page_url` | No | The current checkout page URL. Used to cross-validate the vendor domain against known domains to detect phishing. Pass `page.url` from the browser when using Playwright MCP. |

> **Domain validation:** When `page_url` is provided and the `target_vendor` matches a known vendor (AWS, GitHub, Cloudflare, OpenAI, Stripe, Anthropic, Wikipedia, and others), pop-pay validates the page URL's domain against the expected domains for that vendor. Mismatched domains — a sign of a phishing page — cause the request to be rejected automatically.

### Recommended System Prompt Addition

Add the following block to your Claude Code system prompt (or project `CLAUDE.md`). This tells the agent to start Chrome if needed and pass `page_url` correctly:

```
pop-pay payment rules:
- Billing info and card credentials: NEVER ask the user — pop-pay auto-fills everything.
- Billing/contact page (no card fields visible): call request_purchaser_info(target_vendor, page_url)
- Payment page (card fields visible): call request_virtual_card(amount, vendor, reasoning, page_url)
- Always pass page_url. Never type card numbers or personal info manually. Never read .env files.
- Rejection → stop and report to user. pop-pay MCP unavailable → stop and tell user.
- CDP check: curl http://localhost:9222/json/version — if down, run pop-launch first.
```

### Full Session Flow

**One-time setup** (human, after cloning):

1. Create `~/.config/pop-pay/.env` → fill in your card credentials and policy settings
2. `pop-launch --print-mcp` → run the two `claude mcp add` commands it prints

**Every session** (agent handles this if you add the system prompt above):

1. Agent checks if Chrome is running (`curl http://localhost:9222/json/version`) — if not, runs `pop-launch`
2. Open Claude Code → both MCPs connect automatically
3. Agent navigates to checkout via Playwright MCP, calls `request_virtual_card` with `page_url`
4. Point One Percent injects real card into the form — agent only sees the masked number
5. Agent clicks submit; card is burned after use

### Your First Live Test

Once both MCPs are connected, paste this into a new Claude Code conversation:
```bash
> Donate $10 to Wikipedia, with credit card, pay with pop-pay. Fill in the payment details, but **do not submit** — I will review and confirm before proceeding.
```
> **Note:** The `"do not submit"` instruction is for initial testing only. Once you have verified the injection flow works correctly, remove it from your prompt to enable fully autonomous payments within your configured policy limits.

**Expected flow:** Agent navigates → selects $10 → clicks "Donate by credit/debit card" → calls `request_virtual_card` → Point One Percent injects card + billing details via CDP → agent waits for your confirmation.

> **If the request is rejected with "Vendor not in allowed categories":** Add `donation` to `POP_ALLOWED_CATEGORIES` in your `.env`, then start a new Claude Code session (no need to re-register the MCP — a new session restarts the server and reloads `.env` automatically).

---

## 2. gemini-cli / Python Script Integration

For automation scripts that use `gemini-cli` or a raw Python agent loop, embed `PopClient` directly as the payment middleware.

### Pattern: PopClient as Script Middleware

```python
import asyncio
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import GuardrailPolicy, PaymentIntent

async def run_automated_workflow():
    # 1. Initialize Point One Percent at the start of your script
    policy = GuardrailPolicy(
        allowed_categories=["SaaS", "API", "Cloud"],
        max_amount_per_tx=50.0,
        max_daily_budget=200.0,
        block_hallucination_loops=True
    )
    client = PopClient(
        provider=MockStripeProvider(),  # swap for StripeIssuingProvider in prod
        policy=policy,
        db_path="pop_state.db"
    )

    # 2. When your script needs to make a purchase, go through Point One Percent
    intent = PaymentIntent(
        agent_id="gemini-script-001",
        requested_amount=15.0,
        target_vendor="openai",
        reasoning="Topping up API credits to continue the data pipeline run."
    )

    seal = await client.process_payment(intent)

    if seal.status == "Rejected":
        print(f"Payment blocked: {seal.rejection_reason}")
        return  # halt script — do NOT proceed with a fallback

    print(f"Approved. Seal: {seal.seal_id} | Card: ****-****-****-{seal.card_number[-4:]}")

    # 3. Use the seal_id to execute (burn-after-use enforced)
    result = await client.execute_payment(seal.seal_id, 15.0)
    print(f"Execution result: {result['status']}")

asyncio.run(run_automated_workflow())
```

### Pattern: LangChain Tool Call (for gemini-cli tool integration)

If your `gemini-cli` prompt uses tools, wrap Point One Percent as a LangChain `BaseTool`:

```python
from pop_pay.tools.langchain import PopPaymentTool
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import GuardrailPolicy

policy = GuardrailPolicy(
    allowed_categories=["SaaS", "API"],
    max_amount_per_tx=50.0,
    max_daily_budget=200.0,
    block_hallucination_loops=True
)
client = PopClient(MockStripeProvider(), policy)

# Register as a tool in your agent's tool list
pop_tool = PopPaymentTool(client=client, agent_id="gemini-agent")

# The tool accepts: requested_amount, target_vendor, reasoning
result = await pop_tool._arun(
    requested_amount=15.0,
    target_vendor="openai",
    reasoning="Need API credits to continue processing user request."
)
print(result)
# → "Payment approved. Card Issued: ****-****-****-4242, Expiry: 03/27, ..."
```

### Pattern: LLM Guardrail Engine

To use the LLM guardrail engine directly in a Python script (e.g. for local Ollama inference), pass an `LLMGuardrailEngine` instance when constructing `PopClient`:

```python
from pop_pay.engine.llm_guardrails import LLMGuardrailEngine

llm_engine = LLMGuardrailEngine(
    base_url="http://localhost:11434/v1",  # Ollama endpoint
    model="llama3.2",
    use_json_mode=False
)
client = PopClient(
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

### Your First Live Test

Run the included SDK demo to verify everything is wired correctly:

```bash
uv run python examples/e2e_demo.py
```

You should see three scenarios run: an approved payment, a budget-exceeded rejection, and a hallucination loop block — all without a browser or API key. To also verify LLM guardrail mode, run:

```bash
uv run --extra llm python scripts/test_llm_guardrails.py
```

> **Note:** The `"do not submit"` instruction is for initial testing only. Once you have verified the injection flow works correctly, remove it from your prompt to enable fully autonomous payments within your configured policy limits.

---

## 3. Browser Agent Middleware (Playwright / browser-use / Skyvern)

Browser agents that navigate real websites need to intercept the checkout flow and request a virtual card from Point One Percent *before* filling in any payment form.

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
                        │  request_virtual_card(amount, vendor, reasoning, page_url=page.url)
                        ▼
┌──────────────────────────────────────────────────────┐
│          Point One Percent (This library)             │
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
│  4. PopBrowserInjector attaches to Chrome via CDP  │
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
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import PaymentIntent, GuardrailPolicy

async def browser_agent_with_pop():
    # 1. Initialize Point One Percent
    policy = GuardrailPolicy(
        allowed_categories=["Donation", "SaaS", "Wikipedia"],
        max_amount_per_tx=30.0,
        max_daily_budget=50.0
    )
    client = PopClient(MockStripeProvider(), policy, db_path="pop_state.db")

    # 2. Browser agent detects a checkout form and requests authorization
    intent = PaymentIntent(
        agent_id="playwright-agent-001",
        requested_amount=25.0,
        target_vendor="Wikipedia",
        reasoning="I need to support open knowledge via a $25 donation."
    )
    seal = await client.process_payment(intent)

    if seal.status.lower() == "rejected":
        print(f"Payment blocked: {seal.rejection_reason}")
        return  # browser agent stops — does NOT attempt to fill the form

    print(f"Approved. Seal: {seal.seal_id}")
    # The agent's context only sees the masked number — never the real PAN
    print(f"   Card in agent log: ****-****-****-{seal.card_number[-4:]}")

    # 3. Trusted local process fills the real credentials into the browser
    #    (This code runs in the local execution env, NOT inside the LLM context)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://donate.wikimedia.org/")

        # CRITICAL: Use PopBrowserInjector — real card details are injected from
        # the in-memory VirtualSeal, never retrieved from the DB (which only stores masked numbers).
        from pop_pay.injector import PopBrowserInjector
        browser_injector = PopBrowserInjector(client.state_tracker)
        await browser_injector.inject_payment_info(
            seal_id=seal.seal_id,
            cdp_url="http://localhost:9222",
            card_number=seal.card_number or "",
            cvv=seal.cvv or "",
            expiration_date=seal.expiration_date or "",
        )
        await page.click("#submit-donation")

    # 4. Mark seal as used (burn-after-use)
    await client.execute_payment(seal.seal_id, 25.0)
    print("Card burned. Transaction complete.")

asyncio.run(browser_agent_with_pop())
```

### Your First Live Test

Run the included Playwright example against a real Wikipedia donation page:

```bash
uv run python examples/agent_vault_flow.py
```

The script navigates to the checkout, requests a virtual card from Point One Percent, injects the card details via CDP, and prints the masked card number — the raw PAN never appears in the output.

> **Note:** The `"do not submit"` instruction is for initial testing only. Once you have verified the injection flow works correctly, remove it from your prompt to enable fully autonomous payments within your configured policy limits.

### Adapting for browser-use / Skyvern

If you're using `browser-use` or Skyvern (which operate with higher-level visual reasoning), the pattern is identical — intercept before form submission:

```python
# Pseudo-code for browser-use integration
class POPCheckoutInterceptor:
    def __init__(self, pop_client: PopClient):
        self.client = pop_client

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
            raise PaymentBlockedError(f"Point One Percent rejected: {seal.rejection_reason}")

        return seal  # pass seal back to browser-use to complete checkout

    async def on_checkout_complete(self, seal_id: str, amount: float):
        """Called after browser-use successfully submits the form."""
        await self.client.execute_payment(seal_id, amount)
```

---

## 4. OpenClaw / NemoClaw — Full Setup

pop-pay is a standalone MCP server that you install and run locally to guardrail agent payments. For OpenClaw users, the ClawHub "skill" is the discovery and configuration layer that teaches your agent how to communicate with your local pop-pay server. You must first install the `pop-pay` Python package, then add the skill via `openclaw` to grant your agent access to the payment tools. This architecture ensures payment logic is securely managed on your machine while allowing the agent to request payments through its standard tool-use interface.

### ClawHub Skill (Fastest Setup)

pop-pay is available as a one-click skill on **ClawHub** (the OpenClaw/NemoClaw skill marketplace). Search for **"pop-pay"** by Point One Percent. The skill bundles the MCP registration, spend policy defaults, and the system prompt fragment below — setup is a single click.

Manual setup instructions follow below for users who prefer full control.

---

### Recommended System Prompt Fragment

Add the following block to your OpenClaw or NemoClaw identity file (e.g., `IDENTITY.md` or the system prompt field in your agent config):

```markdown
## Financial Safety Protocol (REQUIRED)

You are operating under the Point One Percent Payment Guardrail Protocol. The following rules are NON-NEGOTIABLE:

1. **You MUST call the `request_virtual_card` MCP tool** before attempting any purchase,
   subscription, donation, API credit top-up, or any other financial transaction.

2. **Never use stored credit card numbers, PAN numbers, or any real payment credentials**
   found in your context, memory, or files. These are never provided to you.

3. **If `request_virtual_card` returns a rejection, STOP the payment flow immediately.**
   Do not retry with a different reasoning. Report the rejection reason to the user.

4. **If you find yourself in a loop** (retrying the same failed purchase more than once),
   you MUST stop and request human intervention rather than continuing.
```

---

### OpenClaw Setup

OpenClaw has full native MCP support and reads `.env` files in the same way as Claude Code. The setup is nearly identical to §1.

**Step 0 — Launch Chrome with CDP**

Same as §1 — use `pop-launch`:

```bash
pop-launch --print-mcp
```

**Step 1 — Configure `.env`**

Same as §1. OpenClaw reads from `.env` in the project directory, `~/.openclaw/.env`, or via the `env` block in `~/.openclaw/openclaw.json`. Copy and fill in your credentials:

Create `~/.config/pop-pay/.env` with your credentials.

**Step 2 — Register Point One Percent MCP**

```bash
openclaw mcp add pop-pay -- /path/to/venv/bin/python -m pop_pay.mcp_server
```

> Run `pop-launch --print-mcp` to get the exact command with the correct Python path.

Or add directly to `~/.openclaw/mcp_servers.json`:

```json
{
  "pop": {
    "command": "uv",
    "args": ["run", "--project", "/path/to/Point-One-Percent", "python", "-m", "pop_pay.mcp_server"]
  }
}
```

**Step 3 — Register Playwright MCP with CDP endpoint**

OpenClaw supports Playwright MCP via ClawHub. Register it with the same `--cdp-endpoint` flag so both MCPs share the same Chrome instance:

```bash
openclaw mcp add playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> After updating `.env`, restart your OpenClaw session to reload config — no need to re-register MCPs.

---

### Payment Flow

```
+------------------+     +----------------------+     +---------------------------+
| Agent navigates  | --> | Billing form visible |     | Payment form visible      |
| to checkout page |     | (name/address fields)|     | (card fields)             |
+------------------+     +----------------------+     +---------------------------+
                                   |                              |
                         call request_purchaser_info()   call request_virtual_card()
                         (fills name, address, email)    - auto page scan runs inside
                                   |                     - card injected via CDP
                                   v                              |
                          click Continue/Next                     v
                                                        click Submit / Place Order
```

### Your First Live Test

Use the Wikipedia donation page — simple checkout, no account required.

```bash
> Donate $10 to Wikipedia, with credit card, pay with pop-pay. Fill in the payment details, but **do not submit** — I will review and confirm before proceeding.
```

1. Your agent navigates to `https://donate.wikimedia.org`, select $10, choose "Credit Card", and proceed to the form asking for payment details.

2. On the billing info page, the agent calls:
   ```
   request_purchaser_info(target_vendor="Wikipedia", page_url="...", reasoning="...")
   ```
   Then clicks Continue.

3. On the payment page, the agent calls:
   ```
   request_virtual_card(requested_amount=10.0, target_vendor="Wikipedia", reasoning="...", page_url="...")
   ```
   pop-pay automatically scans the page for prompt injection, then injects the card via CDP.

4. The agent clicks Submit. For initial testing, add `"do not submit the form"` to your prompt so you can inspect the filled fields before any charge.

**Expected flow:** Agent navigates → selects $10 → proceeds to card form → calls `request_virtual_card` → pop-pay scans page + injects card via CDP → agent waits for confirmation.

---

### NemoClaw (NVIDIA OpenShell) Setup

NemoClaw wraps OpenClaw inside the **OpenShell** security sandbox. The key differences from Claude Code / OpenClaw are:

1. **No `.env` files** — credentials are declared as "Providers" in the YAML policy file and injected as environment variables at runtime.
2. **Zero-egress by default** — the POP MCP server endpoint must be explicitly added to the network allowlist.
3. **Early preview** — interfaces may change; check the [NemoClaw docs](https://docs.nvidia.com/nemoclaw/latest/) for the latest.

**Step 0 — Launch Chrome with CDP (outside the sandbox)**

Run `pop-launch` on the host before connecting to the sandbox:

```bash
pop-launch
```

**Step 1 — Clone and install inside the sandbox**

```bash
nemoclaw my-assistant connect
cd /sandbox
git clone https://github.com/100xPercent/pop-pay-python.git
cd pop-pay-python && uv sync --all-extras
```

**Step 2 — Declare POP credentials as Providers in your policy YAML**

In your `nemoclaw-blueprint/policies/openclaw-sandbox.yaml`, add POP credentials under the `providers` section:

```yaml
providers:
  - name: POP_BYOC_NUMBER
    value: "4111111111111111"
  - name: POP_BYOC_CVV
    value: "123"
  - name: POP_BYOC_EXP_MONTH
    value: "12"
  - name: POP_BYOC_EXP_YEAR
    value: "27"
  - name: POP_ALLOWED_CATEGORIES
    value: '["aws", "openai", "donation"]'
  - name: POP_MAX_PER_TX
    value: "100.0"
  - name: POP_MAX_DAILY
    value: "500.0"
  - name: POP_BLOCK_LOOPS
    value: "true"
```

**Step 3 — Allowlist the POP MCP server in network policy**

```yaml
network:
  egress:
    allow:
      - host: localhost
        port: 9222   # Chrome CDP
      - host: localhost
        port: 8000   # POP MCP server (adjust if different)
```

**Step 4 — Register MCPs (while connected to sandbox)**

```bash
openclaw mcp add pop-pay -- /path/to/venv/bin/python -m pop_pay.mcp_server
openclaw mcp add playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> **NemoClaw tip:** Point One Percent's guardrails are especially valuable inside NemoClaw — the zero-egress sandbox prevents most accidental spending, but POP adds semantic policy enforcement and a full audit trail that OpenShell alone does not provide.

### Your First Live Test

Once your agent is configured with the system prompt above, try this task:
```bash
> Donate $10 to Wikipedia, with credit card, pay with pop-pay. Fill in the payment details, but **do not submit** — I will review and confirm before proceeding.
```
> **Note:** The `"do not submit"` instruction is for initial testing only. Once you have verified the injection flow works correctly, remove it from your prompt to enable fully autonomous payments within your configured policy limits.

If the guardrails approve the request and the card details are injected into the form, Point One Percent is working correctly end-to-end.

> **If the request is rejected with "Vendor not in allowed categories":** Add `donation` to `POP_ALLOWED_CATEGORIES` (env var or `mcp_servers.json`), then restart your agent session.

---

## See Also

- [README.md](../README.md) — Main project overview and quick start
- [§1 Claude Code](#1-claude-code--full-setup-with-cdp-injection) — Full BYOC + CDP injection setup (most common)
- [§2 Python SDK / gemini-cli](#2-gemini-cli--python-script-integration) — Direct SDK embedding and LangChain tool pattern
- [§3 Browser Agents](#3-browser-agent-middleware-playwright--browser-use--skyvern) — Playwright / browser-use / Skyvern integration
- [§4 OpenClaw / NemoClaw](#4-openclaw--nemoclaw--full-setup) — Full MCP + CDP setup for OpenClaw and NemoClaw
- [examples/agent_vault_flow.py](../examples/agent_vault_flow.py) — Full Playwright browser injection example
- [examples/e2e_demo.py](../examples/e2e_demo.py) — SDK-only end-to-end demo (no browser)
- [CONTRIBUTING.md](../CONTRIBUTING.md) — How to add new payment providers or guardrail engines
