# Process supervision

Before this, the live engine and the forward collector ran as bare
`setsid nohup ...&` processes started by hand, and `watchdog.sh` - which
covered only the dashboard and the sim engine, and was itself not scheduled by
anything. Nothing restarted the live trading engine if it died.

Install (collector box):

    sudo cp scripts/systemd/*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now kalshi-sim-engine kalshi-forward-collector

`kalshi-live-engine` (the legacy BTC 15m live engine) was stopped and disabled on 2026-10-24;
live trading now runs in `recursive-engine` on the web box. Its unit and keys stay on the
collector box; do not re-enable it without the owner's go. `scripts/deploy_collector.sh` never
starts a disabled unit.

Each unit is `Restart=always` with a burst limit, so a crash loop backs off
rather than hammering the exchange. Verified by SIGKILLing the sim engine:
systemd replaced it with a new PID within 20s.

`watchdog.sh` is superseded - leaving it running would start a second copy of
processes systemd already owns.

## Recursive (customer app)

Four more units, same shape: `recursive-web` (HTTP, `APP_HOST`/`APP_PORT`, default
127.0.0.1:8090), `recursive-agents`, `recursive-engine`, `recursive-history`. They read
`/opt/kalshi/.env.app` in addition to `.env.aws`. Run `python -m app.schema` once first.
`APP_LIVE_TRADING_ENABLED` must stay unset until the owner explicitly authorises real
orders for app users. `scripts/deploy_web.sh` restarts these four and applies their memory caps
(`systemctl set-property`) on every deploy, since the units on the box were hand-installed.

`tau-scout.timer` (web box) runs the RSI mispricing scout (`app.rsi_scout`). The web bundle
does not ship `scripts/`, so install it by hand like the other timers here.

### World Monitor news poller (optional)

`tau-news.service` runs `app.worldmonitor_data monitor` in a loop, archiving news digests into
the local observation journal so HISTORICAL research reads have a no-lookahead archive to query
(copilot still fetches current news on demand without it). Same env shape as the recursive units
(`.env.app` + `.env.aws`); enable only once `WORLDMONITOR_API_KEY` is set:

    sudo cp scripts/systemd/tau-news.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now tau-news

It and the app server must point at the same `TAU_WORLDMONITOR_JOURNAL` (both default to
`/opt/kalshi/.runtime/worldmonitor/news.sqlite3`). A missing key makes it exit cleanly and the
burst limit stops a crash loop; `TAU_WORLDMONITOR_ENABLED` gates agent exposure, not polling.

## Live alerter

`kalshi-alerter.timer` runs `data_pipeline.live_alerter` every 5 minutes. Until now
the box ran it from a hand-written `run_alerter.sh` and timer that were never checked in;
these units reproduce that (source `.env.aws` + `.env.alerts`, then `unset AWS_PROFILE`
so boto3 falls through to the instance role). Each pass also reconciles our book against
Kalshi's positions; a disagreement is reported only once it survives to the next pass.

    sudo cp scripts/systemd/kalshi-alerter.* /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now kalshi-alerter.timer

If the old hand-made timer is still enabled, disable it first or every alert goes out twice.

## Dashboard and watchdog

These ran only from hand-written files on the servers; they are checked in as copied from
the boxes on 2026-10-24, so rebuilding a box no longer drops them.

- `kalshi-dashboard.service` (web box): the legacy `data_pipeline.dashboard_server` on `.venv`,
  reading `.env.aws` + `.env.dashboard`.
- `tau-watchdog.service` + `tau-watchdog.timer` (both boxes): `data_pipeline.watchdog` every 60s,
  restarting services whose heartbeat stalls. This is the web-box unit. The collector box's copy
  sources `/opt/kalshi/.env` instead of `.env.app` and does not `unset AWS_PROFILE`; when that
  box is rebuilt, install this one and check that `.env.app` (or `.env.watchdog`) carries what
  the watchdog needs there.

    sudo cp scripts/systemd/kalshi-dashboard.service scripts/systemd/tau-watchdog.* /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now kalshi-dashboard tau-watchdog.timer

Both boxes run `kalshi-alerter.timer` today (checked 2026-10-24), each with its own
`.alerter_state.json`, so every alert goes out twice. Keep it enabled on one box only.

### Code paper replay (web box)

`tau-code-paper.timer` runs `app.services.code_paper` at :40. Agent-written code strategies never
run in the paper/live engine; when paper probation places one (one deployment for its whole pooled
stream), this replays each UTC day after it ends and its contracts settle, in the research sandbox
with the strategy's frozen params, and books the trips as closed paper rows (`sim:replay:` refs)
that the tournament and the paper forward gate count. A strategy whose picks change when later
frames are removed is stopped instead. `APP_CODE_PAPER=0` turns it off. Log:
`/opt/kalshi/logs/code_paper.log`.

### Paper liquidity-reward maker (web box)

`tau-lip-maker-paper.timer` runs `app.adapters.sim.maker_paper hourly` at :25. It replays every
closed, archived tick hour of the last 6 that has no result yet, for the reward series in
`data_pipeline.lip_programs.REWARD_SERIES` (crypto lead plus the FX and commodity 15m books;
override with `TAU_LIP_PAPER_SERIES`), against the real pools from the LIP snapshots, and writes one
JSON per hour (totals per config and per series) to `ticks/v1/lip_maker_paper/`. Paper only: it places no orders. Tick files it downloads are
deleted after each hour (`TAU_TICK_CACHE=/opt/kalshi/ticks-cache`). Read the running total with
`python -m app.adapters.sim.maker_paper summary --days 7`.

### Market-making research lab (web box)

`tau-maker-lab.timer` runs `app.maker_lab_run --series auto` every 4 hours at :45, rotating
KXBTCD, KXBTC15M and KXBTC (each series every 12 hours). The model proposes Bitcoin quoting
policies, the queue-aware tick replay scores them on the 24 research hours before a 12-hour
holdout (60-second fill markouts, hour as the unit), and one finalist is judged once on the held-out
hours (`app.services.maker_lab`). Each run sees the summaries of that series' last 3 runs. Results go
to S3 `research-watch/maker/runs/`, the held-out ledger to `research-watch/maker/ledger.json`. Paper
only: it places no orders. Log: `/opt/kalshi/logs/maker_lab.log`.

`scripts/deploy_web.sh` installs and enables these units (its `UNITS` list), so no hand install.

### Weather forecasts (web box)

`kalshi-weather-fcst.timer` runs `app.weather_fcst_collect` hourly at :20, storing every issued
NBM and GFS MOS daily max/min for the stations in `markets.WEATHER_STATIONS` into
`weather_forecasts` (point-in-time: `known_at_utc` = run time + publication lag). Research datasets
and the live engine read the same rows (`app/weather_fcst.py`). Backfill once with
`python -m app.weather_fcst_collect --since 2025-10-01`.

    sudo cp scripts/systemd/kalshi-weather-fcst.* /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now kalshi-weather-fcst.timer

### Sportsbook odds (web box)

Disabled on the web box since 2026-10-24 (no odds API for now); without a key it is a no-op.
`kalshi-sports-odds.timer` runs `app.sports_odds_collect` 5x a day (2 credits per run: NBA + NHL,
about 310 a month, inside The Odds API's free 500). It reads `ODDS_API_KEY` or the Secrets Manager
secret `kalshi/odds_api_key` and is a no-op without one. For a paid plan, tighten `OnCalendar`.

    sudo cp scripts/systemd/kalshi-sports-odds.* /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now kalshi-sports-odds.timer

## Tick recorders (collector box)

`kalshi-tick-recorder` and `coinbase-tick-recorder` stream every Kalshi BTC-series book delta,
trade and ticker, and every Coinbase BTC-USD print and best bid/ask, into hourly NDJSON files
under `/opt/kalshi/ticks`. `spot-tick-recorder` does the same for the other exchanges in the
BRTI (Kalshi's BTC settlement index): Kraken, Bitstamp, Gemini, Bullish, Crypto.com and LMAX,
one directory per venue, one `tick_recorder_spot` heartbeat. `kalshi-tick-archiver.timer` turns
closed hours into S3 Parquet (`ticks/v1/...` in the datalake bucket) and a `tick_archive_hours`
row, then deletes the local file. `scripts/deploy_collector.sh` installs and enables all five;
see `data_pipeline/tick_store.py` for reading the archive.

## Liquidity incentive programs (collector box)

`kalshi-lip-programs.timer` snapshots Kalshi's public liquidity incentive program list
(`GET /incentive_programs`, active and upcoming) every 15 minutes into
`ticks/v1/lip_programs/date=.../HHMM.json.gz` plus `ticks/lip_programs/latest.json.gz`.
`python -m data_pipeline.lip_programs summary` prints the latest pools by series.
`scripts/deploy_collector.sh` installs and enables it.
