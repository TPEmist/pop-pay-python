"""
PopBrowserInjector: CDP-based browser injector with iframe traversal.

Connects to an already-running Chromium browser (via --remote-debugging-port)
and auto-fills credit card fields on the active page — including fields inside
Stripe and other third-party payment iframes.  Also fills billing detail fields
(name, address, email) that live in the main page frame.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

from pop_pay.core.state import PopStateTracker

logger = logging.getLogger(__name__)


# S0.7 F5: PAN/CVV wrapper that masks in repr/str/format so exception
# tracebacks with show_locals (rich.traceback, sys.excepthook) cannot leak
# plaintext. The underlying Unicode data is preserved for JSON serialization
# and Playwright .fill() calls; only Python-level display renders the mask.
class _SecretStr(str):
    __slots__ = ()

    def __repr__(self) -> str:
        return "'***REDACTED***'"

    def __str__(self) -> str:
        return "***REDACTED***"

    def __format__(self, spec: str) -> str:
        return "***REDACTED***"


def _seal(value: str) -> str:
    if isinstance(value, _SecretStr) or not value:
        return value
    return _SecretStr(value)


# S0.7 F6(b): detect Chrome instances launched with verbose logging flags that
# can write plaintext CDP traffic to stderr/disk. Best-effort process scan; if
# enumeration fails we return "" (don't block — the risk is additive not primary).
_RISKY_CHROME_FLAGS = ("--enable-logging", "--v=", "--vmodule=", "--log-net-log")


def _detect_risky_chrome_flags() -> str:
    import subprocess
    import sys as _sys
    try:
        if _sys.platform == "win32":
            out = subprocess.run(
                ["wmic", "process", "where", "name='chrome.exe'", "get", "CommandLine"],
                capture_output=True, text=True, timeout=3,
            ).stdout
        else:
            out = subprocess.run(
                ["ps", "-Ao", "command"],
                capture_output=True, text=True, timeout=3,
            ).stdout
    except (subprocess.SubprocessError, OSError):
        return ""
    for line in out.splitlines():
        low = line.lower()
        if "chrome" not in low and "chromium" not in low:
            continue
        for flag in _RISKY_CHROME_FLAGS:
            if flag in line:
                return flag
    return ""

# ISO 3166-1 alpha-2 → E.164 dial prefix.
# Used to auto-derive the national number from a full E.164 phone string when
# POP_BILLING_PHONE_COUNTRY_CODE is set — no POP_BILLING_PHONE_NATIONAL needed.
_COUNTRY_DIAL_CODES: dict[str, str] = {
    "US": "+1",   "CA": "+1",   "GB": "+44",  "AU": "+61",  "DE": "+49",
    "FR": "+33",  "JP": "+81",  "CN": "+86",  "IN": "+91",  "BR": "+55",
    "TW": "+886", "HK": "+852", "SG": "+65",  "KR": "+82",  "MX": "+52",
    "NL": "+31",  "SE": "+46",  "NO": "+47",  "DK": "+45",  "FI": "+358",
    "CH": "+41",  "AT": "+43",  "BE": "+32",  "IT": "+39",  "ES": "+34",
    "PT": "+351", "PL": "+48",  "RU": "+7",   "UA": "+380", "NZ": "+64",
    "ZA": "+27",  "NG": "+234", "EG": "+20",  "IL": "+972", "AE": "+971",
    "SA": "+966", "TR": "+90",  "AR": "+54",  "CO": "+57",  "CL": "+56",
    "TH": "+66",  "VN": "+84",  "ID": "+62",  "MY": "+60",  "PH": "+63",
}


def _national_number(phone_e164: str, country_code: str) -> str:
    """
    Derive the national (subscriber) number from an E.164 string.

    country_code may be an ISO alpha-2 code ("US"), a dial prefix ("+1"),
    or a dial prefix without plus ("1"). Returns the full E.164 as fallback
    so the injector can still attempt to fill the field.
    """
    if not phone_e164.startswith("+"):
        return phone_e164  # not E.164 — return as-is

    cc = country_code.strip()
    # Normalise to "+X..." form
    if not cc.startswith("+"):
        dial = _COUNTRY_DIAL_CODES.get(cc.upper())
        if dial is None:
            dial = "+" + cc  # treat as raw numeric prefix
    else:
        dial = cc

    if phone_e164.startswith(dial):
        return phone_e164[len(dial):]
    return phone_e164  # prefix didn't match — fall back to full E.164


# ---------------------------------------------------------------------------
# US state abbreviation → full name mapping (for dropdowns that use full names)
# ---------------------------------------------------------------------------
US_STATE_CODES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# ---------------------------------------------------------------------------
# Common CSS selectors for credit card fields across major payment providers
# ---------------------------------------------------------------------------
CARD_NUMBER_SELECTORS = [
    "input[autocomplete='cc-number']",
    "input[name='cardnumber']",
    "input[name='card_number']",
    "input[name='card-number']",
    "input[id*='card'][id*='number']",
    "input[placeholder*='Card number']",
    "input[placeholder*='card number']",
    "input[data-elements-stable-field-name='cardNumber']",   # Stripe Elements
    "input.__PrivateStripeElement",                          # Stripe v2
]

EXPIRY_SELECTORS = [
    "input[autocomplete='cc-exp']",
    "input[name='cc-exp']",
    "input[name='expiry']",
    "input[name='card_expiry']",
    "input[placeholder*='MM / YY']",
    "input[placeholder*='MM/YY']",
    "input[placeholder*='Expiry']",
    "input[data-elements-stable-field-name='cardExpiry']",   # Stripe Elements
]

CVV_SELECTORS = [
    "input[autocomplete='cc-csc']",
    "input[name='cvc']",
    "input[name='cvv']",
    "input[name='security_code']",
    "input[name='card_cvc']",
    "input[placeholder*='CVC']",
    "input[placeholder*='CVV']",
    "input[placeholder*='Security code']",
    "input[data-elements-stable-field-name='cardCvc']",      # Stripe Elements
]

# ---------------------------------------------------------------------------
# Common CSS selectors for billing detail fields (main page frame, not iframes)
# ---------------------------------------------------------------------------
FIRST_NAME_SELECTORS = [
    "input[autocomplete='given-name']",
    "input[name='first_name']",
    "input[name='firstName']",
    "input[name='first-name']",
    "input[id*='first'][id*='name']",
    "input[id='first_name']",
    "input[id='firstName']",
    "input[placeholder*='First name']",
    "input[placeholder*='first name']",
    "input[aria-label*='First name']",
    "input[aria-label*='first name']",
]

LAST_NAME_SELECTORS = [
    "input[autocomplete='family-name']",
    "input[name='last_name']",
    "input[name='lastName']",
    "input[name='last-name']",
    "input[id*='last'][id*='name']",
    "input[id='last_name']",
    "input[id='lastName']",
    "input[placeholder*='Last name']",
    "input[placeholder*='last name']",
    "input[aria-label*='Last name']",
    "input[aria-label*='last name']",
]

FULL_NAME_SELECTORS = [
    "input[autocomplete='name']",
    "input[name='full_name']",
    "input[name='fullName']",
    "input[name='name']",
    "input[id='full_name']",
    "input[id='fullName']",
    "input[placeholder*='Full name']",
    "input[placeholder*='full name']",
    "input[aria-label*='Full name']",
    "input[aria-label*='full name']",
]

STREET_SELECTORS = [
    "input[autocomplete='street-address']",
    "input[autocomplete='address-line1']",
    "input[name='address']",
    "input[name='address1']",
    "input[name='street']",
    "input[name='street_address']",
    "input[name='billing_address']",
    "input[id*='address']",
    "input[id*='street']",
    "input[placeholder*='Street']",
    "input[placeholder*='street']",
    "input[placeholder*='Address']",
    "input[placeholder*='address']",
    "input[aria-label*='Street']",
    "input[aria-label*='street']",
]

ZIP_SELECTORS = [
    "input[autocomplete='postal-code']",
    "input[name='zip']",
    "input[name='postal_code']",
    "input[name='postcode']",
    "input[name='zipcode']",
    "input[name='zip_code']",
    "input[id*='zip']",
    "input[id*='postal']",
    "input[placeholder*='Zip']",
    "input[placeholder*='zip']",
    "input[placeholder*='Postal']",
    "input[placeholder*='postal']",
    "input[aria-label*='Zip']",
    "input[aria-label*='zip']",
    "input[aria-label*='Postal']",
]

EMAIL_SELECTORS = [
    "input[autocomplete='email']",
    "input[type='email']",
    "input[name='email']",
    "input[name='email_address']",
    "input[id='email']",
    "input[id*='email']",
    "input[placeholder*='Email']",
    "input[placeholder*='email']",
    "input[aria-label*='Email']",
    "input[aria-label*='email']",
]

PHONE_SELECTORS = [
    "input[autocomplete='tel']",
    "input[type='tel']",
    "input[name='phone']",
    "input[name='phone_number']",
    "input[name='phoneNumber']",
    "input[name='telephone']",
    "input[name='mobile']",
    "input[id*='phone']",
    "input[id*='tel']",
    "input[id*='mobile']",
    "input[placeholder*='Phone']",
    "input[placeholder*='phone']",
    "input[placeholder*='Mobile']",
    "input[aria-label*='Phone']",
    "input[aria-label*='phone']",
]

# Separate country-code dropdown that appears before the phone number input.
# Matched fuzzily: "US", "+1", "United States" all resolve via _select_option().
PHONE_COUNTRY_CODE_SELECTORS = [
    "select[autocomplete='tel-country-code']",
    "select[name='phone_country_code']",
    "select[name='phoneCountryCode']",
    "select[name='dialCode']",
    "select[name='dial_code']",
    "select[name='country_code']",
    "select[name='countryCode']",
    "select[id*='country_code']",
    "select[id*='dialCode']",
    "select[id*='dial_code']",
    "select[aria-label*='Country code']",
    "select[aria-label*='country code']",
    "select[aria-label*='Dial code']",
]

# Dropdown-capable selectors: include both <select> and <input> variants.
# _fill_field() detects the tag at runtime and uses select_option() or fill()
# accordingly — no separate logic needed when adding new dropdown fields.

COUNTRY_SELECTORS = [
    "select[autocomplete='country']",
    "select[autocomplete='country-name']",
    "select[name='country']",
    "select[name='billing_country']",
    "select[name='billingCountry']",
    "select[id='country']",
    "select[id*='country']",
    "select[aria-label*='Country']",
    "select[aria-label*='country']",
    "input[autocomplete='country']",
    "input[autocomplete='country-name']",
    "input[name='country']",
]

STATE_SELECTORS = [
    "select[autocomplete='address-level1']",
    "select[name='state']",
    "select[name='province']",
    "select[name='region']",
    "select[name='billing_state']",
    "select[id='state']",
    "select[id*='state']",
    "select[id*='province']",
    "select[aria-label*='State']",
    "select[aria-label*='state']",
    "select[aria-label*='Province']",
    "input[autocomplete='address-level1']",
    "input[name='state']",
    "input[name='province']",
]

CITY_SELECTORS = [
    "input[autocomplete='address-level2']",
    "input[name='city']",
    "input[name='town']",
    "input[name='billing_city']",
    "input[id='city']",
    "input[id*='city']",
    "input[placeholder*='City']",
    "input[placeholder*='city']",
    "input[aria-label*='City']",
    "select[autocomplete='address-level2']",
    "select[name='city']",
]


class PopBrowserInjector:
    """
    Attaches to a running Chromium browser via CDP and injects
    card credentials into whatever page is currently active.

    The browser must be launched with --remote-debugging-port=9222.
    Example:
        chromium --remote-debugging-port=9222 https://checkout.example.com

    Usage:
        injector = PopBrowserInjector(state_tracker)
        success = await injector.inject_payment_info(seal_id, card_number=seal.card_number, cvv=seal.cvv, expiration_date=seal.expiration_date)
    """

    def __init__(self, state_tracker: PopStateTracker, headless: bool = False):
        self.state_tracker = state_tracker
        self.headless = headless

    # ------------------------------------------------------------------
    # Shared TOCTOU domain verification
    # ------------------------------------------------------------------

    @staticmethod
    def _verify_domain_toctou(page_url: str, approved_vendor: str) -> str | None:
        """Verify the current page domain matches the approved vendor.

        Uses KNOWN_VENDOR_DOMAINS suffix matching (same as guardrail layer 1) to
        prevent subdomain-spoofing bypasses like "wikipedia.attacker.com".

        Returns None if the domain is OK, or a blocked_reason string
        (e.g. "domain_mismatch:<domain>") if the check fails.
        """
        if not page_url or not approved_vendor:
            return None

        from urllib.parse import urlparse
        import re
        from pop_pay.engine.guardrails import KNOWN_VENDOR_DOMAINS

        actual_domain = urlparse(page_url).netloc.lower().removeprefix("www.")
        vendor_lower = approved_vendor.lower()
        vendor_tokens = set(re.split(r'[\s\-_./]+', vendor_lower)) - {''}

        domain_ok = False
        vendor_is_known = False
        # First: check against KNOWN_VENDOR_DOMAINS using strict suffix matching.
        for known_vendor, known_domains in KNOWN_VENDOR_DOMAINS.items():
            if known_vendor in vendor_tokens or known_vendor == vendor_lower:
                vendor_is_known = True
                if any(actual_domain == d or actual_domain.endswith("." + d)
                       for d in known_domains):
                    domain_ok = True
                break
        # Fallback ONLY for vendors absent from KNOWN_VENDOR_DOMAINS.
        if not domain_ok and not vendor_is_known:
            _common_tlds = {'com', 'org', 'net', 'io', 'co', 'uk', 'jp', 'de', 'fr'}
            domain_labels = set(actual_domain.split(".")) - _common_tlds
            domain_ok = (
                bool(vendor_tokens.intersection(domain_labels))
                or any(
                    tok in label
                    for tok in vendor_tokens
                    for label in domain_labels
                    if len(tok) >= 4
                )
            )

        # Payment processor passthrough
        if not domain_ok:
            import json as _json
            from pop_pay.engine.guardrails import KNOWN_PAYMENT_PROCESSORS
            _user_processors = set(_json.loads(
                os.getenv("POP_ALLOWED_PAYMENT_PROCESSORS", "[]")
            ))
            _all_processors = KNOWN_PAYMENT_PROCESSORS | _user_processors
            if any(actual_domain == p or actual_domain.endswith("." + p)
                   for p in _all_processors):
                domain_ok = True
                logger.info(
                    "PopBrowserInjector: domain '%s' is a known payment processor "
                    "-- TOCTOU passed for vendor '%s'.",
                    actual_domain, approved_vendor,
                )

        if not domain_ok:
            logger.warning(
                "PopBrowserInjector: TOCTOU domain mismatch -- "
                "approved vendor '%s' does not match current page domain '%s'. "
                "Injection blocked.",
                approved_vendor, actual_domain,
            )
            return f"domain_mismatch:{actual_domain}"

        return None

    # ------------------------------------------------------------------
    # Headless browser launch helper
    # ------------------------------------------------------------------

    async def _launch_headless(self, pw):
        """Launch a headless Chromium browser via Playwright.

        Returns a (browser, page) tuple. The caller is responsible for
        closing the browser when done.
        """
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        return browser, page

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def inject_payment_info(
        self,
        seal_id: str,
        cdp_url: str = "http://localhost:9222",
        page_url: str = "",
        card_number: str = "",
        cvv: str = "",
        expiration_date: str = "",
        approved_vendor: str = "",
    ) -> dict:
        """
        Connect to an existing Chromium browser via CDP, find payment fields
        across all frames (including nested third-party iframes), fill them
        with real card details, then disconnect without closing the browser.
        Also fills billing detail fields (name, address, email) from env vars
        in the main page frame, if the env vars are set.

        Args:
            seal_id:          The VirtualSeal ID returned by PopClient.process_payment().
            cdp_url:          The Chrome DevTools Protocol endpoint (default: http://localhost:9222).
            page_url:         Optional. The checkout page URL currently open in the agent's browser.
                              If provided and the CDP browser has no open pages, Aegis will
                              automatically open this URL in the CDP browser before injecting.
                              Pass this when navigating via Playwright MCP to ensure both
                              MCPs operate on the same page.
            card_number:      Card number to inject (passed from in-memory seal, never from DB).
            cvv:              CVV to inject (passed from in-memory seal, never from DB).
            expiration_date:  Expiration date in MM/YY format.
            approved_vendor:  The guardrail-approved vendor name. When both page_url and
                              approved_vendor are provided, the current page domain is verified
                              to match the approved vendor before any injection occurs (TOCTOU guard).

        Returns a dict with:
            "card_filled"    — bool: card number field was found and filled.
            "billing_filled" — bool: at least one billing field was filled.
            "blocked_reason" — str: non-empty if injection was blocked (e.g. "domain_mismatch:<domain>").
        For backwards compatibility, the dict is also truthy/falsy based on
        card_filled (via __bool__ semantics of the first value).
        """
        # S0.7 F5: seal PAN/CVV/expiry at the function boundary so every
        # frame local (including deep helpers) renders masked when
        # tracebacks capture show_locals (rich.traceback, sys.excepthook).
        card_number = _seal(card_number)
        cvv = _seal(cvv)
        expiration_date = _seal(expiration_date)
        result = {"card_filled": False, "billing_filled": False, "blocked_reason": ""}

        # TOCTOU guard: verify the current page domain matches the approved vendor
        blocked = self._verify_domain_toctou(page_url, approved_vendor)
        if blocked:
            result["blocked_reason"] = blocked
            return result

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "playwright is not installed. "
                "Run: pip install pop-pay[browser]  or  pip install playwright"
            )
            return result

        expiry: str = expiration_date

        # Collect billing info from env vars — all optional, skip if empty
        billing_info = {
            "first_name":         os.getenv("POP_BILLING_FIRST_NAME", "").strip(),
            "last_name":          os.getenv("POP_BILLING_LAST_NAME", "").strip(),
            "street":             os.getenv("POP_BILLING_STREET", "").strip(),
            "city":               os.getenv("POP_BILLING_CITY", "").strip(),
            "state":              os.getenv("POP_BILLING_STATE", "").strip(),
            "country":            os.getenv("POP_BILLING_COUNTRY", "").strip(),
            "zip":                os.getenv("POP_BILLING_ZIP", "").strip(),
            "email":              os.getenv("POP_BILLING_EMAIL", "").strip(),
            "phone":              os.getenv("POP_BILLING_PHONE", "").strip(),
            "phone_country_code": os.getenv("POP_BILLING_PHONE_COUNTRY_CODE", "").strip(),
        }
        has_billing = any(billing_info.values())

        browser = None
        try:
            async with async_playwright() as pw:
                if self.headless:
                    browser, page = await self._launch_headless(pw)
                    if page_url:
                        await page.goto(page_url, wait_until="domcontentloaded", timeout=15000)
                        await page.wait_for_timeout(3000)
                else:
                    # S0.7 F6: refuse to inject into a Chrome instance launched with
                    # verbose logging flags — CDP traffic + stdout can leak plaintext
                    # via --enable-logging=stderr and --v=<n>.
                    _flag = _detect_risky_chrome_flags()
                    if _flag:
                        result["blocked_reason"] = f"chrome_logging_flag:{_flag}"
                        logger.error(
                            "PopBrowserInjector: refusing injection — target Chrome has "
                            "%s enabled. Restart Chrome without verbose logging flags.",
                            _flag,
                        )
                        return result

                    # Connect to the *existing* browser — does NOT launch a new instance
                    browser = await pw.chromium.connect_over_cdp(cdp_url)

                    # Search all contexts (not just contexts[0]) — Playwright MCP may
                    # create pages in a non-default context when sharing the same Chrome.
                    page = self._find_best_page(browser)

                    if page is None and page_url:
                        # Auto-bridge: agent navigated via a different browser instance;
                        # open the same URL in the CDP browser so injection can proceed.
                        logger.info(
                            "PopBrowserInjector: no open pages in CDP browser — "
                            "opening page_url: %s", page_url,
                        )
                        page = await self._open_url_in_browser(browser, page_url)

                    if page is None:
                        logger.warning(
                            "PopBrowserInjector: no open pages found via CDP at %s. "
                            "Ensure pop-launch is running and Playwright MCP is configured "
                            "with --cdp-endpoint %s, or pass page_url to request_virtual_card.",
                            cdp_url, cdp_url,
                        )
                        return result

                    await page.bring_to_front()

                # POP_BLACKOUT_MODE: "before" | "after" | "off"
                #   before = mask fields before injection (more secure, agent never sees card)
                #   after  = mask fields after injection (good for demos, shows card briefly)
                #   off    = no masking
                # S0.7 F6(c): default is "before" — agent never sees plaintext in DOM.
                blackout_mode = os.getenv("POP_BLACKOUT_MODE", "before").lower()

                if blackout_mode == "before":
                    await self._enable_blackout(page)

                result["card_filled"] = await self._fill_across_frames(
                    page, card_number, expiry, cvv
                )

                if has_billing:
                    billing_result = await self._fill_billing_fields(
                        page, billing_info
                    )
                    result["billing_filled"] = bool(billing_result["filled"])
                    result["billing_details"] = billing_result

                if blackout_mode == "after":
                    await self._enable_blackout(page)

                return result

        except Exception as exc:
            logger.error("PopBrowserInjector error: %s", exc, exc_info=True)
            return result
        finally:
            # Disconnect the playwright session — does NOT close the real browser
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass

    @staticmethod
    def _find_best_page(browser):
        """
        Search all browser contexts for an open page, preferring checkout/payment URLs.

        Playwright MCP may create pages in a non-default browser context when
        connecting to a shared CDP Chrome. Checking only contexts[0] misses those
        pages; this method walks every context to find the best candidate.
        """
        CHECKOUT_KEYWORDS = (
            "checkout", "payment", "donate", "pay", "purchase",
            "order", "gateway", "cart",
        )
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        if not all_pages:
            return None
        # Prefer pages whose URL looks like a checkout/payment page
        for page in all_pages:
            if any(kw in page.url.lower() for kw in CHECKOUT_KEYWORDS):
                return page
        # Fallback: last page (most recently navigated)
        return all_pages[-1]

    @staticmethod
    async def _open_url_in_browser(browser, url: str):
        """
        Open *url* as a new tab in the CDP browser, wait for it to be interactive,
        and return the Page object.  Used by the auto-bridge path when page_url is
        provided but the CDP browser has no open pages.
        """
        try:
            contexts = browser.contexts
            if not contexts:
                logger.warning("PopBrowserInjector: no contexts available to open URL.")
                return None
            page = await contexts[0].new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            # Allow dynamic payment form JS (e.g. Gr4vy, Stripe) to initialise
            await page.wait_for_timeout(3000)
            logger.info(
                "PopBrowserInjector: auto-bridge opened URL in CDP browser: %s", url
            )
            return page
        except Exception as exc:
            logger.error(
                "PopBrowserInjector: failed to open URL '%s': %s", url, exc
            )
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fill_across_frames(
        self, page, card_number: str, expiry: str, cvv: str
    ) -> bool:
        """
        Walk every frame in the page tree (flat list from Playwright includes
        all nested iframes). Return True as soon as the card number is filled.
        """
        all_frames = page.frames  # includes main frame + all nested iframes
        card_filled = False

        for frame in all_frames:
            try:
                if await self._fill_in_frame(frame, card_number, expiry, cvv):
                    card_filled = True
                    # Keep going for expiry/CVV in case they are in sibling iframes
                    # (common in Stripe's multi-iframe layout)
            except Exception as frame_exc:
                logger.debug("Frame %s skipped: %s", frame.url, frame_exc)
                continue

        # Shadow DOM piercing fallback: search for shadow roots in main page
        if not card_filled:
            if await self._fill_card_in_shadow_dom(page, card_number, expiry, cvv):
                card_filled = True

        return card_filled

    async def _fill_card_in_shadow_dom(
        self, page, card_number: str, expiry: str, cvv: str
    ) -> bool:
        """
        Search for card fields inside Shadow DOM trees using recursive
        queryShadowAll and fill them via native setters + event dispatch.
        """
        try:
            card_selectors = ", ".join(CARD_NUMBER_SELECTORS)
            expiry_selectors = ", ".join(EXPIRY_SELECTORS)
            cvv_selectors = ", ".join(CVV_SELECTORS)

            script = """
            ([cardNumber, expiry, cvv, cardSels, expSels, cvvSels]) => {
                function queryShadowFirst(root, selectors) {
                    const selectorList = selectors.split(', ');
                    for (const sel of selectorList) {
                        try {
                            const found = root.querySelector(sel);
                            if (found) return found;
                        } catch (e) {}
                    }
                    const allElements = root.querySelectorAll('*');
                    for (const el of allElements) {
                        if (el.shadowRoot) {
                            const found = queryShadowFirst(el.shadowRoot, selectors);
                            if (found) return found;
                        }
                    }
                    return null;
                }

                function fillField(root, selectors, value) {
                    const el = queryShadowFirst(root, selectors);
                    if (!el) return false;
                    try {
                        const nativeSetter = Object.getOwnPropertyDescriptor(
                            HTMLInputElement.prototype, 'value'
                        ).set;
                        if (nativeSetter) {
                            nativeSetter.call(el, value);
                        } else {
                            el.value = value;
                        }
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                        return true;
                    } catch (e) {
                        return false;
                    }
                }

                const cardFilled = fillField(document, cardSels, cardNumber);
                if (cardFilled) {
                    fillField(document, expSels, expiry);
                    fillField(document, cvvSels, cvv);
                }
                return cardFilled;
            }
            """
            result = await page.evaluate(script, [
                card_number, expiry, cvv,
                card_selectors, expiry_selectors, cvv_selectors
            ])
            return bool(result)
        except Exception as e:
            logger.debug("PopBrowserInjector: Shadow DOM piercing failed: %s", e)
            return False

    async def _fill_in_frame(
        self, frame, card_number: str, expiry: str, cvv: str
    ) -> bool:
        """
        Attempt to fill card fields inside a single frame.
        Returns True if the card number field was found and filled; False otherwise.
        """
        card_locator = await self._find_visible_locator(frame, CARD_NUMBER_SELECTORS)
        if card_locator is None:
            return False

        await card_locator.fill(card_number)
        logger.info(
            "PopBrowserInjector: ✅ card number injected in frame '%s'", frame.url
        )

        expiry_locator = await self._find_visible_locator(frame, EXPIRY_SELECTORS)
        if expiry_locator:
            await expiry_locator.fill(expiry)
            logger.info("PopBrowserInjector: expiry injected.")

        cvv_locator = await self._find_visible_locator(frame, CVV_SELECTORS)
        if cvv_locator:
            await cvv_locator.fill(cvv)
            logger.info("PopBrowserInjector: CVV injected.")

        return True

    @staticmethod
    async def _dispatch_events(locator) -> None:
        """
        Dispatch trusted change/input events via Playwright's dispatch_event().

        Key: Playwright's dispatch_event() creates TRUSTED events (isTrusted=true),
        unlike el.dispatchEvent() in evaluate() which creates untrusted events.
        Frameworks like Zoho, React, Angular check isTrusted and ignore untrusted ones.
        """
        try:
            await locator.dispatch_event("input")
            await locator.dispatch_event("change")
        except Exception:
            pass
        # Also fire untrusted blur/focusout as safety net (some frameworks need them)
        try:
            await locator.evaluate("""el => {
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }""")
        except Exception:
            pass

    async def _select_option(self, locator, value: str) -> bool:
        """
        Select a <select> option reliably across frameworks.

        Approach:
        1. Scan options to find the best match (exact value → exact text → partial)
        2. Try Playwright's native select_option() first
        3. Verify the value actually stuck (some frameworks override the setter)
        4. If mismatch, fall back to JS native setter trick + comprehensive events
           (bypasses React/Angular/Zoho/Vue framework interception)
        """
        # Step 1: Find the matching option value
        try:
            options = await locator.evaluate(
                "el => Array.from(el.options).map(o => ({value: o.value, text: o.text.trim()}))"
            )
        except Exception as exc:
            logger.warning("PopBrowserInjector: could not read <select> options: %s", exc)
            return False

        value_lower = value.lower()
        matched_value = None

        # Exact value match
        for opt in options:
            if opt["value"].lower() == value_lower:
                matched_value = opt["value"]
                break
        # Exact text match
        if not matched_value:
            for opt in options:
                if opt["text"].lower() == value_lower:
                    matched_value = opt["value"]
                    break
        # Partial match
        if not matched_value:
            for opt in options:
                opt_text = opt["text"].lower()
                opt_val = opt["value"].lower()
                if (value_lower in opt_text or opt_text in value_lower or
                        value_lower in opt_val or opt_val in value_lower):
                    if opt["value"]:
                        matched_value = opt["value"]
                        break

        if not matched_value:
            logger.warning(
                "PopBrowserInjector: no option matched '%s' in %d options. First 5: %s",
                value, len(options), options[:5],
            )
            return False

        logger.debug("PopBrowserInjector: matched '%s' → option value='%s'.", value, matched_value)

        # Step 2: Try Playwright native select_option
        try:
            await locator.select_option(value=matched_value)
        except Exception as exc:
            logger.debug("PopBrowserInjector: native select_option failed: %s", exc)

        # Step 3: Verify the value stuck
        try:
            actual = await locator.evaluate("el => el.value")
        except Exception:
            actual = None

        if actual == matched_value:
            await self._dispatch_events(locator)
            logger.info("PopBrowserInjector: select_option native success → '%s'.", matched_value)
            return True

        # Step 4: Native setter trick — bypasses React/Angular/Zoho/Vue interception
        logger.debug(
            "PopBrowserInjector: native select_option set value='%s' but read back='%s'. "
            "Trying JS native setter fallback.",
            matched_value, actual,
        )
        try:
            success = await locator.evaluate("""(el, val) => {
                // Use the native HTMLSelectElement.prototype setter to bypass
                // framework interceptions (React, Angular, Zoho, Vue).
                const nativeSetter = Object.getOwnPropertyDescriptor(
                    HTMLSelectElement.prototype, 'value'
                ).set;
                nativeSetter.call(el, val);

                // Fire comprehensive event chain
                el.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
                el.dispatchEvent(new FocusEvent('focus', { bubbles: false }));
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new FocusEvent('blur', { bubbles: false }));
                el.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));

                return el.value === val;
            }""", matched_value)
            if success:
                logger.info("PopBrowserInjector: select_option JS native setter success → '%s'.", matched_value)
                return True
            else:
                logger.warning("PopBrowserInjector: JS native setter failed for '%s'.", matched_value)
        except Exception as exc:
            logger.warning("PopBrowserInjector: JS native setter error: %s", exc)

        return False

    async def _fill_field(
        self, page_or_frame, selectors: list, value: str, field_name: str,
        *, label: str = "",
    ) -> bool:
        """
        Fill a billing field that may be either <input> or <select>.

        For <select> elements, tries accessibility-based locator (get_by_label)
        first — this is what Playwright's own MCP uses and is more reliable for
        framework-controlled selects (Zoho, React, etc.). Falls back to CSS
        selector if no label is provided or get_by_label doesn't match.

        For <input> elements, uses CSS selectors via _find_visible_locator.
        """
        if not value:
            return False

        # --- Strategy 1 (selects): try get_by_label first ---
        if label:
            try:
                label_locator = page_or_frame.get_by_label(label)
                if await label_locator.count() > 0:
                    tag = await label_locator.first.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "select":
                        filled = await self._select_option(label_locator.first, value)
                        if filled:
                            logger.info("PopBrowserInjector: %s injected via get_by_label('%s').", field_name, label)
                            return True
            except Exception as exc:
                logger.debug("PopBrowserInjector: get_by_label('%s') failed: %s", label, exc)

        # --- Strategy 2: CSS selector locator ---
        locator = await self._find_visible_locator(page_or_frame, selectors)
        if not locator:
            logger.warning("PopBrowserInjector: no element found for '%s'. Tried %d selectors.", field_name, len(selectors))
            return False
        try:
            tag = await locator.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                filled = await self._select_option(locator, value)
            else:
                await locator.fill(value)
                await self._dispatch_events(locator)
                filled = True
            if filled:
                logger.info("PopBrowserInjector: %s injected via CSS selector.", field_name)
            else:
                logger.warning("PopBrowserInjector: %s — element found but fill/selection failed.", field_name)
            return filled
        except Exception as exc:
            logger.warning("PopBrowserInjector: could not fill %s: %s", field_name, exc)
            return False

    async def _fill_billing_fields(self, page, billing_info: dict) -> dict:
        """
        Fill billing detail fields in the main page frame.
        These fields are standard DOM inputs/selects — NOT inside Stripe iframes.

        Each field is attempted independently; missing selectors are silently skipped.
        Returns dict with per-field results: {"filled": [...], "failed": [...], "skipped": [...]}.
        """
        # Use page (not just main_frame) so get_by_label can search via accessibility tree.
        f = page
        filled = []
        failed = []
        skipped = []
        first_name = billing_info.get("first_name", "")
        last_name  = billing_info.get("last_name", "")
        street     = billing_info.get("street", "")
        zip_code   = billing_info.get("zip", "")
        email      = billing_info.get("email", "")
        phone      = billing_info.get("phone", "")
        country    = billing_info.get("country", "")
        state_raw  = billing_info.get("state", "")
        # Auto-expand US state abbreviations (e.g. "CA" → "California")
        # so dropdowns with full state names match correctly.
        state      = US_STATE_CODES.get(state_raw.upper(), state_raw) if len(state_raw) == 2 else state_raw
        city       = billing_info.get("city", "")

        async def _try(selectors, value, name, label=""):
            if not value:
                skipped.append(name)
                return
            if await self._fill_field(f, selectors, value, name, label=label):
                filled.append(name)
            else:
                failed.append(f"{name} (value='{value}')")

        # Fill ORDER matters: input fields first, then select dropdowns last.
        # Reason: filling inputs can trigger framework re-renders (React, Zoho)
        # which reset previously selected dropdowns. Selects go last to survive.

        # --- Input fields first ---
        await _try(FIRST_NAME_SELECTORS, first_name, "first_name", label="First name")
        await _try(LAST_NAME_SELECTORS, last_name, "last_name", label="Last name")
        if first_name or last_name:
            full_name = " ".join(filter(None, [first_name, last_name])).strip()
            await _try(FULL_NAME_SELECTORS, full_name, "full_name", label="Full name")
        await _try(STREET_SELECTORS,  street,   "street",  label="Address")
        await _try(CITY_SELECTORS,    city,     "city",    label="City")
        await _try(ZIP_SELECTORS,     zip_code, "zip",     label="Zip")
        await _try(EMAIL_SELECTORS,   email,    "email",   label="Email")

        # --- Select dropdowns last (survive re-renders) ---
        await _try(COUNTRY_SELECTORS, country,  "country", label="Country")
        await _try(STATE_SELECTORS,   state,    "state",   label="State")

        # Phone: fill country code dropdown first (if present), then number field.
        phone_country_code = billing_info.get("phone_country_code", "")
        cc_filled = False
        if phone_country_code:
            cc_filled = await self._fill_field(
                f, PHONE_COUNTRY_CODE_SELECTORS, phone_country_code, "phone country code"
            )
            if cc_filled:
                filled.append("phone_country_code")
        phone_value = _national_number(phone, phone_country_code) if cc_filled else phone
        await _try(PHONE_SELECTORS, phone_value, "phone")

        result = {"filled": filled, "failed": failed, "skipped": skipped}
        logger.info("PopBrowserInjector: billing results: %s", result)
        return result

    async def inject_billing_only(
        self,
        cdp_url: str = "http://localhost:9222",
        page_url: str = "",
        approved_vendor: str = "",
    ) -> dict:
        """
        Inject billing fields (name, address, email, phone) into the current page
        without issuing a card or touching the payment/budget system.

        Used by request_purchaser_info for checkout flows where billing info
        is collected on a separate page before the payment form.

        Same TOCTOU domain guard as inject_payment_info.
        Returns {"billing_filled": bool, "blocked_reason": str}.
        """
        result = {"billing_filled": False, "blocked_reason": ""}

        # TOCTOU guard — uses shared method
        blocked = self._verify_domain_toctou(page_url, approved_vendor)
        if blocked:
            result["blocked_reason"] = blocked
            return result

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright is not installed.")
            return result

        billing_info = {
            "first_name":         os.getenv("POP_BILLING_FIRST_NAME", "").strip(),
            "last_name":          os.getenv("POP_BILLING_LAST_NAME", "").strip(),
            "street":             os.getenv("POP_BILLING_STREET", "").strip(),
            "city":               os.getenv("POP_BILLING_CITY", "").strip(),
            "state":              os.getenv("POP_BILLING_STATE", "").strip(),
            "country":            os.getenv("POP_BILLING_COUNTRY", "").strip(),
            "zip":                os.getenv("POP_BILLING_ZIP", "").strip(),
            "email":              os.getenv("POP_BILLING_EMAIL", "").strip(),
            "phone":              os.getenv("POP_BILLING_PHONE", "").strip(),
            "phone_country_code": os.getenv("POP_BILLING_PHONE_COUNTRY_CODE", "").strip(),
        }

        browser = None
        try:
            async with async_playwright() as pw:
                if self.headless:
                    browser, page = await self._launch_headless(pw)
                    if page_url:
                        await page.goto(page_url, wait_until="domcontentloaded", timeout=15000)
                        await page.wait_for_timeout(3000)
                else:
                    # S0.7 F6(b): same verbose-logging guard as card injection path.
                    _flag = _detect_risky_chrome_flags()
                    if _flag:
                        result["blocked_reason"] = f"chrome_logging_flag:{_flag}"
                        logger.error(
                            "PopBrowserInjector: refusing billing injection — target "
                            "Chrome has %s enabled.",
                            _flag,
                        )
                        return result
                    browser = await pw.chromium.connect_over_cdp(cdp_url)
                    page = self._find_best_page(browser)

                    if page is None and page_url:
                        page = await self._open_url_in_browser(browser, page_url)

                    if page is None:
                        logger.warning("PopBrowserInjector: no open pages found for billing injection.")
                        return result

                await page.bring_to_front()

                billing_result = await self._fill_billing_fields(page, billing_info)
                result["billing_filled"] = bool(billing_result["filled"])
                result["billing_details"] = billing_result

                return result

        except Exception as exc:
            logger.error("PopBrowserInjector billing injection error: %s", exc, exc_info=True)
            return result
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass

    @staticmethod 
    async def _enable_blackout(page):
        """
        Mask card fields across ALL frames (including iframes) after injection.

        Instead of a main-frame overlay (which can't cover cross-origin iframes),
        this injects CSS into every frame that hides the text content of card
        input fields using -webkit-text-security and color:transparent.

        The actual form values remain intact for submission — only the visual
        display is hidden, defeating screenshot-based exfiltration.
        """
        try:
            for frame in page.frames:
                try:
                    await frame.evaluate("""() => {
                        const style = document.createElement('style');
                        style.id = 'pop-pay-blackout';
                        style.textContent = `
                            input[autocomplete*="cc-"],
                            input[name*="card"], input[name*="Card"],
                            input[name*="expir"], input[name*="cvc"], input[name*="cvv"],
                            input[data-elements-stable-field-name],
                            input.__PrivateStripeElement,
                            input[name="cardnumber"], input[name="cc-exp"],
                            input[name="security_code"], input[name="card_number"],
                            input[name="card_expiry"], input[name="card_cvc"] {
                                -webkit-text-security: disc !important;
                                color: transparent !important;
                                text-shadow: 0 0 8px rgba(0,0,0,0.5) !important;
                            }
                        `;
                        document.head.appendChild(style);
                    }""")
                except Exception:
                    pass  # cross-origin frames may reject — that's OK
        except Exception as e:
            logger.debug("PopBrowserInjector: failed to enable blackout: %s", e)
 
    @staticmethod
    async def _find_visible_locator(frame, selectors: list):
        """
        Try each CSS selector in order; return the first match in
        the given frame, or None if nothing is found.
        (We removed is_visible() because cross-origin opacity/display rules
        in Stripe iframes sometimes cause it to falsely return False).
        """
        for selector in selectors:
            try:
                locator = frame.locator(selector).first
                count = await locator.count()
                if count > 0:
                    return locator
            except Exception:
                continue
        return None
