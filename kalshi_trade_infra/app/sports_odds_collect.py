"""Snapshot every US sportsbook's NBA/NHL moneyline from The Odds API into sports_odds.

Each run stores one row per (game, book) stamped with this run's collected_at, the time we
knew the price; app/adapters/data/sports_odds as-of joins on it for research and live alike. Historical odds
are a paid add-on, so the history is whatever this collects going forward.

Key: ODDS_API_KEY in the environment, else the AWS Secrets Manager secret kalshi/odds_api_key.
Without one the run is a logged no-op, so the timer can be installed before the key exists.
Each league costs one credit per run (us region, h2h only); an empty league costs nothing.

Usage (web box, timer: scripts/systemd/kalshi-sports-odds.timer):
  python -m app.sports_odds_collect
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.adapters.data.sports_odds import SPORTS, american_to_prob, devig, team_code

ODDS_URL = "https://api.the-odds-api.com/v4/sports/%s/odds"
SECRET_ID = "kalshi/odds_api_key"
# Stop before the monthly quota runs dry so a burst of manual runs can't strand the timer.
RESERVE_CREDITS = 10
_TIMEOUT_S = 30

Row = Tuple  # (sport, event_id, commence, home, away, book, book_update, home_price, away_price, p_home, collected)


def api_key() -> Optional[str]:
    key = (os.environ.get("ODDS_API_KEY") or "").strip()
    if key:
        return key
    try:
        import boto3
        sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        val = sm.get_secret_value(SecretId=SECRET_ID).get("SecretString") or ""
    except Exception:  # noqa: BLE001 - no secret / no permission / no boto3: the run is a no-op
        return None
    val = val.strip()
    if val.startswith("{"):
        try:
            val = str(json.loads(val).get("ODDS_API_KEY") or json.loads(val).get("key") or "")
        except ValueError:
            return None
    return val or None


def _dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def parse_events(sport: str, events: List[Dict], collected: datetime) -> List[Row]:
    """The Odds API /odds payload -> one row per (game, book) with a usable two-way h2h price."""
    out: List[Row] = []
    for ev in events or []:
        home, away = team_code(sport, ev.get("home_team")), team_code(sport, ev.get("away_team"))
        commence = _dt(ev.get("commence_time"))
        if not home or not away or commence is None:
            continue
        for bk in ev.get("bookmakers") or []:
            h2h = next((m for m in bk.get("markets") or [] if m.get("key") == "h2h"), None)
            if not h2h:
                continue
            prices = {o.get("name"): o.get("price") for o in h2h.get("outcomes") or []}
            hp, ap = prices.get(ev.get("home_team")), prices.get(ev.get("away_team"))
            if hp is None or ap is None or len(prices) != 2:
                continue  # a three-way (draw) market or a one-sided quote
            ph, pa = american_to_prob(hp), american_to_prob(ap)
            p_home = devig(ph, pa) if ph is not None and pa is not None else None
            if p_home is None:
                continue
            out.append((sport, str(ev.get("id")), commence, home, away, str(bk.get("key"))[:32],
                        _dt(bk.get("last_update")), float(hp), float(ap), p_home, collected))
    return out


def insert(cur, rows: List[Row]) -> int:
    if not rows:
        return 0
    cur.executemany(
        "INSERT IGNORE INTO sports_odds (sport, event_id, commence_utc, home_code, away_code, book, book_update_utc,"
        " home_price, away_price, p_home, collected_at_utc) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    return int(cur.rowcount or 0)


def collect(cur, key: str, sports=None, get=None, now: Optional[datetime] = None) -> Dict:
    if get is None:
        import requests
        get = requests.get
    collected = (now or datetime.now(timezone.utc)).replace(tzinfo=None, microsecond=0)
    stats: Dict = {"sports": {}, "inserted": 0, "remaining": None, "errors": []}
    for sport in sports or sorted(set(SPORTS.values())):
        if stats["remaining"] is not None and stats["remaining"] < RESERVE_CREDITS:
            stats["errors"].append("%s: skipped, %s credits left" % (sport, stats["remaining"]))
            continue
        try:
            resp = get(ODDS_URL % sport, params={"apiKey": key, "regions": "us", "markets": "h2h",
                                                 "oddsFormat": "american", "dateFormat": "iso"}, timeout=_TIMEOUT_S)
            rem = (getattr(resp, "headers", None) or {}).get("x-requests-remaining")
            if rem is not None:
                stats["remaining"] = int(float(rem))
            if resp.status_code != 200:
                raise RuntimeError("HTTP %s" % resp.status_code)
            events = resp.json()
            rows = parse_events(sport, events, collected)
            stats["sports"][sport] = {"events": len(events or []), "rows": len(rows)}
            stats["inserted"] += insert(cur, rows)
        except Exception as e:  # noqa: BLE001 - one league's failure must not lose the other
            stats["errors"].append("%s: %r" % (sport, e))
    return stats


def main() -> None:
    key = api_key()
    if not key:
        print(json.dumps({"skipped": "no Odds API key (set ODDS_API_KEY or secret %s)" % SECRET_ID}), flush=True)
        return
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            stats = collect(cur, key)
    finally:
        conn.close()
    print(json.dumps(stats), flush=True)


if __name__ == "__main__":
    main()
