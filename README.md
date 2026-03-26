[English](./README.md) | [Chinese](./README.zh-TW.md)

<p align="center">
    <picture>
        <img src="https://raw.githubusercontent.com/TPEmist/project-aegis/main/project_banner.png" alt="Project Aegis (AgentPay)" width="800">
    </picture>
</p>

# Project Aegis - AgentPay

Project Aegis is a payment guardrail and one-time flow protocol specifically designed for Agentic AI (e.g., OpenClaw, NemoClaw, Claude Code, OpenHands). It enables agents to handle financial transactions safely without risking unlimited exposure of human-controlled credit cards.

## 1. The Problem
When Agentic AI encounters a paywall (e.g., domain registration, API credits, compute scaling) during an automated workflow, it is often forced to stop and wait for human intervention. However, providing a physical credit card directly to an agent introduces a "trust crisis": hallucinations or infinite loops could lead to the card being drained.

## 2. Dual Architecture

Project Aegis is designed with a "Dual Architecture" vision to scale from open-source local experiments to enterprise-grade AI production pipelines.

### 1. Hacker Edition (BYOC + DOM Injection)
Built for open-source frameworks like OpenClaw and NemoClaw. The agent **never** receives the true credit card number—it only sees a masked version (\`****-4242\`). When the agent successfully navigates to a checkout paywall, the Aegis \`AegisBrowserInjector\` attaches to the active Chromium browser via the Chrome DevTools Protocol (CDP). It precisely traverses all cross-origin iframes (like Stripe Elements) and injects the real credentials deep into the DOM form elements, delivering **100% protection against prompt injection** or hallucination-driven extractions. Bring Your Own Card (BYOC) locally with absolute peace of mind.

### 2. Enterprise Edition (Stripe Issuing)
The "North Star" for the broader Agentic SaaS ecosystem. Proving that Aegis has the enterprise-grade extensibility required for the real world, it seamlessly connects to verified financial infrastructure. Perfect for platforms building "Agentic Visa" services that programmatically issue real, single-use, burner virtual credit cards (VCCs) via the Stripe API for cloud-hosted AI fleets.

---

## 3. Ecosystem Position: Aegis + Browser Agents = Unstoppable

Modern agentic workflows require two complementary capabilities. Aegis does one, and does it exceptionally well.

### 🎯 What Aegis Is — and Isn't

**Aegis is the agent's financial brain and safe vault.** It is responsible for:
- ✅ Evaluating whether a purchase *should* happen (semantic guardrails)
- ✅ Enforcing hard budget limits (daily cap, per-transaction cap)
- ✅ Issuing one-time virtual cards so real credentials are never exposed
- ✅ Maintaining a full audit trail of every payment attempt

**Aegis does NOT:**
- ❌ Navigate websites or interact with DOM elements
- ❌ Solve CAPTCHAs or bypass bot-detection systems
- ❌ Fill out forms or click "Submit" on behalf of the agent

That's the browser agent's job.

### 🤝 The Handshake: How Aegis and Browser Agents Work Together

The real power emerges when Aegis is paired with a browser automation agent (e.g., OpenHands, browser-use, Skyvern). The workflow is a clean division of labor:

```
1. [Browser Agent]  Navigates to a site, scrapes product info, reaches checkout.
        │
        │  (Hit a paywall / payment form)
        ▼
2. [Browser Agent → Aegis MCP]  Calls request_virtual_card(amount, vendor, reasoning)
        │
        │  (Aegis evaluates: budget OK? vendor approved? no hallucination?)
        ▼
3. [Aegis]  Issues a one-time virtual card (Stripe mode) or mock card (dev mode)
            Returns masked card number to agent. Full card injected only via
            trusted local execution environment — never into the LLM's context.
        │
        ▼
4. [Browser Agent]  Uses the approved credentials to complete the checkout form.
        │
        ▼
5. [The Vault]  Dashboard logs the transaction. Card is immediately burned.
```

### 🌐 Supported Integrations

| Integration path | Works with |
|---|---|
| **MCP Tool** | Claude Code, OpenClaw, NemoClaw, OpenHands, any MCP-compatible host |
| **Python SDK** | Custom Playwright, browser-use, Skyvern, Selenium, gemini-cli |

> **Claude Code** gets full CDP injection — card is auto-filled into the browser form, the agent never sees the raw number. See the **[Integration Guide](./docs/INTEGRATION_GUIDE.md)** for setup instructions and System Prompt templates.

---

## 4. Installation

```bash
# Core only (keyword guardrail + mock provider, zero external dependencies)
pip install aegis-pay

# With LLM-based guardrails (supports OpenAI, Ollama, vLLM, OpenRouter)
pip install aegis-pay[llm]

# With Stripe virtual card issuing
pip install aegis-pay[stripe]

# With LangChain integration
pip install aegis-pay[langchain]

# Full installation (all features)
pip install aegis-pay[all]
```

## 5. Quick Start for OpenClaw / NemoClaw / Claude Code / OpenHands

If you're using OpenClaw, NemoClaw, Claude Code, OpenHands, or any MCP-compatible agentic framework, you can get Aegis running in under 2 minutes:

### Step 1: Install & Start MCP Server

```bash
# Clone the repo
git clone https://github.com/TPEmist/Project-Aegis.git
cd Project-Aegis

# Install dependencies
uv sync --all-extras

# Start the MCP server
uv run python -m aegis.mcp_server
```

### Step 2: Connect to Your Agent

Choose your platform and follow the dedicated setup guide:

| Platform | Setup Guide |
|---|---|
| **Claude Code** (BYOC + CDP injection, recommended) | [Integration Guide §1](./docs/INTEGRATION_GUIDE.md#1-claude-code--full-setup-with-cdp-injection) |
| **Python script / gemini-cli** | [Integration Guide §2](./docs/INTEGRATION_GUIDE.md#2-gemini-cli--python-script-integration) |
| **Playwright / browser-use / Skyvern** | [Integration Guide §3](./docs/INTEGRATION_GUIDE.md#3-browser-agent-middleware-playwright--browser-use--skyvern) |
| **OpenClaw / NemoClaw** | [Integration Guide §4](./docs/INTEGRATION_GUIDE.md#4-openclaw--nemoclaw--system-prompt-configuration) |
| **OpenHands** | Add `uv run python -m aegis.mcp_server` to your `mcpServers` config |

### Step 3: Configure Your Policy (Environment Variables)

```bash
export AEGIS_ALLOWED_CATEGORIES='["aws", "cloudflare", "openai", "github"]'
export AEGIS_MAX_PER_TX=100.0        # Max $100 per single transaction
export AEGIS_MAX_DAILY=500.0         # Max $500 per day total
export AEGIS_BLOCK_LOOPS=true        # Block hallucination/retry loops
# Optional: export AEGIS_STRIPE_KEY=sk_live_... (see §8 for Stripe setup)
```

> **⚠️  After editing `.env`, restart your agent session** (e.g. close and reopen Claude Code) for the changes to take effect. The MCP server loads configuration once at startup — it does not hot-reload.

#### Guardrail Mode: Keyword vs LLM

Aegis ships with two guardrail engines. You switch between them with a single env var:

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
[Aegis] ✅ Payment approved. Card Issued: ****4242, Expiry: 12/25, Amount: 15.0
Agent: "Purchase successful, continuing workflow."
```

If the agent hallucinates or tries to overspend:
```
Agent: "Let me retry buying compute... the previous attempt failed again."
[Tool Call] request_virtual_card(amount=50.0, vendor="AWS", reasoning="failed again, retry loop")
[Aegis] ❌ Payment rejected. Reason: Hallucination or infinite loop detected in reasoning
```

---

## 6. Core Components

### 🛡️ The Vault
A local visualization console powered by **Streamlit** and **SQLite** (`aegis_state.db`). The Vault allows humans to:
- Monitor all issued seals and agent spending activity in real-time.
- Monitor global budget utilization.
- Audit rejection logs from semantic guardrails.

### 📜 The Seal
Virtual, single-use payment credentials with built-in enforcement:
- **Daily Budget Limit Enforcement**: Automatically blocks any request that would exceed the predefined daily spending cap.
- **Burn-after-use Interception**: Ensures that once a virtual card is used, it is immediately invalidated, preventing replay attacks or unauthorized recurring charges.

### 🧠 Semantic Guardrails
Aegis provides two modes of intent evaluation. Both are controlled by `AEGIS_GUARDRAIL_ENGINE` in your `.env` (see [§5 Step 3](#step-3-configure-your-policy-environment-variables) for full configuration).

1. **Keyword mode** (`AEGIS_GUARDRAIL_ENGINE=keyword`, **default**): The `GuardrailEngine` scans the agent's `reasoning` string for suspicious phrases associated with loops or hallucinations (e.g., `"retry"`, `"failed again"`, `"ignore previous"`). Zero dependencies, zero latency, zero cost. Recommended as the starting point for all setups.

2. **LLM mode** (`AEGIS_GUARDRAIL_ENGINE=llm`): The `LLMGuardrailEngine` sends the agent's `reasoning` to an LLM for deep semantic analysis, catching subtler misuse that keyword matching would miss — such as off-topic purchases or logically inconsistent justifications. Supports **any OpenAI-compatible endpoint**: OpenAI, Ollama (local), vLLM, OpenRouter, and more.

## 7. Security Statement
Security is a first-class citizen in Aegis. The SDK **masks card numbers by default** (e.g., `****-****-****-4242`) when returning authorization results to the agent. This prevents sensitive payment information from leaking into agent chat logs, model context windows, or persistent logs, ensuring that only the execution environment handles the raw credentials.

## 8. The Vault Dashboard

The Vault is your real-time monitoring console for all agent payment activity. 

### Starting the Dashboard

```bash
cd Project-Aegis
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
| **💳 Issued Seals & Activity** | Full table of all payment attempts (approved + rejected) with seal ID, amount, vendor, status, and timestamp |
| **🚫 Rejected Summary** | Filtered view showing only rejected/blocked attempts for quick auditing |

### Tips
- Click **Refresh Data** in the sidebar to pull latest activity from the database.
- The dashboard reads from `aegis_state.db` — the same database the SDK writes to. Keep both running simultaneously for live monitoring.
- Each row in the table corresponds to a single `request_virtual_card` call from an agent.

---

## 9. Python SDK Quickstart

Integrate Aegis into your custom Python or LangChain workflows in just a few lines:

```python
from aegis.client import AegisClient
from aegis.providers.stripe_mock import MockStripeProvider
from aegis.core.models import GuardrailPolicy

# Define your safety policy
policy = GuardrailPolicy(
    allowed_categories=["API", "Cloud", "SaaS"], 
    max_amount_per_tx=50.0, 
    max_daily_budget=200.0,
    block_hallucination_loops=True
)

# Initialize the client with keyword-only guardrails (default)
client = AegisClient(
    provider=MockStripeProvider(), 
    policy=policy,
    db_path="aegis_state.db"
)

# Use with LangChain Tool
from aegis.tools.langchain import AegisPaymentTool
tool = AegisPaymentTool(client=client, agent_id="agent-01")
```

> For LLM guardrail engine setup and the full provider reference, see [Integration Guide §2](./docs/INTEGRATION_GUIDE.md#2-gemini-cli--python-script-integration).

---

## 10. Payment Providers: Stripe vs Mock

### Without Stripe (Default — Mock Provider)

By default, Aegis uses the `MockStripeProvider` which simulates virtual card issuance. This is perfect for:
- **Development and testing** — no real money involved
- **Demo and evaluation** — see the full flow without any API keys
- **Hackathons** — get a working prototype in minutes

Mock cards are fully functional within the Aegis system (budget tracking, burn-after-use, guardrails all work), but they are not real payment instruments.

### BYOC — Bring Your Own Card (Hacker Edition)

For developers who want to use their **own physical credit card** with Aegis without a Stripe account. The `LocalVaultProvider` reads card credentials from environment variables and injects them into browser payment forms via CDP — the raw PAN is never exposed to the agent.

**Set the following environment variables (or copy `.env.example`):**
```bash
export AEGIS_BYOC_NUMBER="4111111111111111"   # Your real card number
export AEGIS_BYOC_CVV="123"
export AEGIS_BYOC_EXPIRY="12/27"
export AEGIS_BYOC_NAME="Your Name"            # Optional: cardholder name
# The MCP server will automatically use LocalVaultProvider
uv run python -m aegis.mcp_server
```

**Provider priority (high → low):** Stripe Issuing → BYOC Local → Mock.

If `AEGIS_STRIPE_KEY` is set, Stripe takes precedence. If `AEGIS_BYOC_NUMBER` is set (but no Stripe key), `LocalVaultProvider` is used. If neither is set, `MockStripeProvider` is used for development.

> **Security note:** Never commit real card numbers to version control. Always use `.env` (which is `.gitignore`d) or a secrets manager. The CDP injection ensures the full card number is only handled by the local trusted process, never by the LLM.

> For Python SDK usage of each provider, see [Integration Guide §2](./docs/INTEGRATION_GUIDE.md#2-gemini-cli--python-script-integration).

### With Real Stripe Issuing

To issue **real virtual credit cards** through [Stripe Issuing](https://stripe.com/issuing):

**Prerequisites:**
1. A Stripe account with [Issuing](https://stripe.com/issuing) enabled (requires application approval)
2. Your Stripe secret key (`sk_live_...` or `sk_test_...`)

**Option A: Via Environment Variable (for MCP Server)**
```bash
export AEGIS_STRIPE_KEY=sk_live_your_stripe_key_here
uv run python -m aegis.mcp_server
# The MCP server will automatically use StripeIssuingProvider
```

**What Stripe Issuing does:**
- Creates a real Stripe Cardholder (`Aegis Agent`)
- Issues a virtual card with a spending limit matching the approved amount
- Returns masked card details (last 4 digits only) to the agent
- All Stripe errors are caught and returned as rejection reasons

> **Note:** Stripe Issuing is a premium Stripe product that requires approval. For most development and demo use cases, the Mock provider is sufficient.
