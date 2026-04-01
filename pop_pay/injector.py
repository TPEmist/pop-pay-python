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

    def __init__(self, state_tracker: PopStateTracker):
        self.state_tracker = state_tracker

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
        result = {"card_filled": False, "billing_filled": False, "blocked_reason": ""}

        # TOCTOU guard: verify the current page domain matches the approved vendor
        # Uses KNOWN_VENDOR_DOMAINS suffix matching (same as guardrail layer 1) to
        # prevent subdomain-spoofing bypasses like "wikipedia.attacker.com".
        if page_url and approved_vendor:
            from urllib.parse import urlparse
            import re
            from pop_pay.engine.guardrails import KNOWN_VENDOR_DOMAINS
            actual_domain = urlparse(page_url).netloc.lower().removeprefix("www.")
            vendor_lower = approved_vendor.lower()
            vendor_tokens = set(re.split(r'[\s\-_./]+', vendor_lower)) - {''}

            domain_ok = False
            vendor_is_known = False
            # First: check against KNOWN_VENDOR_DOMAINS using strict suffix matching.
            # A known vendor MUST match a registered known domain — the fallback is
            # skipped, so "wikipedia.attacker.com" never satisfies vendor="wikipedia".
            for known_vendor, known_domains in KNOWN_VENDOR_DOMAINS.items():
                if known_vendor in vendor_tokens or known_vendor == vendor_lower:
                    vendor_is_known = True
                    if any(actual_domain == d or actual_domain.endswith("." + d)
                           for d in known_domains):
                        domain_ok = True
                    break
            # Fallback ONLY for vendors absent from KNOWN_VENDOR_DOMAINS.
            # Checks vendor token against complete domain labels (split on "." only,
            # not hyphens) to prevent "not-github.io" matching vendor "github".
            if not domain_ok and not vendor_is_known:
                _common_tlds = {'com', 'org', 'net', 'io', 'co', 'uk', 'jp', 'de', 'fr'}
                domain_labels = set(actual_domain.split(".")) - _common_tlds
                domain_ok = bool(vendor_tokens.intersection(domain_labels))

            if not domain_ok:
                logger.warning(
                    "PopBrowserInjector: TOCTOU domain mismatch — "
                    "approved vendor '%s' does not match current page domain '%s'. "
                    "Injection blocked.",
                    approved_vendor, actual_domain,
                )
                result["blocked_reason"] = f"domain_mismatch:{actual_domain}"
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
            "first_name": os.getenv("POP_BILLING_FIRST_NAME", "").strip(),
            "last_name":  os.getenv("POP_BILLING_LAST_NAME", "").strip(),
            "street":     os.getenv("POP_BILLING_STREET", "").strip(),
            "zip":        os.getenv("POP_BILLING_ZIP", "").strip(),
            "email":      os.getenv("POP_BILLING_EMAIL", "").strip(),
            "phone":      os.getenv("POP_BILLING_PHONE", "").strip(),
        }
        has_billing = any(billing_info.values())

        browser = None
        try:
            async with async_playwright() as pw:
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

                result["card_filled"] = await self._fill_across_frames(
                    page, card_number, expiry, cvv
                )

                if has_billing:
                    result["billing_filled"] = await self._fill_billing_fields(
                        page, billing_info
                    )

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

        return card_filled

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

    async def _fill_billing_fields(self, page, billing_info: dict) -> bool:
        """
        Fill billing detail fields (name, address, email) in the main page frame.
        These fields are standard DOM inputs — NOT inside Stripe iframes.

        Each field is attempted independently; missing selectors are silently skipped.
        Returns True if at least one billing field was successfully filled.
        """
        main_frame = page.main_frame
        any_filled = False

        first_name = billing_info.get("first_name", "")
        last_name  = billing_info.get("last_name", "")
        street     = billing_info.get("street", "")
        zip_code   = billing_info.get("zip", "")
        email      = billing_info.get("email", "")
        phone      = billing_info.get("phone", "")

        # First name
        if first_name:
            locator = await self._find_visible_locator(main_frame, FIRST_NAME_SELECTORS)
            if locator:
                try:
                    await locator.fill(first_name)
                    logger.info("PopBrowserInjector: first name injected.")
                    any_filled = True
                except Exception as exc:
                    logger.debug("PopBrowserInjector: could not fill first name: %s", exc)

        # Last name
        if last_name:
            locator = await self._find_visible_locator(main_frame, LAST_NAME_SELECTORS)
            if locator:
                try:
                    await locator.fill(last_name)
                    logger.info("PopBrowserInjector: last name injected.")
                    any_filled = True
                except Exception as exc:
                    logger.debug("PopBrowserInjector: could not fill last name: %s", exc)

        # Full name fallback — only used when first+last name fields are absent
        # but a combined "name" field exists on the page
        if first_name or last_name:
            full_name = " ".join(filter(None, [first_name, last_name])).strip()
            if full_name:
                locator = await self._find_visible_locator(main_frame, FULL_NAME_SELECTORS)
                if locator:
                    try:
                        await locator.fill(full_name)
                        logger.info("PopBrowserInjector: full name injected.")
                        any_filled = True
                    except Exception as exc:
                        logger.debug(
                            "PopBrowserInjector: could not fill full name: %s", exc
                        )

        # Street address
        if street:
            locator = await self._find_visible_locator(main_frame, STREET_SELECTORS)
            if locator:
                try:
                    await locator.fill(street)
                    logger.info("PopBrowserInjector: street address injected.")
                    any_filled = True
                except Exception as exc:
                    logger.debug(
                        "PopBrowserInjector: could not fill street address: %s", exc
                    )

        # Zip / postal code
        if zip_code:
            locator = await self._find_visible_locator(main_frame, ZIP_SELECTORS)
            if locator:
                try:
                    await locator.fill(zip_code)
                    logger.info("PopBrowserInjector: zip code injected.")
                    any_filled = True
                except Exception as exc:
                    logger.debug("PopBrowserInjector: could not fill zip code: %s", exc)

        # Email
        if email:
            locator = await self._find_visible_locator(main_frame, EMAIL_SELECTORS)
            if locator:
                try:
                    await locator.fill(email)
                    logger.info("PopBrowserInjector: email injected.")
                    any_filled = True
                except Exception as exc:
                    logger.debug("PopBrowserInjector: could not fill email: %s", exc)

        # Phone (E.164 format, e.g. +14155551234)
        if phone:
            locator = await self._find_visible_locator(main_frame, PHONE_SELECTORS)
            if locator:
                try:
                    await locator.fill(phone)
                    logger.info("PopBrowserInjector: phone injected.")
                    any_filled = True
                except Exception as exc:
                    logger.debug("PopBrowserInjector: could not fill phone: %s", exc)

        return any_filled

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

        # TOCTOU guard — same logic as inject_payment_info
        if page_url and approved_vendor:
            from urllib.parse import urlparse
            import re
            from pop_pay.engine.guardrails import KNOWN_VENDOR_DOMAINS
            actual_domain = urlparse(page_url).netloc.lower().removeprefix("www.")
            vendor_lower = approved_vendor.lower()
            vendor_tokens = set(re.split(r'[\s\-_./]+', vendor_lower)) - {''}

            domain_ok = False
            vendor_is_known = False
            for known_vendor, known_domains in KNOWN_VENDOR_DOMAINS.items():
                if known_vendor in vendor_tokens or known_vendor == vendor_lower:
                    vendor_is_known = True
                    if any(actual_domain == d or actual_domain.endswith("." + d)
                           for d in known_domains):
                        domain_ok = True
                    break
            if not domain_ok and not vendor_is_known:
                _common_tlds = {'com', 'org', 'net', 'io', 'co', 'uk', 'jp', 'de', 'fr'}
                domain_labels = set(actual_domain.split(".")) - _common_tlds
                domain_ok = bool(vendor_tokens.intersection(domain_labels))

            if not domain_ok:
                logger.warning(
                    "PopBrowserInjector: TOCTOU domain mismatch (billing) — "
                    "approved vendor '%s' does not match current page domain '%s'.",
                    approved_vendor, actual_domain,
                )
                result["blocked_reason"] = f"domain_mismatch:{actual_domain}"
                return result

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright is not installed.")
            return result

        billing_info = {
            "first_name": os.getenv("POP_BILLING_FIRST_NAME", "").strip(),
            "last_name":  os.getenv("POP_BILLING_LAST_NAME", "").strip(),
            "street":     os.getenv("POP_BILLING_STREET", "").strip(),
            "zip":        os.getenv("POP_BILLING_ZIP", "").strip(),
            "email":      os.getenv("POP_BILLING_EMAIL", "").strip(),
            "phone":      os.getenv("POP_BILLING_PHONE", "").strip(),
        }

        browser = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(cdp_url)
                page = self._find_best_page(browser)

                if page is None and page_url:
                    page = await self._open_url_in_browser(browser, page_url)

                if page is None:
                    logger.warning("PopBrowserInjector: no open pages found for billing injection.")
                    return result

                await page.bring_to_front()
                result["billing_filled"] = await self._fill_billing_fields(page, billing_info)
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
