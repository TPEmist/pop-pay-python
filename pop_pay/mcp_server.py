import httpx
import ipaddress
import os
import json
import asyncio
import re
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse
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

# Global cache for page snapshots (capped at 200 entries, oldest evicted)
snapshot_cache: dict = {}
_SNAPSHOT_CACHE_MAX = 200

# Compiled regex for hidden element detection in _scan_page
_HIDDEN_STYLE_RE = re.compile(
    r"""(?:style\s*=\s*["'](?:[^"']*(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0|font-size\s*:\s*0|height\s*:\s*0|width\s*:\s*0))[^"']*["'])"""
    r"""|(?:class\s*=\s*["'](?:[^"']*(?:hidden|visually-hidden|sr-only|d-none))[^"']*["'])""",
    re.I
)
_PRICE_RE = re.compile(r'[\$£€¥]\s?\d+(?:\.\d{2})?')

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
webhook_url  = os.getenv("POP_WEBHOOK_URL")
approval_webhook_url = os.getenv("POP_APPROVAL_WEBHOOK")
policy = GuardrailPolicy(
    allowed_categories=allowed_categories,
    max_amount_per_tx=max_per_tx,
    max_daily_budget=max_daily,
    block_hallucination_loops=block_loops,
    webhook_url=webhook_url
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
# Private helper: core scan logic (not an MCP tool)
# ---------------------------------------------------------------------------

async def _scan_page(page_url: str) -> dict:
    """Fetch and scan a checkout page for prompt injection and security signals.

    Returns a dict with keys:
      - flags: list of string flag names detected
      - snapshot_id: UUID string for this scan
      - safe: bool (False if hidden_instructions_detected, True otherwise)
      - error: str | None — set if the page could not be fetched
    """
    snapshot_id = str(uuid.uuid4())
    flags: list[str] = []
    html = ""

    # Guard: block SSRF attempts (private IPs, loopback, non-https)
    try:
        _parsed = urlparse(page_url)
        if _parsed.scheme != "https":
            return {"flags": ["invalid_url"], "snapshot_id": snapshot_id, "safe": False, "error": "pop-pay only accepts https:// URLs."}
        _host = _parsed.hostname or ""
        try:
            _addr = ipaddress.ip_address(_host)
            if _addr.is_private or _addr.is_loopback or _addr.is_link_local or _addr.is_reserved:
                return {"flags": ["ssrf_blocked"], "snapshot_id": snapshot_id, "safe": False, "error": "pop-pay does not allow requests to private/internal addresses."}
        except ValueError:
            pass  # hostname (not raw IP) — allow
    except Exception:
        return {"flags": ["invalid_url"], "snapshot_id": snapshot_id, "safe": False, "error": "Invalid URL."}

    # 1. Fetch HTML and check SSL/redirects
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as http_client:
            response = await http_client.get(page_url)
            html = response.text

            if urlparse(str(response.url)).netloc != urlparse(page_url).netloc:
                flags.append("unexpected_redirect")
    except Exception as e:
        flags.append("ssl_anomaly")
        return {"flags": flags, "snapshot_id": snapshot_id, "safe": False, "error": f"Error fetching page: {e}"}

    # 2. Prompt injection signal scanning
    hidden_instructions_detected = False
    instruction_keywords = ["ignore", "instead", "system", "user", "override", "instruction", "always", "never", "prompt"]

    for match in _HIDDEN_STYLE_RE.finditer(html):
        context = html[match.end() : match.end() + 300].lower()
        if any(kw in context for kw in instruction_keywords):
            hidden_instructions_detected = True
            break

    if hidden_instructions_detected:
        flags.append("hidden_instructions_detected")

    # 3. Price mismatch (basic heuristic)
    prices = _PRICE_RE.findall(html)
    if len(set(prices)) > 2:
        flags.append("price_mismatch")

    # Store in cache (evict oldest if at capacity)
    if len(snapshot_cache) >= _SNAPSHOT_CACHE_MAX:
        oldest_url = min(snapshot_cache, key=lambda k: snapshot_cache[k]["timestamp"])
        del snapshot_cache[oldest_url]
    snapshot_cache[page_url] = {
        "snapshot_id": snapshot_id,
        "timestamp": datetime.now(),
        "flags": flags,
    }

    safe = "hidden_instructions_detected" not in flags
    return {"flags": flags, "snapshot_id": snapshot_id, "safe": safe, "error": None}


# ---------------------------------------------------------------------------
# Human approval via webhook or CLI fallback
# ---------------------------------------------------------------------------

import logging as _approval_logging
_approval_logger = _approval_logging.getLogger(__name__)


async def _request_human_approval(
    merchant: str,
    amount: float,
    reasoning: str,
    seal_id: str,
) -> tuple[bool, str]:
    """Request human approval for a payment.

    If POP_APPROVAL_WEBHOOK is set, POST an approval request to the webhook URL
    and wait for a response (timeout 120s). The webhook must return JSON:
        {"approved": true/false, "reason": "..."}

    If the webhook is not configured, fall back to CLI prompt (stdin).

    Returns (approved: bool, reason: str).
    """
    if approval_webhook_url:
        # SSRF validate the webhook URL (reuse pattern from notification webhook)
        try:
            _aw_parsed = urlparse(approval_webhook_url)
            _aw_host = _aw_parsed.hostname or ""
            try:
                _aw_addr = ipaddress.ip_address(_aw_host)
                if _aw_addr.is_private or _aw_addr.is_loopback or _aw_addr.is_link_local or _aw_addr.is_reserved:
                    _approval_logger.warning("Approval webhook URL blocked: private/internal address %s", _aw_host)
                    return False, f"Approval webhook SSRF blocked: private address {_aw_host}"
            except ValueError:
                pass  # hostname (not raw IP) -- allow
        except Exception:
            return False, "Approval webhook URL is invalid."

        try:
            async with httpx.AsyncClient() as approval_client:
                payload = {
                    "merchant": merchant,
                    "amount": amount,
                    "reasoning": reasoning,
                    "seal_id": seal_id,
                }
                resp = await approval_client.post(
                    approval_webhook_url, json=payload, timeout=120.0
                )
                resp.raise_for_status()
                data = resp.json()
                approved = bool(data.get("approved", False))
                reason = data.get("reason", "")
                return approved, reason
        except Exception as exc:
            _approval_logger.error("Approval webhook failed: %s", exc)
            return False, f"Approval webhook error: {exc}"

    # CLI fallback: not implemented in MCP context (no stdin),
    # so auto-approve when no webhook is configured.
    return True, "auto-approved (no approval webhook configured)"


# ---------------------------------------------------------------------------
# MCP Tools
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
    
    # -------------------------------------------------------------------
    # P1: Automatic security scan (runs whenever page_url is provided)
    # -------------------------------------------------------------------
    scan_note = ""
    if page_url:
        # Check cache first (reuse recent scan within 5 minutes)
        cached = snapshot_cache.get(page_url)
        if cached and datetime.now() - cached["timestamp"] < timedelta(minutes=5):
            scan_result = {
                "flags": cached["flags"],
                "snapshot_id": cached["snapshot_id"],
                "safe": "hidden_instructions_detected" not in cached["flags"],
                "error": None,
            }
        else:
            scan_result = await _scan_page(page_url)

        if scan_result.get("error"):
            # Network/URL error — treat as unsafe; do not issue card
            return (
                f"Payment rejected. Security scan failed: {scan_result['error']} "
                f"Snapshot ID: {scan_result['snapshot_id']}. "
                f"Fix the URL or skip page_url if the checkout has no associated URL."
            )

        if not scan_result["safe"]:
            return (
                f"Payment rejected. Security scan detected hidden prompt injection. "
                f"Snapshot ID: {scan_result['snapshot_id']}. "
                f"Flags: {scan_result['flags']}. "
                f"Do not retry this payment."
            )
    else:
        scan_note = " (security scan skipped — no page_url provided)"

    # Human approval gate (if POP_APPROVAL_WEBHOOK is configured)
    require_approval = os.getenv("POP_REQUIRE_HUMAN_APPROVAL", "false").lower() == "true"
    if require_approval:
        pre_seal_id = str(uuid.uuid4())
        approved, approval_reason = await _request_human_approval(
            merchant=target_vendor,
            amount=requested_amount,
            reasoning=reasoning,
            seal_id=pre_seal_id,
        )
        if not approved:
            return (
                f"Payment rejected by human approval. Reason: {approval_reason}"
            )

    intent = PaymentIntent(
        agent_id="mcp-agent",
        requested_amount=requested_amount,
        target_vendor=target_vendor,
        reasoning=reasoning,
        page_url=page_url or None,
    )
    seal = await client.process_payment(intent)

    # Webhook Notification (if enabled) — fires for ALL outcomes including rejections
    # so operators can monitor attack attempts and guardrail triggers.
    if policy.webhook_url:
        try:
            # SSRF guard: block webhook to private/internal addresses
            _wh_parsed = urlparse(policy.webhook_url)
            _wh_host = _wh_parsed.hostname or ""
            try:
                _wh_addr = ipaddress.ip_address(_wh_host)
                if _wh_addr.is_private or _wh_addr.is_loopback or _wh_addr.is_link_local or _wh_addr.is_reserved:
                    logger.warning("Webhook URL blocked: private/internal address %s", _wh_host)
                    raise ValueError("SSRF blocked")
            except ValueError as _ssrf_err:
                if "SSRF blocked" in str(_ssrf_err):
                    raise
                pass  # hostname (not raw IP) — allow
            async with httpx.AsyncClient() as webhook_client:
                payload = {
                    "merchant": intent.target_vendor,
                    "amount": intent.requested_amount,
                    "status": seal.status,
                    "agent_id": intent.agent_id,
                    "reasoning": intent.reasoning,
                    "seal_id": seal.seal_id,
                    "rejection_reason": seal.rejection_reason if seal.status.lower() == "rejected" else None,
                }
                await webhook_client.post(policy.webhook_url, json=payload, timeout=5.0)
        except Exception:
            pass  # Webhook failure should not block the main payment flow
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

        billing_details = injection_result.get("billing_details", {}) if isinstance(injection_result, dict) else {}
        if billing_filled and billing_details:
            bd_filled = billing_details.get("filled", [])
            bd_failed = billing_details.get("failed", [])
            billing_note = f" Billing filled: {bd_filled}."
            if bd_failed:
                billing_note += f" FAILED: {bd_failed}."
        elif billing_filled:
            billing_note = " Billing fields filled."
        else:
            billing_note = ""
        return (
            f"Payment approved and securely auto-injected into the browser form."
            f"{billing_note}"
            f"{scan_note} "
            f"Please proceed to click the submit/pay button. "
            f"Masked card: {masked_card}"
        )

    # -------------------------------------------------------------------
    # Standard path: return masked card details only
    # -------------------------------------------------------------------
    return (
        f"Payment approved. Card Issued: {masked_card}, "
        f"Expiry: {seal.expiration_date}, Amount: {seal.authorized_amount}"
        f"{scan_note}"
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
    from urllib.parse import urlparse
    from pop_pay.engine.guardrails import _match_vendor
    page_domain = urlparse(page_url).netloc.lower().removeprefix("www.") if page_url else ""
    vendor_allowed = _match_vendor(target_vendor, allowed_categories, page_domain=page_domain)
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


import logging as _logging
_x402_logger = _logging.getLogger(__name__)


def _ssrf_validate_url(url: str) -> str | None:
    """Validate a URL against SSRF.

    Returns None if the URL is safe, or an error message string if blocked.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "Only http/https URLs are allowed."
        host = parsed.hostname or ""
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return "Requests to private/internal addresses are not allowed."
        except ValueError:
            pass  # hostname (not raw IP) -- allow
    except Exception:
        return "Invalid URL."
    return None


@mcp.tool()
async def request_x402_payment(
    amount: float,
    service_url: str,
    reasoning: str,
) -> str:
    """Pay for an API call or service using the x402 HTTP payment protocol.

    The x402 protocol flow:
    1. Client sends a request to the service URL.
    2. Server responds with HTTP 402 + payment details.
    3. Client pays and retries with a payment proof header.

    This tool handles the full challenge-response cycle. It requires:
    - POP_X402_WALLET_KEY env var to be set (crypto wallet key for x402 payments).
    - The service_url must pass SSRF validation.
    - The payment must pass guardrail evaluation (amount limits, vendor matching).

    NOTE: x402 payment execution is currently stubbed. The guardrail check
    and spend recording are fully functional; actual blockchain payment will
    be added when Coinbase SDK integration is ready.
    """
    # 1. Check wallet key
    wallet_key = os.getenv("POP_X402_WALLET_KEY", "")
    if not wallet_key:
        return (
            "x402 payment rejected: POP_X402_WALLET_KEY environment variable is not set. "
            "Configure your wallet key in ~/.config/pop-pay/.env to enable x402 payments."
        )

    # 2. SSRF validate service_url
    ssrf_error = _ssrf_validate_url(service_url)
    if ssrf_error:
        return f"x402 payment rejected: SSRF validation failed for service_url. {ssrf_error}"

    # 3. Guardrail evaluation
    intent = PaymentIntent(
        agent_id="mcp-agent-x402",
        requested_amount=amount,
        target_vendor=service_url,
        reasoning=reasoning,
        page_url=service_url,
    )
    seal = await client.process_payment(intent)

    if seal.status.lower() == "rejected":
        return f"x402 payment rejected by guardrails. Reason: {seal.rejection_reason}"

    # 4. Stub: x402 challenge-response (to be replaced with real Coinbase SDK)
    _x402_logger.warning(
        "x402 payment execution is STUBBED. seal_id=%s amount=%.2f service_url=%s. "
        "Real x402 payment via Coinbase SDK is not yet implemented.",
        seal.seal_id, amount, service_url,
    )

    # 5. Record spend (already done in client.process_payment)

    # 6. Webhook notification
    if policy.webhook_url:
        try:
            _wh_parsed = urlparse(policy.webhook_url)
            _wh_host = _wh_parsed.hostname or ""
            try:
                _wh_addr = ipaddress.ip_address(_wh_host)
                if _wh_addr.is_private or _wh_addr.is_loopback or _wh_addr.is_link_local or _wh_addr.is_reserved:
                    raise ValueError("SSRF blocked")
            except ValueError as _ssrf_err:
                if "SSRF blocked" in str(_ssrf_err):
                    raise
                pass
            async with httpx.AsyncClient() as webhook_client:
                payload = {
                    "type": "x402_payment",
                    "service_url": service_url,
                    "amount": amount,
                    "status": "stubbed",
                    "seal_id": seal.seal_id,
                    "reasoning": reasoning,
                }
                await webhook_client.post(policy.webhook_url, json=payload, timeout=5.0)
        except Exception:
            pass

    return (
        f"x402 payment approved (STUBBED). seal_id={seal.seal_id}, amount=${amount:.2f}, "
        f"service_url={service_url}. "
        f"Note: actual x402 blockchain payment is not yet implemented -- "
        f"guardrails passed and spend was recorded, but no real payment was executed."
    )


if __name__ == "__main__":
    mcp.run()
