# CATEGORIES Decision Criteria

> Mirror of the canonical document in `pop-pay-npm/docs/CATEGORIES_DECISION_CRITERIA.md`.
> Kept in sync per `feedback_publish_both_repos.md` — both repos bump/tag/publish in lockstep.

See [the canonical document](https://github.com/100xPercent/pop-pay/blob/main/docs/CATEGORIES_DECISION_CRITERIA.md) for the authoritative version. The thresholds and process are identical for both the TypeScript and Python engines. Category B numbers from the Python harness MUST match the TypeScript harness within LLM variance tolerance (p95 drift ≤ 5 percentage points, else parity regression).

## Summary of thresholds (non-authoritative)

| Decision | Criteria |
|---|---|
| **Keep** | bypass ≤ 15% AND false-reject ≤ 10% |
| **Keep-but-deprecated** | bypass in (15%, 50%) OR false-reject in (10%, 25%) |
| **Drop** | bypass ≥ 50% OR false-reject ≥ 25% |

Fixed at 2026-04-14 pre-run, no post-hoc moves.
