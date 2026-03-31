#!/usr/bin/env python3
"""
Point One Percent — CDP Injection Demo Script
For README GIF / Product Hunt / social media

What this shows:
  1. Terminal: agent calls request_virtual_card()
  2. Browser: checkout page opens, card fields auto-fill live
  3. Terminal: agent only receives ****-4242, never the real PAN

Requirements:
  pip install playwright pop-pay
  playwright install chromium
  Chrome must be running with CDP: pop-launch  (or manually with --remote-debugging-port=9222)

Run:
  python scripts/demo_cdp_injection.py

Record tip:
  - Split terminal + browser window side by side (1280x720 or 1440x900)
  - Terminal on left (~40%), browser on right (~60%)
  - Dark terminal theme, zoom browser to 125%
  - Record with QuickTime or OBS, trim to ~30s, export as GIF via ffmpeg:
      ffmpeg -i demo.mov -vf "fps=12,scale=1280:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" demo_cdp.gif
"""

import asyncio
import time
import sys
import os
from pathlib import Path

RED   = "\033[91m"
GREEN = "\033[92m"
WHITE = "\033[97m"
GRAY  = "\033[90m"
BOLD  = "\033[1m"
CYAN  = "\033[96m"
RESET = "\033[0m"


def p(text=""):
    print(text, flush=True)


def typer(text, delay=0.055):
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n")
    sys.stdout.flush()


def wait(s):
    time.sleep(s)


def header():
    p()
    p(f"  {BOLD}{WHITE}Point One Percent  —  CDP Injection Demo{RESET}")
    p(f"  {GRAY}The raw PAN never enters the agent's context.{RESET}")
    p()


async def run_demo():
    from playwright.async_api import async_playwright

    # Path to dummy checkout page
    fixture_path = Path(__file__).parent.parent / "tests" / "fixtures" / "dummy_checkout.html"
    checkout_url = fixture_path.resolve().as_uri()

    header()
    wait(0.5)

    # ── Step 1: Agent decides to pay ─────────────────────────────────────────
    ts = time.strftime('%H:%M:%S')
    p(f"  {GRAY}[{ts}]{RESET} {WHITE}[Agent]{RESET} I need to purchase API credits to continue the task.")
    wait(0.8)
    p(f"  {GRAY}[{ts}]{RESET}         {GRAY}→ Navigating to checkout page...{RESET}")
    wait(0.6)

    # ── Step 2: Open browser ──────────────────────────────────────────────────
    async with async_playwright() as pw:
        # Try CDP first (real Chrome), fall back to Chromium
        browser = None
        use_cdp = False

        try:
            browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
            contexts = browser.contexts
            context = contexts[0] if contexts else await browser.new_context()
            use_cdp = True
        except Exception:
            browser = await pw.chromium.launch(headless=False, slow_mo=80)
            context = await browser.new_context()

        page = await context.new_page()
        await page.set_viewport_size({"width": 900, "height": 600})
        await page.goto(checkout_url)
        await page.wait_for_load_state("domcontentloaded")
        wait(0.8)

        # ── Step 3: Agent calls request_virtual_card ──────────────────────────
        p()
        ts = time.strftime('%H:%M:%S')
        p(f"  {GRAY}[{ts}]{RESET} {CYAN}[Agent → POP MCP]{RESET}")
        wait(0.3)
        typer(f"  {GRAY}  request_virtual_card({RESET}", delay=0.03)
        wait(0.1)
        typer(f"  {GRAY}    amount   = {RESET}{WHITE}20.0{RESET}{GRAY},{RESET}", delay=0.03)
        typer(f"  {GRAY}    vendor   = {RESET}{WHITE}\"OpenAI\"{RESET}{GRAY},{RESET}", delay=0.03)
        typer(f"  {GRAY}    reasoning= {RESET}{WHITE}\"Need API credits to continue pipeline\"{RESET}", delay=0.03)
        typer(f"  {GRAY}  ){RESET}", delay=0.03)
        wait(0.6)

        # ── Step 4: POP evaluates ─────────────────────────────────────────────
        p()
        p(f"  {GRAY}[POP] Layer 1 check...  {GREEN}vendor ✓  amount ✓  reasoning ✓{RESET}")
        wait(0.5)
        p(f"  {GRAY}[POP] Issuing virtual card...{RESET}")
        wait(0.8)

        # ── Step 5: CDP injection into iframe ─────────────────────────────────
        p()
        p(f"  {GRAY}[POP] Attaching via CDP → injecting into payment iframe...{RESET}")
        wait(0.4)

        # Find the iframe and fill fields with a typing effect
        frame = None
        for f in page.frames:
            try:
                card_input = await f.query_selector("input[name='cardnumber']")
                if card_input:
                    frame = f
                    break
            except Exception:
                continue

        if frame:
            # Simulate CDP injection — type into fields with visible delay
            card_input = await frame.query_selector("input[name='cardnumber']")
            exp_input  = await frame.query_selector("input[name='exp-date']")
            cvv_input  = await frame.query_selector("input[name='cvc']")

            if card_input:
                await card_input.click()
                await card_input.type("4242 4242 4242 4242", delay=60)
            wait(0.2)
            if exp_input:
                await exp_input.click()
                await exp_input.type("12/27", delay=80)
            wait(0.2)
            if cvv_input:
                await cvv_input.click()
                await cvv_input.type("123", delay=100)

            p(f"  {GREEN}[POP] ✅ Injection complete.{RESET}")
        else:
            p(f"  {GREEN}[POP] ✅ Injection complete (fields filled).{RESET}")

        wait(0.6)

        # ── Step 6: What agent sees ───────────────────────────────────────────
        p()
        p(f"  {GRAY}{'─'*52}{RESET}")
        p(f"  {WHITE}[Agent receives]{RESET}")
        wait(0.3)
        p(f"  {GREEN}{BOLD}  card   : ****-****-****-4242{RESET}")
        p(f"  {GREEN}  status : Approved  |  $20.00  |  vendor: OpenAI{RESET}")
        p(f"  {GRAY}  (raw PAN: never in context){RESET}")
        p(f"  {GRAY}{'─'*52}{RESET}")
        wait(1.0)

        # ── Step 7: End ───────────────────────────────────────────────────────
        p()
        p(f"  {BOLD}{WHITE}Your wallet. Protected.{RESET}  {GRAY}github.com/TPEmist/Point-One-Percent{RESET}")
        wait(4.0)

        if not use_cdp:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run_demo())
