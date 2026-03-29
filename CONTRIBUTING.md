# Contributing to Point One Percent (AgentPay)

Thank you for your interest in contributing to Point One Percent! This project aims to provide an autonomous payment layer for AI agents, where human-defined policy replaces per-transaction approval, ensuring that agents can perform financial transactions fully autonomously within the guardrails and budget limits set by the human operator.

## Project Architecture

Point One Percent is built on three core pillars that work together to provide a fully autonomous, policy-governed payment experience:

### The Vault (Visualization & Management)
The Vault is our local dashboard and state management system.
- **Console:** A Streamlit-powered dashboard (`dashboard/app.py`) for real-time monitoring of agent spending and issued seals.
- **State:** A local SQLite database (`pop_state.db`) that tracks every transaction, audit log, and budget status.

### The Seal (Virtual Transaction Unit)
The Seal is the fundamental unit of authorization in Point One Percent.
- When an agent requests a payment, Point One Percent issues a `VirtualSeal`.
- A `VirtualSeal` contains the virtual card details (pan, cvv, expiry) or a rejection reason.
- Seals are tracked in the Vault to prevent reuse and ensure transparency.

### Semantic Guardrails (Policy & Enforcement)
Guardrails are the "brains" that decide whether a payment should be approved or rejected based on the agent's context.
- **GuardrailEngine:** A fast, keyword-based interceptor that blocks common failure patterns (e.g., loops, hallucinations).
- **LLMGuardrailEngine:** A deep semantic analyzer (powered by GPT-4o-mini) that evaluates the agent's reasoning against the requested `GuardrailPolicy`.
- **GuardrailPolicy:** A set of rules (e.g., `max_amount`, `allowed_vendors`, `purpose_description`) defined by the human user.

### Browser Injector (Autonomous Fulfillment)
For agent frameworks evaluating DOMs, Point One Percent autonomously fulfills authorized payments without leaking the card directly to the LLM. Once the policy and guardrails approve a request, the injection and submission happen without any per-transaction human confirmation.
- **PopBrowserInjector**: Connects strictly out-of-band via CDP (`Chrome DevTools Protocol`). Traverses cross-origin iframes (i.e. Stripe Elements) and auto-populates `<input>` elements safely. After injection, the agent clicks the submit button — this is a standard browser interaction, not a security concern, since card credentials are never in the agent's context.
- **Chrome must be launched with `--remote-debugging-port=9222`** before the injector can attach. Use `--user-data-dir` as well if Chrome is already running (required to open a separate CDP-enabled instance).
- **When using Playwright MCP** (e.g., with Claude Code), configure it with `--cdp-endpoint http://localhost:9222` so that both Playwright MCP and Point One Percent MCP share the same Chrome instance. See [docs/INTEGRATION_GUIDE.md §1](./docs/INTEGRATION_GUIDE.md#1-claude-code--full-setup-with-cdp-injection) for the full setup.

---

## Local Development Setup

We use `uv` for lightning-fast Python package management.

### Prerequisites
- Install **uv**:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### Setup
1. Clone the repository.
2. Copy the provided environment variable reference and configure your local settings:
   ```bash
   cp .env.example .env
   # Edit .env and fill in any credentials you need (BYOC card, Stripe key, etc.)
   ```
3. Run `uv sync` to create a virtual environment and install all dependencies (including dev tools).
   ```bash
   uv sync
   ```

### Running Tests
We use `pytest` for our test suite. To run all tests:
```bash
pytest
```

---

## Call for Contributions

We are actively looking for community help to expand the Point One Percent ecosystem. Specifically, we are looking for:

### 1. New Payment Providers
Help us expand the range of virtual cards Point One Percent can issue by implementing new providers in `pop_pay/providers/`:
- **CoinbaseWalletProvider:** Enable agents to spend via USDC or other crypto-backed virtual cards.
- **PrivacyComProvider:** Integration with Privacy.com for consumer-grade virtual card issuance.

### 2. Dashboard Enhancements
The Vault needs more robust management features:
- **Real Budget-writeback logic:** Currently, the Max Daily Budget slider in the Dashboard is temporary. We need logic to save and persist these limits to the `pop_state.db` and enforce them within the `PopClient`.

### 3. Guardrail Improvements
- New semantic analysis patterns for the `LLMGuardrailEngine`.
- Integration with other LLM providers (Anthropic, local models via Ollama).
- Additional guardrail rules for detecting credential-harvesting prompts or unusual spending velocity patterns.

### 4. Injection Observability
Based on real-world agent testing, two observability gaps have been identified:
- **Billing field confirmation**: When `PopBrowserInjector` auto-fills billing fields (name, address, email), the agent has no way to confirm what was filled without taking a screenshot. The `request_virtual_card` MCP tool should return a summary of which fields were filled and with what values (excluding the card number itself).
- **Injection failure transparency**: If card field injection fails (e.g. payment form not found, iframe traversal issue), the MCP tool currently returns a generic error. More granular failure codes would help agents diagnose and report the correct remediation to users.

### 5. CDP Injection Resilience
The `PopBrowserInjector` handles most common checkout forms and cross-origin Stripe iframes. Contributions are welcome for:
- Shadow DOM traversal (web components used by some payment processors)
- Dynamic form detection (forms that render after JS load with non-standard field naming)
- Automated test fixtures covering more real-world checkout page structures

If you have an idea for a feature or a bug fix, please open an issue or submit a Pull Request!
