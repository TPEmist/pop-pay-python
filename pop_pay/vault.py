"""
pop-pay credential vault — AES-256-GCM encrypted credential storage.

Security model:
- Credentials are encrypted at rest using AES-256-GCM with a machine-derived key.
- The key is derived from a stable machine identifier using scrypt.
- Plaintext credentials never touch disk after init-vault completes.
- OSS version uses a public salt (documented limitation: protects against
  file-read-only agents, not against agents with shell execution).
  PyPI/Cython version will use a compiled-in secret salt.
- Option B passphrase mode: key derived from user passphrase via PBKDF2-HMAC-SHA256
  (600k iterations); stored in OS keyring for the session. Protects against agents
  with shell access — no passphrase, no decryption.
"""
import hashlib as _hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

from pop_pay.errors import VaultDecryptFailed, VaultNotFound, VaultLocked

# AES-256-GCM via cryptography library (pip install cryptography)
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

VAULT_DIR = Path.home() / ".config" / "pop-pay"
VAULT_PATH = VAULT_DIR / "vault.enc"

KEYRING_SERVICE = "pop-pay-vault"
KEYRING_USERNAME = "derived-key-hex"

# OSS public salt — intentionally documented as a security limitation.
# PyPI/Cython builds will replace this with a compiled-in secret.
_OSS_SALT = b"pop-pay-oss-v1-public-salt-2026"

# F13: vault blob format version byte.
# Layout: MAGIC(2)=0x5050 ("PP") || VERSION(1)=0x01 || RESERVED(1)=0x00 ||
#         nonce(12) || ciphertext || tag(16). The 4-byte header is bound into
# AEAD AAD so tampering with it fails tag verification. Legacy v0 blobs have
# no header; the reader detects absence of magic and falls back to the v0
# path (decrypt without AAD). The next save_vault rewrites as v1.
_VAULT_VERSION_V1 = 0x01
_VAULT_HEADER_V1 = bytes([0x50, 0x50, _VAULT_VERSION_V1, 0x00])
_VAULT_HEADER_LEN = 4

# One-time legacy-read migration notice (per process). Reset for tests.
_legacy_v0_notified = False


def _notify_legacy_v0_once() -> None:
    global _legacy_v0_notified
    if _legacy_v0_notified:
        return
    _legacy_v0_notified = True
    sys.stderr.write(
        "pop-pay: migrating vault to format v1; saved once you next update credentials.\n"
    )


def _reset_legacy_migration_notified() -> None:
    """Exported for tests only."""
    global _legacy_v0_notified
    _legacy_v0_notified = False

OSS_WARNING = (
    "\n⚠️  pop-pay SECURITY NOTICE: Running from source build (OSS mode).\n"
    "   Vault encryption uses a public salt. An agent with shell execution\n"
    "   tools could derive the vault key from public information.\n"
    "   For stronger security: install via PyPI (`pip install pop-pay`)\n"
    "   or use `pop-pay init-vault --passphrase` (coming in v0.6.x).\n"
)


def _get_machine_id() -> bytes:
    """Return a stable machine identifier. Falls back through platform-specific sources."""
    # Linux: /etc/machine-id (stable across reboots, not affected by network changes)
    machine_id_path = Path("/etc/machine-id")
    if machine_id_path.exists():
        mid = machine_id_path.read_text().strip()
        if mid:
            return mid.encode()

    # macOS: IOPlatformUUID via ioreg
    if sys.platform == "darwin":
        import subprocess
        try:
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    uid = line.split('"')[-2]
                    return uid.encode()
        except (OSError, subprocess.SubprocessError, IndexError):
            pass

    # Windows: MachineGuid from registry
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                  r"SOFTWARE\Microsoft\Cryptography")
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            return guid.encode()
        except (OSError, ImportError):
            pass

    # Fallback: generate a random ID and store it alongside the vault
    fallback_path = VAULT_DIR / ".machine_id"
    if fallback_path.exists():
        return fallback_path.read_bytes()
    import secrets
    fallback_id = secrets.token_bytes(32)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    fallback_path.write_bytes(fallback_id)
    fallback_path.chmod(0o600)
    return fallback_id


def _get_username() -> bytes:
    """Return a stable username, avoiding os.getlogin() which fails in non-login shells."""
    import pwd
    try:
        return pwd.getpwuid(os.getuid()).pw_name.encode()
    except (KeyError, OSError):
        pass
    return os.environ.get("USER", os.environ.get("USERNAME", "unknown")).encode()


def _derive_key(salt: bytes = None, key_override: bytes = None) -> bytes:
    """Derive AES-256 key. If key_override is provided, use it directly.

    For PyPI/Cython builds: delegates to _vault_core.derive_key() so the
    compiled salt never crosses the Python boundary. Falls back to OSS public
    salt if the Cython module is unavailable or not hardened.
    """
    if key_override is not None:
        return key_override
    import hashlib
    machine_id = _get_machine_id()
    try:
        username = _get_username()
    except (KeyError, OSError):
        username = b"unknown"

    # Try Cython hardened path first (salt stays inside .so, never exposed)
    if salt is None:
        try:
            from pop_pay.engine import _vault_core
            key = _vault_core.derive_key(machine_id, username)
            if key is not None:
                return key
        except (ImportError, AttributeError, OSError):
            pass
        salt = _OSS_SALT

    password = machine_id + b":" + username
    # n=2**14 (16MB) — well within OpenSSL default maxmem (32MB).
    return hashlib.scrypt(password, salt=salt, n=2**14, r=8, p=1, dklen=32)


def derive_key_from_passphrase(passphrase: str) -> bytes:
    """Derive AES-256 key from passphrase + machine_id salt (PBKDF2-HMAC-SHA256).

    Stronger than machine-derived key: passphrase is the secret.
    An agent with shell access cannot brute-force a strong passphrase.
    """
    machine_id = _get_machine_id()
    # Use machine_id as salt so same passphrase on different machines = different key
    return _hashlib.pbkdf2_hmac(
        'sha256',
        passphrase.encode('utf-8'),
        machine_id,
        iterations=600_000,
        dklen=32,
    )


def store_key_in_keyring(key: bytes):
    """Store derived key in OS keyring (macOS Keychain / Linux libsecret / Windows Credential Manager)."""
    try:
        import keyring
    except ImportError:
        raise ImportError(
            "keyring package required for passphrase mode. "
            "Install with: pip install 'pop-pay[passphrase]'"
        )
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key.hex())
    except (RuntimeError, OSError) as e:
        raise VaultLocked(
            "Failed to store derived key in OS keyring.",
            cause=e,
        )


def load_key_from_keyring() -> bytes | None:
    """Load derived key from OS keyring. Returns None if not found or keyring unavailable."""
    try:
        import keyring
        hex_key = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if hex_key:
            return bytes.fromhex(hex_key)
    except (ImportError, ValueError, RuntimeError):
        pass
    return None


def clear_keyring():
    """Remove derived key from OS keyring (called on vault update or explicit lock)."""
    try:
        import keyring
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except keyring.errors.PasswordDeleteError:
            # RT-2 Fix 7: entry already absent — idempotent no-op, matches filesystem wipe semantics
            pass
    except (ImportError, RuntimeError):
        pass


def encrypt_credentials(creds: dict, salt: bytes = None, key_override: bytes = None) -> bytes:
    """Encrypt credentials dict to F13 v1 vault blob.

    Layout: MAGIC(2)=0x5050 || VERSION(1)=0x01 || RESERVED(1)=0x00 ||
            nonce(12) || ciphertext || GCM-tag(16). The 4-byte header is
    bound into AEAD AAD so tampering fails tag verification.
    """
    if AESGCM is None:
        raise ImportError("cryptography package required: pip install 'pop-pay[vault]'")
    import os as _os
    key = _derive_key(salt, key_override=key_override)
    nonce = _os.urandom(12)  # 96-bit random nonce
    aesgcm = AESGCM(key)
    plaintext = json.dumps(creds).encode()
    ciphertext = aesgcm.encrypt(nonce, plaintext, _VAULT_HEADER_V1)  # F13 AAD
    return _VAULT_HEADER_V1 + nonce + ciphertext


def _decrypt_body(
    body: bytes,
    salt: bytes | None,
    key_override: bytes | None,
    aad: bytes | None,
) -> dict:
    key = _derive_key(salt, key_override=key_override)
    nonce, ciphertext = body[:12], body[12:]
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
    except Exception as e:
        raise VaultDecryptFailed(
            "Failed to decrypt vault — wrong key (machine changed?) or corrupted vault.",
            cause=e,
        )
    return json.loads(plaintext)


def decrypt_credentials(blob: bytes, salt: bytes = None, key_override: bytes = None) -> dict:
    """Decrypt vault blob to credentials dict.

    F13 dispatch: if the blob starts with MAGIC(0x5050), read VERSION +
    RESERVED, bind the 4-byte header as AEAD AAD, decrypt the remaining
    body. Legacy v0 blobs (no magic) fall back to the header-less path and
    emit a one-time migration notice.
    """
    if AESGCM is None:
        raise ImportError("cryptography package required: pip install 'pop-pay[vault]'")

    has_magic = len(blob) >= 2 and blob[0] == 0x50 and blob[1] == 0x50
    if has_magic and len(blob) >= _VAULT_HEADER_LEN + 28:  # 4 header + 12 nonce + 16 tag
        version = blob[2]
        if version != _VAULT_VERSION_V1:
            raise VaultDecryptFailed(
                f"vault format v{version} not supported — upgrade pop-pay"
            )
        header = blob[:_VAULT_HEADER_LEN]
        body = blob[_VAULT_HEADER_LEN:]
        try:
            return _decrypt_body(body, salt, key_override, header)
        except VaultDecryptFailed:
            # v1 AEAD verify failed — may be a legacy v0 blob whose random
            # nonce collided with 0x5050 magic (1/65536). Fall through to v0
            # path; AAD security preserved since v0 never had AAD to begin with.
            pass

    # Legacy v0 path (also collided-magic fallback). No AAD.
    if len(blob) < 28:
        raise VaultDecryptFailed("vault.enc is corrupted or too small")
    if not has_magic:
        _notify_legacy_v0_once()
    return _decrypt_body(blob, salt, key_override, None)


def vault_exists() -> bool:
    return VAULT_PATH.exists()


# Vault mode marker schema (F4/F7, S0.7).
# Values written to ~/.config/pop-pay/.vault_mode:
#   - passphrase        — key derived from user passphrase (PBKDF2), kept in OS keyring
#   - machine-hardened  — machine-derived key using CI-injected compiled salt
#   - machine-oss       — machine-derived key using public OSS salt
#   - unknown           — marker file missing
# Legacy values ("hardened", "oss") are migrated on read; next save_vault
# rewrites the file in the new schema.
VAULT_MODES = ("passphrase", "machine-hardened", "machine-oss", "unknown")


def _write_vault_mode(is_passphrase: bool = False):
    """Write .vault_mode marker. Schema: passphrase / machine-hardened / machine-oss."""
    if is_passphrase:
        mode = "passphrase"
    else:
        try:
            from pop_pay.engine import _vault_core
            mode = "machine-hardened" if _vault_core.is_hardened() else "machine-oss"
        except (ImportError, AttributeError):
            mode = "machine-oss"
    marker = VAULT_DIR / ".vault_mode"
    marker.write_text(mode)
    marker.chmod(0o600)


def _read_vault_mode() -> str:
    """Return current vault mode string; migrates legacy 'hardened'/'oss' values."""
    marker = VAULT_DIR / ".vault_mode"
    if not marker.exists():
        return "unknown"
    raw = marker.read_text().strip()
    # Migrate pre-S0.7 legacy values
    if raw == "hardened":
        return "machine-hardened"
    if raw == "oss":
        return "machine-oss"
    if raw in VAULT_MODES:
        return raw
    return "unknown"


def load_vault() -> dict:
    """Load and decrypt vault. Tries passphrase key from keyring first, then machine key.

    Downgrade attack protection: if .vault_mode marker says 'hardened' but the
    Cython hardened build is not available, refuses to attempt OSS salt decryption.
    This prevents an attacker from deleting the .so to force re-initialization
    with the weaker public salt.
    """
    if not VAULT_PATH.exists():
        raise VaultNotFound()

    # Downgrade check: vault marker says hardened but .so is gone
    vault_mode = _read_vault_mode()
    if vault_mode == "machine-hardened":
        try:
            from pop_pay.engine import _vault_core
            if not _vault_core.is_hardened():
                raise RuntimeError(
                    "Vault was created with a hardened PyPI build, but the "
                    "Cython extension is missing or not hardened.\n"
                    "Reinstall via PyPI: pip install pop-pay\n"
                    "If you intentionally switched to OSS, delete ~/.config/pop-pay/vault.enc "
                    "and run pop-init-vault again."
                )
        except ImportError:
            raise RuntimeError(
                "Vault requires hardened build but _vault_core module not found. "
                "Reinstall via PyPI: pip install pop-pay"
            )

    # F3: OSS salt consent gate. machine-oss vaults use a public salt that an
    # agent with shell execution could derive. Require explicit opt-in via
    # POP_ACCEPT_OSS_SALT=1. Passphrase / machine-hardened / unknown bypass.
    if vault_mode == "machine-oss" and os.environ.get("POP_ACCEPT_OSS_SALT") != "1":
        _warning = (
            "pop-pay: vault is encrypted with the OSS public salt. "
            "An agent with shell execution could derive the key from public information."
        )
        sys.stdout.write("\u26a0\ufe0f  " + _warning + "\n")
        sys.stderr.write("\u26a0\ufe0f  " + _warning + "\n")
        raise ValueError(
            "OSS-salt vault load refused: set POP_ACCEPT_OSS_SALT=1 to acknowledge, "
            "or re-init via `pop-pay init-vault --passphrase` for stronger protection."
        )

    blob = VAULT_PATH.read_bytes()
    # Try passphrase-derived key from keyring first (strongest protection)
    passphrase_key = load_key_from_keyring()
    if passphrase_key is not None:
        try:
            return decrypt_credentials(blob, key_override=passphrase_key)
        except VaultDecryptFailed:
            pass  # Wrong key — fall through to machine-derived key
    return decrypt_credentials(blob)


def cleanup_stale_temp_files() -> None:
    """F8: enumerate stale vault.enc*.tmp siblings and securely overwrite + unlink.

    A previous crashed save can leave a `.tmp` sibling that may still hold
    ciphertext bytes; we treat them as sensitive. Best-effort.
    """
    if not VAULT_DIR.exists():
        return
    try:
        entries = list(VAULT_DIR.iterdir())
    except OSError:
        return
    for p in entries:
        name = p.name
        if not (name.startswith("vault.enc") and name.endswith(".tmp")):
            continue
        try:
            size = p.stat().st_size
            if size > 0:
                with p.open("r+b") as f:
                    f.write(b"\x00" * size)
                    f.flush()
                    os.fsync(f.fileno())
            p.unlink()
        except OSError:
            pass


def wipe_vault_artifacts() -> list:
    """F8: enumerate every credential-bearing artifact under VAULT_DIR and
    securely overwrite + unlink. Also clears the OS keyring. Returns the
    list of paths that were wiped."""
    wiped = []
    if VAULT_DIR.exists():
        try:
            entries = list(VAULT_DIR.iterdir())
        except OSError:
            entries = []
        sensitive_names = {".vault_mode", ".machine_id"}
        for p in entries:
            name = p.name
            is_vault_blob = name == "vault.enc" or (name.startswith("vault.enc") and name.endswith(".tmp"))
            if not (is_vault_blob or name in sensitive_names):
                continue
            try:
                size = p.stat().st_size
                if size > 0:
                    with p.open("r+b") as f:
                        f.write(b"\x00" * size)
                        f.flush()
                        os.fsync(f.fileno())
                p.unlink()
                wiped.append(str(p))
            except OSError:
                pass
    clear_keyring()
    return wiped


def save_vault(creds: dict, key_override: bytes = None):
    """Encrypt and atomically write credentials to vault.enc."""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_stale_temp_files()  # F8: sweep prior crashed writes
    blob = encrypt_credentials(creds, key_override=key_override)
    # Atomic write: tmp → fsync → rename
    tmp_path = VAULT_PATH.with_suffix(".enc.tmp")
    tmp_path.write_bytes(blob)
    tmp_path.chmod(0o600)
    with tmp_path.open("rb") as _f:
        os.fsync(_f.fileno())
    tmp_path.rename(VAULT_PATH)
    VAULT_PATH.chmod(0o600)
    VAULT_DIR.chmod(0o700)
    # Verify the vault is readable before wiping anything
    try:
        if key_override is not None:
            decrypt_credentials(VAULT_PATH.read_bytes(), key_override=key_override)
        else:
            decrypt_credentials(VAULT_PATH.read_bytes())
    except VaultDecryptFailed as e:
        raise RuntimeError(f"Vault write verification failed: {e}")
    # Write mode marker — F4/F7: passphrase / machine-hardened / machine-oss
    _write_vault_mode(is_passphrase=key_override is not None)


def secure_wipe_env(env_path: Path):
    """Overwrite .env with zeros then delete. Note: SSD wear-leveling may retain data."""
    if not env_path.exists():
        return
    size = env_path.stat().st_size
    with open(env_path, "r+b") as f:
        f.write(b"\x00" * size)
        f.flush()
        os.fsync(f.fileno())
    env_path.unlink()


# S0.7 F1: env keys that carry plaintext PAN/CVV/expiry. Vault plaintext never
# enters os.environ in the first place; redaction here is defense in depth for
# child processes spawned by pop-pay.
SENSITIVE_ENV_KEYS = (
    "POP_BYOC_NUMBER",
    "POP_BYOC_CVV",
    "POP_BYOC_EXP_MONTH",
    "POP_BYOC_EXP_YEAR",
)


def filtered_env(base: dict | None = None) -> dict:
    """Return a copy of *base* (default os.environ) with SENSITIVE_ENV_KEYS stripped."""
    src = os.environ if base is None else base
    return {k: v for k, v in src.items() if k not in SENSITIVE_ENV_KEYS}
