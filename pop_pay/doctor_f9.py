"""F9 — Chrome binary integrity (pop-pay doctor, Python mirror of TS).

Four-layer defense-in-depth for the "is the Chrome you're attaching CDP to
a tampered binary?" gap. Closes the CDP injection trust boundary documented
in docs/VAULT_THREAT_MODEL.md §2.8.

Layers:
  L1 — OS codesign verify + vendor identity (load-bearing)
  L2 — Static SHA-256 pin against in-repo known-good list
  L3 — Fork whitelist (Google / Brave / MS / Mozilla) with
       --strict / default / --permissive modes
  L4 — Runtime defense-in-depth (extension enumeration + CDP port hijack sniff)

NEVER live-fetches dl.google.com or any remote feed — by design, see
docs/VAULT_THREAT_MODEL.md §2.8 "Rationale — why not live-fetch".
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import platform
import re
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Literal

ForkMode = Literal["strict", "default", "permissive"]
CheckStatus = Literal["pass", "warn", "fail"]


@dataclass
class F9CheckResult:
    id: str
    name: str
    status: CheckStatus
    detail: str
    vendor: str | None = None
    team_id: str | None = None
    sha256: str | None = None
    version: str | None = None
    fork_mode: ForkMode | None = None
    extensions: list[dict[str, str]] = field(default_factory=list)


@dataclass
class F9Options:
    chrome_path: str | None = None
    fork_mode: ForkMode = "default"
    cdp_port: int = 9222
    # Dependency-injection hooks for unit tests; production leaves these None.
    exec_fn: Callable[[str, list[str]], tuple[int | None, str, str]] | None = None
    read_fn: Callable[[str], str] | None = None
    known_good_path: str | None = None
    net_fn: Callable[[str, int, float], str] | None = None
    list_extensions_fn: Callable[[], list[dict[str, str]]] | None = None


@dataclass
class F9RunResult:
    checks: list[F9CheckResult]
    chrome_path: str | None
    executable_path: str | None
    vendor: str | None = None
    team_id: str | None = None
    sha256: str | None = None
    fork_mode: ForkMode = "default"


# --- Chrome path resolution ------------------------------------------------


def resolve_chrome_path(override: str | None = None) -> str | None:
    if override and pathlib.Path(override).exists():
        return override
    env = os.environ.get("POP_CHROME_PATH")
    if env and pathlib.Path(env).exists():
        return env
    sysname = platform.system()
    if sysname == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app",
            "/Applications/Chromium.app",
            "/Applications/Google Chrome Canary.app",
            "/Applications/Brave Browser.app",
            "/Applications/Microsoft Edge.app",
            "/Applications/Firefox.app",
        ]
    elif sysname == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            "/usr/bin/brave-browser",
            "/usr/bin/microsoft-edge",
        ]
    for p in candidates:
        if pathlib.Path(p).exists():
            return p
    return None


def executable_path_for(chrome_path: str) -> str:
    """Map /Applications/Foo.app → the binary inside Contents/MacOS on macOS."""
    if platform.system() == "Darwin" and chrome_path.endswith(".app"):
        macos_dir = pathlib.Path(chrome_path) / "Contents" / "MacOS"
        if macos_dir.exists():
            entries = list(macos_dir.iterdir())
            if entries:
                return str(entries[0])
    return chrome_path


# --- Exec / network shims (test-friendly) ----------------------------------


def _exec(
    opts: F9Options, cmd: str, args: list[str]
) -> tuple[int | None, str, str]:
    if opts.exec_fn is not None:
        return opts.exec_fn(cmd, args)
    try:
        r = subprocess.run(
            [cmd, *args], capture_output=True, text=True, timeout=5, check=False
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


# --- Layer 1 — OS codesign -------------------------------------------------


def parse_macos_codesign(stderr: str) -> tuple[bool, str | None, str | None, str]:
    """Extract (valid, vendor, team_id, detail) from `codesign -dv --verbose=4`."""
    m = re.search(
        r"Authority=Developer ID Application:\s*([^\n(]+?)\s*\(([A-Z0-9]{10})\)",
        stderr,
    )
    if not m:
        return False, None, None, "No Developer ID Authority line found"
    vendor = m.group(1).strip()
    team_id = m.group(2).strip()
    return True, vendor, team_id, f"Signed by {vendor} (Team ID {team_id})"


def _layer1_macos(chrome_path: str, opts: F9Options) -> F9CheckResult:
    # `codesign --verify` (NOT --strict; Chrome's .app bundle contains
    # resource-fork metadata which --strict rejects even though the
    # signature is cryptographically valid. Documented deviation from
    # original spec; see VAULT_THREAT_MODEL.md §2.8.)
    rc, _, stderr = _exec(opts, "codesign", ["--verify", chrome_path])
    if rc != 0:
        return F9CheckResult(
            id="f9_l1_codesign",
            name="F9 Layer 1 — OS codesign",
            status="fail",
            detail=f"codesign --verify exit {rc}: {stderr.strip() or 'invalid signature'}",
        )
    rc2, _, info = _exec(opts, "codesign", ["-dv", "--verbose=4", chrome_path])
    valid, vendor, team_id, detail = parse_macos_codesign(info)
    if not valid:
        return F9CheckResult(
            id="f9_l1_codesign",
            name="F9 Layer 1 — OS codesign",
            status="fail",
            detail=detail,
        )
    return F9CheckResult(
        id="f9_l1_codesign",
        name="F9 Layer 1 — OS codesign",
        status="pass",
        detail=detail,
        vendor=vendor,
        team_id=team_id,
    )


def _package_vendor(pkg_name: str) -> str | None:
    n = pkg_name.lower()
    if "google-chrome" in n:
        return "Google LLC"
    if "chromium" in n:
        return "Chromium"
    if "brave" in n:
        return "Brave Software Inc."
    if "microsoft-edge" in n or "msedge" in n:
        return "Microsoft Corporation"
    if "firefox" in n:
        return "Mozilla Foundation"
    return None


def _layer1_linux(chrome_path: str, opts: F9Options) -> F9CheckResult:
    # Debian/Ubuntu: dpkg -S identifies the package; dpkg -V checks
    # integrity against the package's recorded checksums. Fall through
    # to RPM, then warn.
    rc, out, _ = _exec(opts, "dpkg", ["-S", chrome_path])
    if rc == 0 and out.strip():
        pkg = out.split(":")[0].strip()
        rc2, out2, _ = _exec(opts, "dpkg", ["-V", pkg])
        if rc2 == 0 and not out2.strip():
            return F9CheckResult(
                id="f9_l1_codesign",
                name="F9 Layer 1 — OS codesign",
                status="pass",
                detail=f"dpkg integrity OK for {pkg}",
                vendor=_package_vendor(pkg),
            )
        return F9CheckResult(
            id="f9_l1_codesign",
            name="F9 Layer 1 — OS codesign",
            status="fail",
            detail=f"dpkg -V {pkg} reported changes: {out2.strip()}",
            vendor=_package_vendor(pkg),
        )
    rc3, out3, _ = _exec(opts, "rpm", ["-qf", chrome_path])
    if rc3 == 0 and out3.strip():
        pkg = out3.strip()
        rc4, out4, _ = _exec(opts, "rpm", ["-V", pkg])
        if rc4 == 0:
            return F9CheckResult(
                id="f9_l1_codesign",
                name="F9 Layer 1 — OS codesign",
                status="pass",
                detail=f"rpm integrity OK for {pkg}",
                vendor=_package_vendor(pkg),
            )
        return F9CheckResult(
            id="f9_l1_codesign",
            name="F9 Layer 1 — OS codesign",
            status="fail",
            detail=f"rpm -V {pkg} reported changes: {out4.strip()}",
            vendor=_package_vendor(pkg),
        )
    return F9CheckResult(
        id="f9_l1_codesign",
        name="F9 Layer 1 — OS codesign",
        status="warn",
        detail="No dpkg/rpm record for this Chrome path — cannot verify distro signature",
    )


def _layer1_windows(chrome_path: str, opts: F9Options) -> F9CheckResult:
    # Get-AuthenticodeSignature → "<Status>|<SignerCertificate.Subject>"
    escaped = chrome_path.replace("'", "''")
    rc, out, err = _exec(
        opts,
        "powershell.exe",
        [
            "-NoProfile",
            "-Command",
            f"$s = Get-AuthenticodeSignature -FilePath '{escaped}'; "
            "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)",
        ],
    )
    if rc != 0 or not out.strip():
        return F9CheckResult(
            id="f9_l1_codesign",
            name="F9 Layer 1 — OS codesign",
            status="fail",
            detail=f"Get-AuthenticodeSignature failed: {err.strip() or 'no output'}",
        )
    parts = out.strip().split("|")
    status = parts[0] if parts else ""
    subject = parts[1] if len(parts) > 1 else ""
    if status != "Valid":
        return F9CheckResult(
            id="f9_l1_codesign",
            name="F9 Layer 1 — OS codesign",
            status="fail",
            detail=f"Authenticode status={status} subject={subject}",
        )
    m = re.search(r'CN="?([^,"]+)"?', subject or "")
    vendor = m.group(1).strip() if m else None
    return F9CheckResult(
        id="f9_l1_codesign",
        name="F9 Layer 1 — OS codesign",
        status="pass",
        detail=f"Authenticode Valid, {subject}",
        vendor=vendor,
    )


def layer1_codesign(chrome_path: str, opts: F9Options) -> F9CheckResult:
    sysname = platform.system()
    if sysname == "Darwin":
        return _layer1_macos(chrome_path, opts)
    if sysname == "Windows":
        return _layer1_windows(chrome_path, opts)
    return _layer1_linux(chrome_path, opts)


# --- Layer 2 — Static SHA-256 pin ------------------------------------------


def hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_known_good(opts: F9Options) -> dict:
    here = pathlib.Path(__file__).resolve().parent
    candidates = [
        opts.known_good_path,
        str(here / "data" / "chrome_known_good_sha256.json"),
        str(here.parent / "data" / "chrome_known_good_sha256.json"),
    ]
    for p in candidates:
        if not p:
            continue
        try:
            if not pathlib.Path(p).exists():
                continue
            raw = opts.read_fn(p) if opts.read_fn else pathlib.Path(p).read_text(encoding="utf-8")
            return json.loads(raw)
        except Exception:
            continue
    return {"entries": [], "vendors_accepted_default": [], "vendor_id_macos_known": {}}


def layer2_sha_pin(
    exec_path: str,
    opts: F9Options,
    vendor: str | None = None,
    version: str | None = None,
) -> F9CheckResult:
    try:
        sha = hash_file(exec_path)
    except Exception as e:  # noqa: BLE001
        return F9CheckResult(
            id="f9_l2_sha_pin",
            name="F9 Layer 2 — SHA-256 pin",
            status="fail",
            detail=f"Failed to hash {exec_path}: {e}",
        )
    kg = load_known_good(opts)
    for entry in kg.get("entries", []):
        if entry.get("sha256") == sha:
            return F9CheckResult(
                id="f9_l2_sha_pin",
                name="F9 Layer 2 — SHA-256 pin",
                status="pass",
                detail=(
                    f"SHA matches known-good {entry['vendor']} {entry['channel']} "
                    f"{entry['version']} ({entry['platform']}/{entry['arch']})"
                ),
                sha256=sha,
                version=entry["version"],
            )
    # SHA not in list — warn unless --strict (escalated by orchestrator).
    return F9CheckResult(
        id="f9_l2_sha_pin",
        name="F9 Layer 2 — SHA-256 pin",
        status="warn",
        detail=(
            f"SHA {sha[:16]}… not in known-good list "
            f"(vendor={vendor or '?'}, version={version or '?'}). "
            "Expected for Chrome updates between list bumps; "
            "escalate to fail only under --strict."
        ),
        sha256=sha,
        version=version,
    )


# --- Layer 3 — Fork whitelist ----------------------------------------------


def layer3_fork_whitelist(vendor: str | None, opts: F9Options) -> F9CheckResult:
    mode = opts.fork_mode
    if mode == "permissive":
        return F9CheckResult(
            id="f9_l3_fork",
            name="F9 Layer 3 — Fork whitelist",
            status="pass",
            detail=f"--permissive: any valid codesign accepted (detected vendor={vendor or 'unknown'})",
            vendor=vendor,
            fork_mode=mode,
        )
    if vendor is None:
        return F9CheckResult(
            id="f9_l3_fork",
            name="F9 Layer 3 — Fork whitelist",
            status="fail",
            detail="No vendor identity resolved from Layer 1 — cannot match whitelist",
            fork_mode=mode,
        )
    if mode == "strict":
        if vendor == "Google LLC":
            return F9CheckResult(
                id="f9_l3_fork",
                name="F9 Layer 3 — Fork whitelist",
                status="pass",
                detail="--strict: Google LLC only",
                vendor=vendor,
                fork_mode=mode,
            )
        return F9CheckResult(
            id="f9_l3_fork",
            name="F9 Layer 3 — Fork whitelist",
            status="fail",
            detail=f"--strict rejects vendor {vendor}; only Google LLC accepted",
            vendor=vendor,
            fork_mode=mode,
        )
    kg = load_known_good(opts)
    accepted = kg.get("vendors_accepted_default", [])
    matched = any(v == vendor or vendor.find(v) >= 0 for v in accepted)
    if matched:
        return F9CheckResult(
            id="f9_l3_fork",
            name="F9 Layer 3 — Fork whitelist",
            status="pass",
            detail=f"Vendor {vendor} on default whitelist",
            vendor=vendor,
            fork_mode=mode,
        )
    return F9CheckResult(
        id="f9_l3_fork",
        name="F9 Layer 3 — Fork whitelist",
        status="fail",
        detail=(
            f"Vendor {vendor} not on default whitelist ({', '.join(accepted)}). "
            "Use --permissive to accept any valid codesign."
        ),
        vendor=vendor,
        fork_mode=mode,
    )


# --- Layer 4 — Runtime defense-in-depth ------------------------------------


def _extension_dirs() -> list[str]:
    home = pathlib.Path.home()
    sysname = platform.system()
    if sysname == "Darwin":
        return [
            str(home / "Library/Application Support/Google/Chrome/Default/Extensions"),
            str(home / "Library/Application Support/BraveSoftware/Brave-Browser/Default/Extensions"),
            str(home / "Library/Application Support/Microsoft Edge/Default/Extensions"),
        ]
    if sysname == "Windows":
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData/Local")
        return [
            f"{local}\\Google\\Chrome\\User Data\\Default\\Extensions",
            f"{local}\\Microsoft\\Edge\\User Data\\Default\\Extensions",
        ]
    return [
        str(home / ".config/google-chrome/Default/Extensions"),
        str(home / ".config/chromium/Default/Extensions"),
        str(home / ".config/BraveSoftware/Brave-Browser/Default/Extensions"),
    ]


_EXT_ID_RE = re.compile(r"^[a-p]{32}$")


def enumerate_extensions(opts: F9Options) -> list[dict[str, str]]:
    if opts.list_extensions_fn is not None:
        return opts.list_extensions_fn()
    out: list[dict[str, str]] = []
    for d in _extension_dirs():
        p = pathlib.Path(d)
        if not p.exists():
            continue
        try:
            for child in p.iterdir():
                if _EXT_ID_RE.match(child.name):
                    out.append({"id": child.name, "path": str(child)})
        except Exception:
            continue
    return out


def _probe_port(host: str, port: int, timeout: float) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return "listening"
    except Exception:
        return "closed"
    finally:
        try:
            s.close()
        except Exception:
            pass


def layer4_runtime(opts: F9Options) -> tuple[F9CheckResult, F9CheckResult]:
    exts = enumerate_extensions(opts)
    ext_check = F9CheckResult(
        id="f9_l4_extensions",
        name="F9 Layer 4a — Extension enumeration",
        status="pass",
        detail=("No Chrome extensions found"
                if not exts
                else f"{len(exts)} extension(s) across known browsers"),
        extensions=exts,
    )
    port = opts.cdp_port or 9222
    probe = (
        opts.net_fn("127.0.0.1", port, 0.5)
        if opts.net_fn is not None
        else _probe_port("127.0.0.1", port, 0.5)
    )
    if probe == "listening":
        port_check = F9CheckResult(
            id="f9_l4_cdp_port",
            name="F9 Layer 4b — CDP port hijack sniff",
            status="warn",
            detail=(
                f"Port {port} already listening — pre-existing process could be "
                "impersonating Chrome DevTools. Stop it before launching pop-pay, "
                "or set POP_CDP_URL to a different port."
            ),
        )
    else:
        port_check = F9CheckResult(
            id="f9_l4_cdp_port",
            name="F9 Layer 4b — CDP port hijack sniff",
            status="pass",
            detail=f"Port {port} unclaimed — safe to bind",
        )
    return ext_check, port_check


# --- Orchestrator ---------------------------------------------------------


def run_f9_checks(opts: F9Options | None = None) -> F9RunResult:
    opts = opts or F9Options()
    chrome_path = resolve_chrome_path(opts.chrome_path)
    if not chrome_path:
        miss = F9CheckResult(
            id="f9_l1_codesign",
            name="F9 Layer 1 — OS codesign",
            status="fail",
            detail="No Chrome/Chromium binary found — cannot run F9 checks",
        )
        return F9RunResult(
            checks=[miss],
            chrome_path=None,
            executable_path=None,
            fork_mode=opts.fork_mode,
        )
    exec_path = executable_path_for(chrome_path)
    l1 = layer1_codesign(chrome_path, opts)
    l2 = layer2_sha_pin(exec_path, opts, l1.vendor, l1.version)
    l3 = layer3_fork_whitelist(l1.vendor, opts)
    ext_check, port_check = layer4_runtime(opts)
    if opts.fork_mode == "strict" and l2.status == "warn":
        l2.status = "fail"
        l2.detail = f"--strict: {l2.detail}"
    return F9RunResult(
        checks=[l1, l2, l3, ext_check, port_check],
        chrome_path=chrome_path,
        executable_path=exec_path,
        vendor=l1.vendor,
        team_id=l1.team_id,
        sha256=l2.sha256,
        fork_mode=opts.fork_mode,
    )
