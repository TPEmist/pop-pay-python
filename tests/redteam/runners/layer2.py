"""Layer 2 runner. Harness never reads ~/.config/pop-pay/.env; engine reads its own env."""
from __future__ import annotations
import os
import time

from pop_pay.core.models import GuardrailPolicy, PaymentIntent
from pop_pay.engine.llm_guardrails import LLMGuardrailEngine

_engine: LLMGuardrailEngine | None = None


def _llm_available() -> bool:
    return bool(os.environ.get("POP_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _get_engine() -> LLMGuardrailEngine:
    global _engine
    if _engine is None:
        _engine = LLMGuardrailEngine(
            api_key=os.environ.get("POP_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("POP_LLM_BASE_URL"),
            model=os.environ.get("POP_LLM_MODEL", "gpt-4o-mini"),
        )
    return _engine


async def run_layer2(p: dict) -> dict:
    if not _llm_available():
        return {"runner": "layer2", "verdict": "skip", "reason": "no LLM configured (requires:llm)", "latency_ms": 0}
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
        approved, reason = await _get_engine().evaluate_intent(intent, policy)
        return {
            "runner": "layer2",
            "verdict": "approve" if approved else "block",
            "reason": reason,
            "latency_ms": (time.perf_counter() - start) * 1000,
        }
    except Exception as e:
        return {
            "runner": "layer2",
            "verdict": "error",
            "reason": str(e),
            "latency_ms": (time.perf_counter() - start) * 1000,
            "error": repr(e),
        }
