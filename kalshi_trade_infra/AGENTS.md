# Repository Guidelines

## Project Structure & Module Organization
This repository is a Kalshi BTC 15-minute trading pipeline: ingestion, feature engineering,
simulated + live trading engines, and a dashboard. See `PLAN.md` for current architecture
details and status - it is kept up to date every session.
- `data_pipeline/`: the actual system (collectors, feature builder, sim/live trading engines,
  `dashboard_server.py`, `common.py` for shared DB/auth helpers, `architecture/` for the
  live-trading risk/execution abstractions).
- `client_api/`: pandas DataFrame client for pulling historical data from the dashboard's
  `/api/table` endpoint (used for research, not the live pipeline itself).
- `tests/`: pytest suite using a `FakeCursor` fixture (see `tests/conftest.py`) so engine/risk
  logic is testable without a live database.
- `credentials/`: key material location (do not commit secrets).
- `scripts/`: AWS provisioning/deploy helpers (RDS, EC2).
- `requirements.txt`: pinned runtime + test dependencies.
- `venv/`/`.venv/`: local virtualenvs, gitignored (do not track changes here).

## Build, Test, and Development Commands
Use Python 3.12+ with a virtual environment.
- `python -m venv venv && source venv/bin/activate`: create/activate local env.
- `pip install -r requirements.txt`: install dependencies.
- `python -m data_pipeline.init_schema`: create/migrate the DB schema.
- `python -m pytest tests/`: run the test suite (no live DB required).
- `python -m py_compile data_pipeline/*.py`: quick syntax check.

## Coding Style & Naming Conventions
- Follow PEP 8, 4-space indentation, and explicit type hints for public methods.
- Use `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Keep functions focused; prefer explicit control flow over compact but opaque expressions.
- Keep DB access in the relevant `*_repository.py`/`common.py` layer, not inline in business logic
  (see `sim_repository.py` for the established pattern) - it's what makes engine/risk logic
  testable without a live database.

## Testing Guidelines
- Add unit tests under `tests/` using `pytest` when adding non-trivial logic.
- Name files `test_<module>.py` and cases `test_<behavior>`.
- Prefer testing against a `FakeCursor` (extend the pattern in `tests/conftest.py`) over a live
  DB connection - that's the point of the repository-layer extraction.
- For dashboard/API changes, include at least one happy-path and one error-path test.

## Commit & Pull Request Guidelines
Use Conventional Commit style:
- `feat: add market data polling helper`
- `fix: handle websocket reconnect on ssl error`

PRs should include:
- concise summary of behavior changes,
- risk notes (auth, order placement, rate limit impact),
- validation evidence (commands run, sample output),
- linked issue/task when applicable.

## Security & Configuration Tips
- `.env.aws` holds DB credentials and AWS profile/region for the deployed pipeline; `common.py`
  reads Kalshi API key material via `PROD_KEYID`/`PROD_KEYFILE` (or `KALSHI_WS_KEY_ID`/
  `KALSHI_WS_PRIVATE_KEY_PATH`) and the dashboard's basic-auth/live-trading-gate passwords via
  `DASHBOARD_PASSWORD`/`LIVE_TRADING_PASSWORD`.
- Never commit `.env*`, private keys, or raw account/order responses containing sensitive data
  (`.gitignore` already excludes these).
- `live_trading_engine.py` places real orders when `live_settings.live_enabled=true` - never flip
  that on, or make changes that could effectively do so, without explicit, separate authorization.

## Agent-Specific Operating Principles
These instructions apply to contributors and coding agents working on strategies and platform features.

### Architecture & Change Management
- For new trading strategies or features, optimize for clear architecture, extension points, and future change.
- Design with likely changes in mind (new data sources, strategy variants, execution logic, risk constraints).
- Prefer minimal, intentional abstractions over speculative framework building.

### Decision Process & Collaboration
- For each issue or recommendation, state concrete tradeoffs.
- Provide an opinionated recommendation, not just options.
- Ask for input before committing to a direction when multiple reasonable approaches exist.

### Trading Strategy Expectations
- Operate with a hedge-fund mindset: alpha durability, risk-adjusted returns, drawdown control, tuning, and rebalancing discipline.
- If required data is missing, proactively propose practical data-acquisition paths and identify what support is needed from the repo owner.
- After implementing a strategy, include comprehensive strategy documentation. Prefer diagrams/graphs to explain architecture and signal flow.

### PLAN
- On every turn of response, put your most up to date knowledge about the codebase, architecture design, and action plans in PLAN.md.

### TODO list
- Always keep the running todo list current. It lives in the **`## TODO / Working Queue`**
  section of `../mvp.md` (the old `requested_queue.md` was merged into it). Add any new
  requested-but-unshipped work there, and remove each line the moment it ships. `[blocked]`
  marks work that needs a user/AWS action first.

### Engineering Standards
- Enforce DRY aggressively; flag duplication early.
- Keep code "engineered enough": avoid both fragile hacks and premature complexity.
- Prefer handling edge cases thoughtfully over optimizing only for implementation speed.
- Bias toward explicit code over clever code.
- Keep diffs minimal: solve the problem with the fewest necessary abstractions and files touched.
