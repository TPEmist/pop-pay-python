"""Corpus validator + deduper for the Python harness. Mirrors validate-corpus.ts.

Schema rules and thresholds match the TS version exactly; any divergence is a parity bug.
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CATEGORIES = list("ABCDEFGHIJK")
ID_RE = re.compile(r"^[A-K]-\d{4}$")


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    corpus_hash: str = ""


def _fingerprint(p: dict) -> str:
    fp = {
        "category": p.get("category"),
        "vendor": p.get("vendor"),
        "amount": p.get("amount"),
        "reasoning": p.get("reasoning"),
        "page_url": p.get("page_url"),
        "allowed_categories": sorted(p.get("allowed_categories") or []),
    }
    return hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()


def validate_corpus(raw: Any) -> tuple[ValidationReport, list[dict]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(raw, list):
        return (
            ValidationReport(ok=False, errors=["Corpus must be a JSON array"], corpus_hash=""),
            [],
        )

    seen: dict[str, str] = {}
    ids: set[str] = set()
    deduped: list[dict] = []
    per_cat: dict[str, int] = {}
    per_expected = {"block": 0, "approve": 0}
    dupes = 0

    for i, p in enumerate(raw):
        ctx = f"payload[{i}] (id={p.get('id', '?') if isinstance(p, dict) else '?'})"
        if not isinstance(p, dict):
            errors.append(f"{ctx}: not an object")
            continue
        if not ID_RE.match(p.get("id", "")):
            errors.append(f"{ctx}: id must match [A-K]-NNNN")
        if p.get("category") not in CATEGORIES:
            errors.append(f"{ctx}: invalid category {p.get('category')}")
        vendor = p.get("vendor")
        expected = p.get("expected")
        if not isinstance(vendor, str):
            errors.append(f"{ctx}: vendor must be string")
        elif expected == "approve" and (not vendor or len(vendor) > 200):
            errors.append(f"{ctx}: benign vendor missing or >200 chars")
        elif len(vendor) > 4000:
            errors.append(f"{ctx}: vendor >4000 chars (runaway)")
        amount = p.get("amount")
        if not isinstance(amount, (int, float)) or (isinstance(amount, float) and amount != amount):
            errors.append(f"{ctx}: amount must be number")
        elif expected == "approve" and amount <= 0:
            errors.append(f"{ctx}: benign amount must be positive")
        reasoning = p.get("reasoning")
        if not isinstance(reasoning, str):
            errors.append(f"{ctx}: reasoning must be string")
        elif len(reasoning) > 4000:
            errors.append(f"{ctx}: reasoning >4000 chars (runaway)")
        if not isinstance(p.get("allowed_categories"), list):
            errors.append(f"{ctx}: allowed_categories must be array")
        if p.get("expected") not in ("block", "approve"):
            errors.append(f"{ctx}: expected must be block|approve")
        if not isinstance(p.get("variant_tags"), list):
            errors.append(f"{ctx}: variant_tags must be array")

        pid = p.get("id")
        if pid and pid in ids:
            errors.append(f"{ctx}: duplicate id")
        if pid:
            ids.add(pid)

        fp = _fingerprint(p)
        if fp in seen:
            dupes += 1
            warnings.append(f"{ctx}: semantic duplicate of {seen[fp]}")
            continue
        seen[fp] = pid or ""
        deduped.append(p)

        cat = p.get("category")
        if cat:
            per_cat[cat] = per_cat.get(cat, 0) + 1
        exp = p.get("expected")
        if exp in per_expected:
            per_expected[exp] += 1

    for cat in CATEGORIES:
        n = per_cat.get(cat, 0)
        if n < 5:
            warnings.append(f"Category {cat} has only {n} payloads (target >=5)")

    b_attack = sum(1 for p in deduped if p.get("category") == "B" and p.get("expected") == "block")
    b_benign = sum(1 for p in deduped if p.get("category") == "B" and p.get("expected") == "approve")
    if b_attack > 0 and b_benign < max(25, b_attack // 3):
        warnings.append(f"Category B benign {b_benign} below floor (need max(25, attacks/3))")

    corpus_hash = hashlib.sha256(json.dumps(sorted(p["id"] for p in deduped)).encode()).hexdigest()

    return (
        ValidationReport(
            ok=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            stats={
                "total": len(deduped),
                "per_category": per_cat,
                "per_expected": per_expected,
                "duplicates_removed": dupes,
            },
            corpus_hash=corpus_hash,
        ),
        deduped,
    )


def load_corpus(path: str | Path) -> list[dict]:
    raw = json.loads(Path(path).read_text())
    report, deduped = validate_corpus(raw)
    if not report.ok:
        raise SystemExit("Corpus validation failed:\n" + "\n".join(report.errors))
    for w in report.warnings:
        print(f"[corpus-warning] {w}", file=sys.stderr)
    return deduped


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "tests/redteam/corpus/attacks.json"
    raw = json.loads(Path(path).read_text())
    report, _ = validate_corpus(raw)
    print(json.dumps(report.__dict__, indent=2, default=str))
    sys.exit(0 if report.ok else 1)
