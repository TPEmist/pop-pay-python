"""F9 Chrome binary integrity — unit tests (Python mirror of TS tests).

24 cases. Matches vitest layout one-for-one. Platform-bound dispatch tests
use `if platform.system() != "Darwin": return` so the suite runs green on
any host while each OS-specific path is still covered on its native CI.

Dependency injection: F9Options carries exec_fn / net_fn / list_extensions_fn
/ known_good_path so we never shell out to real codesign / dpkg / rpm /
PowerShell during tests.
"""
from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from pathlib import Path

from pop_pay.doctor_f9 import (
    F9Options,
    layer1_codesign,
    layer2_sha_pin,
    layer3_fork_whitelist,
    layer4_runtime,
    load_known_good,
    parse_macos_codesign,
    run_f9_checks,
)


# --- Layer 1 parse --------------------------------------------------------


def test_layer1_parse_extracts_vendor_and_team_id():
    out = (
        "\nExecutable=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n"
        "Identifier=com.google.Chrome\n"
        "Authority=Developer ID Application: Google LLC (EQHXZ8M8AV)\n"
        "Authority=Developer ID Certification Authority\n"
    )
    valid, vendor, team_id, _ = parse_macos_codesign(out)
    assert valid is True
    assert vendor == "Google LLC"
    assert team_id == "EQHXZ8M8AV"


def test_layer1_parse_rejects_unrelated_output():
    valid, *_ = parse_macos_codesign("some unrelated output\n")
    assert valid is False


def test_layer1_parse_brave_microsoft_mozilla():
    cases = [
        (
            "Authority=Developer ID Application: Brave Software Inc. (KL8N8XSYF4)\n",
            "Brave Software Inc.",
            "KL8N8XSYF4",
        ),
        (
            "Authority=Developer ID Application: Microsoft Corporation (UBF8T346G9)\n",
            "Microsoft Corporation",
            "UBF8T346G9",
        ),
        (
            "Authority=Developer ID Application: Mozilla Foundation (43AQ936H96)\n",
            "Mozilla Foundation",
            "43AQ936H96",
        ),
    ]
    for line, expected_vendor, expected_tid in cases:
        _, vendor, team_id, _ = parse_macos_codesign(line)
        assert vendor == expected_vendor
        assert team_id == expected_tid


# --- Layer 1 dispatch (mocked exec) ---------------------------------------


def _mock_exec(responses: dict[str, tuple[int, str, str]]):
    """Return an exec_fn that matches cmd+args by substring."""
    def _f(cmd: str, args: list[str]) -> tuple[int | None, str, str]:
        key = " ".join([cmd, *args])
        for k, v in responses.items():
            if k in key:
                return v
        return (1, "", "no mock match")
    return _f


def test_layer1_macos_passes_when_codesign_ok():
    if platform.system() != "Darwin":
        return
    opts = F9Options(
        exec_fn=_mock_exec({
            "codesign --verify": (0, "", ""),
            "codesign -dv --verbose=4": (
                0,
                "",
                "Authority=Developer ID Application: Google LLC (EQHXZ8M8AV)\n",
            ),
        })
    )
    r = layer1_codesign("/Applications/Google Chrome.app", opts)
    assert r.status == "pass"
    assert r.vendor == "Google LLC"
    assert r.team_id == "EQHXZ8M8AV"


def test_layer1_macos_fails_when_codesign_verify_nonzero():
    if platform.system() != "Darwin":
        return
    opts = F9Options(
        exec_fn=_mock_exec({"codesign --verify": (1, "", "invalid signature")})
    )
    r = layer1_codesign("/Applications/Google Chrome.app", opts)
    assert r.status == "fail"


def test_layer1_linux_passes_when_dpkg_clean():
    if platform.system() != "Linux":
        return
    opts = F9Options(
        exec_fn=_mock_exec({
            "dpkg -S": (0, "google-chrome-stable: /usr/bin/google-chrome\n", ""),
            "dpkg -V": (0, "", ""),
        })
    )
    r = layer1_codesign("/usr/bin/google-chrome", opts)
    assert r.status == "pass"
    assert r.vendor == "Google LLC"


def test_layer1_linux_fails_when_dpkg_V_reports_changes():
    if platform.system() != "Linux":
        return
    opts = F9Options(
        exec_fn=_mock_exec({
            "dpkg -S": (0, "google-chrome-stable: /usr/bin/google-chrome\n", ""),
            "dpkg -V": (1, "..5......  /usr/bin/google-chrome\n", ""),
        })
    )
    r = layer1_codesign("/usr/bin/google-chrome", opts)
    assert r.status == "fail"


def test_layer1_windows_passes_when_authenticode_valid():
    if platform.system() != "Windows":
        return
    opts = F9Options(
        exec_fn=_mock_exec({
            "Get-AuthenticodeSignature": (
                0,
                'Valid|CN="Google LLC", O=Google LLC, L=Mountain View, S=California, C=US\n',
                "",
            ),
        })
    )
    r = layer1_codesign(
        r"C:\Program Files\Google\Chrome\Application\chrome.exe", opts
    )
    assert r.status == "pass"
    assert r.vendor == "Google LLC"


def test_layer1_windows_fails_when_not_valid():
    if platform.system() != "Windows":
        return
    opts = F9Options(
        exec_fn=_mock_exec({
            "Get-AuthenticodeSignature": (0, "NotSigned|\n", ""),
        })
    )
    r = layer1_codesign(r"C:\x\chrome.exe", opts)
    assert r.status == "fail"


# --- Layer 2 SHA pin ------------------------------------------------------


def _mock_known_good_file(sha: str) -> str:
    d = Path(tempfile.mkdtemp(prefix="f9-kg-"))
    body = {
        "entries": [
            {
                "vendor": "Google LLC",
                "channel": "stable",
                "version": "147.0.0",
                "platform": platform.system().lower(),
                "arch": "universal",
                "sha256": sha,
            }
        ],
        "vendors_accepted_default": [
            "Google LLC",
            "Brave Software Inc.",
            "Microsoft Corporation",
            "Mozilla Foundation",
        ],
        "vendor_id_macos_known": {"Google LLC": "EQHXZ8M8AV"},
    }
    p = d / "kg.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return str(p)


def test_layer2_matches_known_good_entry():
    d = Path(tempfile.mkdtemp(prefix="f9-bin-"))
    bin_path = d / "chrome-bin"
    payload = b"fake-chrome-binary"
    bin_path.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    kg_path = _mock_known_good_file(sha)
    r = layer2_sha_pin(str(bin_path), F9Options(known_good_path=kg_path), "Google LLC")
    assert r.status == "pass"
    assert r.sha256 == sha


def test_layer2_warns_when_sha_not_in_list_default_mode():
    d = Path(tempfile.mkdtemp(prefix="f9-bin-"))
    bin_path = d / "chrome-bin"
    bin_path.write_bytes(b"some-other-bytes")
    kg_path = _mock_known_good_file("0" * 64)
    r = layer2_sha_pin(str(bin_path), F9Options(known_good_path=kg_path), "Google LLC")
    assert r.status == "warn"


def test_layer2_fails_when_binary_unreadable():
    r = layer2_sha_pin("/nonexistent/path/chrome", F9Options())
    assert r.status == "fail"


# --- Layer 3 fork whitelist -----------------------------------------------


def test_layer3_default_passes_google():
    r = layer3_fork_whitelist("Google LLC", F9Options(fork_mode="default"))
    assert r.status == "pass"


def test_layer3_default_passes_brave():
    r = layer3_fork_whitelist("Brave Software Inc.", F9Options(fork_mode="default"))
    assert r.status == "pass"


def test_layer3_default_fails_off_list_vendor():
    r = layer3_fork_whitelist("Sketchy Forks Ltd.", F9Options(fork_mode="default"))
    assert r.status == "fail"


def test_layer3_strict_passes_only_google():
    assert layer3_fork_whitelist("Google LLC", F9Options(fork_mode="strict")).status == "pass"
    assert (
        layer3_fork_whitelist("Brave Software Inc.", F9Options(fork_mode="strict")).status == "fail"
    )


def test_layer3_permissive_passes_any_vendor():
    r = layer3_fork_whitelist("Anyone", F9Options(fork_mode="permissive"))
    assert r.status == "pass"


def test_layer3_fails_when_vendor_is_none_under_default_and_strict():
    assert layer3_fork_whitelist(None, F9Options(fork_mode="default")).status == "fail"
    assert layer3_fork_whitelist(None, F9Options(fork_mode="strict")).status == "fail"


# --- Layer 4 runtime ------------------------------------------------------


def test_layer4_extensions_uses_injected_enumerator():
    exts = [{"id": "a" * 32, "path": "/mock/a"}]
    ext_check, _ = layer4_runtime(
        F9Options(list_extensions_fn=lambda: exts, net_fn=lambda *a: "closed")
    )
    assert ext_check.status == "pass"
    assert ext_check.extensions == exts


def test_layer4_cdp_port_warns_when_listening():
    _, port_check = layer4_runtime(
        F9Options(list_extensions_fn=lambda: [], net_fn=lambda *a: "listening")
    )
    assert port_check.status == "warn"


def test_layer4_cdp_port_passes_when_unclaimed():
    _, port_check = layer4_runtime(
        F9Options(list_extensions_fn=lambda: [], net_fn=lambda *a: "closed")
    )
    assert port_check.status == "pass"


# --- Orchestrator ---------------------------------------------------------


def test_orchestrator_escalates_l2_warn_to_fail_under_strict():
    d = Path(tempfile.mkdtemp(prefix="f9-orch-"))
    bin_path = d / "bin"
    bin_path.write_bytes(b"mismatch")
    kg_dir = Path(tempfile.mkdtemp(prefix="f9-orch-kg-"))
    kg_path = kg_dir / "kg.json"
    kg_path.write_text(
        json.dumps(
            {
                "entries": [],
                "vendors_accepted_default": ["Google LLC"],
                "vendor_id_macos_known": {},
            }
        ),
        encoding="utf-8",
    )
    # Mock exec returns Authority line for codesign calls. On Linux/RPM the
    # fallback branch runs (dpkg/rpm -S with empty stdout) and L1 becomes
    # warn — L2 escalation is what we're asserting here regardless.
    r = run_f9_checks(
        F9Options(
            chrome_path=str(bin_path),
            fork_mode="strict",
            known_good_path=str(kg_path),
            exec_fn=lambda c, a: (
                0,
                "",
                "Authority=Developer ID Application: Google LLC (EQHXZ8M8AV)\n",
            ),
            net_fn=lambda *a: "closed",
            list_extensions_fn=lambda: [],
        )
    )
    l2 = next(c for c in r.checks if c.id == "f9_l2_sha_pin")
    assert l2.status == "fail"


# --- Data file integrity --------------------------------------------------


def test_data_file_has_at_least_one_entry_and_default_vendors():
    kg = load_known_good(F9Options())
    assert len(kg.get("entries", [])) > 0
    assert "Google LLC" in kg.get("vendors_accepted_default", [])


def test_data_file_all_sha_values_are_lowercase_hex_64():
    import re

    pattern = re.compile(r"^[0-9a-f]{64}$")
    kg = load_known_good(F9Options())
    for entry in kg.get("entries", []):
        assert pattern.match(entry["sha256"]), entry["sha256"]
