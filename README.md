# Tau

**An AI research-to-live pipeline for short-horizon binary-options trading
(Kalshi BTC 15-minute & daily markets).** An agent proposes trading
hypotheses, validates each in a backtest it cannot cheat (it never sees the
out-of-sample window while iterating), and only strategies that pass the gates
can be deployed — on paper, or to live money in your own Kalshi account.

> **Source-available, not (yet) open source.** Licensed under the Business
> Source License 1.1 — free for non-production use (evaluation, research,
> personal use); it converts to Apache-2.0 on the Change Date. See
> [LICENSE](LICENSE) and [NOTICE](NOTICE).

---

## What it is

- **Collectors** — Coinbase BTC spot + Kalshi order book → a MySQL feature store.
- **Feature builder** — per-minute features (moneyness, realized vol, z-score, …).
- **Research agent** — an LLM proposes parameterized strategy *specs* (never raw
  code); a deterministic backtester scores them in-sample, then gates the best on
  **unseen** out-of-sample data. Every hypothesis is recorded, passed or not.
- **Simulated + live engines** — share one risk/execution abstraction, so a
  backtest and a deployment evaluate the identical rule. Paper is the default;
  live orders fire only when explicitly enabled, in your own Kalshi account.
- **Dashboard / app** — monitor strategies, review the "homework" (thesis,
  in-sample vs out-of-sample result, number of hypotheses tried), and promote
  sim → live.
- **Tau-RSI** *(in progress)* — a self-evolving research loop adapted from
  **Dream-RSI** (see [NOTICE](NOTICE)): the agent's exploration policy improves
  from its own accumulated discovery history.

## Pass criteria (how a strategy earns "passed")

Data is split 70% in-sample / 30% unseen. Only the best few hypotheses per batch
are tested out-of-sample (multiple-testing discipline). To pass, all gates must
hold on the **unseen** data: positive P&L, ≥ 10 trades, profit factor ≥ 1.1, and
max drawdown ≤ 50% of capital.

## Architecture

```
Coinbase spot ─┐
               ├─► feature store (MySQL) ─► research agent ─► backtester ─► gates
Kalshi book ───┘                                 │                           │
                                                 ▼                           ▼
                                        sim engine / live engine ◄── risk layer
                                                 │
                                                 ▼
                                             dashboard / app
```

## Setup

Requires Python 3.12+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r kalshi_trade_infra/requirements.txt

# configure: copy the example env and fill in DB creds, Kalshi key material, etc.
cp kalshi_trade_infra/.env.example kalshi_trade_infra/.env
# edit kalshi_trade_infra/.env   (see every variable's purpose inline)

# create the schema
python -m data_pipeline.init_schema

# run the tests (no live DB required — a FakeCursor fixture backs the suite)
python -m pytest tests/
```

## Disclaimer

Research/educational software. **Not investment advice.** Trading binary options
risks real capital; live orders fire only when you explicitly enable live mode
and connect your own Kalshi account. No warranty — see the LICENSE.

## License & attribution

Business Source License 1.1 (© 2026 Jihui Tan). The self-evolving research
component adapts **Dream-RSI** (arXiv:2609.14858). Full attributions in
[NOTICE](NOTICE).
