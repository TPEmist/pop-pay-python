[English](./README.md) | [繁體中文](./README.zh-TW.md)

# Project Aegis (AgentPay)

Project Aegis is a payment guardrail and one-time flow protocol specifically designed for Agentic AI (e.g., Claude Code, OpenHands). It enables agents to handle financial transactions safely without risking unlimited exposure of human-controlled credit cards.

## 1. The Problem
When Agentic AI encounters a paywall (e.g., domain registration, API credits, compute scaling) during an automated workflow, it is often forced to stop and wait for human intervention. However, providing a physical credit card directly to an agent introduces a "trust crisis": hallucinations or infinite loops could lead to the card being drained.

## 2. Installation

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

## 3. Quick Start for OpenHands / Claude Code Users

If you're using OpenHands, Claude Code, or any MCP-compatible agentic framework, you can get Aegis running in under 2 minutes:

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

**Claude Code:**
```bash
claude mcp add aegis -- uv run python -m aegis.mcp_server
```

**OpenHands:** Add to your MCP configuration:
```json
{
  "mcpServers": {
    "aegis": {
      "command": "uv",
      "args": ["run", "python", "-m", "aegis.mcp_server"],
      "cwd": "/path/to/Project-Aegis"
    }
  }
}
```

### Step 3: Configure Your Policy (Environment Variables)

```bash
export AEGIS_ALLOWED_CATEGORIES='["aws", "cloudflare", "openai", "github"]'
export AEGIS_MAX_PER_TX=100.0        # Max $100 per single transaction
export AEGIS_MAX_DAILY=500.0         # Max $500 per day total
export AEGIS_BLOCK_LOOPS=true        # Block hallucination/retry loops
# Optional: export AEGIS_STRIPE_KEY=sk_live_... (see §8 for Stripe setup)
```

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

## 4. Core Components

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
Aegis provides two modes of intent evaluation to prevent agents from wasting funds:
1. **Fast Keyword-based Interception** (Default): Uses the `GuardrailEngine` to immediately block requests containing keywords associated with loops or hallucinations (e.g., "retry", "failed again", "ignore previous"). Zero dependencies, zero cost.
2. **LLM-based Guardrail Engine**: Powered by the `LLMGuardrailEngine`, this mode performs deep semantic analysis of the agent's reasoning to detect unrelated purchases or logical inconsistencies. Supports **any OpenAI-compatible endpoint** — including local models via Ollama/vLLM, or cloud providers like OpenAI and OpenRouter.

## 5. Security Statement
Security is a first-class citizen in Aegis. The SDK **masks card numbers by default** (e.g., `****-****-****-4242`) when returning authorization results to the agent. This prevents sensitive payment information from leaking into agent chat logs, model context windows, or persistent logs, ensuring that only the execution environment handles the raw credentials.

## 6. The Vault Dashboard

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

## 7. Python SDK Quickstart

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

# Or use LLM-based guardrails with a local model (e.g., Ollama)
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

# Use with LangChain Tool
from aegis.tools.langchain import AegisPaymentTool
tool = AegisPaymentTool(client=client, agent_id="agent-01")
```

### Supported LLM Providers

| Provider | `base_url` | `model` |
|---|---|---|
| OpenAI (default) | *(not needed)* | `gpt-4o-mini` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.2` |
| vLLM / LM Studio | `http://localhost:8000/v1` | Your model name |
| OpenRouter | `https://openrouter.ai/api/v1` | `anthropic/claude-3-haiku` |
| Any OpenAI-compatible | Your endpoint URL | Your model name |

---

## 8. Payment Providers: Stripe vs Mock

### Without Stripe (Default — Mock Provider)

By default, Aegis uses the `MockStripeProvider` which simulates virtual card issuance. This is perfect for:
- **Development and testing** — no real money involved
- **Demo and evaluation** — see the full flow without any API keys
- **Hackathons** — get a working prototype in minutes

Mock cards are fully functional within the Aegis system (budget tracking, burn-after-use, guardrails all work), but they are not real payment instruments.

```python
from aegis.providers.stripe_mock import MockStripeProvider

client = AegisClient(
    provider=MockStripeProvider(),  # No API key needed
    policy=policy
)
```

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

**Option B: Via Python SDK**
```python
from aegis.providers.stripe_real import StripeIssuingProvider

client = AegisClient(
    provider=StripeIssuingProvider(api_key="sk_live_your_stripe_key_here"),
    policy=policy
)
```

**What Stripe Issuing does:**
- Creates a real Stripe Cardholder (`Aegis Agent`)
- Issues a virtual card with a spending limit matching the approved amount
- Returns masked card details (last 4 digits only) to the agent
- All Stripe errors are caught and returned as rejection reasons

> **Note:** Stripe Issuing is a premium Stripe product that requires approval. For most development and demo use cases, the Mock provider is sufficient.
