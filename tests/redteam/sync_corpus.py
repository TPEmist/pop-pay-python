"""Copy the canonical corpus from the TypeScript repo into the Python repo.

Usage:
    python tests/redteam/sync_corpus.py --from ../pop-pay-npm/tests/redteam/corpus/attacks.json
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="src", required=True, help="Path to canonical attacks.json in the TS repo")
    p.add_argument(
        "--to",
        dest="dst",
        default="tests/redteam/corpus/attacks.json",
        help="Destination inside the Python repo",
    )
    args = p.parse_args()

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    if not src.exists():
        raise SystemExit(f"Source not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    payload = json.loads(dst.read_text())
    ids_hash = hashlib.sha256(json.dumps(sorted(p["id"] for p in payload)).encode()).hexdigest()
    print(f"Synced {len(payload)} payloads. corpus_hash={ids_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
