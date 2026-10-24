"""Push notifications for the live trading account, via SNS.

Why this exists: the dashboard tells the truth but only when someone is
looking at it, and the operator is not always looking. This runs on the box
next to the engine, notices the handful of things worth interrupting someone
for, and emails them. Nothing else in the system can reach outward.

Design rules it follows deliberately:

- **Only on change.** State is kept in ALERTER_STATE_PATH so a standing
  condition is announced once, not every five minutes. An alerter that cries
  every tick gets muted, and a muted alerter is worse than none.
- **A daily heartbeat.** Silence otherwise cannot be distinguished from a dead
  alerter - which is exactly the failure this whole system already suffered
  twice. One quiet summary a day proves the watcher is alive.
- **Read-only.** It never writes to any trading table and never places an
  order. Its IAM policy grants sns:Publish on one topic and nothing else.

Run it every five minutes from the systemd timer in
scripts/systemd/kalshi-alerter.timer (this AMI has no crontab).
"""
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from data_pipeline.common import api_get_auth, get_db_conn, utc_now

SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN", "")
STATE_PATH = os.getenv("ALERTER_STATE_PATH", "/opt/kalshi/.alerter_state.json")
# Absolute floors. Deliberately not derived from the caps: the caps are the
# engine's own limits, and the point of an alert is to catch the case where
# those limits are wrong or not doing what was expected.
CASH_FLOOR = float(os.getenv("ALERT_CASH_FLOOR", "70"))
DAILY_LOSS_ALERT = float(os.getenv("ALERT_DAILY_LOSS", "3"))
POSITION_COST_ALERT = float(os.getenv("ALERT_POSITION_COST", "20"))
# A writer this far past its cadence is treated as stopped, matching the
# dashboard's own as-of rule so the two never disagree.
STALE_MULTIPLE = 6
WRITER_CADENCE = {"live_portfolio_20s": 20, "live_engine": 60, "forward_quotes": 20}
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://dehiuraiut9ro.cloudfront.net/?tab=live-trading")
# The engine crash-looping is invisible to every other check here: it restarts
# fast enough that its snapshot never looks stale, and it writes no trade. That
# is exactly how a deprecated order endpoint went unnoticed while the strategy
# it broke was the one actually trying to trade.
LIVE_LOG = os.getenv("LIVE_ENGINE_LOG", "/opt/kalshi/live_trading_engine.log")
ENGINE_ERROR_MARKERS = ("live trading error", "engine crashed")
# Kalshi requires a periodic location attestation for API trading. It lapses on
# a 7-day window and then every order 403s, silently, exactly like it did on
# 2026-09-27. Warn before that rather than after.
ATTEST_WARN_DAYS = float(os.getenv("ALERT_ATTESTATION_DAYS", "2"))


def load_state() -> Dict:
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(state: Dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def _writer_ages(cur) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    specs = {
        "live_portfolio_20s": "SELECT TIMESTAMPDIFF(SECOND, MAX(snapshot_time_utc), UTC_TIMESTAMP()) a FROM live_portfolio_20s",
        "forward_quotes": "SELECT TIMESTAMPDIFF(SECOND, MAX(snapshot_time_utc), UTC_TIMESTAMP()) a FROM forward_quotes",
        "live_engine": (
            "SELECT TIMESTAMPDIFF(SECOND, updated_at_utc, UTC_TIMESTAMP()) a FROM collector_state "
            "WHERE state_key='live_trading_last_snapshot' LIMIT 1"
        ),
    }
    for name, sql in specs.items():
        try:
            cur.execute(sql)
            row = cur.fetchone() or {}
            out[name] = float(row["a"]) if row.get("a") is not None else None
        except Exception:
            out[name] = None
    return out


def collect(cur) -> Dict:
    """Everything the alert rules need, in one pass."""
    cur.execute("SELECT settings_key, settings_json FROM live_settings")
    enabled: Dict[str, bool] = {}
    for r in cur.fetchall():
        cfg = r["settings_json"] if isinstance(r["settings_json"], dict) else json.loads(r["settings_json"])
        enabled[r["settings_key"]] = bool(cfg.get("live_enabled"))

    cur.execute("SELECT model_name, paused_reason FROM live_model_state WHERE paused=1")
    paused = {r["model_name"]: (r.get("paused_reason") or "no reason recorded") for r in cur.fetchall()}

    cur.execute(
        "SELECT model_name, market_ticker, qty_contracts, entry_price_dollars FROM live_positions"
    )
    positions = [
        {
            "model": r["model_name"],
            "ticker": r["market_ticker"],
            "qty": int(r["qty_contracts"]),
            "entry": float(r["entry_price_dollars"]),
            "cost": float(r["entry_price_dollars"]) * int(r["qty_contracts"]),
        }
        for r in cur.fetchall()
    ]

    cur.execute("SELECT COALESCE(MAX(id),0) m FROM live_trades WHERE status='closed'")
    last_trade_id = int((cur.fetchone() or {}).get("m") or 0)

    cur.execute(
        "SELECT model_name, COALESCE(SUM(pnl_dollars),0) p FROM live_trades "
        "WHERE status='closed' AND DATE(closed_at_utc)=UTC_DATE() GROUP BY model_name"
    )
    daily = {r["model_name"]: float(r["p"]) for r in cur.fetchall()}

    cur.execute(
        "SELECT equity_dollars, raw_json FROM live_portfolio_20s ORDER BY snapshot_time_utc DESC LIMIT 1"
    )
    row = cur.fetchone() or {}
    cash = float(row["equity_dollars"]) if row.get("equity_dollars") is not None else None
    cash_source = "unknown"
    try:
        raw = row.get("raw_json")
        raw = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        cash_source = raw.get("cash_source", "unknown")
    except Exception:
        pass

    return {
        "enabled": enabled,
        "paused": paused,
        "positions": positions,
        "last_trade_id": last_trade_id,
        "daily": daily,
        "cash": cash,
        "cash_source": cash_source,
        "writers": _writer_ages(cur),
    }


# Mismatch kinds. The kind, not the message, is what persistence keys on: a
# size that drifts between runs must not reset the clock and hide a standing
# disagreement forever.
UNTRACKED = "untracked"
BOOK_ONLY = "book_only"
SHORT = "short"
SIZE = "size"
UNREADABLE = "unreadable"
# The 2026-09-27 failure looked like an untracked negative position once Tau's
# NO-side made the exchange sign ambiguous, so untracked is as loud as SHORT.
URGENT_MISMATCH_KINDS = (UNTRACKED, SHORT)
POSITIONS_PAGE_LIMIT = 1000
POSITIONS_MAX_PAGES = 20


def _kalshi_positions() -> List[Dict]:
    """Every market position on the account. The endpoint pages, and a
    holding past the first page would read as a phantom in our book."""
    out: List[Dict] = []
    cursor = None
    for _ in range(POSITIONS_MAX_PAGES):
        params = {"limit": POSITIONS_PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        resp = api_get_auth("/trade-api/v2/portfolio/positions", params=params)
        out.extend(resp.get("market_positions") or [])
        cursor = resp.get("cursor")
        if not cursor:
            return out
    raise RuntimeError("positions did not finish paging after %d pages" % POSITIONS_MAX_PAGES)


def classify_mismatches(cur) -> List[Tuple[str, str, str]]:
    """(key, kind, message) for each disagreement; see position_mismatches."""
    try:
        raw = _kalshi_positions()
    except Exception as e:
        return [(UNREADABLE, UNREADABLE, "could not read Kalshi positions to reconcile: %s" % e)]

    theirs: Dict[str, int] = {}
    for p in raw:
        qty = int(float(p.get("position_fp") or p.get("position") or 0))
        if qty:
            theirs[p["ticker"]] = qty  # signed: + YES, - NO

    ours: Dict[str, int] = {}
    cur.execute("SELECT model_name, market_ticker, qty_contracts FROM live_positions")
    for r in cur.fetchall():
        ours[r["market_ticker"]] = ours.get(r["market_ticker"], 0) + int(r["qty_contracts"])
    cur.execute("SELECT ticker, side, COALESCE(SUM(qty),0) AS qty FROM app_positions "
                "WHERE mode='live' AND status='open' GROUP BY ticker, side")
    for r in cur.fetchall():
        signed = int(r["qty"]) if str(r["side"]).lower() == "yes" else -int(r["qty"])
        ours[r["ticker"]] = ours.get(r["ticker"], 0) + signed

    out = []
    for ticker in sorted(set(theirs) | set(ours)):
        t = theirs.get(ticker, 0)
        o = ours.get(ticker, 0)
        if t == o:
            continue
        if o == 0:
            side = "NO" if t < 0 else "YES"
            kind, msg = UNTRACKED, "Kalshi holds %d %s x %s that our book does not know about" % (abs(t), side, ticker)
        elif t == 0:
            kind, msg = BOOK_ONLY, "our book holds %d x %s that Kalshi does not" % (o, ticker)
        elif (t > 0) != (o > 0):
            # Opposite directions is the only genuine short now (sell with nothing behind it).
            kind, msg = SHORT, "SHORT/direction mismatch on %s: Kalshi %d, our book %d" % (ticker, t, o)
        else:
            kind, msg = SIZE, "size mismatch on %s: Kalshi %d, our book %d" % (ticker, abs(t), abs(o))
        out.append(("%s|%s" % (ticker, kind), kind, msg))
    return out


def position_mismatches(cur) -> List[str]:
    """Where our book and Kalshi's disagree about what we hold.

    This is the check that was missing on 2026-09-27. Orders were recorded as
    filled when they had been cancelled, so the engine "closed" positions it
    did not hold - and a sell with nothing behind it opens a short. Kalshi
    knew the whole time; nothing ever asked it.

    Tau-aware. The operator account now also carries Tau's per-user live
    positions, which live in ``app_positions`` (with a 'yes'/'no' side), not the
    old ``live_positions`` table. So "ours" is the SIGNED net of BOTH tables per
    ticker: YES adds +qty, NO adds -qty - mirroring the exchange, which reports a
    NO position as a negative (short-YES) ``position``. Without app_positions every
    Tau live holding looked untracked; without the sign a legitimately held NO
    looked like a short. Only a genuine opposite-direction net is flagged SHORT now.

    Deliberately stateless and cheap: it compares holdings, not money. A
    balance check would need deposits and withdrawals tracked, which they are
    not, and would be wrong the first time either happened.
    """
    return [msg for _, _, msg in classify_mismatches(cur)]


def engine_errors_since(offset: int) -> Tuple[int, List[str]]:
    """New engine error lines since the last check, and the new read offset.
    A rotated or truncated log resets the offset rather than replaying."""
    try:
        size = os.path.getsize(LIVE_LOG)
    except OSError:
        return offset, []
    if size < offset:
        offset = 0
    hits: List[str] = []
    try:
        with open(LIVE_LOG, "r", errors="replace") as fh:
            fh.seek(offset)
            for line in fh:
                low = line.lower()
                if any(m in low for m in ENGINE_ERROR_MARKERS):
                    hits.append(line.strip()[:300])
            offset = fh.tell()
    except OSError:
        return offset, []
    return offset, hits


def attestation_days_left() -> Optional[float]:
    """Days until the Kalshi location attestation expires, or None if it cannot
    be read. Absent timestamp means never attested, which is also a warning."""
    try:
        ts = api_get_auth("/trade-api/v2/api_keys").get("api_key_region_expiration_ts")
    except Exception:
        return None
    if not ts:
        return -1.0
    return (int(ts) - time.time()) / 86400.0


def new_closed_trades(cur, since_id: int) -> List[Dict]:
    cur.execute(
        "SELECT id, model_name, market_ticker, qty_contracts, entry_price_dollars, "
        "exit_price_dollars, pnl_dollars, closed_at_utc FROM live_trades "
        "WHERE status='closed' AND id > %s ORDER BY id",
        (since_id,),
    )
    return list(cur.fetchall())


def build_alerts(now: Dict, prev: Dict, cur) -> Tuple[List[str], List[str]]:
    """Returns (urgent_lines, normal_lines). Urgent ones set the subject."""
    urgent: List[str] = []
    normal: List[str] = []
    first_run = not prev

    prev_paused = prev.get("paused", {}) or {}
    for model, reason in (now["paused"] or {}).items():
        if model not in prev_paused:
            urgent.append(f"HALTED: {model} stopped itself - {reason}")

    prev_enabled = prev.get("enabled", {}) or {}
    if not first_run:
        for model, is_on in (now["enabled"] or {}).items():
            was = prev_enabled.get(model)
            if was is not None and bool(was) != bool(is_on):
                normal.append(f"Switch changed: {model} is now {'LIVE' if is_on else 'off'}")

    prev_trade_id = int(prev.get("last_trade_id") or 0)
    if not first_run and now["last_trade_id"] > prev_trade_id:
        for t in new_closed_trades(cur, prev_trade_id):
            pnl = float(t["pnl_dollars"] or 0.0)
            sign = "+" if pnl >= 0 else "-"
            normal.append(
                f"Trade closed: {t['model_name']} {t['market_ticker']} "
                f"{t['qty_contracts']} @ {float(t['entry_price_dollars']):.2f} -> "
                f"{float(t['exit_price_dollars'] or 0):.2f}  {sign}${abs(pnl):.2f}"
            )

    prev_keys = {p.get("key") for p in (prev.get("positions") or [])}
    for p in now["positions"]:
        key = f"{p['model']}|{p['ticker']}|{p['qty']}"
        p["key"] = key
        if key not in prev_keys:
            line = (
                f"Position opened: {p['model']} {p['ticker']} "
                f"{p['qty']} @ ${p['entry']:.2f}  (cost ${p['cost']:.2f})"
            )
            if p["cost"] > POSITION_COST_ALERT:
                urgent.append(f"LARGE {line}")
            else:
                normal.append(line)

    for model, pnl in (now["daily"] or {}).items():
        if pnl <= -abs(DAILY_LOSS_ALERT) and float((prev.get("daily") or {}).get(model, 0.0)) > -abs(DAILY_LOSS_ALERT):
            urgent.append(f"DOWN ${abs(pnl):.2f} today on {model} (UTC day)")

    cash = now["cash"]
    if cash is not None and cash < CASH_FLOOR and (prev.get("cash") is None or prev["cash"] >= CASH_FLOOR):
        urgent.append(f"CASH ${cash:.2f} is below the ${CASH_FLOOR:.0f} floor")
    if now["cash_source"] != "kalshi_api" and prev.get("cash_source") == "kalshi_api":
        urgent.append(f"Balance is no longer coming from the Kalshi API (now: {now['cash_source']}) - it is an estimate")

    # Settlement moves Kalshi's position to zero a beat before the engine
    # books it, so a single disagreement is usually just that. Only report a
    # mismatch that is still there on the next run five minutes later, then
    # stay quiet while it stands and say so once when it clears.
    mismatches = classify_mismatches(cur)
    seen_before = set(prev.get("position_mismatch") or [])
    announced_before = set(prev.get("position_mismatch_announced") or [])
    announced = []
    for key, kind, msg in mismatches:
        if key in announced_before:
            announced.append(key)
        elif key in seen_before:
            (urgent if kind in URGENT_MISMATCH_KINDS else normal).append("book disagrees with Kalshi: " + msg)
            announced.append(key)
    current_keys = {key for key, _, _ in mismatches}
    for key in sorted(announced_before - current_keys):
        if key == UNREADABLE:
            normal.append("Resolved: Kalshi positions are readable again")
        else:
            normal.append("Resolved: book agrees with Kalshi again on " + key.split("|", 1)[0])
    now["position_mismatch"] = sorted(current_keys)
    now["position_mismatch_announced"] = sorted(announced)

    new_offset, errs = engine_errors_since(int(prev.get("log_offset") or 0))
    now["log_offset"] = new_offset
    if errs and not first_run:
        uniq = []
        for e in errs:
            short = e.split(": ", 1)[-1][:160]
            if short not in uniq:
                uniq.append(short)
        urgent.append(
            f"ENGINE ERRORED {len(errs)}x since the last check - it cannot place orders: {uniq[0]}"
        )

    days = attestation_days_left()
    now["attest_days"] = days
    if days is not None and days < ATTEST_WARN_DAYS:
        was = prev.get("attest_days")
        if was is None or was >= ATTEST_WARN_DAYS:
            urgent.append(
                f"Kalshi location attestation {'EXPIRED' if days <= 0 else f'expires in {days:.1f} days'}"
                " - re-verify in the Kalshi app or every order will 403"
            )

    prev_stale = set(prev.get("stale") or [])
    stale_now = []
    for name, age in (now["writers"] or {}).items():
        expect = WRITER_CADENCE.get(name, 60)
        if age is None or age > expect * STALE_MULTIPLE:
            stale_now.append(name)
            if name not in prev_stale:
                shown = "never" if age is None else f"{int(age)}s"
                urgent.append(f"STALE: {name} has not written for {shown} - its numbers may be frozen")
    for name in prev_stale:
        if name not in stale_now:
            normal.append(f"Recovered: {name} is writing again")
    now["stale"] = stale_now

    return urgent, normal


def heartbeat_body(now: Dict) -> str:
    live = [m for m, on in (now["enabled"] or {}).items() if on] or ["none"]
    cash = "unknown" if now["cash"] is None else f"${now['cash']:.2f}"
    today = sum((now["daily"] or {}).values())
    return (
        f"Daily check-in. Nothing needed your attention.\n\n"
        f"Cash: {cash} ({now['cash_source']})\n"
        f"Live: {', '.join(live)}\n"
        f"Open positions: {len(now['positions'])}\n"
        f"Realised so far this UTC day: ${today:.2f}\n"
        f"Halted: {', '.join(now['paused']) if now['paused'] else 'none'}\n"
    )


def publish(subject: str, body: str) -> None:
    if not SNS_TOPIC_ARN:
        print("SNS_TOPIC_ARN not set; would have sent:\n" + subject + "\n" + body)
        return
    import boto3

    boto3.client("sns", region_name=SNS_TOPIC_ARN.split(":")[3]).publish(
        TopicArn=SNS_TOPIC_ARN, Subject=subject[:99], Message=body
    )


def main() -> None:
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            now = collect(cur)
            prev = load_state()
            urgent, normal = build_alerts(now, prev, cur)

        today = utc_now().strftime("%Y-%m-%d")
        lines = urgent + normal
        if lines:
            subject = f"Kalshi: {urgent[0][:80]}" if urgent else f"Kalshi: {normal[0][:80]}"
            body = "\n".join(f"- {ln}" for ln in lines)
            body += f"\n\nCash: {'unknown' if now['cash'] is None else '$%.2f' % now['cash']}"
            body += f"\nOpen positions: {len(now['positions'])}"
            body += f"\n\n{DASHBOARD_URL}"
            publish(subject, body)
            print(f"sent {len(lines)} line(s)")
        elif prev.get("heartbeat_date") != today:
            publish("Kalshi: daily check-in, all quiet", heartbeat_body(now) + f"\n{DASHBOARD_URL}")
            print("sent heartbeat")
        else:
            print("nothing to report")

        now["heartbeat_date"] = today if (not lines and prev.get("heartbeat_date") != today) else prev.get("heartbeat_date", today)
        save_state(now)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
