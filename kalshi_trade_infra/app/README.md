# Tau (v0.1)

The customer product: Google sign-in, agents that research Kalshi Bitcoin markets, a
backtest gate the agent cannot game, paper-first deployment, and a co-pilot chat.
Product truth is in `../PRODUCT.md`; the operator console (`data_pipeline/dashboard_server.py`)
is unchanged and separate.

## Frontend presentation

Account, Billing and System are grouped under Settings; the legacy URLs remain.
Dashboard shows portfolio/open positions first, followed by performance and recent
research. Hot Markets stays below the shared header without visibility toggles.
Repeated descriptions and the Overview divider are removed. Current Research,
Strategies, model selection, demo curves, code browser and account controls remain.
[Review scope and verification](../results/frontend_cosmetics_pr_2026-10-16/HANDOFF.md).

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    SPA["app/static (vanilla SPA)<br/>Dashboard · Research · Strategies · Deploy · Funds"]
  end
  SPA -- "JSON + X-Recursive header" --> WEB["app.server<br/>stdlib HTTP, sessions, rate limits"]
  WEB -- "Google OIDC + PKCE" --> G[(Google)]
  WEB --> DB[(MySQL / RDS)]
  AG["app.worker agents<br/>research · chat · review"] --> DB
  AG -- "Messages API" --> C[(Claude)]
  EN["app.worker engine<br/>paper + live, every slot"] --> DB
  EN -- "live book, results" --> K[(Kalshi REST)]
  EN -- "1m candles" --> CB[(Coinbase)]
  EN -. "user's own key, IOC orders<br/>(off: APP_LIVE_TRADING_ENABLED)" .-> K
  HI["app.market_history<br/>every 10 min"] --> DB
  HI --> K
  HI --> CB
```

Every process is stateless apart from MySQL, so each scales by running more copies:
agent runs are claimed with `SELECT … FOR UPDATE SKIP LOCKED`, engine decisions with a
per-deployment, per-slot claim (`claim_decision`), and every money write is idempotent.

## The research loop (why it's "recursive")

```mermaid
sequenceDiagram
  participant U as User
  participant A as Agent (Claude)
  participant B as Backtester
  U->>A: direction + note (e.g. "volatility mispricing")
  Note over A: context = in-sample window only<br/>+ this user's past results (memory)
  A->>B: round 1: 4 hypotheses (thesis + spec)
  B-->>A: IN-SAMPLE metrics only
  A->>B: round 2: 3 refinements
  B-->>A: IN-SAMPLE metrics only
  Note over B: freeze top 3 by in-sample score
  B->>B: out-of-sample run + 5 gates
  B-->>U: every slip saved: PASSED / VOID / REJECTED,<br/>"1 of N tried" shown on each
```

The agent never sees out-of-sample numbers or even the out-of-sample dates while it
iterates. Each run's results become memory for the next run on that market.

## The rule (one implementation, two callers)

`app/spec.py` is the only decision logic. The backtester and the live engine both call
`entries()` / `exit_signal()` on snapshots built by the same `markets.snapshot()`, so a
deployed strategy trades exactly what passed.

```
fair P(YES) = Phi( (ln(S/K) + mu*T) / (sigma*sqrt(T)) )
  sigma = vol_scale * realised 1m vol (15 or 60 min)
  mu    = drift_beta * BTC return over drift_window / drift_window
edge(YES) = P - yes_ask        edge(NO) = yes_bid - P
enter when edge >= min_edge, price/tte/spread in range, all filters hold
exit: take_profit / stop_loss / edge decay, else hold to settlement
```

| Market | Kalshi series | Decision cadence | History |
|---|---|---|---|
| `btc15m` | KXBTC15M | every minute | 30 days of 1m candles |
| `btc_daily` | KXBTCD, 5pm EDT event only | every hour | 60 days of 1h candles (strikes within ±7% of BTC at open) |

Fills: buy at the ask, sell at the bid, Kalshi taker fee (`kalshi_fees`) on every fill,
settle on Kalshi's own `result`. Paper fills are capped at the size shown on the book.

## Gates (all must pass to deploy)

| Gate | Threshold |
|---|---|
| Makes money in-sample | > $0 |
| Makes money on unseen data | > $0 |
| Enough unseen trades | ≥ 10 |
| Unseen profit factor | ≥ 1.1 |
| Unseen worst drawdown | ≤ 50% of capital |

Agent adjustments (chat or autopilot) are re-backtested against the same gates before they
can be proposed or applied.

## Guardrails

* Autopilot may: apply gate-passing adjustments that don't raise stake or position count,
  deploy passed strategies **on paper**, and pause anything. It may never move money to
  live or resume a live deployment.
* Loss guard (engine, no model involved): a deployment that loses more than
  max(2 × its backtest's worst unseen drawdown, 50% of capital) is paused, and a review run is queued.
* Live for app users is off unless `APP_LIVE_TRADING_ENABLED=1`; live is YES-only, needs a
  connected key and a typed `LIVE` confirmation.
* Kalshi private keys are AES-256-GCM encrypted (`APP_SECRET_KEY`), bound to the user id.
* Limits: 2 concurrent / 12 daily research runs, 40 chat messages per hour, 10 active deployments.

## Run locally

```bash
docker run -d --name recursive-mysql -e MYSQL_ROOT_PASSWORD=devroot -e MYSQL_DATABASE=kalshi_trade -p 3307:3306 mysql:8.0
export MYSQL_HOST=127.0.0.1 MYSQL_PORT=3307 MYSQL_USER=root MYSQL_PASSWORD=devroot
python -m app.schema
python -m app.market_history            # leave running; first backfill takes ~20 min
APP_DEV_LOGIN=1 APP_INSECURE_COOKIES=1 python -m app.server   # http://127.0.0.1:8090/auth/dev
ANTHROPIC_API_KEY=... python -m app.worker agents
python -m app.worker engine
APP_TEST_MYSQL=1 python -m pytest tests/   # includes the money-path tests against MySQL
```

## Production environment (`/opt/kalshi/.env.app`)

| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | OAuth client (Web application) |
| `APP_GOOGLE_REDIRECT_URI` | e.g. `https://<host>/auth/google/callback`, registered in Google Cloud |
| `APP_SECRET_KEY` | 32 random bytes, urlsafe base64 (`python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`) |
| `ANTHROPIC_API_KEY`, `APP_AGENT_MODEL` | agent model (default `claude-sonnet-5-5`) |
| `APP_LIVE_TRADING_ENABLED` | leave unset until explicitly authorised |

CloudFront in front of the app must forward cookies and allow POST (the existing
distribution forwards no cookies and was GET-only until 2026-09-26).
