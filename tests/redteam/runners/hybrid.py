"""Hybrid runner — Layer1 short-circuits on block; else fall through to Layer2."""
from __future__ import annotations
import time

from .layer1 import run_layer1
from .layer2 import run_layer2


async def run_hybrid(p: dict) -> dict:
    start = time.perf_counter()
    l1 = await run_layer1(p)
    if l1["verdict"] == "block":
        return {"runner": "hybrid", "verdict": "block", "reason": f"layer1:{l1['reason']}", "latency_ms": (time.perf_counter() - start) * 1000}
    if l1["verdict"] == "error":
        return {"runner": "hybrid", "verdict": "error", "reason": f"layer1_error:{l1['reason']}", "latency_ms": (time.perf_counter() - start) * 1000, "error": l1.get("error")}
    l2 = await run_layer2(p)
    return {"runner": "hybrid", "verdict": l2["verdict"], "reason": f"layer2:{l2['reason']}", "latency_ms": (time.perf_counter() - start) * 1000, "error": l2.get("error")}
