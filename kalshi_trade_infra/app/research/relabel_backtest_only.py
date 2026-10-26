"""One-time, idempotent relabel of legacy 'passed' strategies.

Before 'passed' was made a strict full-pipeline outcome, the loose adjust path and older code
wrote status='passed' on strategies that never went through pre-registration or the Statistical
Gatekeeper, so they carry NO experiment at all. This reclassifies exactly those rows as the
non-deployable 'backtest-only', so 'passed' means only a validated, gatekeeper-cleared outcome.

Relabel only — no deletes, fully reversible (set the status back). Idempotent: once no such row
remains, a re-run changes nothing. It touches ONLY rows that have neither a stored experiment_id
nor any legacy strategy_id-linked experiment, so a genuinely validated 'passed' is never flipped
even if its experiment_id column was never backfilled.

NOT auto-run and NOT part of init_schema. Run it manually on the box after review:

    python -m app.research.relabel_backtest_only
"""
from __future__ import annotations


def relabel_legacy_passed(cur) -> int:
    """Flip every un-validated 'passed' row (no linked experiment, either way) to 'backtest-only'.
    Returns the number of rows relabelled. Takes a cursor so it is testable against FakeCursor."""
    cur.execute(
        "UPDATE app_strategies s SET s.status='backtest-only' "
        "WHERE s.status='passed' AND s.experiment_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM app_experiments e WHERE e.strategy_id=s.id)"
    )
    return cur.rowcount


def main() -> None:
    from data_pipeline.common import get_db_conn  # local: keeps the function import-light + testable

    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            n = relabel_legacy_passed(cur)
        conn.commit()
        print("Relabelled %d legacy 'passed' strategy row(s) to 'backtest-only'." % n)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
