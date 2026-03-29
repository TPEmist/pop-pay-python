# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
