"""TOCTOU runner — reuses _verify_domain_toctou from pop_pay.injector.

Only C / H / layer_target=toctou payloads exercise this; others return skip.
"""
from __future__ import annotations
import time

from pop_pay.injector import PopBrowserInjector as Injector


async def run_toctou(p: dict) -> dict:
    relevant = p.get("category") in ("C", "H") or p.get("layer_target") == "toctou"
    if not relevant:
        return {"runner": "toctou", "verdict": "skip", "reason": "not a toctou-class payload", "latency_ms": 0}
    page_url = p.get("page_url")
    if not page_url:
        return {"runner": "toctou", "verdict": "skip", "reason": "no page_url", "latency_ms": 0}
    start = time.perf_counter()
    try:
        result = Injector._verify_domain_toctou(page_url, p["vendor"])  # staticmethod
        return {
            "runner": "toctou",
            "verdict": "approve" if result is None else "block",
            "reason": result or "domain_ok",
            "latency_ms": (time.perf_counter() - start) * 1000,
        }
    except Exception as e:
        return {
            "runner": "toctou",
            "verdict": "error",
            "reason": str(e),
            "latency_ms": (time.perf_counter() - start) * 1000,
            "error": repr(e),
        }
