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

## 3. Core Components

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

## 4. Security Statement
Security is a first-class citizen in Aegis. The SDK **masks card numbers by default** (e.g., `****-****-****-4242`) when returning authorization results to the agent. This prevents sensitive payment information from leaking into agent chat logs, model context windows, or persistent logs, ensuring that only the execution environment handles the raw credentials.

## 5. Integration with Claude Code & OpenHands
Aegis fully supports the **Model Context Protocol (MCP)**. You can integrate our guardrails and card issuance mechanism into your agentic workflow with a single command.

**Start MCP Server:**
```bash
# Claude Code
claude mcp add aegis -- uv run python -m aegis.mcp_server

# Or run directly
uv run python -m aegis.mcp_server
```

**Configure via environment variables:**
```bash
export AEGIS_ALLOWED_CATEGORIES='["aws", "cloudflare", "openai"]'
export AEGIS_MAX_PER_TX=100.0
export AEGIS_MAX_DAILY=500.0
export AEGIS_BLOCK_LOOPS=true
# Optional: set AEGIS_STRIPE_KEY to use real Stripe Issuing
```

**Automated Purchase Example:**
```
Claude: "I found the required dependency, but the repository requires a one-time API key purchase of $15."
User: "Please proceed if necessary, you have Aegis permissions."
[Tool Call] request_virtual_card(amount=15.0, vendor="AWS", reasoning="Need API key for dependency installation")
[Aegis Vault] Request approved. Card Issued: ****4242, Expiry: 12/25...
Claude: "I successfully bypassed the paywall and the installation is complete."
```

## 6. Python SDK Quickstart
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
