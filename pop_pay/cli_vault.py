"""pop-pay init-vault CLI command."""
import getpass
import sys
from pathlib import Path
from pop_pay.vault import save_vault, vault_exists, secure_wipe_env, VAULT_DIR, VAULT_PATH, OSS_WARNING


def cmd_init_vault():
    """Interactive setup: encrypt card credentials and burn .env."""
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
        save_vault(creds)
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

    print("\nSetup complete. The MCP server will auto-decrypt the vault at startup.")
