# Repository Guidelines

**Product: "RSI for Trading."** A self-improving quant pipeline — ideation → simulation → real
execution — for Kalshi BTC prediction markets. It places **real orders** and evolves its own
strategy-search policy (Tau-RSI). Optimize for durable alpha and robustness, not demo polish.
Ship fast by keeping diffs minimal and reusing what's here; ship safe by never weakening a
guard. Deep architecture lives in `PLAN.md` (kept current every session) and the rigorous-
research spec in `RESEARCH_PIPELINE_DESIGN.md`. This file holds only what an agent can't infer
from the code: commands, non-obvious conventions, and the safety/rigor bars.

## Project Structure
- `data_pipeline/`: the live system — collectors, feature builder, sim/live engines,
  `dashboard_server.py`, `common.py` (DB/auth helpers), `architecture/` (live risk/execution).
- `app/`: the customer product (research agent, backtester, quant/stats toolkit, server, SPA).
- `client_api/`: pandas client for the dashboard's `/api/table` (research, not the live path).
- `tests/`: pytest with a `FakeCursor` fixture (`tests/conftest.py`) — engine/risk logic is
  testable with no live DB. `credentials/`: key material (never commit). `scripts/`: AWS deploy.

## Build, Test, Deploy
Python 3.12+ in a venv. `pip install -r requirements.txt`.
- `python -m pytest tests/` — full suite, no live DB. Run before every commit; keep it green.
- `python -m py_compile app/*.py data_pipeline/*.py` — fast syntax check.
- `python -m app.schema` — create/migrate the FULL schema (idempotent): it runs
  `data_pipeline.init_schema` (pipeline tables) **and** the app-level `_add_column_if_missing`
  migrations (e.g. the `app_users` autopilot/risk/exec columns, `app_order_intents`). **Deploys MUST
  run `app.schema`, not `data_pipeline.init_schema` alone** — the latter skips the app migrations, so
  new app columns silently never land and features that read them crash at runtime (observed: the
  autopilot broke on a missing `exec_max_book_fraction` column).
- **Deploy (when explicitly asked):** tar the **whole `app/` package** — never file-by-file
  (partial deploys drop imports and crash-loop the box). Ship to the **web box**
  (the CloudFront origin), not a collector box — see memory + `PLAN.md` for exact IDs/commands.
  Invalidate CloudFront `/*` (the HTML carries the `?v=` asset hash). **Verify a live `curl`
  returns 200 — "service active" is not proof.** These three are the documented causes of past
  silent outages; treat them as a checklist, not advice.

## Coding Style
- PEP 8, 4-space indent, explicit type hints on public methods. `snake_case` funcs/vars,
  `PascalCase` classes, `UPPER_SNAKE_CASE` constants. Explicit over clever; focused functions.
- **DB access stays in the repository layer** (`*_repository.py`/`common.py`), never inline in
  business logic (pattern: `sim_repository.py`) — that layer is what makes engine/risk logic
  testable against `FakeCursor`. Enforce DRY; flag duplication early.
- **Stdlib/quant-toolkit first.** Reuse `app/quant.py` (fees, vol, edge, Kelly, drawdown) and
  `app/stats.py`; do not re-implement math or add numpy/scipy unless profiling demands it.

## Testing
- Add `tests/test_<module>.py`, cases `test_<behavior>`, for any non-trivial logic. Prefer
  `FakeCursor` over a live DB. Dashboard/API changes need ≥1 happy-path and ≥1 error-path test.
- Non-trivial branch/loop/parser/money path leaves one runnable check behind.

## Quant-Research Rigor (the product's whole point)
A fee-surviving BTC edge is rare; it is trivially easy to *fake* one. For any strategy,
backtest, or research-pipeline change, hold the bar in `RESEARCH_PIPELINE_DESIGN.md`:
- **Mechanism before rule** — name who is on the other side and why the edge persists. No
  mechanism, no hypothesis.
- **Pre-register, then freeze** — the spec, hypothesis, and test are fixed before any held-out
  number is seen. The generator never sees validation/holdout outcomes; only the gatekeeper does.
- **Count every trial** — trial count is invisible in code and inflates every result; the
  immutable ledger exists so DSR/FDR corrections stay honest. Record failures and INCONCLUSIVEs.
- **Judge with tests, not point thresholds** — bootstrap CIs, PSR/DSR, FDR budget, purged
  walk-forward + embargo. "No reliable edge" is a first-class, valuable result.
- Fees are a hard, state-dependent hurdle; net-of-fee or it doesn't count.

## Security & Safety (NON-NEGOTIABLE)
- `live_trading_engine.py` places real orders when `live_settings.live_enabled=true` — never
  flip that on, or make changes that could effectively do so, without explicit, separate
  authorization. Deploy/live checks may only ever become *stricter*, never weaker or reordered.
- `.env.aws` holds DB creds + AWS profile/region; `common.py` reads Kalshi key material via
  `PROD_KEYID`/`PROD_KEYFILE` (or `KALSHI_WS_KEY_ID`/`KALSHI_WS_PRIVATE_KEY_PATH`) and the
  dashboard basic-auth/live-gate passwords via `DASHBOARD_PASSWORD`/`LIVE_TRADING_PASSWORD`.
- Never commit `.env*`, private keys, or raw account/order responses (`.gitignore` covers these).
- Run `/security-review` on any diff touching money, orders, auth, or a control path.

## Skills
- `/ponytail` before any **backend** code; `/impeccable` before any **frontend/UI** work.
- `/devlog-sync` whenever `mvp.md`'s Queue/Done changes (regenerates the public Dev Logs).
- `/security-review` per the safety rule above. `/code-review`, `/simplify` are available on demand.
- **Skills worth building (propose, don't auto-author):** a `quant-rigor` checklist skill
  distilling `RESEARCH_PIPELINE_DESIGN.md` (pre-registration, trial-count, purged WF, DSR/PSR
  gates); a `deploy-verify` skill encoding the whole-`app/`-tar + correct-box + CloudFront-`/*`
  + curl-200 procedure above.

## Agent Operating Principles
- **Opinionated recommendation, not a menu.** State concrete tradeoffs; surface genuine
  either/or decisions as a selection and ask before committing. For missing data, propose a
  practical acquisition path and name the support needed.
- **Minimal intentional abstractions.** Design for likely change (new data/strategy/execution/
  risk), but no speculative framework building. Fewest files touched; root-cause over symptom.
- **Parallelize independent work, sequence dependencies.** Fan out read-heavy research and
  disjoint-file edits to subagents (keeps their file-dumps out of your context — relay only the
  conclusion); serialize anything sharing a file (e.g. `schema.py`, `agent.py` have one owner).
- **PLAN/mvp discipline (every turn):** keep `PLAN.md` current; keep the todo list in `../mvp.md`
  current — open work under `## TODO / Working Queue` (one flat list; `[blocked]` = needs a
  user/AWS action). The moment something ships, MOVE it to `## Done` (dated), don't delete it.
- After implementing a strategy, document it; prefer diagrams for architecture/signal flow.

## Continuous Improvement Protocol (bounded self-improvement — the agents' own RSI loop)
This file is living documentation. Each session (or when a recurring failure surfaces) an agent
MAY propose **exactly one** small refinement to AGENTS.md, from harvested signal: recent commits,
`mvp.md` Done, subagent findings, repeated mistakes. Rules that make it safe, not a runaway rewrite:
- **Additive value or proven-dead removal only** — add a rule that would have prevented a *real,
  observed* miss, or cut guidance shown to be ignored/obsolete. Never bloat; sharpen before append.
- **Never touch the safety/security bar except to strengthen it.** Never an automatic or unbounded
  self-rewrite — it is one human-reviewed edit in a normal commit, reversible like any other.
- **Log it** in the changelog below: dated, one line. Keep only the last ~10 entries (prune oldest).

### Instruction changelog
- 2026-10-17 — Fixed the migration command: deploys must run `python -m app.schema` (pipeline
  tables + app-level `_add_column_if_missing` migrations), not `data_pipeline.init_schema` alone,
  which silently skips app columns (broke the autopilot on a missing `exec_max_book_fraction`).
- 2026-10-16 — Restructured for speed+safety: added product framing, Deploy checklist (whole-app
  tar / correct box / CloudFront `/*` / curl-200, from documented outages), a Quant-Research Rigor
  bar tied to `RESEARCH_PIPELINE_DESIGN.md`, sharpened skills + parallel-vs-sequence guidance, and
  this bounded self-improvement protocol. Safety rules preserved and made more prominent.

## Commit & PR
Conventional Commits (`feat: …`, `fix: …`). PRs: behavior-change summary, risk notes (auth, order
placement, rate limits), validation evidence (commands + output), linked task.
