<p align="center">
    <picture>
        <img src="https://raw.githubusercontent.com/TPEmist/Point-One-Percent/main/project_banner.png" alt="Point One Percent (AgentPay)" width="800">
    </picture>
</p>

# Point One Percent - Agent Pay

<p align="center">
  <a href="https://glama.ai/mcp/servers/TPEmist/Point-One-Percent"><img src="https://glama.ai/mcp/servers/TPEmist/Point-One-Percent/badges/score.svg" alt="Glama MCP score"></a>
  &nbsp;&nbsp;
  <a href="https://www.producthunt.com/products/project-aegis?embed=true&utm_source=badge-featured&utm_medium=badge&utm_campaign=badge-point-one-percent-ai-agent-pay" target="_blank" rel="noopener noreferrer"><img alt="Point One Percent on Product Hunt" width="140" height="30" src="https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=1105745&theme=neutral&t=1774937261413"></a>
</p>

> it only takes 0.1% of Hallucination to drain 100% of your wallet.

<p align="center">
  <img src="assets/runtime_demo.gif" alt="Point One Percent — live CDP injection demo" width="800">
</p>

Point One Percent is a payment guardrail and one-time flow protocol specifically designed for Agentic AI (e.g., OpenClaw, NemoClaw, Claude Code, OpenHands). It enables agents to handle financial transactions safely without risking unlimited exposure of human-controlled credit cards.

## 1. The Problem
When Agentic AI encounters a paywall (e.g., domain registration, API credits, compute scaling) during an automated workflow, it is often forced to stop and wait for human intervention. However, providing a physical credit card directly to an agent introduces a "trust crisis": hallucinations or infinite loops could lead to the card being drained.

## 2. Dual Architecture

Point One Percent is designed with a "Dual Architecture" vision to scale from open-source local experiments to enterprise-grade AI production pipelines.

### 1. Hacker Edition (BYOC + DOM Injection)
Built for open-source frameworks like OpenClaw and NemoClaw. The agent **never** receives the true credit card number—it only sees a masked version (\`****-4242\`). When the agent successfully navigates to a checkout paywall, the `PopBrowserInjector` attaches to the active Chromium browser via the Chrome DevTools Protocol (CDP). It precisely traverses all cross-origin iframes (like Stripe Elements) and injects the real credentials deep into the DOM form elements, delivering **100% protection against prompt injection** or hallucination-driven extractions. Bring Your Own Card (BYOC) locally with absolute peace of mind.

### 2. Enterprise Edition (Stripe Issuing)
The "North Star" for the broader Agentic SaaS ecosystem. Proving that Point One Percent has the enterprise-grade extensibility required for the real world, it seamlessly connects to verified financial infrastructure. Perfect for platforms building "Agentic Visa" services that programmatically issue real, single-use, burner virtual credit cards (VCCs) via the Stripe API for cloud-hosted AI fleets.

---

## 3. Ecosystem Position: Point One Percent + Browser Agents = Unstoppable

Modern agentic workflows require two complementary capabilities. Point One Percent does one, and does it exceptionally well.

### What Point One Percent Is — and Isn't

**Point One Percent is the agent's financial brain and safe vault.** It is responsible for:
- Evaluating whether a purchase *should* happen (semantic guardrails)
- Enforcing hard budget limits (daily cap, per-transaction cap)
- Issuing one-time virtual cards so real credentials are never exposed
- Maintaining a full audit trail of every payment attempt

**Point One Percent does NOT:**
- Navigate websites or interact with DOM elements
- Solve CAPTCHAs or bypass bot-detection systems

That's the browser agent's job.

### The Handshake: How Point One Percent and Browser Agents Work Together

The real power emerges when Point One Percent is paired with a browser automation agent (e.g., OpenHands, browser-use, Skyvern). The workflow is a clean division of labor:

```
1. [Browser Agent]  Navigates to a site, scrapes product info, reaches checkout.
        │
        │  (Hit a paywall / payment form)
        ▼
2. [Browser Agent → POP MCP]  Calls request_virtual_card(amount, vendor, reasoning)
        │
        │  (Point One Percent evaluates: budget OK? vendor approved? no hallucination?)
        ▼
3. [POP]  Issues a one-time virtual card (Stripe mode) or mock card (dev mode).
            Full card credentials handled only by the local trusted process —
            never exposed to the agent or LLM context.
        │
        ▼
4. [POP]  Injects real credentials into the checkout form via CDP.
            The agent receives only a transaction confirmation — no card details.
        │
        ▼
5. [Browser Agent]  Clicks the submit button to complete the transaction.
        │
        ▼
6. [The Vault]  Dashboard logs the transaction. Card is immediately burned.
```

### Supported Integrations

| Integration path | Works with |
|---|---|
| **MCP Tool** | Claude Code, OpenClaw, NemoClaw, OpenHands, any MCP-compatible host |
| **Python SDK** | Custom Playwright, browser-use, Skyvern, Selenium, gemini-cli |

> **Any browser-capable agent** (Claude Code, OpenClaw, browser-use, Skyvern, etc.) gets full CDP injection — card is auto-filled into the payment form, the agent only ever sees the masked confirmation (`****-****-****-4242`). See the **[Integration Guide](./docs/INTEGRATION_GUIDE.md)** for setup instructions and System Prompt templates.

---

## 4. Installation

> **Shell note:** `[...]` is special syntax in zsh and bash — always wrap the package name in quotes.

```bash
# Core only (keyword guardrail + mock provider, zero external dependencies)
pip install "pop-pay"

# Claude Code / MCP integration
pip install "pop-pay[mcp]"

# Claude Code + CDP injection (BYOC)
pip install "pop-pay[mcp,browser]"

# With LLM-based guardrails (supports OpenAI, Ollama, vLLM, OpenRouter)
pip install "pop-pay[mcp,llm]"

# With Stripe virtual card issuing
pip install "pop-pay[stripe]"

# With LangChain integration
pip install "pop-pay[langchain]"

# Full installation (all features)
pip install "pop-pay[all]"
```

## 5. Quick Start for OpenClaw / NemoClaw / Claude Code / OpenHands

If you're using OpenClaw, NemoClaw, Claude Code, OpenHands, or any MCP-compatible agentic framework, you can get Point One Percent running in under 2 minutes:

### Step 1: Set Up Environment & Install

```bash
# Create a dedicated directory and virtualenv
mkdir ~/pop-pay && cd ~/pop-pay
python3 -m venv .venv && source .venv/bin/activate

# Install — quotes required for zsh/bash
pip install "pop-pay[all]"
```

> **Contributing / local development?** See [CONTRIBUTING.md](./CONTRIBUTING.md) for the `git clone` + `uv sync` path.

### Step 1b: Initialize the Credential Vault

**v0.6.0+:** Credentials are stored in an AES-256-GCM encrypted vault — no plaintext `.env` required.

```bash
pop-init-vault
```

This will prompt for your card credentials (input is hidden), encrypt them into `~/.config/pop-pay/vault.enc`, and securely wipe any existing `.env`. The MCP server auto-decrypts the vault at startup — no extra steps needed per session.

**Passphrase mode (stronger — protects against agents with shell access):**

```bash
pop-init-vault --passphrase   # one-time setup
pop-unlock                     # run once before each MCP server session
```

`pop-unlock` derives the key from your passphrase and stores it in the OS keyring. The MCP server reads it automatically at startup.

**Security levels (lowest → highest):**

| Mode | Protects against |
|---|---|
| `.env` file (legacy) | Nothing — plaintext on disk |
| Vault, machine key, OSS source | File-read agents |
| Vault, machine key, `pip install pop-pay` | File-read agents + casual shell inspection |
| Vault + passphrase | File-read agents + shell agents |
| Stripe Issuing (commercial) | All local threats — no credentials stored |

> **Policy & non-credential config** (allowed vendors, spending limits, CDP URL) is still read from `~/.config/pop-pay/.env`. Only card credentials moved to the vault.

### Step 2: Launch Chrome & Get MCP Commands

```bash
pop-launch --print-mcp
```

This launches Chrome with CDP enabled and prints the exact `claude mcp add` commands to run.

### Step 3: Add to Claude Code

Choose your platform and follow the dedicated setup guide:

| Platform | Setup Guide |
|---|---|
| **Claude Code** (BYOC + CDP injection, recommended) | [Integration Guide §1](./docs/INTEGRATION_GUIDE.md#1-claude-code--full-setup-with-cdp-injection) |
| **Python script / gemini-cli** | [Integration Guide §2](./docs/INTEGRATION_GUIDE.md#2-gemini-cli--python-script-integration) |
| **Playwright / browser-use / Skyvern** | [Integration Guide §3](./docs/INTEGRATION_GUIDE.md#3-browser-agent-middleware-playwright--browser-use--skyvern) |
| **OpenClaw / NemoClaw** | [Integration Guide §4](./docs/INTEGRATION_GUIDE.md#4-openclaw--nemoclaw--system-prompt-configuration) |
| **OpenHands** | Add `python -m pop_pay.mcp_server` to your `mcpServers` config |

### Step 4: Configure Policy

Edit `~/.config/pop-pay/.env` (see Step 1b). Key variables:

| Variable | Default | Description |
|---|---|---|
| `POP_ALLOWED_CATEGORIES` | `["aws","cloudflare"]` | Vendors the agent is allowed to pay |
| `POP_MAX_PER_TX` | `100.0` | Max $ per transaction |
| `POP_MAX_DAILY` | `500.0` | Max $ per day |
| `POP_BLOCK_LOOPS` | `true` | Block hallucination/retry loops |
| `POP_AUTO_INJECT` | `false` | Enable CDP card injection |
| `POP_GUARDRAIL_ENGINE` | `keyword` | Guardrail engine: `keyword` (zero-cost, default) or `llm` (semantic, two-layer) — see [Guardrail Mode](#guardrail-mode-keyword-vs-llm) |

> **After editing `.env`, fully close and reopen Claude Code.** The MCP server loads configuration at startup — `!claude mcp list` alone is not sufficient to pick up `.env` changes.

#### Guardrail Mode: Keyword vs LLM

Point One Percent ships with two guardrail engines. You switch between them with a single env var:

| | `keyword` (default) | `llm` |
|---|---|---|
| **How it works** | Blocks requests whose `reasoning` string contains suspicious keywords (e.g. "retry", "failed again", "ignore previous instructions") | Sends the agent's `reasoning` to an LLM for deep semantic analysis |
| **What it catches** | Obvious loops, hallucination phrases, prompt injection attempts | Subtle off-topic purchases, logical inconsistencies, policy violations that keyword matching misses |
| **Cost** | Zero — no API calls, instant | One LLM call per `request_virtual_card` invocation |
| **Dependencies** | None | Any OpenAI-compatible endpoint |
| **Best for** | Development, low-risk workflows, cost-sensitive setups | Production, high-value transactions, untrusted agent pipelines |

> **Tip:** `keyword` mode requires no extra config. To enable LLM mode, see the [full configuration reference in the Integration Guide §1](./docs/INTEGRATION_GUIDE.md#guardrail-mode-configuration).

### Step 4: Use It

Your agent now has access to the `request_virtual_card` tool. When it encounters a paywall:

```
Agent: "I need to purchase an API key from AWS for $15 to continue."
[Tool Call] request_virtual_card(amount=15.0, vendor="AWS", reasoning="Need API key for deployment")
[POP] Payment approved. Card Issued: ****4242, Expiry: 12/25, Amount: 15.0
Agent: "Purchase successful, continuing workflow."
```

If the agent hallucinates or tries to overspend:
```
Agent: "Let me retry buying compute... the previous attempt failed again."
[Tool Call] request_virtual_card(amount=50.0, vendor="AWS", reasoning="failed again, retry loop")
[POP] Payment rejected. Reason: Hallucination or infinite loop detected in reasoning
```

---

## 6. Core Components

### The Vault
A local visualization console powered by **Streamlit** and **SQLite** (`pop_state.db`). The Vault allows humans to:
- Monitor all issued seals and agent spending activity in real-time.
- Monitor global budget utilization.
- Audit rejection logs from semantic guardrails.

### The Seal
Virtual, single-use payment credentials with built-in enforcement:
- **Daily Budget Limit Enforcement**: Automatically blocks any request that would exceed the predefined daily spending cap.
- **Burn-after-use Interception**: Ensures that once a virtual card is used, it is immediately invalidated, preventing replay attacks or unauthorized recurring charges.

### Semantic Guardrails
Point One Percent provides two modes of intent evaluation. Both are controlled by `POP_GUARDRAIL_ENGINE` in your `.env` (see [§5 Step 3](#step-3-configure-your-policy-environment-variables) for full configuration).

1. **Keyword mode** (`POP_GUARDRAIL_ENGINE=keyword`, **default**): The `GuardrailEngine` scans the agent's `reasoning` string for suspicious phrases associated with loops or hallucinations (e.g., `"retry"`, `"failed again"`, `"ignore previous"`). Zero dependencies, zero latency, zero cost. Recommended as the starting point for all setups.

2. **LLM mode** (`POP_GUARDRAIL_ENGINE=llm`): The `LLMGuardrailEngine` sends the agent's `reasoning` to an LLM for deep semantic analysis, catching subtler misuse that keyword matching would miss — such as off-topic purchases or logically inconsistent justifications. Supports **any OpenAI-compatible endpoint**: OpenAI, Ollama (local), vLLM, OpenRouter, and more.

## 7. Security Statement

Security is a first-class citizen in Point One Percent. The SDK **masks card numbers by default** (e.g., `****-****-****-4242`) when returning authorization results to the agent. This prevents sensitive payment information from leaking into agent chat logs, model context windows, or persistent logs, ensuring that only the execution environment handles the raw credentials.

**v0.6.0 defense-in-depth hardening:**

| Layer | Defense |
|---|---|
| **Encrypted vault** | Card credentials stored as AES-256-GCM ciphertext (`vault.enc`); plaintext never touches disk after `pop-init-vault` |
| **Passphrase mode** | Key derived from user passphrase via PBKDF2 (600k iterations); stored in OS keyring — agents with shell access cannot derive the key |
| **Database** | SQLite only stores masked card (`****-4242`); `card_number` and `cvv` columns removed entirely |
| **Injection-time TOCTOU guard** | Domain verified against guardrail-approved vendor at the moment of injection — prevents redirect-to-attacker attacks |
| **Repr redaction** | `VirtualSeal.__repr__` always emits `****-REDACTED`; credentials cannot leak via logs or tracebacks |
| **Core dump prevention** | MCP server disables core dumps at startup (`RLIMIT_CORE=0`) |
| **Process isolation** | Agent communicates via MCP JSON-RPC as a separate process — cannot access MCP server memory or env vars through the protocol |

See [SECURITY.md](./SECURITY.md) for the full threat model, red team results, and documented limitations.

## 8. The Vault Dashboard

The Vault is your real-time monitoring console for all agent payment activity.

### Starting the Dashboard

```bash
cd Point-One-Percent
uv run streamlit run dashboard/app.py
# Dashboard opens at http://localhost:8501
```

### Dashboard Layout

| Section | Description |
|---|---|
| **Sidebar: Max Daily Budget slider** | Adjust the displayed budget cap for visualization (does not affect backend policy — backend policy is configured via env vars or SDK) |
| **Today's Spending** | Total amount spent by agents today |
| **Remaining Budget** | How much budget is left for the day |
| **Budget Utilization** | Visual progress bar showing spend % |
| **Issued Seals & Activity** | Full table of all payment attempts (approved + rejected) with seal ID, amount, vendor, status, and timestamp |
| **Rejected Summary** | Filtered view showing only rejected/blocked attempts for quick auditing |

### Tips
- Click **Refresh Data** in the sidebar to pull latest activity from the database.
- The dashboard reads from `pop_state.db` — the same database the SDK writes to. Keep both running simultaneously for live monitoring.
- Each row in the table corresponds to a single `request_virtual_card` call from an agent.

---

## 9. Python SDK Quickstart

Integrate Point One Percent into your custom Python or LangChain workflows in just a few lines:

```python
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import GuardrailPolicy

# Define your safety policy
policy = GuardrailPolicy(
    allowed_categories=["API", "Cloud", "SaaS"],
    max_amount_per_tx=50.0,
    max_daily_budget=200.0,
    block_hallucination_loops=True
)

# Initialize the client with keyword-only guardrails (default)
client = PopClient(
    provider=MockStripeProvider(),
    policy=policy,
    db_path="pop_state.db"
)

# Use with LangChain Tool
from pop_pay.tools.langchain import PopPaymentTool
tool = PopPaymentTool(client=client, agent_id="agent-01")
```

> For LLM guardrail engine setup and the full provider reference, see [Integration Guide §2](./docs/INTEGRATION_GUIDE.md#2-gemini-cli--python-script-integration).

---

## 10. Payment Providers: Stripe vs Mock

### Without Stripe (Default — Mock Provider)

By default, Point One Percent uses the `MockStripeProvider` which simulates virtual card issuance. This is perfect for:
- **Development and testing** — no real money involved
- **Demo and evaluation** — see the full flow without any API keys
- **Hackathons** — get a working prototype in minutes

Mock cards are fully functional within the system (budget tracking, burn-after-use, guardrails all work), but they are not real payment instruments.

### BYOC — Bring Your Own Card (Hacker Edition)

For developers who want to use their **own physical credit card** with Point One Percent without a Stripe account. The `LocalVaultProvider` reads card credentials from environment variables and injects them into browser payment forms via CDP — the raw PAN is never exposed to the agent.

**Add to your `~/.config/pop-pay/.env`:**
```bash
POP_BYOC_NUMBER=4111111111111111   # Your real card number
POP_BYOC_CVV=123
POP_BYOC_EXP_MONTH=12              # Expiry month, e.g. 04
POP_BYOC_EXP_YEAR=27               # Expiry year, e.g. 31
POP_AUTO_INJECT=true
```
Then restart Claude Code. The MCP server will automatically use `LocalVaultProvider`.

**Provider priority (high → low):** Stripe Issuing → BYOC Local → Mock.

If `POP_STRIPE_KEY` is set, Stripe takes precedence. If `POP_BYOC_NUMBER` is set (but no Stripe key), `LocalVaultProvider` is used. If neither is set, `MockStripeProvider` is used for development.

> **Security note:** Never commit real card numbers to version control. Always use `.env` (which is `.gitignore`d) or a secrets manager. The CDP injection ensures the full card number is only handled by the local trusted process, never by the LLM.

> For Python SDK usage of each provider, see [Integration Guide §2](./docs/INTEGRATION_GUIDE.md#2-gemini-cli--python-script-integration).

### With Real Stripe Issuing

To issue **real virtual credit cards** through [Stripe Issuing](https://stripe.com/issuing):

**Prerequisites:**
1. A Stripe account with [Issuing](https://stripe.com/issuing) enabled (requires application approval)
2. Your Stripe secret key (`sk_live_...` or `sk_test_...`)

**Option A: Via Environment Variable (for MCP Server)**
```bash
export POP_STRIPE_KEY=sk_live_your_stripe_key_here
python -m pop_pay.mcp_server
# The MCP server will automatically use StripeIssuingProvider
```

**What Stripe Issuing does:**
- Creates a real Stripe Cardholder (`POP Agent`)
- Issues a virtual card with a spending limit matching the approved amount
- Returns masked card details (last 4 digits only) to the agent
- All Stripe errors are caught and returned as rejection reasons

> **Note:** Stripe Issuing is a premium Stripe product that requires approval. For most development and demo use cases, the Mock provider is sufficient.
