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
