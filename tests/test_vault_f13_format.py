"""F13 — vault blob format version byte.

Covers:
  - v1 blob layout: MAGIC(0x5050) || VERSION(0x01) || RESERVED(0x00) || body
  - AEAD AAD binding: tampered header fails with VaultDecryptFailed
  - Unknown VERSION byte raises "format vN not supported"
  - Legacy v0 (no-header) blob round-trips via fallback path
  - One-time legacy migration notice
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from pop_pay.errors import VaultDecryptFailed
from pop_pay.vault import (
    _reset_legacy_migration_notified,
    decrypt_credentials,
    encrypt_credentials,
)

TEST_KEY = bytes.fromhex(
    "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
)
TEST_SALT = b"test-salt-for-unit-tests-pop-pay"
CREDS = {"card_number": "4111111111111111", "cvv": "123"}


def _build_legacy_v0_blob(key: bytes, creds: dict) -> bytes:
    """Pre-F13 shape: nonce(12) || ct || tag(16), no AAD."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    # Avoid accidental magic collision (1/65536) — retry nonces.
    while nonce[:2] == b"\x50\x50":
        nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_and_tag = aesgcm.encrypt(nonce, json.dumps(creds).encode(), None)
    return nonce + ct_and_tag


class TestV1Layout:
    def test_header_bytes(self):
        blob = encrypt_credentials(CREDS, key_override=TEST_KEY)
        assert blob[0] == 0x50
        assert blob[1] == 0x50
        assert blob[2] == 0x01
        assert blob[3] == 0x00

    def test_v1_is_four_bytes_longer_than_v0(self):
        v1 = encrypt_credentials(CREDS, key_override=TEST_KEY)
        v0 = _build_legacy_v0_blob(TEST_KEY, CREDS)
        assert len(v1) == len(v0) + 4

    def test_round_trip(self):
        blob = encrypt_credentials(CREDS, salt=TEST_SALT)
        assert decrypt_credentials(blob, salt=TEST_SALT) == CREDS


class TestAEADBinding:
    def test_tampered_reserved_byte_fails(self):
        blob = bytearray(encrypt_credentials(CREDS, key_override=TEST_KEY))
        blob[3] = 0xFF  # flip RESERVED — still has magic + version 0x01
        with pytest.raises(VaultDecryptFailed):
            decrypt_credentials(bytes(blob), key_override=TEST_KEY)

    def test_unknown_version_rejected_before_aead(self):
        blob = bytearray(encrypt_credentials(CREDS, key_override=TEST_KEY))
        blob[2] = 0x02  # claim v2 — not supported
        with pytest.raises(VaultDecryptFailed, match="v2 not supported"):
            decrypt_credentials(bytes(blob), key_override=TEST_KEY)


class TestLegacyV0:
    def setup_method(self):
        _reset_legacy_migration_notified()

    def test_decrypts_legacy_v0(self):
        blob = _build_legacy_v0_blob(TEST_KEY, CREDS)
        assert blob[:2] != b"\x50\x50"
        assert decrypt_credentials(blob, key_override=TEST_KEY) == CREDS

    def test_emits_migration_notice_once(self, capsys):
        blob = _build_legacy_v0_blob(TEST_KEY, CREDS)
        decrypt_credentials(blob, key_override=TEST_KEY)
        decrypt_credentials(blob, key_override=TEST_KEY)
        captured = capsys.readouterr()
        matches = captured.err.count("migrating vault to format v1")
        assert matches == 1


class TestV1ToV0Fallback:
    """v1 header parse + AEAD verify fails → fall back to v0 path.

    Covers the 1/65536 case where a legacy v0 blob's random nonce happens to
    start with 0x5050 0x01 0x00 (same prefix as v1 magic + VERSION + RESERVED).
    """

    def _build_collided_v0(self) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        # Force nonce prefix to match v1 header so the reader enters the
        # v1 path, attempts AAD decrypt, fails, and falls back.
        nonce = b"\x50\x50\x01\x00" + os.urandom(8)
        aesgcm = AESGCM(TEST_KEY)
        ct_and_tag = aesgcm.encrypt(nonce, json.dumps(CREDS).encode(), None)
        return nonce + ct_and_tag

    def test_decrypts_collided_v0(self):
        blob = self._build_collided_v0()
        assert blob[0] == 0x50
        assert blob[1] == 0x50
        assert blob[2] == 0x01
        assert decrypt_credentials(blob, key_override=TEST_KEY) == CREDS


class TestMigrationRewriteOnSave:
    def test_rewrite_yields_v1(self):
        _reset_legacy_migration_notified()
        v0 = _build_legacy_v0_blob(TEST_KEY, CREDS)
        decoded = decrypt_credentials(v0, key_override=TEST_KEY)
        assert decoded == CREDS
        rewritten = encrypt_credentials(decoded, key_override=TEST_KEY)
        assert rewritten[0] == 0x50
        assert rewritten[1] == 0x50
        assert rewritten[2] == 0x01
