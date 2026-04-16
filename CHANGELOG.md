# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.9] - 2026-04-16

### Security (RT-2 Round 2 — P1 SQLite freelist PAN leak + vault hygiene)

Seven-fix bundle addressing a Round 2 red-team finding where plaintext PAN data could persist in SQLite freelist pages and WAL/SHM sidecars after legacy schema migration, and tightening runtime PAN/CVV handling through the provider and injector paths.

**PAN leak acceptance:** 9 → 0 leaked bytes verified via PoC against `aegis_state.db` post-migration (SQLite freelist + SHM sidecar + SecretStr string-ops coverage).

**Verification:** eng local / secretary local / founder fresh install all converged on 223 pass / 5 skip after Fix 7 keyring idempotency landed. Fresh-shell reproduction now mandatory per process update (see CONTRIBUTING).

- **Fix 1 — SQLite freelist zeroing.** `PopStateTracker._init_db()` sets `PRAGMA secure_delete = ON` and performs a one-time `VACUUM` during legacy-schema migration (guarded by `PRAGMA user_version = 2`, idempotent). Rewrites every freelist page, including pages that still carried plaintext `card_number` residue after the legacy `DROP TABLE` + `RENAME`. `pop_pay/core/state.py:26-66` / `:135-145`.
- **Fix 2 — Owner-only state DB permissions.** `chmod 0600` applied to `aegis_state.db` at open time. POSIX only; Windows ACLs out of scope. `pop_pay/core/state.py:18-22`.
- **Fix 3 — `SecretStr` opaque type for PAN/CVV throughout the pipeline.**
  - **3.1** New `pop_pay/core/secret_str.py` — `@dataclass(frozen=True, slots=True)` wrapper with `.reveal()` / `.last4()`; redacting `__str__` / `__repr__` / `__format__` / `__bool__`; not a `str` subclass, so string-ops (concat, encode, slice, `json.dumps`) raise rather than leak. Hashable, picklable, equality by value.
  - **3.2** `pop_pay/injector.py` migrated to `SecretStr`. Legacy `_SecretStr(str)` shim retained unused at this step to preserve bisect-green across the multi-commit migration.
  - **3.3 + 3.4** `VirtualSeal.card_number` / `VirtualSeal.cvv` re-typed `Optional[SecretStr]` with Pydantic `ConfigDict(arbitrary_types_allowed=True)`; all providers (`byoc_local`, `stripe_mock`, `stripe_real`) wrap at capture, all readers (`client.py`, `mcp_server.py`, `tools/langchain.py`) consume via `.last4()`. Landed as a single commit to preserve bisect-green — the type change breaks readers immediately.
  - **3.5** Vault CLI (`cli_vault.py`, `cli_unlock.py`) wraps PAN / CVV / passphrase in `SecretStr` at `getpass` capture; `.reveal()` called only at the cryptographic boundary (PBKDF2, JSON encryption).
  - **3.6** Final cleanup: `class _SecretStr(str)` shim deleted from `pop_pay/injector.py` once all call sites had migrated to `pop_pay.core.secret_str.SecretStr`.
- **Fix 4 — Drop `masked_card` AES-GCM-over-hostname-HMAC encryption.** `masked_card` is already a PCI-DSS 3.3 permitted last-4 projection (redacted by definition). Prior encryption added no meaningful protection over the Fix 2 `0600` file mode and impeded auditability. Stored plaintext from v0.8.9 forward. `pop_pay/core/state.py:173-193`.
- **Fix 6 — `.gitignore` hardening.** `*.db-wal`, `*.db-shm`, `aegis_state.db*` added so SQLite sidecars carrying plaintext residue during migration cannot land via `git add -A` mid-session. `.gitignore:18-21`.
- **Fix 7 — `wipe_vault_artifacts` idempotency.** `clear_keyring()` now swallows `keyring.errors.PasswordDeleteError` as an idempotent no-op, matching the surrounding filesystem-wipe semantics. Previously: calling wipe on a fresh machine (no prior vault init) or a second time on any machine raised `PasswordDeleteError: Item not found`. Two new regression tests added (`test_wipe_vault_artifacts_idempotent_on_missing_keychain_entry`, `test_wipe_vault_artifacts_idempotent_on_repeat_call`), monkeypatched — no real Keychain contact. `pop_pay/vault.py:187-196`.

### Internal
- **Deleted legacy `class _SecretStr(str)` shim** from `pop_pay/injector.py` (Fix 3.6). Leading-underscore, never part of the public surface — fully replaced by `pop_pay.core.secret_str.SecretStr`. No external consumers (cross-repo grep clean).

### Notes
- `masked_card` rows written by v0.8.7 / v0.8.8 (AES-GCM-encrypted base64) will render as base64 in the dashboard after this upgrade. Not a silent failure mode — the stored string is simply no longer decoded post-Fix 4. Supported remediation: `pop-init-vault --wipe` + fresh seal generation.

[0.8.9]: https://github.com/100xPercent/pop-pay-python/compare/v0.8.8...v0.8.9

## [0.8.8] - 2026-04-15

### Security (S0.7 Vault Hardening — F1-F8)
- **F1 — `filtered_env()` + `SENSITIVE_ENV_KEYS`.** Strips `POP_BYOC_NUMBER` / `POP_BYOC_CVV` / `POP_BYOC_EXP_MONTH` / `POP_BYOC_EXP_YEAR` from any env dict spawned to child processes. `load_vault()` guarantees BYOC keys never leak into `os.environ`. New regression tests cover subprocess env inheritance.
- **F3 — OSS salt consent gate.** `machine-oss` vaults now refuse to decrypt unless `POP_ACCEPT_OSS_SALT=1` is set. Passphrase-mode vaults bypass the gate. Protects against silent weak-crypto decryption when running OSS-source builds.
- **F4 — Vault mode marker migration.** Legacy markers (`hardened` / `oss`) transparently migrate on read to `machine-hardened` / `machine-oss`; `passphrase` marker distinguishes keyring-backed vaults from machine-id vaults.
- **F6 — Typed error lifecycle.** `ProviderUnreachable`, `InvalidResponse`, `RetryExhausted` are now raised from the LLM guardrail and no longer swallowed as `(False, ...)` block verdicts. Retry exhaustion cannot masquerade as a guardrail rejection (bug fix: engine retry-exhaust).
- **F7 — Downgrade refuse.** `machine-hardened` marker + native `_vault_core.is_hardened()` returning `False` raises `RuntimeError` on `load_vault()`; `pop-init-vault` refuses overwrite.
- **F8 — Stale `.tmp` sweep + `wipe_vault_artifacts()`.** `save_vault()` sweeps `vault.enc*.tmp` siblings before atomic-writing. New `pop-init-vault --wipe` enumerates and deletes `vault.enc`, `.vault_mode`, `.machine_id`, and stale `.tmp` files.
- **Bounty policy remains private.** Three scope categories (Passive Leak / Active Attack / Vault Extraction) retained; public tier disclosure + Hall of Fame deferred until internal red team iteration completes.

### Added
- **Error Model Refactor (`pop_pay/errors.py`).** Full `PopPayError` hierarchy: `VaultDecryptFailed` / `VaultNativeUnavailable` / `ConfigMissing` / `ConfigInvalid` / `ProviderUnreachable` / `InvalidResponse` / `RetryExhausted` / `InjectorTimeout` / `InjectorCDPFailure` / `LLMAPIKeyMissing`. CLI entry points route through `handle_cli_error()` for consistent exit codes and user-facing remediation.
- **RT-1 harness + 585-payload v1 corpus parity.** `tests/redteam/` with 5 runner paths (`layer1`, `layer2`, `full_mcp`, `toctou`, `hybrid`), corpus mirrored from the npm repo at `tests/redteam/corpus/attacks.json`, validator, aggregator, per-runner tests.
- **LLM guardrail prompt upgrade.** Switched to few-shot XML-examples format with inline injection-resistance demos (`evil-payments.io`, `admin-override` reasoning). New `block_hallucination_loops` policy switch.
- **`docs/CATEGORIES_DECISION_CRITERIA.md`** — S0.2a decision framework for vendor allowlist categories.
- **`docs/GUARDRAIL_BENCHMARK.md`** — formal benchmark methodology + results registry.

### Changed
- **Capability-forward documentation.** `SECURITY.md` / `docs/THREAT_MODEL.md` rewritten per CEO REVISE — legacy 20-scenario / 95% claims and §5 Known Limitations removed from the public face; threat-model prelude relocated to `docs/internal/py-security-history.md`.
- **`.env` template quoting.** `POP_ALLOWED_CATEGORIES` JSON arrays wrapped in single quotes; `POP_BILLING_STREET` / `POP_BILLING_CITY` values with spaces double-quoted so `dotenv` parses them cleanly.

## [0.8.7] - 2026-04-14

### Added
- **`pop-pay doctor` diagnostic subcommand** — Python parity with the TS `pop-pay doctor`. 10 generic checks: `python_version` (≥3.10), `chromium`, `cdp_port`, `config_dir`, `vault`, `env_vars`, `policy_config`, `layer1_probe`, `layer2_probe`, `injector_smoke`. Exit codes match TS: `0` clean / `1` blocker failed / `2` crash. Supports `--json`.
- **New dispatcher** `pop_pay.cli_main` — `pop-pay` now routes `doctor` to the new handler and falls through to the dashboard for no-arg invocation (legacy UX preserved).
- **New entry point** `pop-pay-doctor` (pyproject `[project.scripts]`) for direct invocation.
- **Remediation catalog** at `config/doctor-remediation.yaml` — same flat schema as the npm repo; parsed by an inline YAML-lite reader (no new runtime dependency).
- **`docs/DOCTOR.md`** — with KNOWN LIMITATIONS documenting the intentional engine-classify gap (local handler now; typed engine classifier swap deferred to post-refactor round 2 of the paused Error Model Refactor track).

### Security
- **F5 — seal PAN/CVV in exception frame locals.** `_SecretStr` wraps card_number / expiry / cvv in `pop_pay/injector.py`; `repr()` / `str()` / `__format__` all render `***REDACTED***`, so `sys.excepthook`, `rich.traceback`, and `faulthandler.show_locals` cannot leak plaintext. Unicode payload preserved for JSON serialization and Playwright `.fill()`.
- **Bounty program set to private.** Reports go to `security@pop-pay.ai`; scope retained as three categories (Passive Leak / Active Attack / Vault Extraction); public tiers and Hall of Fame will open after internal red team completes iterative hardening rounds.
- **`check_env_vars` is format-only and content-blind.** `POP_LLM_*` secrets reported as `present (hidden)` / `missing`; no length, prefix, or hash ever emitted.
- **`check_layer2_probe` is TCP-only.** Connects and disconnects — no HTTP request, no API key transmitted, no quota consumed.
- **Internal vault canary `examples/vault-challenge/vault.enc.challenge`** — internal cryptographic boundary target (mirror of npm repo); external challenge opens with public bounty. AES-256-GCM blob with discarded scrypt passphrase + fake card + flag string. Reproducible `gen-challenge.js` / `gen-challenge.py` generators. See `examples/vault-challenge/README.md`.

### Documentation
- **`docs/VAULT_THREAT_MODEL.md` v0.1** — vault-layer threat model (mirror of npm repo). Active attacks + standalone passive failure mode section with 7 concrete scenarios. Python-side line-level audit of `_vault_core.pyx` + `pop_pay/vault.py` flagged as pending in §5.
- **`docs/HALL_OF_FAME.md`** — placeholder; published when bounty program opens publicly.

## [0.8.6] - 2026-04-13

### Changed
- **README cross-link to npm repo**: added a note pointing Node.js / JavaScript users to `pop-pay (npm)` (`npm i -g pop-pay` or `brew install 100xPercent/tap/pop-pay`), noting shared security model and vault format for safe runtime switching.
- **`glama.json` alignment**: description and keywords aligned with the CLI-first framing used in the npm repo (maintainer: TPEmist).

### Notes
- No source-code changes. Docs / distribution release paired with npm `0.5.6`.

## [0.8.4] - 2026-04-10

### Fixed
- **`mcpName` case mismatch with MCP Registry**: updated `[tool.mcp] mcpName` from `io.github.100xpercent/pop-pay` to `io.github.100xPercent/pop-pay` to match the GitHub org case, aligning with the npm package and the Official MCP Registry entry.

## [0.8.3] - 2026-04-10

### Changed
- **MCP marketplace metadata**: added `[tool.mcp]` namespace `io.github.100xpercent/pop-pay`, keywords, and project URLs to pyproject.toml for marketplace discovery.
- **GitHub org migration**: updated README badges and `[project.urls]` from `TPEmist/pop-pay-python` to `100xPercent/pop-pay-python`.

## [0.8.2] - 2026-04-10

### Fixed
- **`request_purchaser_info` still blocked unapproved vendors after v0.8.0:** v0.8.0 was supposed to turn vendor blocking into pure audit logging, but the handler kept its original `return` guard, so the billing-info auto-fill was still hard-rejected when the vendor was absent from `POP_ALLOWED_CATEGORIES`. Vendor blocking is now explicitly controlled by `POP_PURCHASER_INFO_BLOCKING` (default `true`, zero-trust). **Security scan and domain-mismatch checks are never bypassed by this flag.**
- **Audit log rows did not record outcome/reason:** v0.8.0 wrote a single audit row at the top of the handler saying "this was attempted" without recording what actually happened. Operators had no way to tell a rejection from a success in the dashboard. The handler now emits exactly one audit row per call at the resolved exit point with `outcome` (`approved` / `rejected_vendor` / `rejected_security` / `blocked_bypassed` / `error_injector` / `error_fields`) and `rejection_reason` (human-readable context when relevant).

### Added
- **`POP_PURCHASER_INFO_BLOCKING` env var (default `true`):** explicit toggle for `request_purchaser_info` vendor allowlist enforcement. When set to any other string (e.g. `false`), the vendor check becomes advisory and the bypass is audited as `outcome='blocked_bypassed'`. Documented in `docs/ENV_REFERENCE.md` and `CONTRIBUTING.md` (Open Discussion section inviting community feedback on the default).
- **`audit_log.outcome` + `audit_log.rejection_reason` columns:** new columns on `audit_log`. Migration is idempotent and additive — existing rows written by v0.8.0 / v0.8.1 get `outcome='unknown'` so the dashboard can still surface them without breaking. `PopStateTracker.record_audit_event()` signature extended with `outcome` and `rejection_reason` kwargs (backwards-compatible — both default to `None`).
- **Dashboard AUDIT_LOG — OUTCOME + REASON columns:** new columns in the dashboard audit table with color coding (`approved` green, rejected/error red, `blocked_bypassed` orange, `unknown` gray).
- **Handler smoke tests:** new `tests/test_purchaser_info_handler.py` drives `request_purchaser_info` through all six exit points and asserts the audit row written. State-level tests for outcome persistence and the legacy audit_log migration also extended.

### Changed
- **Schema migration:** opening a legacy DB now also runs an additive `ALTER TABLE audit_log ADD COLUMN outcome TEXT` / `ADD COLUMN rejection_reason TEXT` pair (idempotent via `PRAGMA table_info` check). The dashboard API does the same defensively so launching the dashboard before the tracker can't break the `/api/audit` SELECT.

## [0.8.1] - 2026-04-10

### Changed
- **Dashboard default port 3210 → 8860.** 8860 is less commonly occupied by other local-dev tooling than 3xxx ports, and ties into the "pay" brand root. Override with `--port` as before. Users running the dashboard with no explicit `--port` will need to update bookmarks to `http://127.0.0.1:8860`.

## [0.8.0] - 2026-04-10

### Added
- **`audit_log` table:** informational audit trail for MCP tool invocations. Every `request_purchaser_info` call now logs `event_type`, `vendor`, `reasoning`, and an ISO 8601 UTC timestamp. Non-blocking — failures to log never interrupt the main flow.
- **Dashboard AUDIT_LOG section:** new table rendering `/api/audit` events (id, event_type, vendor, reasoning, timestamp).
- **`PopStateTracker.record_audit_event()` / `.get_audit_events()`:** public API for emitting and reading audit events.

### Fixed
- **Bug 1 — timestamps now ISO 8601 with `Z` suffix:** `issued_seals.timestamp` previously used SQLite `CURRENT_TIMESTAMP` (`YYYY-MM-DD HH:MM:SS`), which is ambiguous about timezone and parsed as local time by browsers. New inserts use `datetime.now(timezone.utc)` serialized as `YYYY-MM-DDTHH:MM:SSZ`. Legacy rows are migrated in-place on first open.
- **Bug 2 — `rejection_reason` column now persisted:** dashboard REJECTION_LOG previously showed an empty REASON column because `issued_seals` had no `rejection_reason` column. Added column + wired `client.py` to pass the reason through for all three rejection paths (budget, engine, success→null). Migration adds the column to legacy DBs.
- **Dashboard/tracker schema drift:** `dashboard/server.py` used to run its own `init_db()` which didn't know about new columns. It now delegates schema creation + migration to `PopStateTracker`, so the dashboard and MCP server always agree on schema even if the dashboard is launched first against a legacy DB.

### Changed
- **Schema migration (upgrade-safe):** opening a legacy DB now (1) rebuilds `issued_seals` if it still has `card_number`/`cvv` columns (very-legacy path, preserves masked data); (2) adds `rejection_reason` if missing; (3) rewrites legacy `YYYY-MM-DD HH:MM:SS` timestamps to ISO 8601 Z format; (4) creates `audit_log` table. Migration is idempotent — running twice is a no-op.
- **`datetime.utcnow()` → `datetime.now(timezone.utc)`:** the former is deprecated in Python 3.12+ and returns a naive datetime. The latter is timezone-aware and future-proof.
- **Dashboard port 3210:** no functional change, but documented: port was chosen arbitrarily during initial dashboard bring-up and is kept for continuity with existing user bookmarks.

## [0.6.34] - 2026-04-06

### Fixed
- **Select dropdown — fill order (root cause):** Filling `<input>` fields triggers framework re-renders (Zoho, React) that reset previously selected `<select>` dropdowns. Fix: inputs first (name, street, city, zip, email), selects last (country, state). Removed diagnostic code from v0.6.30-v0.6.33.

## [0.6.32] - 2026-04-06

### Fixed
- **Select dropdown — use `get_by_label()` as primary locator:** Root cause confirmed: CSS selector `select[name='state']` finds the element and sets the DOM value, but Zoho's framework UI doesn't update. Playwright MCP's own approach uses accessibility-based `page.getByLabel('State')` which works correctly. Fix: for `<select>` elements, try `get_by_label()` first (matching Playwright MCP's behavior), fall back to CSS selectors. Changed billing field search context from `page.main_frame` to `page` to enable accessibility tree resolution.

## [0.6.31] - 2026-04-06

### Fixed
- **Select dropdown — trusted events:** Root cause: `el.dispatchEvent()` in JS evaluate creates untrusted events (`isTrusted: false`). Zoho and other frameworks ignore untrusted change/input events. Fix: use Playwright's `locator.dispatch_event()` which creates trusted events (`isTrusted: true`).

## [0.6.30] - 2026-04-06

### Changed
- **Select dropdown diagnostic:** After `select_option()`, verify value by reading back `el.value`. If empty, report diagnostic in MCP response: element visibility, name, option count, frame URL. Enables root-cause identification without server logs.

## [0.6.29] - 2026-04-06

### Fixed
- **Select dropdown — native setter fallback:** Root cause: Playwright's `select_option()` silently succeeds but the value doesn't stick on React/Angular/Zoho forms (framework overrides the native setter). Fix: after `select_option()`, verify the value by reading it back. If mismatch, use `HTMLSelectElement.prototype.value` native setter to bypass framework interception, plus full event chain (focusin → focus → mousedown → mouseup → click → input → change → blur → focusout).

## [0.6.28] - 2026-04-06

### Changed
- **Billing field diagnostics in MCP response:** `request_virtual_card` now reports which billing fields were filled, failed, or skipped directly in the agent response (e.g. `Billing filled: [first_name, street, email]. FAILED: [state (value='California'), country (value='US')]`). Enables root-cause diagnosis without server logs.

## [0.6.27] - 2026-04-06

### Fixed
- **Select dropdown: revert to Playwright-native `select_option()`** — JS evaluate approach was overfit. Confirmed Playwright's `select_option()` works correctly over CDP. Root cause still under investigation (likely selector matching or timing). Added diagnostic logging to `_fill_field` and `_select_option` to identify the exact failure point on next test run.

## [0.6.26] - 2026-04-06

### Fixed
- **Select dropdown rewrite:** Replaced Playwright `select_option()` (silently fails on Zoho/React over CDP) with JavaScript-based selection as primary approach. Fires full event chain: focusin → focus → mousedown → mouseup → click → input → change → blur → focusout. Matching priority: exact value → exact text → partial match.

## [0.6.25] - 2026-04-06

### Fixed
- **US state abbreviation auto-expand:** `POP_BILLING_STATE=CA` now auto-converts to "California" for dropdowns that use full state names. Fixes Zoho and similar forms.
- **Screenshot blackout configurable:** New `POP_BLACKOUT_MODE` env var: `before` (mask before injection, most secure), `after` (mask after injection, good for demos, default), `off` (no masking).

### Added
- **Headless/Docker injection mode:** `--headless` flag for `pop-launch`. Launches headless Chrome via Playwright instead of connecting to existing CDP. Includes `examples/Dockerfile.headless`.
- **TOCTOU domain-check refactor:** Extracted duplicated TOCTOU logic into shared `_verify_domain_toctou()` method.
- **x402 protocol support (stubbed):** New `request_x402_payment()` MCP tool for HTTP 402 agent-to-service micropayments. Guardrail check and spend recording functional; blockchain payment execution stubbed pending Coinbase SDK.
- **Biometric approval webhook:** `POP_APPROVAL_WEBHOOK` env var — POST approval requests to external webhook (WebAuthn/Slack/custom) with 120s timeout. Falls back to auto-approve when not configured.
- **Dashboard slider DB writeback:** Spend limit slider now persists changes to SQLite.
- 30 new tests (headless, x402, approval webhook, dashboard settings). Total: 131 tests.

## [0.6.24] - 2026-04-06

### Fixed
- **Select/dropdown injection (Bug Fix):** Added `_dispatch_events()` to fire `input`, `change`, and `blur` events after filling `<select>` and `<input>` fields. Fixes frameworks (Zoho, React, Angular, Vue) that rely on DOM events for state updates. Also added JavaScript-based fallback for non-standard `<select>` elements.
- **Screenshot protection rewrite (Bug Fix):** Replaced broken full-screen overlay approach with per-field CSS masking (`-webkit-text-security: disc`, `color: transparent`) injected into ALL frames including cross-origin iframes. Masking persists after injection (no auto-remove), defeating screenshot-based card exfiltration.
- **Webhook SSRF guard:** Added private IP / loopback / link-local / reserved address validation to webhook URL dispatch, matching the existing `_scan_page()` SSRF protections.
- **Dead code removal:** Removed unreachable `ssl_anomaly` check in `_scan_page()` (line 170) — already guarded by scheme check at line 149.

### Added
- **CDP regression test suite:** 26 new tests covering 10 checkout stacks (Stripe Elements, Shopify, WooCommerce, Magento, BigCommerce, Adyen, PayPal, Braintree, Square, custom HTML) with HTML fixture files. Total: 101 tests.
- **Threat Model:** `docs/THREAT_MODEL.md` — STRIDE analysis, 5 security primitives, 10 attack scenarios with mitigations.
- **Compliance FAQ:** `docs/COMPLIANCE_FAQ.md` — PCI DSS scope argument, data flow diagram, SOC 2 roadmap, GDPR note.
- **README rewrite:** Security-first positioning ("The runtime security layer for AI agent commerce"), guardrail benchmark section, architecture table with 5 security primitives.

### Changed
- **zh-TW Integration Guide:** Synced missing `pop-launch --print-mcp` line with English version.

## [0.6.21] - 2026-04-05

### Fixed
- **ClawHub SKILL.md `requires.env`:** Removed `POP_WEBHOOK_URL` and `POP_LLM_API_KEY` from the required env declarations. These vars are optional (webhook notifications are disabled by default; LLM guardrail mode is opt-in). Listing them as required caused the ClawHub scanner to flag an incorrect "required but optional" policy violation.

## [0.6.19] - 2026-04-04

### Removed
- **`page_snapshot` MCP tool (breaking change):** Removed the public `page_snapshot()` MCP tool. The same scan now runs automatically inside `request_virtual_card` whenever `page_url` is provided. Agents that called `page_snapshot` explicitly should remove those calls.

### Fixed
- `_scan_page` error strings updated from "page_snapshot only accepts..." to "pop-pay only accepts..." — no longer references a removed tool name.

### Added
- **Screenshot Blackout Security (P1):** Added `_enable_blackout()` and `_disable_blackout()` methods to `PopBrowserInjector`. During credential injection (card or billing), a full-screen black overlay (`z-index: 999999`, `pointer-events: none`) is now applied to the browser viewport. Prevents screen recording or screenshot tools from capturing sensitive fields while they are being filled. Restoration is guaranteed via `finally` blocks.

## [0.6.18] - 2026-04-03

### Added
- **P1: Page Snapshot Security Tool:** Added `@mcp.tool() page_snapshot(page_url)` to scan checkout pages for prompt injection signals (hidden text, zero-pixel elements, malicious instructions) before payment.
- **Mandatory Snapshot Check (P1):** `request_virtual_card` now warns if no valid security snapshot (valid for 5 mins) is found for the `page_url`, encouraging a "scan-before-pay" workflow.
- P3: Added webhook_url support to GuardrailPolicy for Slack/Teams/PagerDuty notifications
- Docs: Added OpenClaw skill documentation at docs/openclaw-skill.md

### Fixed
- **Vendor matching unified (`_match_vendor`):** Extracted shared `_match_vendor()` helper in `guardrails.py`. Both `GuardrailEngine.evaluate_intent()` and `request_purchaser_info` MCP tool now use the same logic — token-exact, token-in-allowed, token-subset, and page-domain fallback. Eliminates the prior divergence where a vendor could pass one gate but be rejected by the other.
- **Page domain token min-length filter (H-3):** Short TLD tokens (`io`, `co`, etc.) in `page_url` domain no longer falsely match allowed categories. Tokens shorter than 4 characters are now filtered out before domain-based vendor matching.
- **LangChain Tool — TOCTOU domain guard added (QUALITY-4):** `PopPaymentInput` now accepts `page_url`; `_arun()` passes `page_url` and `approved_vendor` to `inject_payment_info()`. LangChain path now has the same domain validation as the MCP server path.
- **LangChain test mock reflects production return format (L-4):** `test_langchain_tool_injector_failure_feedback` mock updated from `return_value=False` to `return_value={"card_filled": False, ...}` — matches the actual dict format `inject_payment_info()` returns.

### Added
- **`pop-init-vault` template — missing billing fields (L-2):** Generated `.env` template now includes `POP_BILLING_CITY`, `POP_BILLING_STATE`, `POP_BILLING_COUNTRY`, `POP_BILLING_PHONE_COUNTRY_CODE` (commented out with examples).

### Docs
- **Integration Guide example — CDP injection (L-3 follow-up):** Updated manual integration example to use `PopBrowserInjector` instead of bare `page.fill()` calls — correctly shows that card details flow through the injector from the in-memory seal, not from DB.

---

## [0.6.16] - 2026-04-01

### Fixed
- **mcp_server.py — RuntimeError not caught:** Vault `load_vault()` raises `RuntimeError` when a hardened vault exists but OSS source is running. Added `RuntimeError` to the `except (ValueError, RuntimeError)` guard — server no longer crashes on startup in this configuration.
- **langchain.py — dict injection result always truthy:** `inject_payment_info()` returns a dict; `if not injection_ok:` was always `False` for any non-empty dict, masking injection failures and skipping budget rollback. Now inspects `card_filled` key explicitly.
- **inject_billing_only — missing billing fields:** `billing_info` dict in `inject_billing_only` was missing `city`, `state`, `country`, `phone_country_code`. All `POP_BILLING_*` env vars now consistently read in both `inject_payment_info` and `inject_billing_only`.
- **llm_guardrails.py — @retry decorator never fires:** All exceptions were caught inside `evaluate_intent`, preventing tenacity from seeing them. Retriable errors (`APIStatusError` with 429/5xx, `APIConnectionError`) now re-raise so tenacity can back off and retry.

### Docs
- **Integration Guide:** Removed non-existent `get_seal_details()` call; replaced with correct `seal.card_number / .cvv / .expiration_date` access pattern.
- **README:** Added explicit note that Stripe Issuing returns last-4-only — CDP auto-injection is incompatible with Stripe Issuing; use BYOC for CDP injection.

---

## [0.6.15] - 2026-04-01

### Fixed
- **`inject_billing_only` missing billing fields:** Same issue as `inject_payment_info` — city/state/country/phone_country_code not populated in `inject_billing_only`'s local billing_info dict. `request_purchaser_info` was affected.
- **`inject_payment_info` missing billing fields:** The `billing_info` dict built inside `inject_payment_info` was not updated when city/state/country/phone_country_code were added in v0.6.12–0.6.14. Fields were correctly wired in `_fill_billing_fields()` but never populated — phone country code, country, state, and city injection silently failed via `request_virtual_card`. All fields now read from env vars consistently.

## [0.6.14] - 2026-04-01

### Changed
- **Phone country code auto-derive:** Refactored to remove `POP_BILLING_PHONE_NATIONAL`. `_national_number()` derives national number from E.164 + country code via 50-country dial code table. Accepts ISO alpha-2 (`"US"`), dial prefix (`"+1"`), or raw digits.

## [0.6.13] - 2026-04-01

### Added
- **Phone country code dropdown support:** `PHONE_COUNTRY_CODE_SELECTORS` (13 selectors covering `select[name='dialCode']`, `select[name='countryCode']`, etc.). `POP_BILLING_PHONE_COUNTRY_CODE` (ISO code or dial prefix: `"US"`, `"+1"`, etc.) fills the country code select; national number is **auto-derived** from the E.164 `POP_BILLING_PHONE` value via a 50-country dial code table — no separate `POP_BILLING_PHONE_NATIONAL` needed. Falls back to full E.164 for combined inputs or unknown country codes.

## [0.6.12] - 2026-04-01

### Added
- **Dropdown field support:** New `_select_option()` helper tries exact value → exact label → case-insensitive fuzzy match against option text. New `_fill_field()` helper detects `<select>` vs `<input>` at runtime and routes accordingly — all existing and future fields get dropdown support automatically.
- **Country, state, city billing fields:** `POP_BILLING_COUNTRY`, `POP_BILLING_STATE`, `POP_BILLING_CITY` env vars. Injector fills the corresponding form fields, including dropdown variants (`select[name='country']`, etc.).
- **New selectors:** `COUNTRY_SELECTORS`, `STATE_SELECTORS`, `CITY_SELECTORS` covering `autocomplete`, `name`, `id`, `aria-label` attributes for both `<select>` and `<input>` variants.

### Changed
- `_fill_billing_fields()` refactored to use unified `_fill_field()` — ~50 lines removed, all fields now handled consistently.
- `byoc_local.py` `billing_info` dict extended with `city`, `state`, `country`.
- `.env.example` updated with new billing fields and inline comments.

## [0.6.11] - 2026-04-01

### Changed
- **Refactor:** Moved `KNOWN_PAYMENT_PROCESSORS` out of `guardrails.py` into its own
  `pop_pay/engine/known_processors.py` module. `guardrails.py` re-exports it for
  backwards compatibility. The list is now `frozenset` (immutable at runtime).
  PR diffs for new processor additions are now isolated to a single focused file.

## [0.6.10] - 2026-04-01

### Added
- **`KNOWN_PAYMENT_PROCESSORS` built-in allowlist** (`guardrails.py`): 19 known third-party payment processors (Stripe, Zoho, Square, PayPal, Braintree, Adyen, Checkout.com, Paddle, FastSpring, Gumroad, Recurly, Chargebee, Eventbrite, Tito, Luma, Universe, 2Checkout, Authorize.net). When a checkout page redirects to any of these domains, the TOCTOU domain guard passes automatically — vendor intent was already verified by the policy gate.
- **`POP_ALLOWED_PAYMENT_PROCESSORS` env var**: User-extensible JSON array for processors not in the built-in list. Merged with `KNOWN_PAYMENT_PROCESSORS` at injection time.
- **`docs/CATEGORIES_COOKBOOK.md` — Payment Processors section**: Full table of built-in processors with domains and example vendors; instructions for extending the list via env var and contributing new entries.

### Changed
- `injector.py`: Both `inject_payment_info` and `inject_billing_only` TOCTOU checks now include a processor passthrough step after vendor domain matching fails.
- `.env.example`: Added `POP_ALLOWED_PAYMENT_PROCESSORS` (commented out) with explanation.

## [0.6.9] - 2026-04-01

### Added
- **docs/CATEGORIES_COOKBOOK.md:** Explains how `POP_ALLOWED_CATEGORIES` matching works (two-layer: policy gate + TOCTOU domain guard), why semantic labels like `"Event"` do not match arbitrary vendor names, two configuration patterns (specific named vendors vs broad categories), real-world config examples, known limitations, and a quick diagnostic guide.

### Changed
- **README:** Linked Categories Cookbook from `POP_ALLOWED_CATEGORIES` env var description.
- **CONTRIBUTING:** Linked Categories Cookbook from local dev setup step 4.

## [0.6.8] - 2026-04-01

### Fixed
- **Vendor matching — domain fallback:** When agent passes a domain as `target_vendor` (e.g. `"bayarea.makerfaire.com"`), allowed categories are now also matched against `page_url` domain tokens. Handles cases where agent extracts vendor from URL instead of page content.
- **Tool descriptions:** `target_vendor` parameter now explicitly states to pass a human-readable name (e.g. `"Maker Faire"`), not a URL or domain.

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
