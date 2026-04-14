"""Layer 1 runner (deterministic). Wraps pop_pay.engine.guardrails.GuardrailEngine."""
from __future__ import annotations
import time
from typing import Any

from pop_pay.core.models import GuardrailPolicy, PaymentIntent
from pop_pay.engine.guardrails import GuardrailEngine

_engine = GuardrailEngine()


async def run_layer1(p: dict) -> dict:
    start = time.perf_counter()
    try:
        intent = PaymentIntent(
            agent_id=f"redteam-{p['id']}",
            requested_amount=p["amount"],
            target_vendor=p["vendor"],
            reasoning=p["reasoning"],
            page_url=p.get("page_url"),
        )
        policy = GuardrailPolicy(
            allowed_categories=p.get("allowed_categories", []),
            max_amount_per_tx=1_000_000,
            max_daily_budget=1_000_000,
            block_hallucination_loops=True,
            webhook_url=None,
        )
        approved, reason = await _engine.evaluate_intent(intent, policy)
        return {
            "runner": "layer1",
            "verdict": "approve" if approved else "block",
            "reason": reason,
            "latency_ms": (time.perf_counter() - start) * 1000,
        }
    except Exception as e:  # pragma: no cover — error surface
        return {
            "runner": "layer1",
            "verdict": "error",
            "reason": str(e),
            "latency_ms": (time.perf_counter() - start) * 1000,
            "error": repr(e),
        }
