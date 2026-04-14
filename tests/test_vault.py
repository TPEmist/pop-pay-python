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
    """Tampered blob must raise VaultDecryptFailed."""
    pytest.importorskip("cryptography", reason="cryptography package required for vault tests")
    from pop_pay.vault import encrypt_credentials, decrypt_credentials
    from pop_pay.errors import VaultDecryptFailed

    creds = {"card_number": "4111111111111111", "cvv": "999"}
    blob = encrypt_credentials(creds)

    # Flip a byte in the ciphertext region (after the 12-byte nonce)
    tampered = bytearray(blob)
    tampered[20] ^= 0xFF
    with pytest.raises(VaultDecryptFailed):
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
