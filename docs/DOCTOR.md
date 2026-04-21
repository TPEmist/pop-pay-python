# `pop-pay doctor` (Python)

Python-repo parity for the TypeScript `pop-pay doctor` diagnostic. See the
TS repo's [`docs/DOCTOR.md`](../../pop-pay-npm/docs/DOCTOR.md) for full
documentation; this file notes only the Python differences.

## Usage

```
$ pop-pay doctor
$ pop-pay doctor --json           # machine-readable
$ pop-pay doctor --strict         # F9: only Google Chrome, SHA must match known-good list
$ pop-pay doctor --permissive     # F9: accept any Chrome-family binary with a valid code signature
$ pop-pay-doctor                  # equivalent direct entry point
$ python -m pop_pay.cli_doctor
```

Exit codes match the TS version: `0` ok / `1` blocker failed / `2` doctor crashed.

## Checks (15 total)

Same check set as TS, with `python_version` (≥3.10) replacing `node_version`:

| id | Purpose | Blocker? |
|---|---|---|
| `python_version` | Python ≥ 3.10 | yes |
| `chromium` | Chrome / Chromium present | yes |
| `cdp_port` | CDP port free | no |
| `config_dir` | `~/.config/pop-pay/` | no |
| `vault` | `vault.enc` present | no |
| `env_vars` | format-only, never logs values | no |
| `policy_config` | JSON array validation | no |
| `layer1_probe` | `pop_pay.engine` loads | yes |
| `layer2_probe` | TCP reachability; no API request sent | no |
| `injector_smoke` | `chrome --version` | no |
| `f9_l1_codesign` | Chrome binary has a valid OS code signature | **yes** |
| `f9_l2_sha_pin` | Chrome SHA-256 matches the in-repo known-good list | no (yes under `--strict`) |
| `f9_l3_fork` | Chrome vendor on fork whitelist | **yes** |
| `f9_l4_extensions` | Enumerate installed Chrome-family extensions (informational) | no |
| `f9_l4_cdp_port` | Warn if CDP port is already listening — possible hijack (see VAULT_THREAT_MODEL §2.9) | no |

## F9 — Chrome binary integrity

F9 closes the trust boundary between pop-pay and the Chrome binary it drives over CDP. See `docs/VAULT_THREAT_MODEL.md` §2.8 for the threat model.

**Four layers** (identical semantics to the TS doctor):

1. **OS codesign (primary, load-bearing).** macOS `codesign --verify` + parse of the `Authority=Developer ID Application: <vendor> (<team-id>)` line; Linux `dpkg -V` / `rpm -V`; Windows `Get-AuthenticodeSignature`. Failure blocks startup.
2. **Static SHA-256 pin (secondary).** Chrome executable hashed and compared against `pop_pay/data/chrome_known_good_sha256.json`. Manual PR bump per Chrome major release — the PR review step IS the supply-chain defense. Warn under default; **fail** under `--strict`.
3. **Fork whitelist (tertiary).** Default accepts Google / Brave / Microsoft / Mozilla. `--strict` accepts only Google LLC. `--permissive` accepts any binary with a valid code signature.
4. **Defense-in-depth (runtime).** Extension enumeration across Chrome/Brave/Edge profile dirs + CDP port hijack sniff.

**Never live-fetches `dl.google.com`.** Six-reason rationale is in `VAULT_THREAT_MODEL.md` §2.8.

**Deviation from spec:** macOS L1 uses `codesign --verify` (not `--strict`) because Chrome's `.app` bundle contains resource-fork metadata which `--strict` rejects despite a cryptographically valid signature. Documented in `pop_pay/doctor_f9.py` `_layer1_macos` and in VAULT_THREAT_MODEL §2.8.

**Bumping the known-good list:** open a PR adding an entry to `pop_pay/data/chrome_known_good_sha256.json`. Required fields: `vendor`, `channel`, `version`, `platform`, `arch`, `sha256`. On macOS discover Team ID via `codesign -dv --verbose=4 /Applications/Google\ Chrome.app`.

## Privacy & safety

Identical guarantees to the TS doctor:
- `env_vars` checks presence + JSON parse; **never reads or emits values**.
- `layer2_probe` is TCP-only; your `POP_LLM_API_KEY` is never transmitted.

## Remediation catalog

`config/doctor-remediation.yaml` in this repo, same flat schema as the TS repo.
Parsed by an inline minimal YAML-lite parser in `pop_pay/cli_doctor.py`
(no runtime `pyyaml` dependency added).

## KNOWN LIMITATIONS

- **Typed-engine-failure classification deferred — intentional, not oversight.** doctor ships with a local error handler and does not depend on the engine error model. The engine-wide Error Model Refactor is on a separate track (currently paused, pending founder decision — see `workspace/projects/pop-pay/redteam-plan-2026-04-13.md`). A post-refactor round 2 will swap doctor's local handler for the typed engine classifier.
- **`cdp_port`**: TCP probe only; cannot identify the owning process.
- **`injector_smoke`**: `--version` only, does not boot a headless page.
- **No CATEGORIES policy checks yet.** Gated on S0.2 B-class decision, arriving in S1.1.
- **F9 `f9_l2_sha_pin` lag.** The SHA list is bumped by PR and intentionally trails Chrome's auto-update cadence; a miss under default mode is a *warn* by design. Run `--strict` only in environments where the list can be kept fresh.

## Entry points

`pyproject.toml`:
```
pop-pay         = "pop_pay.cli_main:main"   # dispatcher: doctor or dashboard
pop-pay-doctor  = "pop_pay.cli_doctor:main" # direct entry
```

The `pop-pay` script falls through to the dashboard when no subcommand is supplied — preserving the prior `pop-pay` UX.
