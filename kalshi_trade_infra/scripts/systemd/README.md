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
