"""pop-pay init-vault CLI command."""
import argparse
import getpass
import sys
from pathlib import Path
from pop_pay.vault import save_vault, vault_exists, secure_wipe_env, VAULT_DIR, VAULT_PATH, OSS_WARNING


def cmd_init_vault():
    """Interactive setup: encrypt card credentials and burn .env."""
    parser = argparse.ArgumentParser(description="Initialize pop-pay credential vault")
    parser.add_argument("--passphrase", action="store_true",
                        help="Protect vault with a passphrase (stronger; requires pop-unlock each session)")
    args = parser.parse_args()

    print("pop-pay vault setup")
    print("=" * 40)
    print("Your card credentials will be encrypted and stored at:")
    print(f"  {VAULT_PATH}")
    print("The original .env will be securely wiped after encryption.")
    print()
    print(OSS_WARNING)

    if vault_exists():
        overwrite = input("A vault already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            print("Aborted.")
            sys.exit(0)

    key_override = None
    if args.passphrase:
        from pop_pay.vault import derive_key_from_passphrase, store_key_in_keyring
        print("\nPassphrase mode: your vault will be encrypted with a passphrase.")
        print("You must run `pop-unlock` before each MCP server session.\n")
        while True:
            p1 = getpass.getpass("  Choose passphrase: ")
            p2 = getpass.getpass("  Confirm passphrase: ")
            if p1 != p2:
                print("  Passphrases do not match. Try again.")
                continue
            if len(p1) < 8:
                print("  Passphrase must be at least 8 characters.")
                continue
            key_override = derive_key_from_passphrase(p1)
            store_key_in_keyring(key_override)
            print("  Passphrase set. Vault unlocked for this session.")
            break

    print("Enter your card credentials (input is hidden):")
    card_number = getpass.getpass("  Card number: ").strip().replace(" ", "").replace("-", "")
    exp_month = getpass.getpass("  Expiry month (MM): ").strip()
    exp_year = getpass.getpass("  Expiry year (YY): ").strip()
    cvv = getpass.getpass("  CVV: ").strip()

    creds = {
        "card_number": card_number,
        "cvv": cvv,
        "exp_month": exp_month,
        "exp_year": exp_year,
        "expiration_date": f"{exp_month}/{exp_year}",
    }

    print("\nEncrypting and writing vault...")
    try:
        save_vault(creds, key_override=key_override)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Vault written to {VAULT_PATH}")

    # Offer to wipe .env
    env_candidates = [
        Path.home() / ".config" / "pop-pay" / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in env_candidates:
        if env_path.exists():
            wipe = input(f"\nSecurely wipe {env_path}? [y/N]: ").strip().lower()
            if wipe == "y":
                secure_wipe_env(env_path)
                print(f"{env_path} wiped.")

    if args.passphrase:
        print("\nSetup complete. This session is already unlocked.")
        print("Run `pop-unlock` before each new MCP server session.")
    else:
        print("\nSetup complete. The MCP server will auto-decrypt the vault at startup.")
