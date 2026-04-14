"""Tests for passphrase-based vault encryption."""
import pytest


def test_passphrase_key_differs_from_machine_key():
    """Passphrase key should differ from machine-derived key."""
    pytest.importorskip("cryptography")
    from pop_pay.vault import _derive_key, derive_key_from_passphrase
    machine_key = _derive_key()
    passphrase_key = derive_key_from_passphrase("test-passphrase-123")
    assert machine_key != passphrase_key


def test_passphrase_encrypt_decrypt_roundtrip():
    """Encrypt with passphrase key, decrypt with same passphrase key."""
    pytest.importorskip("cryptography")
    from pop_pay.vault import encrypt_credentials, decrypt_credentials, derive_key_from_passphrase
    key = derive_key_from_passphrase("my-strong-passphrase")
    creds = {"card_number": "4111111111111111", "cvv": "123"}
    blob = encrypt_credentials(creds, key_override=key)
    result = decrypt_credentials(blob, key_override=key)
    assert result == creds


def test_passphrase_wrong_key_fails():
    """Wrong passphrase cannot decrypt vault."""
    pytest.importorskip("cryptography")
    from pop_pay.vault import encrypt_credentials, decrypt_credentials, derive_key_from_passphrase
    key1 = derive_key_from_passphrase("correct-passphrase")
    key2 = derive_key_from_passphrase("wrong-passphrase")
    blob = encrypt_credentials({"card_number": "4111"}, key_override=key1)
    from pop_pay.errors import VaultDecryptFailed
    with pytest.raises(VaultDecryptFailed):
        decrypt_credentials(blob, key_override=key2)


def test_passphrase_different_from_machine_cannot_decrypt():
    """Machine-derived key cannot decrypt passphrase-encrypted vault."""
    pytest.importorskip("cryptography")
    from pop_pay.vault import encrypt_credentials, decrypt_credentials, derive_key_from_passphrase, _derive_key
    passphrase_key = derive_key_from_passphrase("secret-pass")
    machine_key = _derive_key()
    blob = encrypt_credentials({"card_number": "4111"}, key_override=passphrase_key)
    from pop_pay.errors import VaultDecryptFailed
    with pytest.raises(VaultDecryptFailed):
        decrypt_credentials(blob, key_override=machine_key)
