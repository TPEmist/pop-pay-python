[![PyPI version](https://img.shields.io/pypi/v/pop-pay.svg)](https://pypi.org/project/pop-pay/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![CI](https://github.com/100xPercent/pop-pay-python/actions/workflows/test.yml/badge.svg)](https://github.com/100xPercent/pop-pay-python/actions/workflows/test.yml) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

<p align="center">
    <picture>
        <img src="https://raw.githubusercontent.com/100xPercent/pop-pay-python/main/project_banner.png" alt="Point One Percent (AgentPay)" width="800">
    </picture>
</p>

# Point One Percent — pop-pay
<p align="left"><i>it only takes <b>0.1%</b> of Hallucination to drain <b>100%</b> of your wallet.</i></p>

The runtime security layer for AI agent commerce. Card credentials are injected directly into the browser DOM via CDP — they never enter the agent's context window. One hallucinated prompt can't drain a wallet it can't see.

<p align="center">
  <img src="https://raw.githubusercontent.com/100xPercent/pop-pay-python/main/assets/runtime_demo.gif" alt="Point One Percent — live CDP injection demo" width="800">
</p>

## Getting Started

Install the core package with MCP support:

```bash
pip install "pop-pay[mcp]"
```

<details>
<summary>Claude Code</summary>

```bash
claude mcp add pop-pay -- python3 -m pop_pay.mcp_server
```

With environment variables:

```bash
claude mcp add pop-pay \
  -e POP_CDP_URL=http://localhost:9222 \
  -e POP_ALLOWED_CATEGORIES='["aws","cloudflare"]' \
  -e POP_MAX_PER_TX=100.0 \
  -e POP_MAX_DAILY=500.0 \
  -e POP_GUARDRAIL_ENGINE=keyword \
  -- python3 -m pop_pay.mcp_server
```

</details>

<details>
<summary>OpenClaw / NemoClaw</summary>

Compatible with any MCP host. See the [Integration Guide](./docs/INTEGRATION_GUIDE.md) for setup instructions and System Prompt templates.

</details>

<details>
<summary>Docker</summary>

```bash
docker-compose up -d
```

Runs the MCP server + headless Chromium with CDP. Mount your encrypted vault from the host. See `docker-compose.yml` for configuration.

</details>

<details>
<summary>Other installation variants</summary>

```bash
# Core only (keyword guardrail + mock provider)
pip install "pop-pay"

# With CDP injection (browser automation)
pip install "pop-pay[mcp,browser]"

# With LLM-based guardrails (OpenAI, Ollama, vLLM, OpenRouter)
pip install "pop-pay[mcp,llm]"

# With Stripe virtual card issuing
pip install "pop-pay[stripe]"

# With LangChain integration
pip install "pop-pay[langchain]"

# Full installation (all features)
pip install "pop-pay[all]"
```

</details>

## Vault Setup

Credentials are stored in an AES-256-GCM encrypted vault — plaintext card data never touches disk.

```bash
pop-init-vault
```

**Passphrase mode** (recommended — protects against agents with shell access):

```bash
pop-init-vault --passphrase   # one-time setup
pop-unlock                     # run once before each MCP session
```

`pop-unlock` derives the key from your passphrase and stores it in the OS keyring. The MCP server reads it automatically at startup.

## MCP Tools

| Tool | Description |
|:---|:---|
| `request_virtual_card` | Issue a virtual card and inject credentials into the checkout page via CDP. |
| `request_purchaser_info` | Auto-fill billing/contact info (name, address, email, phone). |
| `request_x402_payment` | Pay for API calls via the x402 HTTP payment protocol. |
| `page_snapshot` | Scan a checkout page for hidden prompt injections or anomalies. |

## Configuration

Core variables in `~/.config/pop-pay/.env`. See [ENV_REFERENCE.md](./docs/ENV_REFERENCE.md) for the full list.

| Variable | Default | Description |
|---|---|---|
| `POP_ALLOWED_CATEGORIES` | `["aws","cloudflare"]` | Approved vendor categories — see [Categories Cookbook](./docs/CATEGORIES_COOKBOOK.md) |
| `POP_MAX_PER_TX` | `100.0` | Max USD per transaction |
| `POP_MAX_DAILY` | `500.0` | Max USD per day |
| `POP_BLOCK_LOOPS` | `true` | Block hallucination/retry loops |
| `POP_AUTO_INJECT` | `true` | Enable CDP card injection |
| `POP_GUARDRAIL_ENGINE` | `keyword` | `keyword` (zero-cost) or `llm` (semantic) |

### Guardrail Mode

| | `keyword` (default) | `llm` |
|---|---|---|
| **Mechanism** | Keyword matching on reasoning string | Semantic analysis via LLM |
| **Cost** | Zero — no API calls | One LLM call per request |
| **Best for** | Development, low-risk workflows | Production, high-value transactions |

> To enable LLM mode, see [Integration Guide §1](./docs/INTEGRATION_GUIDE.md#guardrail-mode-configuration).

## Providers

| Provider | Description |
|:---|:---|
| **BYOC** (default) | Bring Your Own Card — encrypted vault credentials, local CDP injection. |
| **Stripe Issuing** | Real virtual cards via Stripe API. Requires `POP_STRIPE_KEY`. |
| **Lithic** | Multi-issuer adapter (Stripe Issuing / Lithic). |
| **Mock** | Test mode with generated card numbers for development. |

**Priority:** Stripe Issuing → BYOC Local → Mock.

## Dashboard

The Vault Dashboard provides real-time monitoring of all agent payment activity, budget utilization, and rejection logs.

```bash
uv run streamlit run dashboard/app.py
# Opens at http://localhost:8501
```

## Python SDK

Integrate pop-pay into custom Python or LangChain workflows:

```python
from pop_pay.client import PopClient
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.core.models import GuardrailPolicy

client = PopClient(
    provider=MockStripeProvider(),
    policy=GuardrailPolicy(
        allowed_categories=["API", "Cloud"],
        max_amount_per_tx=50.0,
        max_daily_budget=200.0,
    ),
)

# LangChain integration
from pop_pay.tools.langchain import PopPaymentTool
tool = PopPaymentTool(client=client, agent_id="agent-01")
```

> See [Integration Guide §2](./docs/INTEGRATION_GUIDE.md#2-gemini-cli--python-script-integration) for the full SDK and provider reference.

## Security

| Layer | Defense |
|---|---|
| **Context Isolation** | Card credentials never enter the agent's context window or logs |
| **Encrypted Vault** | AES-256-GCM with PBKDF2 key derivation and OS keyring integration |
| **TOCTOU Guard** | Domain verified at the moment of CDP injection — blocks redirect attacks |
| **Repr Redaction** | Automatic masking (`****-4242`) in all MCP responses, logs, and tracebacks |

See [THREAT_MODEL.md](./docs/THREAT_MODEL.md) for the full STRIDE analysis and [COMPLIANCE_FAQ.md](./docs/COMPLIANCE_FAQ.md) for enterprise details.

## Architecture

- **Python** — Core engine, MCP server, guardrail logic, CLI
- **Cython** — Performance-critical vault operations and memory protection
- **Chrome DevTools Protocol** — Direct DOM injection via raw WebSocket
- **SQLite** — Local transaction auditing and state management

## Documentation

- [Threat Model](docs/THREAT_MODEL.md) — STRIDE analysis, 5 security primitives, 10 attack scenarios
- [Guardrail Benchmark](docs/THREAT_MODEL.md#guardrail-benchmark) — 95% accuracy across 20 test scenarios
- [Compliance FAQ](docs/COMPLIANCE_FAQ.md) — PCI DSS, SOC 2, GDPR details
- [Environment Reference](docs/ENV_REFERENCE.md) — All POP_* environment variables
- [Integration Guide](docs/INTEGRATION_GUIDE.md) — Setup for Claude Code, Python SDK, and browser agents
- [Categories Cookbook](docs/CATEGORIES_COOKBOOK.md) — POP_ALLOWED_CATEGORIES patterns and examples

## License

MIT
