# RT-1 Red Team Harness (Python parity)

Mirror of `pop-pay-npm/tests/redteam/`. Same corpus, same metrics shape, thin Python runners.

## Corpus source

The canonical corpus lives in the TypeScript repo: `pop-pay-npm/tests/redteam/corpus/attacks.json`.

The Python harness expects a local copy at `tests/redteam/corpus/attacks.json`. Keep it in sync via:

```bash
python tests/redteam/sync_corpus.py --from ../pop-pay-npm/tests/redteam/corpus/attacks.json
```

Corpus hash is recorded at the top of each JSONL artifact; a parity-regression alert fires if hashes differ between the two repos on the same run.

## Running

```bash
# Full corpus, Layer 1 only (no LLM)
POP_REDTEAM=1 pytest tests/redteam -v

# Full corpus + all 5 paths
export POP_LLM_API_KEY=sk-...
export POP_LLM_MODEL=gpt-4o-mini-2024-07-18
POP_REDTEAM=1 python -m tests.redteam.run_corpus --n 5 --concurrency 20

# B-class only (S1.1 input)
POP_REDTEAM=1 python -m tests.redteam.run_corpus --filter B
```

**Does NOT read `~/.config/pop-pay/.env`.** Same rule as TS.

## Parity contract

- Same corpus hash
- Same aggregator output shape (see `aggregator.py`)
- Same B-class decision thresholds (per `docs/CATEGORIES_DECISION_CRITERIA.md`)
- Bypass rate drift >5pp between TS and Python on the same corpus = parity regression → head-of-eng
