"""Tick recorder: every Kalshi WebSocket message for the Bitcoin series and every Coinbase BTC
tick, appended verbatim to hourly NDJSON files on the collector box's disk.

Why a separate recorder instead of more forward_collector rows: forward_collector keeps only
the top of book of ONE active 15-minute contract per series, and writes it to RDS row by row.
Full depth for every BTC contract (15m, hourly KXBTCD above/below, KXBTC ranges, the weekly and
yearly ones) is millions of messages a day, which RDS cannot absorb. Here nothing per-tick
touches the database: lines go to disk, tick_archiver turns each closed hour into S3 Parquet,
and only a 10-second heartbeat (collector_state) and an hourly manifest row reach RDS.

One line per message: {"rt": <receive time, epoch ns>, "m": <the exchange message verbatim>}.
The recorder also keeps every Kalshi book in memory and writes a {"rt":..,"checkpoint":{...}}
line at the top of each hour file, so any hour can be replayed without the snapshot that was
sent when the market was first subscribed (a weekly contract's may be days old).

Run:  python -m data_pipeline.tick_recorder kalshi      (unit kalshi-tick-recorder)
      python -m data_pipeline.tick_recorder coinbase    (unit coinbase-tick-recorder)
"""
import asyncio
import json
import os
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import certifi

from data_pipeline.common import api_get, fetch_open_markets, get_db_conn, parse_iso_to_dt, utc_now

TICK_DIR = os.getenv("TAU_TICK_DIR", "/opt/kalshi/ticks")
# Explicit series list (comma separated). Unset: every Kalshi series whose ticker starts with one of
# TAU_TICK_SERIES_PREFIXES, discovered from /series, plus the core three if discovery fails.
TICK_SERIES = [s.strip() for s in os.getenv("TAU_TICK_SERIES", "").split(",") if s.strip()]
TICK_SERIES_PREFIXES = [s.strip() for s in os.getenv("TAU_TICK_SERIES_PREFIXES", "KXBTC").split(",") if s.strip()]
CORE_SERIES = ["KXBTC15M", "KXBTCD", "KXBTC"]
KALSHI_CHANNELS = ["orderbook_delta", "trade", "ticker"]
COINBASE_PRODUCTS = [s.strip() for s in os.getenv("TAU_TICK_COINBASE_PRODUCTS", "BTC-USD").split(",") if s.strip()]
# matches = every print; ticker = best bid/ask (and sizes) at each print; heartbeat = 1/s liveness.
COINBASE_CHANNELS = [s.strip() for s in os.getenv("TAU_TICK_COINBASE_CHANNELS", "matches,ticker,heartbeat").split(",") if s.strip()]
COINBASE_WS = os.getenv("TAU_TICK_COINBASE_WS", "wss://ws-feed.exchange.coinbase.com")

DISCOVERY_S = 30           # market discovery cadence; also run right after each quarter hour
PRESUBSCRIBE_S = 180       # subscribe unopened markets this long before they open
UNSUB_GRACE_S = 180        # keep a closed market's stream this long for settlement prints
HEARTBEAT_S = 10
RESYNC_MIN_S = 30          # per subscription group
RESYNC_BUDGET = 20         # all groups, per 10 minutes
SILENCE_RECONNECT_S = {"kalshi": 45, "coinbase": 15}   # no message this long while subscribed -> reconnect


def _ns() -> int:
    return time.time_ns()


class HourlyFile:
    """Appends lines to {root}/{source}/{YYYYMMDD}/{HH}.ndjson, rolling over on the UTC hour.
    on_roll(write, rt_ns) is called with the new file open so the caller can write a header line
    stamped just before the line that started the hour."""

    def __init__(self, root: str, source: str, on_roll=None) -> None:
        self.root, self.source, self.on_roll = root, source, on_roll
        self._fh = None
        self._hour: Optional[Tuple[str, str]] = None
        self.path: Optional[str] = None
        self.lines = 0
        self.bytes = 0

    def _hour_of(self, rt_ns: int) -> Tuple[str, str]:
        dt = datetime.fromtimestamp(rt_ns / 1e9, tz=timezone.utc)
        return dt.strftime("%Y%m%d"), dt.strftime("%H")

    def write(self, rt_ns: int, line: str) -> None:
        hour = self._hour_of(rt_ns)
        if hour != self._hour:
            self._open(hour)
            if self.on_roll is not None:
                self.on_roll(self._write_raw, rt_ns - 1)
        self._write_raw(line)

    def _write_raw(self, line: str) -> None:
        self._fh.write(line)
        self._fh.write("\n")
        self.lines += 1
        self.bytes += len(line) + 1

    def _open(self, hour: Tuple[str, str]) -> None:
        self.close()
        d = os.path.join(self.root, self.source, hour[0])
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(d, hour[1] + ".ndjson")
        self._fh = open(self.path, "a", buffering=1 << 20)
        self._hour = hour

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


# --- Kalshi book state -------------------------------------------------------------------------

def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def snapshot_levels(msg: Dict, side: str) -> List[Tuple[float, float]]:
    """[(price_dollars, qty)] for one side of an orderbook_snapshot, whichever encoding Kalshi
    sent: <side>_dollars_fp / <side>_dollars as [["0.0800", "300.00"], ...] or <side> in cents."""
    for key, scale in ((side + "_dollars_fp", 1.0), (side + "_dollars", 1.0), (side, 0.01)):
        levels = msg.get(key)
        if levels:
            out = []
            for lvl in levels:
                p, q = _num(lvl[0]), _num(lvl[1])
                if p is not None and q is not None:
                    out.append((round(p * scale, 4), q))
            return out
    return []


def delta_fields(msg: Dict) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """(side, price_dollars, delta_qty) of an orderbook_delta message."""
    price = _num(msg.get("price_dollars"))
    if price is None:
        cents = _num(msg.get("price"))
        price = None if cents is None else cents / 100.0
    delta = _num(msg.get("delta_fp"))
    if delta is None:
        delta = _num(msg.get("delta"))
    return msg.get("side"), None if price is None else round(price, 4), delta


class Books:
    """In-memory Kalshi books, {ticker: {"yes": {price: qty}, "no": {...}}}, for hourly checkpoints."""

    def __init__(self) -> None:
        self.books: Dict[str, Dict[str, Dict[float, float]]] = {}

    def snapshot(self, msg: Dict) -> None:
        t = msg.get("market_ticker")
        if t:
            self.books[t] = {s: dict(snapshot_levels(msg, s)) for s in ("yes", "no")}

    def delta(self, msg: Dict) -> None:
        t = msg.get("market_ticker")
        side, price, d = delta_fields(msg)
        if not t or side not in ("yes", "no") or price is None or d is None:
            return
        lv = self.books.setdefault(t, {"yes": {}, "no": {}})[side]
        q = lv.get(price, 0.0) + d
        if q <= 1e-9:
            lv.pop(price, None)
        else:
            lv[price] = q

    def drop(self, tickers) -> None:
        for t in tickers:
            self.books.pop(t, None)

    def checkpoint(self) -> Dict[str, Dict[str, List[List[float]]]]:
        return {t: {s: sorted([p, q] for p, q in b[s].items()) for s in ("yes", "no")}
                for t, b in self.books.items()}


# --- Kalshi market discovery ---------------------------------------------------------------------

def discover_series() -> List[str]:
    if TICK_SERIES:
        return list(TICK_SERIES)
    found: Set[str] = set()
    try:
        data = api_get("/series", {"category": "Crypto"})
        for s in data.get("series") or []:
            t = s.get("ticker") or ""
            if any(t.startswith(p) for p in TICK_SERIES_PREFIXES):
                found.add(t)
    except Exception as e:
        print(f"[WARN] series discovery failed: {e}", flush=True)
    found.update(c for c in CORE_SERIES if any(c.startswith(p) for p in TICK_SERIES_PREFIXES))
    return sorted(found)


def upcoming_markets(series: str, now: datetime) -> List[Dict]:
    """Unopened markets that open within PRESUBSCRIBE_S, so a new 15-minute or hourly contract
    is streamed from its first second rather than from the next discovery pass."""
    out: List[Dict] = []
    try:
        data = api_get("/markets", {"series_ticker": series, "status": "unopened", "limit": 1000})
    except Exception:
        return out
    for m in data.get("markets") or []:
        ot = parse_iso_to_dt(m.get("open_time"))
        if ot is not None and (ot - now).total_seconds() <= PRESUBSCRIBE_S:
            out.append(m)
    return out


def wanted_markets(series_list: List[str]) -> Dict[str, Dict]:
    """{ticker: market} of every open (and about-to-open) market in the series."""
    now = utc_now()
    out: Dict[str, Dict] = {}
    for s in series_list:
        try:
            for m in fetch_open_markets(s, get=api_get, max_pages=5):
                out[m["ticker"]] = m
            for m in upcoming_markets(s, now):
                out.setdefault(m["ticker"], m)
        except Exception as e:
            print(f"[WARN] discovery {s}: {e}", flush=True)
    return out


# --- heartbeat ------------------------------------------------------------------------------------

def write_heartbeat(key: str, state: Dict) -> None:
    """collector_state row the live alerter watches. Best effort, on a worker thread."""
    try:
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO collector_state (state_key,state_value,updated_at_utc) VALUES (%s,%s,%s)
                       ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)""",
                    (key, json.dumps(state, default=str), utc_now().replace(tzinfo=None)),
                )
        finally:
            conn.close()
    except Exception as e:
        print(f"[WARN] heartbeat {key} failed: {e}", flush=True)


class Recorder:
    source = ""

    def __init__(self) -> None:
        self.file = HourlyFile(TICK_DIR, self.source, on_roll=self.on_roll)
        self.counts: Dict[str, int] = {}
        self.window: Dict[str, int] = {}
        self.last_msg_ns = 0
        self.connected_ns = 0
        self.reconnects = 0
        self.seq_gaps = 0
        self.errors: List[str] = []
        self.ws = None

    def on_roll(self, write, rt: int) -> None:
        pass

    def record(self, rt: int, raw: str, typ: str) -> None:
        self.file.write(rt, '{"rt":%d,"m":%s}' % (rt, raw))
        self.counts[typ] = self.counts.get(typ, 0) + 1
        self.window[typ] = self.window.get(typ, 0) + 1
        self.last_msg_ns = rt

    def meta(self, event: str, **kw) -> None:
        rt = _ns()
        self.file.write(rt, json.dumps({"rt": rt, "meta": event, **kw}))

    def heartbeat_state(self) -> Dict:
        now = _ns()
        return {
            "host": socket.gethostname(),
            "connected": self.ws is not None,
            "last_msg_age_s": None if not self.last_msg_ns else round((now - self.last_msg_ns) / 1e9, 1),
            "msgs_last_window": dict(self.window),
            "window_s": HEARTBEAT_S,
            "msgs_total": dict(self.counts),
            "reconnects": self.reconnects,
            "seq_gaps": self.seq_gaps,
            "file": self.file.path,
            "file_bytes": self.file.bytes,
            "errors": self.errors[-5:],
        }

    async def heartbeat_loop(self) -> None:
        key = "tick_recorder_" + self.source
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            self.file.flush()
            state = self.heartbeat_state()
            self.window = {}
            await asyncio.to_thread(write_heartbeat, key, state)
            silent = (_ns() - max(self.last_msg_ns, self.connected_ns)) / 1e9
            if self.ws is not None and self.expect_traffic() and silent > SILENCE_RECONNECT_S[self.source]:
                print(f"[WARN] {self.source}: silent {silent:.0f}s, reconnecting", flush=True)
                await self.ws.close()

    def expect_traffic(self) -> bool:
        return True

    async def run(self) -> None:
        asyncio.create_task(self.heartbeat_loop())
        while True:
            try:
                await self.session()
            except Exception as e:
                self.errors.append(f"{utc_now().isoformat()} {type(e).__name__}: {e}"[:300])
                print(f"[WARN] {self.source} websocket: {e}", flush=True)
            self.ws = None
            self.reconnects += 1
            self.meta("disconnected")
            await asyncio.sleep(min(30, 2 ** min(self.reconnects, 5)) if self.last_msg_ns == 0 else 2)

    async def session(self) -> None:
        raise NotImplementedError


class KalshiRecorder(Recorder):
    source = "kalshi"

    def __init__(self) -> None:
        super().__init__()
        from data_pipeline.forward_collector import WsTickerFeed  # reuses its key loading + signing
        self.auth = WsTickerFeed()
        if not self.auth.enabled:
            raise RuntimeError("Kalshi WS credentials missing (KALSHI_WS_KEY_ID / KALSHI_WS_PRIVATE_KEY_PATH)")
        self.books = Books()
        self.series: List[str] = []
        self.series_at = 0.0
        self._id = 0
        self.pending: Dict[int, Dict] = {}            # cmd id -> group
        self.groups: List[Dict] = []                  # {"tickers": set, "close": dt, "sids": {channel: sid}}
        self.sid_group: Dict[int, Dict] = {}
        self.last_seq: Dict[int, int] = {}
        self.close_time: Dict[str, Optional[datetime]] = {}

    def on_roll(self, write, rt: int) -> None:
        write(json.dumps({"rt": rt, "checkpoint": self.books.checkpoint()}, separators=(",", ":")))

    def subscribed_tickers(self) -> Set[str]:
        out: Set[str] = set()
        for g in self.groups:
            out |= g["tickers"]
        return out

    def expect_traffic(self) -> bool:
        return bool(self.groups)

    async def send(self, cmd: str, params: Dict, group: Optional[Dict] = None) -> None:
        self._id += 1
        if group is not None:
            self.pending[self._id] = group
        await self.ws.send(json.dumps({"id": self._id, "cmd": cmd, "params": params}))

    async def subscribe(self, tickers: List[str], channels: List[str] = KALSHI_CHANNELS) -> None:
        close = [self.close_time.get(t) for t in tickers]
        group = {"tickers": set(tickers), "sids": {}, "channels": list(channels),
                 "close": max((c for c in close if c is not None), default=None)}
        self.groups.append(group)
        await self.send("subscribe", {"channels": list(channels), "market_tickers": sorted(tickers)}, group)

    async def unsubscribe(self, group: Dict) -> None:
        sids = list(group["sids"].values())
        if sids:
            await self.send("unsubscribe", {"sids": sids})
        for s in sids:
            self.sid_group.pop(s, None)
            self.last_seq.pop(s, None)
        if group in self.groups:
            self.groups.remove(group)

    async def resync(self, sid: int) -> None:
        """A sequence gap means a lost delta, so this group's book is wrong: drop its orderbook
        stream and resubscribe, which sends a fresh snapshot."""
        group = self.sid_group.get(sid)
        if group is None:
            return
        # Bounded: a group resyncs at most once per RESYNC_MIN_S, and all groups together at most
        # RESYNC_BUDGET times per 10 minutes. If gaps were systematic (a seq semantics change),
        # unbounded resubscribes would hammer the exchange; the raw stream is kept either way.
        now = time.time()
        self.resync_times = [t for t in getattr(self, "resync_times", []) if now - t < 600]
        if now - group.get("resynced_at", 0.0) < RESYNC_MIN_S or len(self.resync_times) >= RESYNC_BUDGET:
            return
        self.resync_times.append(now)
        self.sid_group.pop(sid, None)
        self.last_seq.pop(sid, None)
        group["sids"].pop("orderbook_delta", None)
        await self.send("unsubscribe", {"sids": [sid]})
        group["channels"] = [c for c in group["channels"] if c != "orderbook_delta"]
        if not group["channels"]:
            self.groups.remove(group)
        await self.subscribe(sorted(group["tickers"]), ["orderbook_delta"])
        self.groups[-1]["resynced_at"] = now

    async def discovery_loop(self) -> None:
        while self.ws is not None:
            try:
                if not self.series or time.time() - self.series_at > 3600:
                    self.series = await asyncio.to_thread(discover_series)
                    self.series_at = time.time()
                markets = await asyncio.to_thread(wanted_markets, self.series)
                await self.reconcile(markets)
            except Exception as e:
                self.errors.append(f"discovery {type(e).__name__}: {e}"[:300])
                print(f"[WARN] discovery: {e}", flush=True)
            await asyncio.sleep(_next_discovery_delay(time.time()))

    async def reconcile(self, markets: Dict[str, Dict]) -> None:
        for t, m in markets.items():
            self.close_time[t] = parse_iso_to_dt(m.get("close_time"))
        have = self.subscribed_tickers()
        new = [t for t in markets if t not in have]
        # One subscription per event (and per opened/unopened), so a whole event is unsubscribed
        # when it closes and a rejected unopened market never takes open ones down with it.
        by_event: Dict[Tuple[str, bool], List[str]] = {}
        for t in new:
            key = (markets[t].get("event_ticker") or t, str(markets[t].get("status")) in ("active", "open"))
            by_event.setdefault(key, []).append(t)
        for tickers in by_event.values():
            await self.subscribe(tickers)
        if new:
            print(f"subscribed {len(new)} markets in {len(by_event)} events; total {len(self.subscribed_tickers())}", flush=True)
        now = utc_now()
        for g in list(self.groups):
            if g["close"] is not None and (now - g["close"]).total_seconds() > UNSUB_GRACE_S \
                    and not (g["tickers"] & set(markets)):
                await self.unsubscribe(g)
                self.books.drop(g["tickers"])

    def handle(self, rt: int, raw: str) -> Optional[Tuple[str, Dict]]:
        data = json.loads(raw)
        typ = data.get("type") or "?"
        self.record(rt, raw, typ)
        return typ, data

    async def session(self) -> None:
        import websockets
        self.groups, self.pending, self.sid_group, self.last_seq = [], {}, {}, {}
        async with websockets.connect(
            self.auth.ws_url, additional_headers=self.auth._auth_headers(), ssl=self.auth._ssl_ctx,
            ping_interval=20, ping_timeout=20, open_timeout=15, max_size=64 << 20, max_queue=4096,
        ) as ws:
            self.ws = ws
            self.connected_ns = _ns()
            self.meta("connected")
            print("kalshi tick recorder connected", flush=True)
            disc = asyncio.create_task(self.discovery_loop())
            try:
                async for raw in ws:
                    rt = _ns()
                    typ, data = self.handle(rt, raw)
                    await self.on_message(typ, data)
            finally:
                self.ws = None
                disc.cancel()

    async def on_message(self, typ: str, data: Dict) -> None:
        msg = data.get("msg") or {}
        if typ in ("orderbook_snapshot", "orderbook_delta"):
            sid, seq = data.get("sid"), data.get("seq")
            if sid is not None and seq is not None:
                prev = self.last_seq.get(sid)
                self.last_seq[sid] = seq
                if typ == "orderbook_delta" and prev is not None and seq != prev + 1:
                    self.seq_gaps += 1
                    self.meta("seq_gap", sid=sid, expected=prev + 1, got=seq)
                    await self.resync(sid)
                    return
            if typ == "orderbook_snapshot":
                self.books.snapshot(msg)
            else:
                self.books.delta(msg)
        elif typ == "subscribed":
            group = self.pending.get(data.get("id"))
            ch, sid = msg.get("channel"), msg.get("sid")
            if group is not None and ch and sid is not None:
                group["sids"][ch] = sid
                self.sid_group[sid] = group
                if len(group["sids"]) >= len(group["channels"]):
                    self.pending.pop(data.get("id"), None)
        elif typ == "error":
            self.errors.append(f"ws error {msg}"[:300])
            print(f"[WARN] kalshi ws error: {data}", flush=True)
            group = self.pending.pop(data.get("id"), None)
            if group is not None and not group["sids"] and group in self.groups:
                self.groups.remove(group)  # never streamed: the next discovery pass retries it


def _next_discovery_delay(now_s: float) -> float:
    """Seconds to the next discovery pass: DISCOVERY_S, or sooner so one runs 1s after each
    quarter hour (when 15-minute and hourly contracts open)."""
    to_quarter = 900 - (now_s % 900) + 1.0
    return max(1.0, min(DISCOVERY_S, to_quarter))


class CoinbaseRecorder(Recorder):
    source = "coinbase"

    def __init__(self) -> None:
        super().__init__()
        self.last_trade_id: Dict[str, int] = {}
        self._ssl = ssl.create_default_context(cafile=certifi.where())

    async def session(self) -> None:
        import websockets
        async with websockets.connect(COINBASE_WS, ssl=self._ssl, ping_interval=20, ping_timeout=20,
                                      open_timeout=15, max_size=16 << 20, max_queue=4096) as ws:
            self.ws = ws
            self.connected_ns = _ns()
            self.last_trade_id = {}
            self.meta("connected")
            await ws.send(json.dumps({"type": "subscribe", "product_ids": COINBASE_PRODUCTS,
                                      "channels": COINBASE_CHANNELS}))
            print(f"coinbase tick recorder connected {COINBASE_PRODUCTS} {COINBASE_CHANNELS}", flush=True)
            try:
                async for raw in ws:
                    rt = _ns()
                    data = json.loads(raw)
                    typ = data.get("type") or "?"
                    self.record(rt, raw, typ)
                    if typ in ("match", "last_match"):
                        self.check_trade_id(data)
                    elif typ == "error":
                        self.errors.append(f"ws error {data}"[:300])
            finally:
                self.ws = None

    def check_trade_id(self, data: Dict) -> None:
        """Coinbase trade_ids are consecutive per product, so a jump is a missed print."""
        pid, tid = data.get("product_id"), data.get("trade_id")
        if pid is None or tid is None:
            return
        tid = int(tid)
        prev = self.last_trade_id.get(pid)
        if prev is not None and tid > prev + 1:
            self.seq_gaps += 1
            self.meta("trade_id_gap", product_id=pid, expected=prev + 1, got=tid)
        if prev is None or tid > prev:
            self.last_trade_id[pid] = tid


def main(argv: List[str]) -> None:
    which = argv[1] if len(argv) > 1 else "kalshi"
    rec = {"kalshi": KalshiRecorder, "coinbase": CoinbaseRecorder}[which]()
    print(f"tick recorder {which} -> {TICK_DIR}", flush=True)
    asyncio.run(rec.run())


if __name__ == "__main__":
    main(sys.argv)
