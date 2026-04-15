"""
test_vault.py — Security tests for vault encryption and SQLite hardening.
"""
import os
import stat
import pytest
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Vault tests
# ---------------------------------------------------------------------------

def test_vault_encrypt_decrypt(tmp_path):
    """Round-trip: save then load credentials returns identical dict."""
    pytest.importorskip("cryptography", reason="cryptography package required for vault tests")
    from pop_pay.vault import encrypt_credentials, decrypt_credentials

    creds = {
        "card_number": "4111111111111111",
        "cvv": "123",
        "exp_month": "12",
        "exp_year": "28",
        "expiration_date": "12/28",
    }
    blob = encrypt_credentials(creds)
    result = decrypt_credentials(blob)
    assert result == creds


def test_vault_wrong_key_raises():
    """Tampered blob must raise ValueError."""
    pytest.importorskip("cryptography", reason="cryptography package required for vault tests")
    from pop_pay.vault import encrypt_credentials, decrypt_credentials

    creds = {"card_number": "4111111111111111", "cvv": "999"}
    blob = encrypt_credentials(creds)

    # Flip a byte in the ciphertext region (after the 12-byte nonce)
    tampered = bytearray(blob)
    tampered[20] ^= 0xFF
    with pytest.raises(ValueError):
        decrypt_credentials(bytes(tampered))


def test_vault_atomic_write(tmp_path, monkeypatch):
    """After save_vault, vault.enc exists and has mode 0o600."""
    pytest.importorskip("cryptography", reason="cryptography package required for vault tests")
    from pop_pay import vault as vault_mod

    # Redirect vault paths to tmp_path
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(vault_mod, "VAULT_PATH", tmp_path / "vault.enc")

    creds = {"card_number": "4111111111111111", "cvv": "123", "expiration_date": "12/28"}
    vault_mod.save_vault(creds)

    vault_file = tmp_path / "vault.enc"
    assert vault_file.exists(), "vault.enc should exist after save_vault"
    file_mode = stat.S_IMODE(vault_file.stat().st_mode)
    assert file_mode == 0o600, f"vault.enc permissions should be 0o600, got {oct(file_mode)}"


# ---------------------------------------------------------------------------
# SQLite security tests
# ---------------------------------------------------------------------------

def test_sqlite_no_cvv():
    """record_seal does not accept a cvv param, and get_seal_details does not exist."""
    from pop_pay.core.state import PopStateTracker
    import inspect

    tracker = PopStateTracker(db_path=":memory:")

    # get_seal_details must not exist
    assert not hasattr(tracker, "get_seal_details"), (
        "get_seal_details() must be removed — it returned plaintext card data"
    )

    # record_seal must not accept cvv
    sig = inspect.signature(tracker.record_seal)
    assert "cvv" not in sig.parameters, (
        "record_seal() must not accept a cvv parameter"
    )

    tracker.close()


def test_sqlite_masked_card():
    """Masked card is stored correctly and retrievable."""
    from pop_pay.core.state import PopStateTracker

    tracker = PopStateTracker(db_path=":memory:")
    tracker.record_seal(
        seal_id="seal-test-001",
        amount=19.99,
        vendor="TestVendor",
        status="Issued",
        masked_card="****-****-****-4242",
        expiration_date="12/28",
    )

    masked = tracker.get_seal_masked_card("seal-test-001")
    assert masked == "****-****-****-4242", f"Expected masked card, got: {masked!r}"

    tracker.close()


# ---------------------------------------------------------------------------
# VirtualSeal repr redaction test
# ---------------------------------------------------------------------------

def test_virtual_seal_repr_redacted():
    """repr(seal) must not contain actual card number or CVV."""
    from pop_pay.core.models import VirtualSeal

    seal = VirtualSeal(
        seal_id="seal-repr-test",
        card_number="4111111111111111",
        cvv="999",
        expiration_date="12/28",
        authorized_amount=50.0,
        status="Issued",
    )

    r = repr(seal)
    assert "4111111111111111" not in r, "repr() must not expose card_number"
    assert "999" not in r, "repr() must not expose CVV"
    assert "REDACTED" in r or "****" in r, "repr() should indicate redaction"


# ---------------------------------------------------------------------------
# F4/F7: Vault marker schema + downgrade refuse (S0.7)
# ---------------------------------------------------------------------------

def test_vault_mode_legacy_hardened_migrates(tmp_path, monkeypatch):
    """Legacy 'hardened' marker must be read as 'machine-hardened'."""
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    (tmp_path / ".vault_mode").write_text("hardened")
    assert vault_mod._read_vault_mode() == "machine-hardened"


def test_vault_mode_legacy_oss_migrates(tmp_path, monkeypatch):
    """Legacy 'oss' marker must be read as 'machine-oss'."""
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    (tmp_path / ".vault_mode").write_text("oss")
    assert vault_mod._read_vault_mode() == "machine-oss"


def test_vault_mode_missing_returns_unknown(tmp_path, monkeypatch):
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    assert vault_mod._read_vault_mode() == "unknown"


def test_vault_mode_passphrase_write(tmp_path, monkeypatch):
    """is_passphrase=True writes 'passphrase' regardless of is_hardened."""
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    vault_mod._write_vault_mode(is_passphrase=True)
    assert (tmp_path / ".vault_mode").read_text() == "passphrase"


def test_vault_load_refuses_downgrade_machine_hardened(tmp_path, monkeypatch):
    """Marker says 'machine-hardened' but native reports not-hardened → refuse."""
    pytest.importorskip("cryptography")
    import pop_pay.vault as vault_mod
    from pop_pay.engine import _vault_core
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(vault_mod, "VAULT_PATH", tmp_path / "vault.enc")
    (tmp_path / ".vault_mode").write_text("machine-hardened")
    (tmp_path / "vault.enc").write_bytes(b"\x00" * 64)  # stub blob

    monkeypatch.setattr(_vault_core, "is_hardened", lambda: False)
    with pytest.raises(RuntimeError, match="hardened"):
        vault_mod.load_vault()


def test_vault_load_refuses_machine_oss_without_consent(tmp_path, monkeypatch):
    """F3: machine-oss vault must refuse load without POP_ACCEPT_OSS_SALT=1."""
    pytest.importorskip("cryptography")
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(vault_mod, "VAULT_PATH", tmp_path / "vault.enc")
    (tmp_path / ".vault_mode").write_text("machine-oss")
    (tmp_path / "vault.enc").write_bytes(b"\x00" * 64)
    monkeypatch.delenv("POP_ACCEPT_OSS_SALT", raising=False)
    with pytest.raises(ValueError, match="POP_ACCEPT_OSS_SALT"):
        vault_mod.load_vault()


def test_vault_load_machine_oss_consent_bypass(tmp_path, monkeypatch):
    """F3: POP_ACCEPT_OSS_SALT=1 bypasses the consent gate (reaches decrypt path)."""
    pytest.importorskip("cryptography")
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(vault_mod, "VAULT_PATH", tmp_path / "vault.enc")
    (tmp_path / ".vault_mode").write_text("machine-oss")
    (tmp_path / "vault.enc").write_bytes(b"\x00" * 64)
    monkeypatch.setenv("POP_ACCEPT_OSS_SALT", "1")
    with pytest.raises(Exception) as exc_info:
        vault_mod.load_vault()
    assert "POP_ACCEPT_OSS_SALT" not in str(exc_info.value)


def test_vault_load_passphrase_bypasses_oss_gate(tmp_path, monkeypatch):
    """F3: passphrase marker bypasses the OSS consent gate entirely."""
    pytest.importorskip("cryptography")
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(vault_mod, "VAULT_PATH", tmp_path / "vault.enc")
    (tmp_path / ".vault_mode").write_text("passphrase")
    (tmp_path / "vault.enc").write_bytes(b"\x00" * 64)
    monkeypatch.delenv("POP_ACCEPT_OSS_SALT", raising=False)
    with pytest.raises(Exception) as exc_info:
        vault_mod.load_vault()
    assert "POP_ACCEPT_OSS_SALT" not in str(exc_info.value)


def test_vault_load_refuses_downgrade_legacy_hardened_marker(tmp_path, monkeypatch):
    """Legacy 'hardened' marker (migrated to machine-hardened on read) must also refuse."""
    pytest.importorskip("cryptography")
    import pop_pay.vault as vault_mod
    from pop_pay.engine import _vault_core
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(vault_mod, "VAULT_PATH", tmp_path / "vault.enc")
    (tmp_path / ".vault_mode").write_text("hardened")  # pre-S0.7 value
    (tmp_path / "vault.enc").write_bytes(b"\x00" * 64)

    monkeypatch.setattr(_vault_core, "is_hardened", lambda: False)
    with pytest.raises(RuntimeError, match="hardened"):
        vault_mod.load_vault()


# ---------------------------------------------------------------------------
# F1: plaintext PAN/CVV must not leak into os.environ or child processes
# ---------------------------------------------------------------------------

def test_filtered_env_strips_all_byoc_keys():
    from pop_pay.vault import filtered_env, SENSITIVE_ENV_KEYS
    base = {
        "POP_BYOC_NUMBER": "4111111111111111",
        "POP_BYOC_CVV": "123",
        "POP_BYOC_EXP_MONTH": "12",
        "POP_BYOC_EXP_YEAR": "27",
        "HARMLESS": "ok",
    }
    out = filtered_env(base)
    for k in SENSITIVE_ENV_KEYS:
        assert k not in out
    assert out["HARMLESS"] == "ok"


def test_sensitive_env_keys_is_immutable_and_complete():
    from pop_pay.vault import SENSITIVE_ENV_KEYS
    assert "POP_BYOC_NUMBER" in SENSITIVE_ENV_KEYS
    assert "POP_BYOC_CVV" in SENSITIVE_ENV_KEYS
    assert "POP_BYOC_EXP_MONTH" in SENSITIVE_ENV_KEYS
    assert "POP_BYOC_EXP_YEAR" in SENSITIVE_ENV_KEYS
    assert isinstance(SENSITIVE_ENV_KEYS, tuple)


def test_child_process_with_filtered_env_cannot_see_byoc(monkeypatch):
    """Spawn a child via subprocess using filtered_env; BYOC vars must be absent."""
    import subprocess, sys, json as _json
    from pop_pay.vault import filtered_env
    monkeypatch.setenv("POP_BYOC_NUMBER", "4111111111111111")
    monkeypatch.setenv("POP_BYOC_CVV", "123")
    code = (
        "import os,json; "
        "print(json.dumps({k: os.environ.get(k) for k in "
        "('POP_BYOC_NUMBER','POP_BYOC_CVV','POP_BYOC_EXP_MONTH','POP_BYOC_EXP_YEAR')}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=filtered_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    seen = _json.loads(result.stdout)
    assert all(v is None for v in seen.values()), seen


def test_load_vault_does_not_inject_byoc_into_environ(tmp_path, monkeypatch):
    """F1 post-condition: load_vault must not populate os.environ with plaintext."""
    pytest.importorskip("cryptography")
    import pop_pay.vault as vault_mod
    from pop_pay.vault import SENSITIVE_ENV_KEYS
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(vault_mod, "VAULT_PATH", tmp_path / "vault.enc")
    (tmp_path / ".vault_mode").write_text("machine-hardened")
    creds = {"card_number": "4111111111111111", "cvv": "999", "expiration_date": "12/28"}
    blob = vault_mod.encrypt_credentials(creds)
    (tmp_path / "vault.enc").write_bytes(blob)
    try:
        from pop_pay.engine import _vault_core
        monkeypatch.setattr(_vault_core, "is_hardened", lambda: True)
    except ImportError:
        pass
    for k in SENSITIVE_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    try:
        vault_mod.load_vault()
    except Exception:
        pass
    for k in SENSITIVE_ENV_KEYS:
        assert k not in os.environ, f"load_vault leaked {k} into os.environ"


# ---------------------------------------------------------------------------
# F8: stale .tmp cleanup + wipe_vault_artifacts (S0.7)
# ---------------------------------------------------------------------------

def test_cleanup_stale_temp_files_wipes_siblings(tmp_path, monkeypatch):
    """cleanup_stale_temp_files removes vault.enc*.tmp siblings."""
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    stale1 = tmp_path / "vault.enc.tmp"
    stale2 = tmp_path / "vault.enc.abc.tmp"
    keep = tmp_path / "vault.enc"
    other = tmp_path / "unrelated.tmp"
    for p in (stale1, stale2, keep, other):
        p.write_bytes(b"secret-data")
    vault_mod.cleanup_stale_temp_files()
    assert not stale1.exists()
    assert not stale2.exists()
    assert keep.exists(), "vault.enc must not be wiped"
    assert other.exists(), "unrelated .tmp must not be wiped"


def test_wipe_vault_artifacts_enumerates_all_credential_files(tmp_path, monkeypatch):
    """wipe_vault_artifacts removes vault.enc, .tmp siblings, .vault_mode, .machine_id."""
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    targets = [
        tmp_path / "vault.enc",
        tmp_path / "vault.enc.tmp",
        tmp_path / ".vault_mode",
        tmp_path / ".machine_id",
    ]
    keep = tmp_path / "policy.env"
    for p in targets:
        p.write_bytes(b"x" * 16)
    keep.write_bytes(b"keep-me")
    wiped = vault_mod.wipe_vault_artifacts()
    for p in targets:
        assert not p.exists(), f"{p.name} should have been wiped"
    assert keep.exists(), "non-credential file must not be wiped"
    assert len(wiped) == 4


def test_wipe_vault_artifacts_idempotent_on_empty_dir(tmp_path, monkeypatch):
    """wipe_vault_artifacts on empty dir returns [] and does not throw."""
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    wiped = vault_mod.wipe_vault_artifacts()
    assert wiped == []


def test_save_vault_sweeps_stale_tmp_before_writing(tmp_path, monkeypatch):
    """save_vault calls cleanup_stale_temp_files — pre-existing stale .tmp gone after save."""
    pytest.importorskip("cryptography")
    import pop_pay.vault as vault_mod
    monkeypatch.setattr(vault_mod, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(vault_mod, "VAULT_PATH", tmp_path / "vault.enc")
    stale = tmp_path / "vault.enc.stale.tmp"
    stale.write_bytes(b"old-ciphertext")
    creds = {"card_number": "4111111111111111", "cvv": "123", "expiration_date": "12/28"}
    vault_mod.save_vault(creds)
    assert not stale.exists(), "save_vault should have swept stale .tmp"
    assert (tmp_path / "vault.enc").exists()
