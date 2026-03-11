## Research

- Extend the expiry-resolution research window beyond the current ~4 day sample so model selection is not dominated by one short regime.
- Add contract-level outcome labels directly from market settlement or final bucket resolution instead of proxying with terminal YES bids.
- Test calibration layers on top of the boosted and random-forest candidates so `p_yes - ask` is a cleaner edge signal.

## Execution

- Replace the current take-profit-or-final-bid proxy with a richer execution simulator that handles partial fills, queue position, and stop-loss/timeout exits.
- Add a capital allocator so overlapping candidate trades compete for limited bankroll instead of using a single-position heuristic.
- Track per-trade max adverse excursion and max favorable excursion to tune exits with real path information.

## Infrastructure

- Rebuild the checked-in virtualenv workflow; the current repo-local `venv` points at a missing Python 3.12 interpreter.
- Add a preflight command that verifies API auth, dashboard connectivity, and MySQL env before any long-running pipeline process starts.
- Separate runtime requirements from research/test requirements so client/dashboard/research dependencies stay explicit.

## Deployment

- Promote a research model into `live_trading_engine.py` only after it stays positive under corrected out-of-sample execution assumptions.
- Persist trained model artifacts and validation rules so live runs are frozen to a specific research snapshot.
- Add live monitoring for probability drift, edge drift, and hit-rate decay after deployment.
