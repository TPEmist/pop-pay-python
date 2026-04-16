"""pop-unlock CLI — derive vault key from passphrase and store in OS keyring.

Run this BEFORE starting the MCP server when using passphrase mode:
    pop-unlock

The MCP server will find the key in the OS keyring and auto-decrypt the vault
without prompting (autonomous operation for the rest of the session).

To lock the vault (remove key from keyring):
    pop-unlock --lock
"""
import sys


def cmd_unlock():
    import argparse
    parser = argparse.ArgumentParser(description="Unlock pop-pay vault for this session")
    parser.add_argument("--lock", action="store_true", help="Remove key from keyring (lock vault)")
    args = parser.parse_args()

    try:
        from pop_pay.vault import (
            clear_keyring, derive_key_from_passphrase,
            store_key_in_keyring, vault_exists, decrypt_credentials,
            VAULT_PATH
        )
    except ImportError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if args.lock:
        clear_keyring()
        print("Vault locked — key removed from keyring.")
        print("Restart the MCP server to apply.")
        return

    if not vault_exists():
        print("No vault found. Run `pop-init-vault` first.")
        sys.exit(1)

    import getpass
    from pop_pay.core.secret_str import SecretStr
    # RT-2 R2 Fix 3.5 (Q5) — wrap passphrase in SecretStr so show_locals
    # tracebacks do not leak it. .reveal() only at the PBKDF2 call boundary.
    passphrase = SecretStr(getpass.getpass("Vault passphrase: "))
    if not passphrase:
        print("Passphrase cannot be empty.")
        sys.exit(1)

    # Verify the passphrase works before storing
    key = derive_key_from_passphrase(passphrase.reveal())
    try:
        blob = VAULT_PATH.read_bytes()
        decrypt_credentials(blob, key_override=key)
    except ValueError:
        print("Wrong passphrase — vault not unlocked.")
        sys.exit(1)

    store_key_in_keyring(key)
    print("Vault unlocked for this session.")
    print("Start (or restart) the MCP server — it will auto-decrypt using the stored key.")
    print("Run `pop-unlock --lock` to re-lock when done.")
