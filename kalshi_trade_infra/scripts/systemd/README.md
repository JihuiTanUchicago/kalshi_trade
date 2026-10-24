# Process supervision

Before this, the live engine and the forward collector ran as bare
`setsid nohup ...&` processes started by hand, and `watchdog.sh` - which
covered only the dashboard and the sim engine, and was itself not scheduled by
anything. Nothing restarted the live trading engine if it died.

Install:

    sudo cp scripts/systemd/*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now kalshi-live-engine kalshi-sim-engine kalshi-forward-collector

`kalshi-dashboard.service` already existed and is unchanged.

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
orders for app users.

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
