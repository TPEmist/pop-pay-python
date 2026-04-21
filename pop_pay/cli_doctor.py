"""pop-pay doctor — diagnostic command (Python parity with TS doctor).

Ships with a local error handler by design; does not depend on engine error
model. See docs/DOCTOR.md — KNOWN LIMITATIONS for the engine-classify gap
and post-refactor round 2 plan.
"""

from __future__ import annotations

import json
import os
import pathlib
import platform
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urlparse

from pop_pay.doctor_f9 import (
    F9CheckResult,
    F9Options,
    ForkMode,
    run_f9_checks,
)

CheckStatus = Literal["pass", "warn", "fail"]


@dataclass
class DoctorCheck:
    id: str
    name: str
    status: CheckStatus
    blocker: bool
    detail: str | None = None
    remediation: str | None = None


def _parse_remediation_yaml(text: str) -> dict[str, dict]:
    """Minimal parser for our flat schema: <id>: { remediation, blocker }."""
    out: dict[str, dict] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")) and line.rstrip().endswith(":"):
            current = line.rstrip()[:-1].strip()
            out[current] = {}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if ":" not in stripped:
            continue
        k, v = stripped.split(":", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        if k == "remediation":
            out[current]["remediation"] = v
        elif k == "blocker":
            out[current]["blocker"] = v == "true"
    return out


def _load_remediation_catalog() -> dict[str, dict]:
    here = pathlib.Path(__file__).resolve().parent
    candidates = [
        here.parent / "config" / "doctor-remediation.yaml",
        here / "config" / "doctor-remediation.yaml",
    ]
    for p in candidates:
        if p.exists():
            try:
                return _parse_remediation_yaml(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _mk(
    cid: str,
    name: str,
    status: CheckStatus,
    detail: str | None,
    catalog: dict[str, dict],
    blocker_override: bool | None = None,
) -> DoctorCheck:
    entry = catalog.get(cid, {})
    blocker_default = entry.get("blocker", False)
    blocker = blocker_override if blocker_override is not None else blocker_default
    return DoctorCheck(
        id=cid,
        name=name,
        status=status,
        detail=detail,
        remediation=None if status == "pass" else entry.get("remediation"),
        blocker=bool(blocker) if status == "fail" else False,
    )


# --- individual checks ----------------------------------------------------


def _check_python_version(cat):
    v = sys.version.split()[0]
    major = sys.version_info[0]
    minor = sys.version_info[1]
    if major > 3 or (major == 3 and minor >= 10):
        return _mk("python_version", f"Python {v} (≥3.10 required)", "pass", None, cat)
    return _mk("python_version", f"Python {v} (≥3.10 required)", "fail", f"Need ≥3.10, got {v}", cat, True)


def _find_chrome() -> str | None:
    override = os.environ.get("POP_CHROME_PATH")
    if override:
        return override if pathlib.Path(override).exists() else None
    sysname = platform.system()
    if sysname == "Darwin":
        for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ):
            if pathlib.Path(p).exists():
                return p
    elif sysname == "Windows":
        for p in (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ):
            if pathlib.Path(p).exists():
                return p
    else:
        import shutil
        for name in ("google-chrome", "chromium", "chromium-browser"):
            f = shutil.which(name)
            if f:
                return f
    return None


def _check_chromium(cat):
    p = _find_chrome()
    if p:
        return _mk("chromium", "Chromium found", "pass", p, cat)
    return _mk("chromium", "Chromium", "fail", "No Chrome/Chromium found in standard paths", cat)


def _cdp_port() -> int:
    url = os.environ.get("POP_CDP_URL", "http://localhost:9222")
    try:
        parsed = urlparse(url)
        return parsed.port or 9222
    except Exception:
        return 9222


def _check_cdp_port(cat):
    port = _cdp_port()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return _mk("cdp_port", f"CDP port {port}", "warn", f"Port {port} already in use — may conflict", cat)
    except Exception:
        return _mk("cdp_port", f"CDP port {port}", "pass", f"Port {port} available", cat)
    finally:
        try:
            s.close()
        except Exception:
            pass


def _check_config_dir(cat):
    d = pathlib.Path.home() / ".config" / "pop-pay"
    if d.exists():
        return _mk("config_dir", "~/.config/pop-pay/", "pass", str(d), cat)
    return _mk("config_dir", "~/.config/pop-pay/", "warn", f"Does not exist: {d}", cat)


def _check_vault(cat):
    vp = os.environ.get("POP_VAULT_PATH") or str(pathlib.Path.home() / ".config" / "pop-pay" / "vault.enc")
    p = pathlib.Path(vp)
    if not p.exists():
        return _mk("vault", "vault.enc", "warn", f"Not initialized ({vp})", cat)
    try:
        size = p.stat().st_size
        if size < 16:
            return _mk("vault", "vault.enc", "fail", f"File too small ({size}B) — possibly corrupt", cat)
        return _mk("vault", "vault.enc", "pass", f"Found ({size}B)", cat)
    except Exception as e:
        return _mk("vault", "vault.enc", "fail", f"stat failed: {e}", cat)


def _check_env_vars(cat):
    """Format-only. Never log values. Presence check + JSON-parse for array envs."""
    names = [
        "POP_LLM_API_KEY",
        "POP_LLM_BASE_URL",
        "POP_LLM_MODEL",
        "POP_LLM_PROVIDER",
        "POP_ALLOWED_CATEGORIES",
        "POP_ALLOWED_PAYMENT_PROCESSORS",
        "POP_BLOCK_LOOPS",
        "POP_BLOCK_KEYWORDS",
        "POP_CDP_URL",
        "POP_VAULT_PATH",
        "POP_AUTO_INJECT",
    ]
    summary = []
    parse_errors = []
    for n in names:
        raw = os.environ.get(n)
        if raw is None:
            summary.append(f"{n}: missing")
            continue
        if n in ("POP_ALLOWED_CATEGORIES", "POP_ALLOWED_PAYMENT_PROCESSORS"):
            try:
                v = json.loads(raw)
                if isinstance(v, list):
                    summary.append(f"{n}: present ({len(v)} entries)")
                else:
                    summary.append(f"{n}: present (INVALID — not an array)")
                    parse_errors.append(n)
            except Exception:
                summary.append(f"{n}: present (INVALID JSON)")
                parse_errors.append(n)
            continue
        # All other vars (including POP_LLM_* secrets): presence-only, zero
        # signal about content. No length, no prefix, no hash.
        summary.append(f"{n}: present (hidden)")
    detail = "\n".join(summary)
    if parse_errors:
        return _mk(
            "env_vars",
            "Environment variables",
            "fail",
            detail + f"\nparse errors: {', '.join(parse_errors)}",
            cat,
        )
    return _mk("env_vars", "Environment variables (format-only)", "pass", detail, cat)


def _check_policy_config(cat):
    issues = []
    cats_count = 0
    procs_count = 0
    for n, label in (("POP_ALLOWED_CATEGORIES", "categories"), ("POP_ALLOWED_PAYMENT_PROCESSORS", "processors")):
        raw = os.environ.get(n)
        if raw is None:
            continue
        try:
            v = json.loads(raw)
            if not isinstance(v, list):
                issues.append(f"{n} must be JSON array")
            elif label == "categories":
                cats_count = len(v)
            else:
                procs_count = len(v)
        except Exception:
            issues.append(f"{n} not valid JSON")
    if issues:
        return _mk("policy_config", "Policy config", "fail", "; ".join(issues), cat)
    return _mk(
        "policy_config",
        "Policy config",
        "pass",
        f"allowed_categories={cats_count}, allowed_processors={procs_count}",
        cat,
    )


def _check_layer1_probe(cat):
    try:
        import importlib
        import time as _t

        t0 = _t.time()
        importlib.import_module("pop_pay.engine")
        ms = int((_t.time() - t0) * 1000)
        return _mk("layer1_probe", "Layer 1 guardrail", "pass", f"loaded in {ms}ms", cat)
    except Exception as e:
        return _mk("layer1_probe", "Layer 1 guardrail", "fail", f"load failed: {e}", cat, True)


def _check_layer2_probe(cat):
    api_key = os.environ.get("POP_LLM_API_KEY")
    base_url = os.environ.get("POP_LLM_BASE_URL", "https://api.openai.com")
    model = os.environ.get("POP_LLM_MODEL", "gpt-4o-mini")
    if not api_key:
        return _mk(
            "layer2_probe",
            "Layer 2 (LLM) probe",
            "warn",
            "POP_LLM_API_KEY unset — LLM guardrail disabled",
            cat,
        )
    try:
        u = urlparse(base_url)
        host = u.hostname or "api.openai.com"
        port = u.port or (443 if u.scheme == "https" else 80)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        import time as _t

        t0 = _t.time()
        try:
            s.connect((host, port))
            ms = int((_t.time() - t0) * 1000)
            s.close()
            return _mk(
                "layer2_probe",
                "Layer 2 (LLM) reachability",
                "pass",
                f"{host}:{port} reachable ({ms}ms), model={model}",
                cat,
            )
        except Exception as e:
            ms = int((_t.time() - t0) * 1000)
            return _mk(
                "layer2_probe",
                "Layer 2 (LLM) reachability",
                "fail",
                f"{host}:{port} unreachable ({ms}ms): {e}",
                cat,
            )
    except Exception as e:
        return _mk("layer2_probe", "Layer 2 (LLM) reachability", "fail", str(e), cat)


def _check_injector_smoke(cat):
    chrome = _find_chrome()
    if not chrome:
        return _mk("injector_smoke", "Injector smoke", "fail", "No Chromium binary to smoke-test", cat)
    try:
        r = subprocess.run([chrome, "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout:
            return _mk("injector_smoke", "Injector smoke (Chrome --version)", "pass", r.stdout.strip(), cat)
        return _mk("injector_smoke", "Injector smoke", "warn", f"Chrome exited {r.returncode}", cat)
    except Exception as e:
        return _mk("injector_smoke", "Injector smoke", "fail", str(e), cat)


# --- output ---------------------------------------------------------------

_ICONS = {"pass": "[✓]", "warn": "[⚠]", "fail": "[✗]"}


def _get_version() -> str:
    try:
        import importlib.metadata as md

        return md.version("pop-pay")
    except Exception:
        return "unknown"


def _render(checks: list[DoctorCheck]) -> None:
    version = _get_version()
    title = f"╭─ pop-pay doctor v{version} ─╮"
    print()
    print(title)
    print("│  Checking installation... │")
    print("╰" + "─" * (len(title) - 2) + "╯")
    print()
    for c in checks:
        print(f"{_ICONS[c.status]} {c.name}")
        if c.detail:
            for line in c.detail.split("\n"):
                print(f"    {line}")
        if c.remediation:
            print(f"    → {c.remediation}")
        if c.status != "pass":
            print()
    passed = sum(1 for c in checks if c.status == "pass")
    warned = sum(1 for c in checks if c.status == "warn")
    failed = sum(1 for c in checks if c.status == "fail")
    blockers = sum(1 for c in checks if c.status == "fail" and c.blocker)
    print("═══ Summary ═══")
    print(f"  {passed} passed | {warned} warnings | {failed} errors")
    if blockers:
        print(f"  pop-pay cannot start — {blockers} blocker(s) above")
    elif failed:
        print(f"  pop-pay may start, but {failed} non-blocking error(s) present")
    else:
        print("  pop-pay is ready.")
    print()


def _f9_to_doctor(r: F9CheckResult, cat: dict[str, dict]) -> DoctorCheck:
    """Adapt an F9CheckResult onto the DoctorCheck surface for rendering.

    Any F9 failure is treated as a blocker at the doctor level (mirrors TS).
    Under default mode, f9_l2_sha_pin returns warn (not fail), so only the
    load-bearing layers (L1 codesign, L3 fork whitelist, and L2 under --strict)
    actually surface as blocking fails.
    """
    return _mk(
        r.id,
        r.name,
        r.status,
        r.detail,
        cat,
        blocker_override=(r.status == "fail"),
    )


def run_doctor(as_json: bool = False, fork_mode: ForkMode = "default") -> list[DoctorCheck]:
    cat = _load_remediation_catalog()
    checks = [
        _check_python_version(cat),
        _check_chromium(cat),
        _check_cdp_port(cat),
        _check_config_dir(cat),
        _check_vault(cat),
        _check_env_vars(cat),
        _check_policy_config(cat),
        _check_layer1_probe(cat),
        _check_layer2_probe(cat),
        _check_injector_smoke(cat),
    ]
    # F9 — Chrome binary integrity (4 layers; L4 emits two rows). Never
    # live-fetches; see docs/VAULT_THREAT_MODEL.md §2.8.
    f9 = run_f9_checks(F9Options(fork_mode=fork_mode, cdp_port=_cdp_port()))
    for r in f9.checks:
        checks.append(_f9_to_doctor(r, cat))
    if as_json:
        print(json.dumps([asdict(c) for c in checks], indent=2))
    else:
        _render(checks)
    return checks


def _parse_fork_mode(argv: list[str]) -> ForkMode:
    if "--strict" in argv:
        return "strict"
    if "--permissive" in argv:
        return "permissive"
    return "default"


def main() -> int:
    argv = sys.argv[1:]
    as_json = "--json" in argv
    fork_mode = _parse_fork_mode(argv)
    checks = run_doctor(as_json=as_json, fork_mode=fork_mode)
    return 1 if any(c.status == "fail" and c.blocker for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
