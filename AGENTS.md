# Repository Guidelines

## Project Structure & Module Organization
This repository is a lightweight Python Kalshi trading client and example runner.
- `clients.py`: core HTTP/WebSocket client implementations (`KalshiHttpClient`, `KalshiWebSocketClient`, `Environment`).
- `main.py`: minimal authenticated entrypoint (balance check + WebSocket connect).
- `example.py`: extended API usage and order lifecycle demo.
- `credentials/`: key material location (do not commit secrets).
- `requirements.txt`: pinned runtime dependencies.
- `venv/`: local virtualenv (treat as local-only; avoid editing/tracking changes here).

Keep new strategy logic in separate modules (for example, `strategies/`) and keep transport/auth concerns in `clients.py`.

## Build, Test, and Development Commands
Use Python 3.12+ with a virtual environment.
- `python -m venv venv && source venv/bin/activate`: create/activate local env.
- `pip install -r requirements.txt`: install dependencies.
- `python main.py`: run the authenticated baseline flow.
- `python example.py`: run API and order example flow.
- `python -m py_compile clients.py main.py example.py`: quick syntax check.

## Coding Style & Naming Conventions
- Follow PEP 8, 4-space indentation, and explicit type hints for public methods.
- Use `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Keep functions focused; prefer explicit control flow over compact but opaque expressions.
- Preserve current client interface style (path-based `get/post/delete`) when adding endpoints.

## Testing Guidelines
No formal test suite exists yet. For now:
- Add unit tests under `tests/` using `pytest` when adding non-trivial logic.
- Name files `test_<module>.py` and cases `test_<behavior>`.
- For API changes, include at least one happy-path and one error-path test (mock HTTP/WebSocket boundaries).

## Commit & Pull Request Guidelines
Git history is minimal (`Initial commit`), so adopt Conventional Commit style now:
- `feat: add market data polling helper`
- `fix: handle websocket reconnect on ssl error`

PRs should include:
- concise summary of behavior changes,
- risk notes (auth, order placement, rate limit impact),
- validation evidence (commands run, sample output),
- linked issue/task when applicable.

## Security & Configuration Tips
- Configure `.env` with `ENVIRONMENT`, `DEMO_KEYID`/`PROD_KEYID`, and key file paths.
- Never commit `.env`, private keys, or raw account/order responses containing sensitive data.
- Prefer `DEMO` for development; explicitly document any `PROD` testing steps in PRs.

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

### Engineering Standards
- Enforce DRY aggressively; flag duplication early.
- Keep code "engineered enough": avoid both fragile hacks and premature complexity.
- Prefer handling edge cases thoughtfully over optimizing only for implementation speed.
- Bias toward explicit code over clever code.
- Keep diffs minimal: solve the problem with the fewest necessary abstractions and files touched.
