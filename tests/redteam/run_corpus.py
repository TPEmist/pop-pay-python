"""Corpus runner — Python parity. Writes tests/redteam/runs/<ts>.jsonl.

Usage:
    POP_REDTEAM=1 python -m tests.redteam.run_corpus [--filter B] [--n 5] [--concurrency 20]
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .aggregator import aggregate
from .runners.full_mcp import run_full_mcp
from .runners.hybrid import run_hybrid
from .runners.layer1 import run_layer1
from .runners.layer2 import run_layer2
from .runners.toctou import run_toctou
from .validate_corpus import load_corpus


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


async def _run_one(p: dict, idx: int) -> dict:
    l1, l2, hy, fm, tc = await asyncio.gather(
        run_layer1(p), run_layer2(p), run_hybrid(p), run_full_mcp(p), run_toctou(p)
    )
    attribution = []
    if l1["verdict"] == "block":
        attribution.append("layer1")
    if l2["verdict"] == "block":
        attribution.append("layer2")
    if fm["verdict"] == "block" and fm["reason"].startswith("scan:"):
        attribution.append("scan")
    if tc["verdict"] == "block":
        attribution.append("toctou")
    return {
        "payload_id": p["id"],
        "category": p["category"],
        "expected": p["expected"],
        "run_index": idx,
        "layer1": l1,
        "layer2": l2,
        "hybrid": hy,
        "full_mcp": fm,
        "toctou": tc,
        "attribution": attribution,
    }


async def _run(opts) -> None:
    corpus = load_corpus(opts.corpus)
    filtered = [p for p in corpus if not opts.filter or p["category"] == opts.filter]
    if not filtered:
        raise SystemExit(f"No payloads after filter={opts.filter}")

    raw = json.loads(Path(opts.corpus).read_text())
    corpus_hash = hashlib.sha256(json.dumps(sorted(p["id"] for p in raw)).encode()).hexdigest()

    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    out_path = out_dir / (f"{stamp}{'-' + opts.filter if opts.filter else ''}.jsonl")

    header = {
        "type": "header",
        "corpus_hash": corpus_hash,
        "corpus_size": len(filtered),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "model": os.environ.get("POP_LLM_MODEL"),
        "n_runs_per_payload": opts.n,
    }

    sem = asyncio.Semaphore(opts.concurrency)
    rows: list[dict] = []

    async def _bound(p: dict, idx: int) -> dict:
        async with sem:
            return await _run_one(p, idx)

    tasks = [_bound(p, i) for i in range(opts.n) for p in filtered]
    total = len(tasks)

    with out_path.open("w") as fh:
        fh.write(json.dumps(header) + "\n")
        done = 0
        for coro in asyncio.as_completed(tasks):
            row = await coro
            rows.append(row)
            fh.write(json.dumps({"type": "row", **row}) + "\n")
            done += 1
            if done % 50 == 0:
                print(f"[redteam] {done}/{total}", file=sys.stderr)

        report = aggregate(rows, corpus_hash)
        fh.write(json.dumps({"type": "report", **report}) + "\n")

    print(f"[redteam] wrote {out_path}", file=sys.stderr)
    print(json.dumps(report, indent=2, default=str))


def main() -> int:
    if os.environ.get("POP_REDTEAM") != "1":
        print("POP_REDTEAM=1 required. Refusing to run.", file=sys.stderr)
        return 2
    p = argparse.ArgumentParser()
    p.add_argument("--filter", default=None, help="Restrict to a single category letter")
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--concurrency", type=int, default=int(os.environ.get("POP_REDTEAM_CONCURRENCY", "20")))
    p.add_argument("--corpus", default="tests/redteam/corpus/attacks.json")
    p.add_argument("--out-dir", default="tests/redteam/runs")
    asyncio.run(_run(p.parse_args()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
