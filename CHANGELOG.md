# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.7] - 2026-04-01

### Fixed
- **Vendor name matching:** Multi-word allowed categories (e.g. `"Maker Faire"`) now correctly match vendor names like `"Maker Faire Bay Area 2026"` using token-subset logic. Replaced unsafe substring check with token-subset check.
- **Tool descriptions:** `request_purchaser_info` and `request_virtual_card` now explicitly state that the agent should never ask the user for personal info — pop-pay auto-fills from stored config.
- **System prompt template:** Condensed to 6 lines while preserving all critical agent behavior rules.

## [0.6.6] - 2026-04-01

### Added
- **`request_purchaser_info` MCP tool:** Fills billing/contact fields (name, email, phone, address) on purchaser info pages without issuing a card or touching the payment/budget system. Designed for two-page checkout flows where billing and payment are on separate pages. Includes the same TOCTOU domain guard and vendor whitelist check as `request_virtual_card`. Single-page checkouts (e.g. Wikipedia donate) continue to use only `request_virtual_card`.
- **`POP_BILLING_PHONE` env var:** E.164 format phone number (`+14155551234`) for auto-filling phone fields on checkout pages. Added to `.env.example`, `pop-init-vault` template, and injector.

### Changed
- `request_virtual_card` docstring clarified: call this only when card fields are visible; billing fields are auto-filled on the same page as a side effect.

## [0.6.5] - 2026-04-01

### Security
- **Removed `get_compiled_salt()` stub:** The function was removed from Python in v0.6.1 but a dead-code stub returning `None` survived in the compiled Cython `.so`. Removed from source to eliminate dead code. No security impact (the stub returned `None`), but clean removal closes the gap between intent and implementation.

### Testing
- **Red team validation (v0.6.4 PyPI build):** Formal test of all five attack vectors against the published Cython wheel confirmed: `derive_key()` is callable from Python but the salt never surfaces (attacker gets the derived key, not the secret salt — reversing the salt requires Ghidra/IDA Pro binary analysis); `_A1`/`_B2` XOR constants are not accessible from Python; downgrade attack blocked by `.vault_mode` marker; `.vault_mode` tampering causes decryption failure (wrong key path). Full results in SECURITY.md.

## [0.6.4] - 2026-03-31

### Security
- **Vault-embedded mode marker:** `.vault_mode` file records whether vault was created with a hardened PyPI build or OSS public salt. `load_vault()` and `pop-init-vault` both check this marker — if vault is marked `hardened` but the Cython `.so` is missing, the system refuses to decrypt or overwrite rather than silently falling back to the weaker OSS salt.
- **Downgrade attack hardening in `pop-init-vault`:** Replaces the bypassable `POP_STRICT_MODE` env-var check with the tamper-evident `.vault_mode` marker. An agent with shell access cannot bypass protection by unsetting an environment variable — the marker file itself must be manually deleted (an observable action) to override.
- **Removed `POP_STRICT_MODE`:** Env-var-based strict mode was bypassable via `unset POP_STRICT_MODE`. Protection is now structural, not configuration-dependent.

## [0.6.3] - 2026-03-31

### Security
- **Downgrade attack prevention:** `POP_STRICT_MODE=1` env var refuses vault decryption if Cython hardened build is unavailable — prevents attacker from deleting `.so` to force re-initialization with weak OSS salt.
- **Salt memory cleanup:** Reconstructed salt stored in `bytearray` and zeroed immediately after `scrypt` call.
- **Obfuscated variable names:** XOR pair variables renamed from descriptive to non-descriptive names to raise binary reverse engineering cost.

## [0.6.2] - 2026-03-31

### Security
- **XOR obfuscation:** Compiled salt now stored as two XOR-paired integer lists in the `.so` binary. Neither list alone reveals the salt; reconstruction happens only inside `derive_key()` at runtime. Defeats `strings` static binary scanning.

## [0.6.1] - 2026-03-31

### Security
- **Critical fix:** Compiled salt no longer exposed via `get_compiled_salt()`. Key derivation now happens entirely inside the Cython `.so` — the salt never crosses the Python boundary. An attacker with shell access can call `derive_key()` but cannot retrieve the salt itself.

## [0.6.0] - 2026-03-31

### Security
- **Passphrase vault mode:** Agent with shell access cannot decrypt vault without knowing the passphrase; passphrase never stored on disk
- **TOCTOU injection guard:** `inject_payment_info` now verifies the current page domain matches the guardrail-approved vendor before injecting credentials — blocks redirect-to-attacker attacks between approval and injection
- **SQLite CVV removal:** `issued_seals` table no longer stores `card_number` or `cvv` columns. Only `masked_card` (e.g. `****-****-****-4242`) is persisted. An agent with file-read access to `pop_state.db` can no longer retrieve real card credentials via SQL.
- **Vault encryption at rest:** New `vault.py` provides AES-256-GCM encrypted credential storage in `~/.config/pop-pay/vault.enc`. Key is machine-derived via scrypt; plaintext credentials never touch disk after `pop-init-vault` completes.
- **Injector credential isolation:** `inject_payment_info()` now receives card credentials as parameters from the in-memory `VirtualSeal` object, not by fetching them from the database. `get_seal_details()` removed entirely.
- **VirtualSeal repr redaction:** `__repr__` and `__str__` on `VirtualSeal` always emit `****-REDACTED` for `card_number` and `***` for `cvv`, preventing accidental credential logging.
- **Core dump prevention:** `mcp_server.py` disables core dumps at startup via `resource.setrlimit(RLIMIT_CORE, (0, 0))` to prevent credentials appearing in crash dumps.

### Added
- **`pop-unlock` CLI command:** Derives vault key from passphrase and stores in OS keyring; MCP server auto-reads at startup — enables passphrase-protected autonomous sessions
- **`pop-init-vault --passphrase` flag:** Initialize vault with passphrase encryption (PBKDF2-HMAC-SHA256, 600k iterations) for stronger protection than machine-derived key
- **`pop_pay/vault.py`:** AES-256-GCM encrypted credential vault with machine-derived scrypt key, atomic write, and OSS security notice.
- **`pop_pay/cli_vault.py`:** Interactive `pop-init-vault` CLI command — prompts for card credentials, encrypts them, optionally wipes `.env`.
- **`pop-init-vault` entry point:** New CLI script registered in `pyproject.toml`.
- **`vault` optional dependency group:** `pip install 'pop-pay[vault]'` pulls in `cryptography`.
- **`passphrase` optional dependency group:** `pip install 'pop-pay[passphrase]'` pulls in `keyring`.
- **Cython build pipeline:** `_vault_core.pyx` Cython extension for compiled key derivation; PyPI wheels include compiled `.so` with CI-injected secret salt; source builds fall back to `_vault_core_fallback.py` with public salt
- **GitHub Actions `build-wheels.yml`:** cibuildwheel workflow for multi-platform wheel builds (Linux x86_64/aarch64, macOS x86_64/arm64, Windows)
- **`pop-pay init-vault --hardened`:** Runtime indicator showing whether compiled (PyPI) or OSS salt is in use

## [0.5.9] - 2026-03-28

### Security
- **`.env` path hardening:** `mcp_server.py` now reads from `~/.config/pop-pay/.env` first — this location is outside the agent's working directory, preventing agent file-read tools from accessing card credentials. Falls back to standard dotenv cwd search only if the config file does not exist. Users should migrate to `~/.config/pop-pay/.env`.
- **System prompt template:** Added three explicit rules to the recommended CLAUDE.md/system prompt snippet: NEVER read `.env` files, ONLY use `request_virtual_card` for payments, stop and report if pop-pay MCP is unavailable.
- **LLM guardrail crash fix:** `openai.OpenAIError` reference in `evaluate_intent` now correctly uses `self._openai.OpenAIError` (lazy import was applied in v0.5.8 but this exception handler was missed).

### Docs
- Updated all `.env` path references in README, INTEGRATION_GUIDE.md, and INTEGRATION_GUIDE.zh-TW.md from `~/pop-pay/.env` to `~/.config/pop-pay/.env`

## [0.5.8] - 2026-03-31

### Security
- **HybridGuardrailEngine:** `POP_GUARDRAIL_ENGINE=llm` now runs Layer 1 keyword check first before invoking the LLM — obvious attacks are rejected instantly without spending API tokens
- **LLM prompt isolation:** Agent `reasoning` is now wrapped in `<agent_reasoning>` XML tags to reduce prompt injection surface in LLM guardrail mode
- **Domain cross-validation:** When `page_url` is provided, pop-pay validates the URL's domain against known vendor domains (AWS, GitHub, Cloudflare, OpenAI, Stripe, Anthropic, Wikipedia, and others) — mismatched domains are rejected to block phishing attacks
- **Injection pattern detection:** Layer 1 now blocks JSON-like structures, role injection (`you are now`), instruction overrides (`ignore all previous`), and false pre-approval claims in agent reasoning

### Added
- **`page_url` parameter on `request_virtual_card`:** Optional URL for domain cross-validation; pass `page.url` from Playwright MCP
- **`POP_EXTRA_BLOCK_KEYWORDS` env var:** Comma-separated list of custom keywords to extend the built-in Layer 1 blocklist
- **`scripts/demo_cdp_injection.py`:** Terminal + browser demo script for recording the CDP injection flow as a GIF

### Fixed
- **Vendor matching bug:** Replaced substring matching (`"ai" in "mail"` → True) with token-based intersection; fixes false-positive vendor approvals
- **LangChain card masking:** Added null check on `seal.card_number` before masking; handles pre-masked Stripe Issuing format (`****4242`) without crash
- **Input validation:** Added `max_length` constraints to `PaymentIntent` (`target_vendor`: 200, `reasoning`: 2000) to prevent oversized LLM payloads

### Docs
- Updated `POP_GUARDRAIL_ENGINE` documentation to reflect hybrid two-layer behavior
- Added `request_virtual_card` parameter table with `page_url` and domain validation notes
- Added `POP_EXTRA_BLOCK_KEYWORDS` to `.env` reference section

## [0.5.7] - 2026-03-29

### Changed
- **Class renames (breaking):** All `Aegis*` class names replaced with `Pop*` to align with the `pop-pay` package name:
  - `AegisClient` → `PopClient`
  - `AegisBrowserInjector` → `PopBrowserInjector`
  - `AegisStateTracker` → `PopStateTracker`
  - `AegisPaymentInput` → `PopPaymentInput`
  - `AegisPaymentTool` → `PopPaymentTool`
- **MCP server name:** `FastMCP("pop-vault")` → `FastMCP("pop-pay")`
- **README / docs:** Full pip-only quick start — venv setup, `.env` location, quotes requirement, `[mcp,browser]` / `[mcp,llm]` extras, `pop-launch --print-mcp` replaces hardcoded `claude mcp add` commands, session restart requirement documented
- **README.pypi.md:** Quick Start Step 1 was incorrectly showing `git clone` — now correctly shows `pip install` flow
- All `uv run python -m pop_pay.mcp_server` → `python -m pop_pay.mcp_server` in user-facing docs

### Added
- `tests/test_rename_smoke.py`: Smoke tests verifying all renamed classes import and function correctly

## [0.5.6] - 2026-03-28

### Fixed
- `pop-launch --print-mcp`: call site still passing `project_root` after signature change — removed stale argument.

## [0.5.5] - 2026-03-28

### Fixed
- `mcp_server.py`: `StripeIssuingProvider` import made lazy — `pip install "pop-pay[mcp]"` no longer crashes with `ModuleNotFoundError: No module named 'stripe'` when the `[stripe]` extra is not installed.
- `pop-launch --print-mcp`: MCP server command now uses `sys.executable` instead of hardcoded `uv run --project <path>`, making it correct for pip venv installs.

## [0.5.4] - 2026-03-27

### Changed
- **README Quick Start**: Replaced `git clone` + `uv sync` path with `pip install pop-pay[mcp]` + `python -m pop_pay.mcp_server`. Git clone path moved to CONTRIBUTING.md (development only). `.env` is read from the current working directory — no source code needed.

## [0.5.3] - 2026-03-26

### Changed
- **PyPI README**: Removed language toggle; English-first presentation for international audience.

## [0.5.2] - 2026-03-26

### Changed
- **Product vision clarified**: Point One Percent is an autonomous payment layer — human-defined policy replaces per-transaction approval. Updated README, CONTRIBUTING, and Integration Guide to reflect this.
- **README workflow**: POP injects credentials via CDP; agent clicks submit (no card exposure); agent receives transaction confirmation only, no masked card number.
- **README "does NOT" list**: Removed "Fill out forms or click Submit" — POP's CDP injection *does* handle form filling.
- **CONTRIBUTING**: Replaced "Human-in-the-Loop" framing with "fully autonomous, policy-governed payment experience".
- **Integration Guide (EN + zh-TW)**: All four "Your First Live Test" sections now clarify that `"do not submit"` is for initial testing only; removing it enables fully autonomous payments.

## [0.5.1] - 2026-03-26

### Changed
- **Integration Guide**: Added "Your First Live Test" section at the end of all four integration patterns (Claude Code, Python SDK, Browser Agent, OpenClaw/NemoClaw) with concrete first-run prompts and expected outcomes.
- **Integration Guide**: Documented that updating `.env` only requires starting a new agent session — no need to remove and re-register the MCP.

## [0.5.0] - 2026-03-26

### Changed
- **Project renamed**: "Project Aegis" → "Point One Percent"; PyPI package `aegis-pay` → `pop-pay`; Python module `aegis` → `pop_pay`; env vars `AEGIS_*` → `POP_*`; CLI `aegis-launch` → `pop-launch`; DB file `aegis_state.db` → `pop_state.db`; MCP server name `aegis` → `pop`.
- **Tagline added**: "it only takes 0.1% of Hallucination to drain 100% of your wallet."
- **GitHub repo**: https://github.com/TPEmist/Point-One-Percent

## [0.4.0] - 2026-03-25

### Fixed
- **BYOC env vars**: Corrected docs (`AEGIS_BYOC_EXPIRY` → `AEGIS_BYOC_EXP_MONTH` + `AEGIS_BYOC_EXP_YEAR`) to match actual code in `byoc_local.py`. Removed undocumented `AEGIS_BYOC_NAME` from all docs.
- **Stripe SDK compatibility**: `test_stripe_real.py` now uses `stripe.StripeError` instead of the removed `stripe.error.StripeError` path (stripe SDK v6+).
- **Null guard on card_number**: `mcp_server.py` no longer crashes with `TypeError` when `seal.card_number` is `None`.
- **StripeIssuingProvider async safety**: Blocking `stripe.issuing.*` calls are now wrapped in `asyncio.to_thread()` to avoid blocking the event loop.
- **StripeIssuingProvider Cardholder deduplication**: Cardholder ID is now cached per-instance; no longer creates a new Cardholder on every `issue_card` call.

### Added
- **`pop_pay.__version__`**: Package version is now accessible via `import pop_pay; pop_pay.__version__`.

### Removed
- **No-op test**: Removed `test_llm_guardrails_error_handling` which contained only `pass` and tested nothing.
- **`AEGIS_UNMASK_CARDS` CHANGELOG entry**: This feature was announced prematurely in v0.3.7 but never implemented. It has been removed from the changelog as it would expose real card numbers to the LLM context in BYOC mode — violating the core security design of Aegis.

## [0.3.7] - 2026-03-25
### Added
- **`page_url` parameter for `request_virtual_card`**: Optional parameter that lets the agent pass the current checkout URL. If the CDP browser has no open tabs (e.g., Chrome was restarted mid-session), Aegis auto-opens the URL before injecting. Eliminates the need for manual tab management.
- **`AegisBrowserInjector._find_best_page`**: Searches all browser contexts (not just `contexts[0]`) for a checkout page, preferring URLs containing payment/checkout keywords. Fixes injection failures when Playwright MCP creates pages in a non-default context.
- **`AegisBrowserInjector._open_url_in_browser`**: Opens a URL as a new tab in the CDP browser and waits for the payment form JS to initialise. Used by the `page_url` auto-bridge path.

### Fixed
- **MCP server loads `.env` at startup**: Added `load_dotenv()` call at the top of `mcp_server.py` so environment variables (including `AEGIS_ALLOWED_CATEGORIES`, `AEGIS_AUTO_INJECT`, etc.) are correctly read from `.env` without requiring shell-level exports.
- **Injection failure error message**: Now explains the most likely cause (two separate browser instances) and the fix (`page_url` parameter or `--cdp-endpoint` config), instead of a generic "could not find card fields" message.

### Changed
- **Docs — `--scope global` → `--scope user`**: `global` is not a valid Claude Code scope; corrected to `user` (`~/.claude.json`) in both INTEGRATION_GUIDE.md and INTEGRATION_GUIDE.zh-TW.md.
- **Docs — Setup flow clarified**: One-time setup vs per-session steps are now clearly separated. Agent is responsible for checking/starting Chrome via `aegis-launch`; the `--print-mcp` step is called out as one-time only.
- **Docs — Removed redundant `request_virtual_card` call example**: `page_url` usage is covered by the tool docstring and the system prompt template; the separate doc section was duplicate and aimed at the wrong audience.

## [0.3.6] - 2026-03-25
### Added
- **`aegis-launch` CLI**: One-command Chrome CDP launcher. Auto-discovers Chrome on macOS/Linux/Windows, launches with `--remote-debugging-port` and `--user-data-dir`, polls until ready, and prints the exact `claude mcp add` commands for your machine. Options: `--port`, `--url`, `--profile-dir`, `--print-mcp`.
- **Billing field auto-fill**: `AegisBrowserInjector` now fills billing detail fields (first name, last name, street, zip, email) from `AEGIS_BILLING_*` env vars in the main page frame, in the same CDP pass as card injection. Returns `{"card_filled": bool, "billing_filled": bool}`.

### Fixed
- **`inject_payment_info` return type**: Changed from `bool` to `dict` with `card_filled` and `billing_filled` keys. Backwards-compatible (`bool(result)` still works via truthiness of `card_filled`).
- **Test assertion updated**: `test_injector_no_fields_returns_false` updated to assert the dict return value.

### Changed
- **Docs restructure**: README slimmed to landing page; INTEGRATION_GUIDE promoted to canonical setup reference with Claude Code as §1, `aegis-launch` as primary Step 0 (manual Chrome launch folded into `<details>`).
- **Guardrail mode docs**: Full `keyword` vs `llm` comparison table and LLM config options (OpenAI / Ollama / OpenRouter) moved to INTEGRATION_GUIDE §1 as the single source of truth.

## [0.3.4] - 2026-03-25
### Fixed
- **BYOC Provider Wiring**: `LocalVaultProvider` was not wired into `mcp_server.py`. Real card credentials set via `AEGIS_BYOC_NUMBER` were silently ignored and fell through to `MockStripeProvider`. Added a dedicated BYOC branch to the provider selection logic. Provider priority (high → low): Stripe Issuing → BYOC Local → Mock.

### Added
- **`.env.example`**: Added a full environment variable reference file to the repo root, including all `AEGIS_*` policy variables and the new `AEGIS_BILLING_*` fields.
- **Claude Code Full Setup Guide**: Documented the complete three-component setup for Claude Code (Hacker Edition / BYOC): Chrome CDP launch (`--remote-debugging-port=9222`), Aegis MCP registration with `--project` flag, and Playwright MCP registration with `--cdp-endpoint`. Both MCPs share the same Chrome instance so users can watch the full injection flow live.

## [0.3.3] - 2026-03-23
### Added
- **Browser Automation Layer (`AegisBrowserInjector`)**: Implemented CDP-based cross-origin iframe traversal logic to securely auto-fill real cards for Playwright or browser-use workflows, hiding raw PAN from the agent's context.
- **Optional Dependencies (`[browser]`)**: Added `playwright` directly back into the extra dependencies to streamline installation (`pip install aegis-pay[browser]`).
- **Core Dependencies**: Registered explicitly missing `python-dotenv` for local setups leveraging `LocalVaultProvider`.
- **Scripts Organization**: Moved root `inspect_stripe.py` and `scrape_wiki_donate.py` developer tools to an enclosed `scripts/` directory for cleaner builds.

### Fixed
- **Static Analysis Cleanup**: Removed unused modules like `import asyncio` in `mcp_server.py`, following a Vulture static code analysis pass.

## [0.2.0] - 2026-03-20
### Added
- **Open-Source Framework Support**: Added explicit MCP configuration and integration documentation for **OpenClaw**, **NemoClaw**, Claude Code, and OpenHands.
- **Multilingual Support**: Added Traditional Chinese (`README.zh-TW.md`) documentation alongside the English version.
- **LLM Provider Flexibility**: `LLMGuardrailEngine` now explicitly supports custom `base_url` and `model` parameters, enabling usage of **Ollama**, **vLLM**, OpenRouter, and any OpenAI-compatible API.
- **Dependency Handling**: Split dependencies into optional extras (`[llm]`, `[stripe]`, `[mcp]`, `[langchain]`, `[all]`) to drastically reduce `pip install aegis-pay` bloat for lightweight agents.
- **Dependency Injection**: `AegisClient` now supports injecting a custom `GuardrailEngine` during initialization.
- **Automated Testing**: Added a comprehensive suite of 20 `pytest` cases covering Pydantic models, budget enforcement, providers, and integration logic.

### Changed
- **MCP Configuration**: The MCP Server is now fully controlled via environment variables (`AEGIS_ALLOWED_CATEGORIES`, `AEGIS_MAX_PER_TX`, `AEGIS_MAX_DAILY`, `AEGIS_BLOCK_LOOPS`, `AEGIS_STRIPE_KEY`) instead of hardcoded policies.
- **State Management**: Migrated from unreliable in-memory lists to a robust SQLite (`aegis_state.db`) back-end (`AegisStateTracker`) with persistent connections.
- **Dashboard Data**: The Streamlit Vault Dashboard now reads directly from the live `aegis_state.db` SQLite database rather than mock data.

### Fixed
- **Daily Budget Enforcement**: Fixed an issue where the daily budget cap was not accurately tracking and blocking agent spend across sequential runs.
- **Stripe Provider Exceptions**: Refactored `StripeIssuingProvider` to gracefully catch and return explicit `stripe.StripeError` codes as formal rejection reasons instead of crashing the agent workflow.
- **Cardholder API**: Fixed the Stripe implementation by properly generating a `Cardholder` object before attempting to issue virtual cards.
- **Burn-after-use Security**: Implemented validation to ensure requested execution attempts correctly utilize issued `seal_id` mapping.

## [0.1.0] - Early 2026
### Added
- Initial release of Project Aegis (AgentPay).
- Basic `GuardrailPolicy`, `VirtualSeal`, and `PaymentIntent` Pydantic models.
- Minimal MVP Streamlit Dashboard (The Vault).
- Initial `MockStripeProvider` for testing workflows.
