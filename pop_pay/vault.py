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
        except Exception:
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
        except Exception:
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
    except Exception:
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
    except Exception:
        username = b"unknown"

    # Try Cython hardened path first (salt stays inside .so, never exposed)
    if salt is None:
        try:
            from pop_pay.engine import _vault_core
            key = _vault_core.derive_key(machine_id, username)
            if key is not None:
                return key
        except Exception:
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
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key.hex())
    except ImportError:
        raise ImportError(
            "keyring package required for passphrase mode. "
            "Install with: pip install 'pop-pay[passphrase]'"
        )


def load_key_from_keyring() -> bytes | None:
    """Load derived key from OS keyring. Returns None if not found or keyring unavailable."""
    try:
        import keyring
        hex_key = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if hex_key:
            return bytes.fromhex(hex_key)
    except Exception:
        pass
    return None


def clear_keyring():
    """Remove derived key from OS keyring (called on vault update or explicit lock)."""
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        pass


def encrypt_credentials(creds: dict, salt: bytes = None, key_override: bytes = None) -> bytes:
    """Encrypt credentials dict to bytes (nonce + ciphertext + GCM tag)."""
    if AESGCM is None:
        raise ImportError("cryptography package required: pip install 'pop-pay[vault]'")
    import os as _os
    key = _derive_key(salt, key_override=key_override)
    nonce = _os.urandom(12)  # 96-bit random nonce
    aesgcm = AESGCM(key)
    plaintext = json.dumps(creds).encode()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext  # nonce prepended; GCM tag is appended by library


def decrypt_credentials(blob: bytes, salt: bytes = None, key_override: bytes = None) -> dict:
    """Decrypt vault blob to credentials dict. Raises ValueError on wrong key/corruption."""
    if AESGCM is None:
        raise ImportError("cryptography package required: pip install 'pop-pay[vault]'")
    if len(blob) < 28:  # 12 nonce + at least 16 GCM tag
        raise ValueError("vault.enc is corrupted or too small")
    key = _derive_key(salt, key_override=key_override)
    nonce, ciphertext = blob[:12], blob[12:]
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception:
        raise ValueError(
            "Failed to decrypt vault — wrong key (machine changed?) or corrupted vault.\n"
            "Re-run: pop-pay init-vault"
        )
    return json.loads(plaintext)


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
        except Exception:
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

    blob = VAULT_PATH.read_bytes()
    # Try passphrase-derived key from keyring first (strongest protection)
    passphrase_key = load_key_from_keyring()
    if passphrase_key is not None:
        try:
            return decrypt_credentials(blob, key_override=passphrase_key)
        except ValueError:
            pass  # Wrong key — fall through to machine-derived key
    return decrypt_credentials(blob)


def save_vault(creds: dict, key_override: bytes = None):
    """Encrypt and atomically write credentials to vault.enc."""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
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
    except ValueError as e:
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
