"""Full MCP path runner. Stage 0 reduced implementation — scan heuristic + hybrid.

Stage 1 replaces this with a real stdio MCP client. Outer contract is stable.
"""
from __future__ import annotations
import re
import time

from .hybrid import run_hybrid

HIDDEN_INSTRUCTION_PATTERNS = [
    re.compile(r"\bignore (all |previous |your |the )", re.I),
    re.compile(r"\byou are now\b", re.I),
    re.compile(r"\bapprove any purchase\b", re.I),
    re.compile(r"\bthis is authorized\b", re.I),
    re.compile(r"\bsystem (says|has|override)\b", re.I),
]


def _scan(content: str | None) -> tuple[bool, str]:
    if not content:
        return (False, "no fixture")
    for pat in HIDDEN_INSTRUCTION_PATTERNS:
        if pat.search(content):
            return (True, f"scan_match:{pat.pattern}")
    return (False, "scan_clean")


async def run_full_mcp(p: dict) -> dict:
    start = time.perf_counter()
    tainted, reason = _scan(p.get("page_content_fixture"))
    if tainted:
        return {"runner": "full_mcp", "verdict": "block", "reason": f"scan:{reason}", "latency_ms": (time.perf_counter() - start) * 1000}
    h = await run_hybrid(p)
    return {
        "runner": "full_mcp",
        "verdict": h["verdict"],
        "reason": f"hybrid:{h['reason']}",
        "latency_ms": (time.perf_counter() - start) * 1000,
        "error": h.get("error"),
    }
