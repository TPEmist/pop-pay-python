"""Pytest entry — gated by POP_REDTEAM=1. Schema/smoke only; full run via run_corpus.py."""
from __future__ import annotations
import os
import asyncio
import json
from pathlib import Path

import pytest

from .aggregator import aggregate
from .runners.hybrid import run_hybrid
from .runners.layer1 import run_layer1
from .validate_corpus import load_corpus, validate_corpus

GATED = os.environ.get("POP_REDTEAM") == "1"
CORPUS = Path(__file__).parent / "corpus" / "attacks.json"


@pytest.mark.skipif(not GATED, reason="POP_REDTEAM not set")
class TestRedTeam:
    @pytest.fixture(scope="class")
    def corpus(self) -> list[dict]:
        if not CORPUS.exists():
            pytest.skip(f"corpus missing at {CORPUS}")
        return load_corpus(CORPUS)

    def test_corpus_schema(self, corpus):
        raw = json.loads(CORPUS.read_text())
        report, _ = validate_corpus(raw)
        assert report.ok, "\n".join(report.errors)

    def test_corpus_coverage(self, corpus):
        assert len(corpus) >= 500
        cats = {p["category"] for p in corpus}
        for c in "ABCDEFGHIJK":
            assert c in cats, f"category {c} missing"

    @pytest.mark.asyncio
    async def test_layer1_smoke(self, corpus):
        b = next((p for p in corpus if p["category"] == "B" and p["expected"] == "block"), None)
        if not b:
            pytest.skip("no B-class attack in corpus yet")
        r = await run_layer1(b)
        assert r["verdict"] in ("approve", "block", "error")

    @pytest.mark.asyncio
    async def test_hybrid_smoke(self, corpus):
        r = await run_hybrid(corpus[0])
        assert r["runner"] == "hybrid"

    def test_aggregator_shape(self, corpus):
        synth = [
            {
                "payload_id": p["id"],
                "category": p["category"],
                "expected": p["expected"],
                "run_index": 0,
                "layer1": {"runner": "layer1", "verdict": "block", "reason": "stub", "latency_ms": 1},
                "layer2": {"runner": "layer2", "verdict": "skip", "reason": "no LLM", "latency_ms": 0},
                "hybrid": {"runner": "hybrid", "verdict": "block", "reason": "stub", "latency_ms": 1},
                "full_mcp": {"runner": "full_mcp", "verdict": "block", "reason": "stub", "latency_ms": 1},
                "toctou": {"runner": "toctou", "verdict": "skip", "reason": "n/a", "latency_ms": 0},
                "attribution": ["layer1"],
            }
            for p in corpus[:5]
        ]
        r = aggregate(synth, "stub-hash")
        assert r["b_class"]["decision"] in {"keep", "keep-deprecated", "drop"}
