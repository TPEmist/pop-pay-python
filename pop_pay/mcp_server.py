import os
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Prevent credentials from appearing in core dumps
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except Exception:
    pass  # Windows or restricted env — best effort

# Load .env from the dedicated config dir first (preferred, keeps credentials out of the
# project working directory and away from agent file-read tools).
# Falls back to the standard dotenv cwd-search if no config file exists yet.
_config_env = Path.home() / ".config" / "pop-pay" / ".env"
if _config_env.exists():
    load_dotenv(_config_env)
else:
    load_dotenv()

# ---------------------------------------------------------------------------
# Vault: load encrypted credentials if vault.enc exists
# ---------------------------------------------------------------------------
_vault_creds: dict = {}
try:
    from pop_pay.vault import vault_exists, load_vault, OSS_WARNING
    if vault_exists():
        from pop_pay.vault import load_key_from_keyring
        import sys as _sys
        if load_key_from_keyring() is None:
            _sys.stderr.write(OSS_WARNING)
        _vault_creds = load_vault()
except ImportError:
    pass  # cryptography not installed, vault not available
except (ValueError, RuntimeError) as _ve:
    import sys as _sys
    _sys.stderr.write(f"\n⚠️  pop-pay vault error: {_ve}\n")

# Vault credentials override env vars for BYOC
if _vault_creds:
    os.environ.setdefault("POP_BYOC_NUMBER", _vault_creds.get("card_number", ""))
    os.environ.setdefault("POP_BYOC_CVV", _vault_creds.get("cvv", ""))
    os.environ.setdefault("POP_BYOC_EXP_MONTH", _vault_creds.get("exp_month", ""))
    os.environ.setdefault("POP_BYOC_EXP_YEAR", _vault_creds.get("exp_year", ""))

from pop_pay.core.models import PaymentIntent, GuardrailPolicy
from pop_pay.providers.stripe_mock import MockStripeProvider
from pop_pay.providers.byoc_local import LocalVaultProvider
from pop_pay.client import PopClient

mcp = FastMCP("pop-pay")

# ---------------------------------------------------------------------------
# Load configuration from environment
# ---------------------------------------------------------------------------
allowed_categories = json.loads(os.getenv("POP_ALLOWED_CATEGORIES", '["aws", "cloudflare"]'))
max_per_tx   = float(os.getenv("POP_MAX_PER_TX", "100.0"))
max_daily    = float(os.getenv("POP_MAX_DAILY", "500.0"))
block_loops  = os.getenv("POP_BLOCK_LOOPS", "true").lower() == "true"
stripe_key   = os.getenv("POP_STRIPE_KEY")
cdp_url      = os.getenv("POP_CDP_URL", "http://localhost:9222")
auto_inject  = os.getenv("POP_AUTO_INJECT", "false").lower() == "true"
engine_type  = os.getenv("POP_GUARDRAIL_ENGINE", "keyword").lower()
llm_api_key  = os.getenv("POP_LLM_API_KEY", "")
llm_base_url = os.getenv("POP_LLM_BASE_URL", None)
llm_model    = os.getenv("POP_LLM_MODEL", "gpt-4o-mini")

policy = GuardrailPolicy(
    allowed_categories=allowed_categories,
    max_amount_per_tx=max_per_tx,
    max_daily_budget=max_daily,
    block_hallucination_loops=block_loops
)

if stripe_key:
    from pop_pay.providers.stripe_real import StripeIssuingProvider
    provider = StripeIssuingProvider(api_key=stripe_key)
elif os.getenv("POP_BYOC_NUMBER"):
    provider = LocalVaultProvider()
else:
    provider = MockStripeProvider()

engine = None
if engine_type == "llm":
    from pop_pay.engine.llm_guardrails import LLMGuardrailEngine, HybridGuardrailEngine
    engine = HybridGuardrailEngine(LLMGuardrailEngine(
        api_key=llm_api_key,
        base_url=llm_base_url,
        model=llm_model,
        use_json_mode=True
    ))

client = PopClient(provider, policy, engine=engine)

# ---------------------------------------------------------------------------
# Optional: browser injector (only loaded when POP_AUTO_INJECT=true)
# ---------------------------------------------------------------------------
injector = None
if auto_inject:
    try:
        from pop_pay.injector import PopBrowserInjector
        injector = PopBrowserInjector(client.state_tracker)
    except ImportError:
        pass  # playwright not installed — injector disabled silently


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------
@mcp.tool()
async def request_virtual_card(
    requested_amount: float,
    target_vendor: str,
    reasoning: str,
    page_url: str = "",
) -> str:
    """Request a one-time virtual credit card for an automated purchase.

    This tool reads card credentials and billing info from the user's pre-configured
    secure vault and local config. You do NOT need to ask the user for any card number,
    CVV, name, email, phone, or address — just call this tool when card fields are visible.

    IMPORTANT USAGE RULES:
    - ONLY call this tool when you are currently on the checkout/payment page
      and can visually see credit card input fields in the browser.
    - If you are on a billing/contact info page (name, email, phone, address) but
      card fields are NOT visible yet, use request_purchaser_info instead.
    - DO NOT call this if you have not yet navigated to the checkout form.
    - DO NOT retry with a different reasoning if this tool returns a rejection.
    - Card credentials and billing info are auto-injected into the form —
      you only need to click the submit/pay button after approval.
    - target_vendor: The human-readable vendor name (e.g. "AWS", "Wikipedia", "Maker Faire").
      Do NOT pass a URL or domain — pass the vendor's common name.
    - page_url: Pass the current checkout page URL (e.g. from browser_navigate result).
      Required when using Playwright MCP — Point One Percent uses this to sync the page
      into its CDP browser for injection.
    """
    intent = PaymentIntent(
        agent_id="mcp-agent",
        requested_amount=requested_amount,
        target_vendor=target_vendor,
        reasoning=reasoning,
        page_url=page_url or None,
    )
    seal = await client.process_payment(intent)

    if seal.status.lower() == "rejected":
        return f"Payment rejected by guardrails. Reason: {seal.rejection_reason}"

    last4 = seal.card_number[-4:] if seal.card_number else "????"
    masked_card = f"****-****-****-{last4}"

    # -------------------------------------------------------------------
    # Auto-injection path: if enabled, inject into the active browser tab
    # -------------------------------------------------------------------
    if injector is not None:
        injection_result = await injector.inject_payment_info(
            seal_id=seal.seal_id,
            cdp_url=cdp_url,
            page_url=page_url,
            card_number=seal.card_number or _vault_creds.get("card_number", ""),
            cvv=seal.cvv or _vault_creds.get("cvv", ""),
            expiration_date=seal.expiration_date or _vault_creds.get("expiration_date", ""),
            approved_vendor=intent.target_vendor,
        )

        # inject_payment_info now returns a dict; support both dict and legacy bool
        if isinstance(injection_result, dict):
            card_filled    = injection_result.get("card_filled", False)
            billing_filled = injection_result.get("billing_filled", False)
            blocked_reason = injection_result.get("blocked_reason", "")
        else:
            # backwards-compatible fallback if a custom injector returns a bool
            card_filled    = bool(injection_result)
            billing_filled = False
            blocked_reason = ""

        if not card_filled:
            # Undo the seal — cancel the budget reservation
            client.state_tracker.mark_used(seal.seal_id)
            if blocked_reason.startswith("domain_mismatch:"):
                actual = blocked_reason.split(":", 1)[1]
                return (
                    f"Payment blocked. Security: current page domain '{actual}' does not match "
                    f"approved vendor '{intent.target_vendor}'. "
                    f"Possible attack or navigation error — do not retry."
                )
            return (
                "Payment rejected. Error: Point One Percent could not find credit card input fields. "
                "Most likely cause: you navigated via Playwright MCP but Point One Percent is looking "
                "at a different browser instance. Fix: pass the current checkout URL as "
                "page_url — e.g. request_virtual_card(..., page_url='https://...'). "
                "Alternatively, ensure Playwright MCP is configured with "
                "--cdp-endpoint http://localhost:9222 so both MCPs share the same browser."
            )

        billing_note = (
            " Billing fields (name, address, email) were also filled automatically."
            if billing_filled
            else ""
        )
        return (
            f"Payment approved and securely auto-injected into the browser form."
            f"{billing_note} "
            f"Please proceed to click the submit/pay button. "
            f"Masked card: {masked_card}"
        )

    # -------------------------------------------------------------------
    # Standard path: return masked card details only
    # -------------------------------------------------------------------
    return (
        f"Payment approved. Card Issued: {masked_card}, "
        f"Expiry: {seal.expiration_date}, Amount: {seal.authorized_amount}"
    )


@mcp.tool()
async def request_purchaser_info(
    target_vendor: str,
    page_url: str = "",
    reasoning: str = "",
) -> str:
    """Auto-fill purchaser/billing info (name, email, phone, address) from the user's pre-configured profile.

    IMPORTANT: This tool reads the user's billing info from their local config and injects
    it directly into the browser form via CDP. You do NOT need to ask the user for their
    name, email, phone, or address — just call this tool and it handles everything automatically.

    WHEN TO USE:
    - You are on a purchaser/billing/contact info page with fields for name, email,
      phone, or address — but NO credit card input fields are visible yet.
    - Call this immediately without asking the user for any personal information.
    - After this completes, navigate to the payment page and call request_virtual_card
      when card fields are visible.

    target_vendor: The human-readable vendor or event name (e.g. "Maker Faire", "Wikipedia",
      "AWS"). Do NOT pass a URL or domain name — pass the vendor's common name as you
      would describe it to a human.

    DO NOT use if card input fields are already visible — use request_virtual_card instead
    (it fills both card credentials and billing info in one step).

    This tool does NOT issue a card, does NOT charge anything, and does NOT affect your budget.
    """
    if injector is None:
        return (
            "Billing info injection is not available. "
            "Ensure POP_AUTO_INJECT=true in ~/.config/pop-pay/.env and restart the MCP server."
        )

    # Lightweight vendor check: is this vendor in the allowed list?
    # Three-way match: exact | token-in-allowed | allowed-substring-of-vendor
    import re
    vendor_lower = target_vendor.lower()
    vendor_tokens = set(re.split(r'[\s\-_./]+', vendor_lower)) - {''}
    allowed_lower = [c.lower() for c in allowed_categories]
    # Also check page_url domain tokens against allowed categories
    # Handles the case where agent passes a domain as target_vendor (e.g. "bayarea.makerfaire.com")
    from urllib.parse import urlparse
    page_domain = urlparse(page_url).netloc.lower().removeprefix("www.") if page_url else ""
    page_domain_tokens = set(re.split(r'[\s\-_./]+', page_domain)) - {''}

    vendor_allowed = (
        vendor_lower in allowed_lower                          # exact: "aws" == "aws"
        or any(tok in allowed_lower for tok in vendor_tokens) # token: "aws" in ["aws",...]
        or any(                                                # token-subset: all words of "maker faire"
            set(re.split(r'[\s\-_./]+', cat)) - {''} <= vendor_tokens  # appear in vendor tokens
            for cat in allowed_lower
        )
        or any(                                                # fallback: match against page domain
            set(re.split(r'[\s\-_./]+', cat)) - {''} <= page_domain_tokens
            for cat in allowed_lower
        )
    )
    if not vendor_allowed:
        return (
            f"Vendor '{target_vendor}' is not in your allowed categories. "
            f"Billing info will not be filled for unapproved vendors. "
            f"Update POP_ALLOWED_CATEGORIES in ~/.config/pop-pay/.env to add it."
        )

    result = await injector.inject_billing_only(
        cdp_url=cdp_url,
        page_url=page_url,
        approved_vendor=target_vendor,
    )

    blocked_reason = result.get("blocked_reason", "")
    billing_filled = result.get("billing_filled", False)

    if blocked_reason.startswith("domain_mismatch:"):
        actual = blocked_reason.split(":", 1)[1]
        return (
            f"Blocked. Current page domain '{actual}' does not match "
            f"approved vendor '{target_vendor}'. "
            f"Possible navigation error — do not retry."
        )

    if not billing_filled:
        return (
            "Could not find billing fields on the current page. "
            "Make sure you are on the billing/contact info page before calling this tool. "
            "If using Playwright MCP, pass the current page URL as page_url."
        )

    return (
        f"Billing info filled successfully for '{target_vendor}'. "
        f"Name, address, email, and/or phone fields have been auto-populated. "
        f"Proceed to the payment page and call request_virtual_card when card fields are visible."
    )


if __name__ == "__main__":
    mcp.run()
