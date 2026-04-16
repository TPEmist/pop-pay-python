"""pop-pay init-vault CLI command."""
import argparse
import getpass
import sys
from pathlib import Path
from pop_pay.vault import (
    save_vault, vault_exists, secure_wipe_env,
    VAULT_DIR, VAULT_PATH, OSS_WARNING,
    _read_vault_mode, wipe_vault_artifacts,
)
from pop_pay.core.secret_str import SecretStr
from pop_pay.errors import (
    handle_cli_error,
    VaultDecryptFailed,
)
from pop_pay.errors import (
    handle_cli_error,
    VaultDecryptFailed,
)


def cmd_init_vault():
    """Entry point wrapper: delegates to _cmd_init_vault and formats typed errors."""
    try:
        _cmd_init_vault()
    except Exception as e:
        handle_cli_error(e)


def _cmd_init_vault():
    """Interactive setup: encrypt card credentials and burn .env."""
    parser = argparse.ArgumentParser(description="Initialize pop-pay credential vault")
    parser.add_argument("--passphrase", action="store_true",
                        help="Protect vault with a passphrase (stronger; requires pop-unlock each session)")
    parser.add_argument("--wipe", action="store_true",
                        help="F8: securely wipe all vault artifacts (vault.enc, .vault_mode, .machine_id, stale .tmp) and clear keyring, then exit.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompts (used with --wipe).")
    args = parser.parse_args()

    if args.wipe:
        if not args.yes and sys.stdin.isatty():
            ack = input(
                "Wipe ALL pop-pay vault artifacts (vault.enc, .vault_mode, keyring, stale .tmp)? [y/N]: "
            ).strip().lower()
            if ack != "y":
                print("Aborted.")
                sys.exit(0)
        wiped = wipe_vault_artifacts()
        if not wiped:
            print("No vault artifacts found.")
        else:
            for p in wiped:
                print(f"wiped: {p}")
        print("Keyring entry cleared.")
        sys.exit(0)

    print("pop-pay vault setup")
    print("=" * 40)
    print("Your card credentials will be encrypted and stored at:")
    print(f"  {VAULT_PATH}")
    print()
    print(OSS_WARNING)

    if vault_exists():
        # Downgrade guard: refuse to overwrite a hardened vault from an OSS build
        vault_mode = _read_vault_mode()
        if vault_mode == "machine-hardened":
            try:
                from pop_pay.engine import _vault_core
                is_hardened = _vault_core.is_hardened()
            except ImportError:
                is_hardened = False
            if not is_hardened:
                raise VaultDecryptFailed(
                    "Existing vault was created with a hardened PyPI build, "
                    "but the Cython extension is missing or not hardened. "
                    "Re-initializing now would DOWNGRADE encryption to the public OSS salt.",
                    remediation=(
                        "Reinstall via PyPI (pip install pop-pay) and re-run pop-init-vault; "
                        "or, if intentionally switching to OSS, delete "
                        f"{VAULT_PATH} and {VAULT_DIR / '.vault_mode'} first."
                    ),
                )

        overwrite = input("A vault already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            print("Aborted.")
            sys.exit(0)

    # F3: OSS salt consent gate at init time. Non-passphrase init on a
    # non-hardened build requires explicit consent — POP_ACCEPT_OSS_SALT=1
    # or interactive y/N when stdin is a TTY.
    if not args.passphrase:
        try:
            from pop_pay.engine import _vault_core
            _is_hardened = _vault_core.is_hardened()
        except (ImportError, AttributeError):
            _is_hardened = False
        if not _is_hardened:
            import os as _os
            if _os.environ.get("POP_ACCEPT_OSS_SALT") == "1":
                pass
            elif sys.stdin.isatty():
                ack = input(
                    "Proceed with OSS public salt? This offers weaker protection than --passphrase. [y/N]: "
                ).strip().lower()
                if ack != "y":
                    print("Aborted. Re-run with --passphrase, or set POP_ACCEPT_OSS_SALT=1.")
                    sys.exit(1)
            else:
                sys.stderr.write(
                    "pop-init-vault: OSS public salt requires consent. "
                    "Set POP_ACCEPT_OSS_SALT=1 or pass --passphrase.\n"
                )
                sys.exit(1)

    key_override = None
    if args.passphrase:
        from pop_pay.vault import derive_key_from_passphrase, store_key_in_keyring
        print("\nPassphrase mode: your vault will be encrypted with a passphrase.")
        print("You must run `pop-unlock` before each MCP server session.\n")
        while True:
            # RT-2 R2 Fix 3.5 (Q5) — passphrase wrapped in SecretStr; equality
            # compare uses dataclass __eq__ (by-value). len() is not available
            # on SecretStr — use .reveal() for the length gate only.
            p1 = SecretStr(getpass.getpass("  Choose passphrase: "))
            p2 = SecretStr(getpass.getpass("  Confirm passphrase: "))
            if p1 != p2:
                print("  Passphrases do not match. Try again.")
                continue
            if len(p1.reveal()) < 8:
                print("  Passphrase must be at least 8 characters.")
                continue
            key_override = derive_key_from_passphrase(p1.reveal())
            store_key_in_keyring(key_override)
            print("  Passphrase set. Vault unlocked for this session.")
            break

    print("Enter your card credentials (input is hidden):")
    # RT-2 R2 Fix 3.5 — wrap PAN/CVV in SecretStr immediately after capture so
    # any traceback with show_locals (rich.traceback, sys.excepthook) renders
    # `***REDACTED***` for these frame locals. .reveal() is required at vault
    # encryption time (json.dumps cannot serialize SecretStr by design) — that
    # single call site is the audit footprint for unsealing.
    card_number = SecretStr(
        getpass.getpass("  Card number: ").strip().replace(" ", "").replace("-", "")
    )
    exp_month = getpass.getpass("  Expiry month (MM): ").strip()
    exp_year = getpass.getpass("  Expiry year (YY): ").strip()
    cvv = SecretStr(getpass.getpass("  CVV: ").strip())

    creds = {
        "card_number": card_number.reveal(),
        "cvv": cvv.reveal(),
        "exp_month": exp_month,
        "exp_year": exp_year,
        "expiration_date": f"{exp_month}/{exp_year}",
    }

    print("\nEncrypting and writing vault...")
    save_vault(creds, key_override=key_override)
    print(f"Vault written to {VAULT_PATH}")

    # Handle policy .env
    policy_env_path = VAULT_DIR / ".env"
    env_candidates = [policy_env_path, Path.cwd() / ".env"]

    # Offer to wipe any .env that contains old-format card credentials
    wiped_policy_env = False
    for env_path in env_candidates:
        if env_path.exists():
            content = env_path.read_text()
            if any(k in content for k in ("POP_BYOC_NUMBER", "POP_BYOC_CVV")):
                wipe = input(f"\n\033[1;31m{env_path} contains card credentials. Securely wipe it?\033[0m [y/N]: ").strip().lower()
                if wipe == "y":
                    secure_wipe_env(env_path)
                    print(f"{env_path} wiped.")
                    if env_path == policy_env_path:
                        wiped_policy_env = True

    # If no policy .env exists (or was just wiped), offer to create a template
    if not policy_env_path.exists() or wiped_policy_env:
        print(f"\nNo policy config found at {policy_env_path}.")
        create = input("Create a policy template .env? [y/N]: ").strip().lower()
        if create == "y":
            VAULT_DIR.mkdir(parents=True, exist_ok=True)
            policy_env_path.write_text(
                "# pop-pay policy configuration\n"
                "# Card credentials are stored in vault.enc — do not add them here.\n\n"
                "# Vendors the agent is allowed to pay (JSON array)\n"
                'POP_ALLOWED_CATEGORIES=\'["aws", "cloudflare", "openai", "github", "Wikipedia", "donation", "Wikimedia"]\'\n\n'
                "# Spending limits\n"
                "POP_MAX_PER_TX=100.0\n"
                "POP_MAX_DAILY=500.0\n"
                "POP_BLOCK_LOOPS=true\n\n"
                "# CDP injection (required for BYOC card filling)\n"
                "POP_AUTO_INJECT=true\n"
                "POP_CDP_URL=http://localhost:9222\n\n"
                "# Guardrail engine: keyword (default, zero-cost) or llm\n"
                "# POP_GUARDRAIL_ENGINE=keyword\n\n"
                "# Billing info for auto-filling name/address fields on checkout pages\n"
                "# POP_BILLING_FIRST_NAME=Bob\n"
                "# POP_BILLING_LAST_NAME=Smith\n"
                "# POP_BILLING_EMAIL=bob@example.com\n"
                "# POP_BILLING_PHONE_COUNTRY_CODE=+1\n"
                "# POP_BILLING_PHONE=+14155551234\n"
                '# POP_BILLING_STREET="123 Main St"\n'
                '# POP_BILLING_CITY="Redwood City"\n'
                "# POP_BILLING_ZIP=94043\n"
                "# POP_BILLING_STATE=CA\n"
                "# POP_BILLING_COUNTRY=US\n"
            )
            policy_env_path.chmod(0o600)
            print(f"Template created at {policy_env_path} — edit to set your policy.")

    if args.passphrase:
        print("\nSetup complete. This session is already unlocked.")
        print("Run `pop-unlock` before each new MCP server session.")
    else:
        print("\nSetup complete. The MCP server will auto-decrypt the vault at startup.")
