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
- **PopBrowserInjector**: Connects out-of-band via Playwright's `connectOverCDP` (not raw WebSocket). Traverses cross-origin iframes (including Stripe Elements sandboxed iframes) and Shadow DOM trees, auto-populating `<input>` and `<select>` elements safely. After injection, the agent clicks the submit button — card credentials are never in the agent's context.
- **PAN encryption at rest**: Card data stored in the state tracker is encrypted with AES-256-GCM. The encryption key is derived from `POP_STATE_ENCRYPTION_KEY` env var or a hostname-based HMAC fallback.
- **Security scan**: Every page is scanned for hidden prompt-injection elements before card injection proceeds.
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
2. Install dependencies:
   ```bash
   uv sync
   ```
3. Initialize the credential vault (card credentials are encrypted at rest — no plaintext `.env` required):
   ```bash
   pop-init-vault
   ```
   This will prompt for your card credentials and encrypt them to `~/.config/pop-pay/vault.enc`.
4. Copy the policy template and configure your local settings:
   ```bash
   cp .env.example ~/.config/pop-pay/.env
   # Edit ~/.config/pop-pay/.env — set allowed vendors, spending limits, CDP URL, etc.
   # Do NOT add card credentials here; they live in the vault.
   ```
   See [docs/CATEGORIES_COOKBOOK.md](./docs/CATEGORIES_COOKBOOK.md) for guidance on configuring `POP_ALLOWED_CATEGORIES`.

### Running Tests
We use `pytest` for our test suite. To run all tests:
```bash
pytest
```

### Schema Changes

`PopStateTracker` (`pop_pay/core/state.py`) is the single source of truth for the SQLite schema. The dashboard (`dashboard/server.py`) delegates all table creation and migration to `PopStateTracker` on startup. If you add or modify a column:

1. Update the `CREATE TABLE` in `PopStateTracker.__init__` so fresh DBs get the new shape.
2. Add a migration branch next to the existing ones (add-column / rebuild) so legacy DBs upgrade in place. **Migrations must be idempotent** — running them on an already-migrated DB must be a no-op.
3. Use ISO 8601 UTC with a `Z` suffix for all timestamps (`datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")`). Do **not** use SQLite `CURRENT_TIMESTAMP`, which is ambiguous about timezone and parses as local time in browsers.
4. Add a regression test in `tests/test_audit_and_migration.py` that constructs a pre-change DB, opens it with `PopStateTracker`, and asserts the new shape.

### Dashboard Port

The local dashboard listens on **port 3210** by default. This number was chosen arbitrarily during initial bring-up; it has no special meaning and is kept stable so existing user bookmarks continue to work. Override with the `--port` flag if you need to run multiple dashboards side-by-side.

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

### 5. Injection Resilience
The `PopBrowserInjector` uses Playwright's `connectOverCDP` for cross-origin iframe traversal and includes Shadow DOM piercing. Contributions are welcome for:
- Dynamic form detection (forms that render after JS load with non-standard field naming)
- Automated test fixtures covering more real-world checkout page structures
- Additional `<select>` dropdown handling for country/state pickers

### 6. Security: Opaque Agent Responses

**Current behavior:** When a payment or billing request is rejected, the MCP tool returns a detailed rejection reason to the agent (e.g. `"Vendor 'X' is not in your allowed categories"`, `"domain_mismatch:attacker.com"`).

**Problem:** Detailed rejection reasons help adversarial agents refine their attacks. An agent that learns *why* it was blocked can adjust its vendor name, reasoning, or navigation to bypass the guardrail on the next attempt. This is analogous to verbose error messages in web authentication enabling user enumeration.

**Desired behavior:**
- **Agent-facing (MCP response):** Always return a single opaque message: `"Payment request blocked by security policy."` — no details about which rule triggered or why.
- **Human-facing (Dashboard / `pop_state.db`):** Full rejection reason, vendor, amount, reasoning, and guardrail layer stored and visible to the operator.

**Implementation notes:**
- `mcp_server.py` `request_virtual_card` and `request_purchaser_info` should catch all rejection/block paths and return the opaque string before returning to the agent.
- `pop_state.db` audit log already stores structured data — the detailed reason should continue to be written there.
- The `rejection_reason` column on `issued_seals` (added in v0.8.0) already surfaces in the Dashboard's REJECTION_LOG table. Any new opaque-response work should continue to write the full reason there while returning the generic string to the MCP caller.
- Edge case: injection failures that require agent action (e.g. "card fields not found — pass page_url") are UX errors, not security rejections, and may still return actionable messages to the agent.

### 7. Known Payment Processors List

`pop_pay/engine/known_processors.py` contains the built-in allowlist of third-party payment processors that are trusted to pass the TOCTOU domain guard. When a vendor's checkout page redirects to one of these domains, pop-pay allows the injection to proceed.

**Contributions welcome:** If you encounter a legitimate payment processor that is not on the list, open a PR that adds it to `KNOWN_PAYMENT_PROCESSORS` in `known_processors.py`. Please include:
- The processor's domain (e.g. `"pay.example.com"`)
- A comment with the processor name and one or two example vendors that use it
- A brief note in the PR description confirming you verified the domain is controlled by the payment processor, not a reseller or affiliate

If you have an idea for a feature or a bug fix, please open an issue or submit a Pull Request!

## Open Discussion: masked_card Encryption

Currently, `masked_card` values (e.g., `****-4242`) are encrypted at rest in SQLite using AES-256-GCM. The dashboard API decrypts them before display.

We're seeking community input on whether this encryption is necessary:
- **Current state**: Masked card values like `****-4242` are encrypted in `pop_state.db` and decrypted on read
- **Argument for keeping**: Defense-in-depth — even masked data gets encryption
- **Argument for removing**: `****-4242` is not PCI-sensitive data (PCI DSS explicitly allows truncated PAN display). Encryption adds complexity and caused a dashboard display bug where raw ciphertext was shown instead of the masked value
- **Note**: Full card numbers are never stored in the database — only the masked form

If you have opinions on this, please open an issue or discussion.
