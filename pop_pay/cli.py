"""pop-launch: Launch Chrome with CDP + optional Playwright MCP setup."""

from __future__ import annotations

import argparse
import pathlib
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _find_chrome() -> str | None:
    """Return the first available Chrome/Chromium executable path, or None."""
    system = platform.system()

    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for path in candidates:
            if pathlib.Path(path).exists():
                return path

    elif system == "Linux":
        import shutil

        candidates = [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ]
        for name in candidates:
            found = shutil.which(name)
            if found:
                return found

    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for path in candidates:
            if pathlib.Path(path).exists():
                return path

    return None


def _wait_for_chrome(port: int, timeout: float = 10.0) -> dict | None:
    """Poll the CDP /json/version endpoint until Chrome is ready.

    Returns the parsed JSON dict on success, or None on timeout.
    """
    url = f"http://localhost:{port}/json/version"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                import json

                return json.loads(resp.read())
        except Exception:
            time.sleep(0.5)
    return None


def _print_mcp_instructions(port: int) -> None:
    """Print the claude mcp add commands the user needs to run."""
    cdp_endpoint = f"http://localhost:{port}"
    print()
    print("Point One Percent is ready. Add it to Claude Code with:")
    print()
    print(
        f"  claude mcp add pop-pay -- {sys.executable} -m pop_pay.mcp_server"
    )
    print(
        f"  claude mcp add playwright -- npx @playwright/mcp@latest --cdp-endpoint {cdp_endpoint}"
    )
    print()
    print("Then start Claude Code and you're set.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pop-launch",
        description="Launch Chrome with CDP remote debugging for Point One Percent / Playwright MCP.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9222,
        help="Chrome remote debugging port (default: 9222)",
    )
    parser.add_argument(
        "--profile-dir",
        type=pathlib.Path,
        default=pathlib.Path("~/.pop/chrome-profile"),
        help="Chrome user-data-dir (default: ~/.pop/chrome-profile)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Optional URL to open in Chrome on launch",
    )
    parser.add_argument(
        "--print-mcp",
        action="store_true",
        help="After Chrome is ready, print the claude mcp add commands to run",
    )

    args = parser.parse_args(argv)

    # Resolve profile directory (expand ~)
    profile_dir: pathlib.Path = args.profile_dir.expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    chrome = _find_chrome()
    if chrome is None:
        print(
            "ERROR: Could not find Chrome or Chromium. "
            "Please install Google Chrome and try again.",
            file=sys.stderr,
        )
        return 1

    cmd = [
        chrome,
        f"--remote-debugging-port={args.port}",
        f"--user-data-dir={profile_dir}",
    ]
    if args.url:
        cmd.append(args.url)

    print(f"Launching Chrome: {chrome}")
    print(f"  --remote-debugging-port={args.port}")
    print(f"  --user-data-dir={profile_dir}")
    if args.url:
        print(f"  Opening URL: {args.url}")

    # Launch Chrome as a detached background process
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    print(f"\nWaiting for Chrome to be ready on port {args.port}...")
    info = _wait_for_chrome(args.port)
    if info is None:
        print(
            f"ERROR: Chrome did not become ready within 10 seconds on port {args.port}.",
            file=sys.stderr,
        )
        return 1

    browser_version = info.get("Browser", "unknown")
    print(f"Chrome is ready. Browser: {browser_version}")

    if args.print_mcp:
        _print_mcp_instructions(args.port)

    return 0


if __name__ == "__main__":
    sys.exit(main())
