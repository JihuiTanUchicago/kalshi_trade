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
      python -m data_pipeline.tick_recorder spot        (unit spot-tick-recorder: the other BRTI
                                                         exchanges, one source directory each)
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
# The other CF Benchmarks BRTI constituents (Kalshi's BTC settlement index), recorded by SpotRecorder.
SPOT_VENUES = [s.strip() for s in os.getenv("TAU_TICK_SPOT_VENUES", "kraken,bitstamp,gemini,bullish,cryptocom,lmax").split(",") if s.strip()]


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
        self.updated: Dict[str, int] = {}      # ticker -> rt of its last snapshot/delta

    def snapshot(self, msg: Dict, rt: Optional[int] = None) -> None:
        t = msg.get("market_ticker")
        if t:
            self.books[t] = {s: dict(snapshot_levels(msg, s)) for s in ("yes", "no")}
            if rt is not None:
                self.updated[t] = rt

    def delta(self, msg: Dict, rt: Optional[int] = None) -> None:
        t = msg.get("market_ticker")
        side, price, d = delta_fields(msg)
        if not t or side not in ("yes", "no") or price is None or d is None:
            return
        if rt is not None:
            self.updated[t] = rt
        lv = self.books.setdefault(t, {"yes": {}, "no": {}})[side]
        q = lv.get(price, 0.0) + d
        if q <= 1e-9:
            lv.pop(price, None)
        else:
            lv[price] = q

    def drop(self, tickers) -> None:
        for t in tickers:
            self.books.pop(t, None)
            self.updated.pop(t, None)

    def checkpoint(self) -> Dict[str, Dict]:
        """{ticker: {"yes": [[p, q]..], "no": [..], "t": rt of the last real update}}; "t" lets a
        reader of a later hour still know how stale the book is."""
        out = {}
        for t, b in self.books.items():
            out[t] = {s: sorted([p, q] for p, q in b[s].items()) for s in ("yes", "no")}
            if t in self.updated:
                out[t]["t"] = self.updated[t]
        return out


MARKET_META_KEYS = ("event_ticker", "open_time", "close_time", "floor_strike", "cap_strike", "strike_type", "status")


def market_meta(m: Dict) -> Dict:
    """What features need about a contract: its window and strike(s). Series from the ticker prefix."""
    out = {k: m.get(k) for k in MARKET_META_KEYS if m.get(k) is not None}
    out["ticker"] = m.get("ticker")
    out["series_ticker"] = m.get("series_ticker") or str(m.get("ticker") or "").split("-")[0]
    return out


# --- Kalshi market discovery ---------------------------------------------------------------------

# Research can ask for per-second data on a series it lacks (app_data_requests, kind "ticks");
# those series are recorded alongside the BTC ones, re-read every REQUEST_REFRESH_S.
REQUEST_REFRESH_S = 600
REQUEST_LIMIT = 6
SPOT_SYMBOLS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LTC", "LINK", "SHIB", "HYPE")


def spot_product(series: str) -> Optional[str]:
    """Coinbase product that prices a Kalshi crypto series (KXETH15M -> ETH-USD), else None."""
    s = (series or "").upper()
    for sym in SPOT_SYMBOLS:
        if s.startswith("KX" + sym):
            return sym + "-USD"
    return None


def requested_tick_series(limit: int = REQUEST_LIMIT) -> List[str]:
    """Series with open "ticks" data requests, oldest first; [] if the helper or table is absent."""
    try:
        from data_pipeline import common
        fn = getattr(common, "requested_series", None)
        if fn is None:
            return []
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                rows = fn(cur, "ticks", limit) or []
        finally:
            conn.close()
    except Exception as e:
        print(f"[WARN] requested series read failed: {e}", flush=True)
        return []
    out = []
    for r in rows:
        v = r if isinstance(r, str) else (r.get("series") or r.get("series_ticker") if isinstance(r, dict) else None)
        if v and v not in out:
            out.append(str(v))
    return out


def discover_series() -> List[str]:
    if TICK_SERIES:
        return sorted(set(TICK_SERIES) | set(requested_tick_series()))
    found: Set[str] = set(requested_tick_series())
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
        # Kalshi frames end with a newline; left in, it would split the line (the 19:00Z hour
        # on 2026-10-24 was written that way; tick_archiver.read_records repairs it).
        self.file.write(rt, '{"rt":%d,"m":%s}' % (rt, raw.strip()))
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
            await self.publish(key, state)
            silent = (_ns() - max(self.last_msg_ns, self.connected_ns)) / 1e9
            if self.ws is not None and self.expect_traffic() and silent > self.silence_limit():
                print(f"[WARN] {self.source}: silent {silent:.0f}s, reconnecting", flush=True)
                await self.ws.close()

    async def publish(self, key: str, state: Dict) -> None:
        await asyncio.to_thread(write_heartbeat, key, state)

    def expect_traffic(self) -> bool:
        return True

    def silence_limit(self) -> float:
        return SILENCE_RECONNECT_S.get(self.source, 60)

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
    """One socket, one subscription per channel. Kalshi folds every later ``subscribe`` for a
    channel into that channel's existing sid (it answers "ok" with the sid, not "subscribed"),
    so markets are added with ``subscribe`` and removed with ``update_subscription``
    delete_markets on each sid; never ``unsubscribe``, which would end the stream for every
    market at once. ``seq`` counts every message on a sid, all markets together."""
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
        self.close_time: Dict[str, Optional[datetime]] = {}
        self.meta_by_ticker: Dict[str, Dict] = {}
        self.resync_times: List[float] = []
        self.solo: Set[str] = set()                   # tickers whose batch was rejected: one per command
        self.reset_session()

    def reset_session(self) -> None:
        self._id = 0
        self._rt = 0
        self.subscribed: Set[str] = set()
        self.pending: Dict[int, List[str]] = {}       # subscribe cmd id -> tickers
        self.sids: Dict[str, int] = {}                # channel -> sid
        self.last_seq: Dict[int, int] = {}

    def on_roll(self, write, rt: int) -> None:
        write(json.dumps({"rt": rt, "checkpoint": self.books.checkpoint()}, separators=(",", ":")))
        metas = [m for t, m in self.meta_by_ticker.items() if t in self.subscribed]
        if metas:
            write(json.dumps({"rt": rt, "markets": metas}, separators=(",", ":")))

    def subscribed_tickers(self) -> Set[str]:
        return set(self.subscribed)

    def expect_traffic(self) -> bool:
        return bool(self.subscribed)

    async def send(self, cmd: str, params: Dict) -> int:
        self._id += 1
        await self.ws.send(json.dumps({"id": self._id, "cmd": cmd, "params": params}))
        return self._id

    async def subscribe(self, tickers: List[str], channels: List[str] = KALSHI_CHANNELS) -> None:
        if not tickers:
            return
        self.subscribed.update(tickers)
        cid = await self.send("subscribe", {"channels": list(channels), "market_tickers": sorted(tickers)})
        self.pending[cid] = list(tickers)

    async def remove(self, tickers: List[str]) -> None:
        if not tickers:
            return
        for sid in sorted(set(self.sids.values())):
            await self.send("update_subscription",
                            {"sids": [sid], "market_tickers": sorted(tickers), "action": "delete_markets"})
        self.subscribed.difference_update(tickers)
        self.solo.difference_update(tickers)
        self.books.drop(tickers)
        for t in tickers:
            self.meta_by_ticker.pop(t, None)

    async def resync(self) -> None:
        """A seq gap on the orderbook sid means some delta was lost, and with one sid for all
        markets we cannot tell which book is wrong: resubscribe the orderbook channel for every
        market, which sends fresh snapshots. Bounded to once per RESYNC_MIN_S and RESYNC_BUDGET
        per 10 minutes so a systematic issue cannot hammer the exchange; the raw stream is kept."""
        now = time.time()
        self.resync_times = [t for t in self.resync_times if now - t < 600]
        if (self.resync_times and now - self.resync_times[-1] < RESYNC_MIN_S) or len(self.resync_times) >= RESYNC_BUDGET:
            return
        self.resync_times.append(now)
        sid = self.sids.pop("orderbook_delta", None)
        if sid is not None:
            await self.send("unsubscribe", {"sids": [sid]})
            self.last_seq.pop(sid, None)
        tickers = sorted(self.subscribed)
        if tickers:
            cid = await self.send("subscribe", {"channels": ["orderbook_delta"], "market_tickers": tickers})
            self.pending[cid] = []
        self.meta("resync", markets=len(tickers))

    async def discovery_loop(self) -> None:
        while self.ws is not None:
            try:
                if not self.series or time.time() - self.series_at > REQUEST_REFRESH_S:
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
        changed = []
        for t, m in markets.items():
            meta = market_meta(m)
            if self.meta_by_ticker.get(t) != meta:
                self.meta_by_ticker[t] = meta
                changed.append(meta)
        if changed:
            rt = _ns()
            self.file.write(rt, json.dumps({"rt": rt, "markets": changed}, separators=(",", ":")))
        # Open and unopened markets go in separate commands, so a rejected unopened market
        # cannot take open ones down with it.
        new = [t for t in markets if t not in self.subscribed]
        batch = [t for t in new if t not in self.solo]
        opened = [t for t in batch if str(markets[t].get("status")) in ("active", "open")]
        unopened = [t for t in batch if t not in set(opened)]
        await self.subscribe(opened)
        await self.subscribe(unopened)
        for t in new:
            if t in self.solo:
                await self.subscribe([t])
        if new:
            print(f"subscribed {len(new)} markets ({len(unopened)} not yet open); total {len(self.subscribed)}", flush=True)
        now = utc_now()
        done = [t for t in self.subscribed if t not in markets and self.close_time.get(t) is not None
                and (now - self.close_time[t]).total_seconds() > UNSUB_GRACE_S]
        if done:
            await self.remove(done)
            print(f"removed {len(done)} closed markets; total {len(self.subscribed)}", flush=True)

    def handle(self, rt: int, raw: str) -> Optional[Tuple[str, Dict]]:
        data = json.loads(raw)
        typ = data.get("type") or "?"
        self.record(rt, raw, typ)
        return typ, data

    async def session(self) -> None:
        import websockets
        self.reset_session()
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
                    self._rt = rt
                    await self.on_message(typ, data)
            finally:
                self.ws = None
                disc.cancel()

    async def on_message(self, typ: str, data: Dict) -> None:
        msg = data.get("msg") or {}
        sid, seq = data.get("sid"), data.get("seq")
        if typ == "subscribed":
            ch, s = msg.get("channel"), msg.get("sid")
            if ch and s is not None:
                self.sids[ch] = s
                self.last_seq.pop(s, None)
            self.pending.pop(data.get("id"), None)
            return
        if sid is not None and seq is not None:
            prev = self.last_seq.get(sid)
            self.last_seq[sid] = seq
            if prev is not None and seq != prev + 1:
                self.seq_gaps += 1
                self.meta("seq_gap", sid=sid, expected=prev + 1, got=seq)
                if sid == self.sids.get("orderbook_delta"):
                    await self.resync()
                    return
        if typ == "orderbook_snapshot":
            self.books.snapshot(msg, self._rt or None)
        elif typ == "orderbook_delta":
            self.books.delta(msg, self._rt or None)
        elif typ == "error":
            self.errors.append(f"ws error {msg}"[:300])
            print(f"[WARN] kalshi ws error: {data}", flush=True)
            failed = self.pending.pop(data.get("id"), None)
            if failed:
                # The next discovery pass retries them, one per command if it was a batch, so one
                # bad market cannot keep a whole batch out.
                self.subscribed.difference_update(failed)
                if len(failed) > 1:
                    self.solo.update(failed)
        elif typ == "ok":
            self.pending.pop(data.get("id"), None)


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
        self.products: List[str] = list(COINBASE_PRODUCTS)

    def wanted_products(self) -> List[str]:
        """The configured products plus the spot behind every requested Kalshi series."""
        out = list(COINBASE_PRODUCTS)
        for s in requested_tick_series():
            p = spot_product(s)
            if p and p not in out:
                out.append(p)
        return out

    async def products_loop(self) -> None:
        while self.ws is not None:
            await asyncio.sleep(REQUEST_REFRESH_S)
            try:
                wanted = await asyncio.to_thread(self.wanted_products)
                new = [p for p in wanted if p not in self.products]
                if new and self.ws is not None:
                    await self.ws.send(json.dumps({"type": "subscribe", "product_ids": new, "channels": COINBASE_CHANNELS}))
                    self.products += new
                    print(f"coinbase: added {new}", flush=True)
            except Exception as e:
                self.errors.append(f"products {type(e).__name__}: {e}"[:300])

    async def session(self) -> None:
        import websockets
        async with websockets.connect(COINBASE_WS, ssl=self._ssl, ping_interval=20, ping_timeout=20,
                                      open_timeout=15, max_size=16 << 20, max_queue=4096) as ws:
            self.ws = ws
            self.connected_ns = _ns()
            self.last_trade_id = {}
            self.meta("connected")
            self.products = await asyncio.to_thread(self.wanted_products)
            await ws.send(json.dumps({"type": "subscribe", "product_ids": self.products,
                                      "channels": COINBASE_CHANNELS}))
            print(f"coinbase tick recorder connected {self.products} {COINBASE_CHANNELS}", flush=True)
            refresh = asyncio.create_task(self.products_loop())
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
                refresh.cancel()

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


# --- The other BRTI constituent exchanges ---------------------------------------------------------
# Kalshi's BTC contracts settle on CF Benchmarks' BRTI, a once-a-second index over the BTC-USD
# order books of its constituent exchanges: Coinbase, Kraken, Bitstamp, Gemini, Bullish, Crypto.com
# and LMAX Digital (itBit was suspended 2026-07-27). Coinbase alone misses moves led elsewhere, so
# each venue's public BTC feed (prints plus best bid/ask) is recorded verbatim too, one source
# directory per venue, all in one process. tick_archiver parses them into <venue>_trades and
# <venue>_quotes; the raw lines are kept, so a parser fix can re-archive old hours.

SPOT_STATE: Dict[str, Dict] = {}


class _Conns:
    """The open sockets of one venue session, closed together (heartbeat_loop closes self.ws)."""

    def __init__(self) -> None:
        self.socks: List = []

    async def close(self) -> None:
        for ws in self.socks:
            await ws.close()


class SpotRecorder(Recorder):
    """One exchange's public BTC market data. A subclass gives ``streams`` (url, subscribe
    messages) and may override ``kind`` (message type label for the counters), ``check``
    (sequence/trade-id gap detection), ``reply`` (answers the venue requires, e.g. heartbeats),
    ``keepalive`` and ``must_reconnect``."""
    streams: List[Tuple[str, List[Dict]]] = []
    silence_s = 30
    subscribe_delay_s = 0.0
    keepalive_s = 0

    def __init__(self) -> None:
        super().__init__()
        self._ssl = ssl.create_default_context(cafile=certifi.where())
        self.last_seq: Dict[str, int] = {}

    def silence_limit(self) -> float:
        return self.silence_s

    async def publish(self, key: str, state: Dict) -> None:
        SPOT_STATE[self.source] = state     # one collector_state row for all venues (run_spot)

    def kind(self, data) -> str:
        if isinstance(data, dict):
            return str(data.get("type") or data.get("channel") or data.get("event") or data.get("method") or "?")[:40]
        return "list"

    def check(self, data) -> None:
        pass

    def reply(self, data) -> Optional[Dict]:
        return None

    def keepalive(self) -> Optional[Dict]:
        return None

    def must_reconnect(self, data) -> bool:
        return False

    def seq_check(self, key: str, value, step_ok=lambda prev, cur: cur == prev + 1) -> None:
        """Record a gap when ``value`` does not follow the last one seen for ``key``."""
        try:
            cur = int(value)
        except (TypeError, ValueError):
            return
        prev = self.last_seq.get(key)
        if prev is not None and cur > prev and not step_ok(prev, cur):
            self.seq_gaps += 1
            self.meta("seq_gap", key=key, expected=prev + 1, got=cur)
        if prev is None or cur > prev:
            self.last_seq[key] = cur

    async def pump(self, ws, url: str, subs: List[Dict]) -> None:
        if self.subscribe_delay_s:
            await asyncio.sleep(self.subscribe_delay_s)
        for msg in subs:
            await ws.send(json.dumps(msg))
        async for raw in ws:
            rt = _ns()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                data = json.loads(raw)
            except ValueError:
                self.errors.append(f"non-json {raw[:120]}")
                continue
            if "\n" in raw.strip():           # one line per message, whatever the venue sends
                raw = json.dumps(data, separators=(",", ":"))
            self.record(rt, raw, self.kind(data))
            out = self.reply(data)
            if out is not None:
                await ws.send(json.dumps(out))
            if isinstance(data, dict) and (data.get("error") or data.get("event") == "bts:error"
                                           or data.get("type") == "error" or data.get("success") is False):
                self.errors.append(f"{url} {raw[:200]}")
            self.check(data)
            if self.must_reconnect(data):
                print(f"{self.source}: venue asked for a reconnect", flush=True)
                return

    async def keepalive_loop(self, ws) -> None:
        while self.keepalive_s:
            await asyncio.sleep(self.keepalive_s)
            msg = self.keepalive()
            if msg is not None:
                await ws.send(json.dumps(msg))

    async def session(self) -> None:
        import websockets
        conns = _Conns()
        tasks = []
        try:
            for url, subs in self.streams:
                ws = await websockets.connect(url, ssl=self._ssl, ping_interval=20, ping_timeout=20,
                                              open_timeout=15, max_size=16 << 20, max_queue=4096)
                conns.socks.append(ws)
                tasks.append(asyncio.create_task(self.pump(ws, url, subs)))
                if self.keepalive_s:
                    tasks.append(asyncio.create_task(self.keepalive_loop(ws)))
            self.ws = conns
            self.connected_ns = _ns()
            self.last_seq = {}
            self.meta("connected", urls=[u for u, _ in self.streams])
            print(f"{self.source} tick recorder connected {[u for u, _ in self.streams]}", flush=True)
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if t.exception() is not None:
                    raise t.exception()
        finally:
            self.ws = None
            for t in tasks:
                t.cancel()
            await conns.close()


class KrakenRecorder(SpotRecorder):
    """WS v2: every BTC/USD print (``trade``, side = taker) and best bid/ask on each change
    (``ticker`` with event_trigger bbo). trade_id is consecutive per pair; 1/s heartbeats."""
    source = "kraken"
    symbol = os.getenv("TAU_TICK_KRAKEN_SYMBOL", "BTC/USD")
    streams = [("wss://ws.kraken.com/v2", [
        {"method": "subscribe", "params": {"channel": "trade", "symbol": [symbol], "snapshot": False}},
        {"method": "subscribe", "params": {"channel": "ticker", "symbol": [symbol], "event_trigger": "bbo"}},
    ])]
    silence_s = 15

    def kind(self, data) -> str:
        if isinstance(data, dict):
            return str(data.get("channel") or data.get("method") or "?")
        return "list"

    def check(self, data) -> None:
        if isinstance(data, dict) and data.get("channel") == "trade" and data.get("type") == "update":
            for t in data.get("data") or []:
                self.seq_check("trade:" + str(t.get("symbol")), t.get("trade_id"))


class BitstampRecorder(SpotRecorder):
    """Every btcusd print (live_trades; type 0 = taker buy) and the top-100 book on each change
    (order_book; its first level is the touch). Trade ids are global, so no gap check here.
    Bitstamp sends bts:request_reconnect before maintenance."""
    source = "bitstamp"
    pair = os.getenv("TAU_TICK_BITSTAMP_PAIR", "btcusd")
    streams = [("wss://ws.bitstamp.net", [
        {"event": "bts:subscribe", "data": {"channel": "live_trades_" + pair}},
        {"event": "bts:subscribe", "data": {"channel": "order_book_" + pair}},
    ])]
    silence_s = 60

    def kind(self, data) -> str:
        if isinstance(data, dict):
            ch = str(data.get("channel") or "")
            return str(data.get("event") or "?") + (":book" if ch.startswith("order_book") else "")
        return "list"

    def must_reconnect(self, data) -> bool:
        return isinstance(data, dict) and data.get("event") == "bts:request_reconnect"


class GeminiRecorder(SpotRecorder):
    """v1 market data for BTCUSD: prints and top-of-book changes, with 5s heartbeats.
    socket_sequence counts every message on the socket from 0, so a jump is a lost message."""
    source = "gemini"
    symbol = os.getenv("TAU_TICK_GEMINI_SYMBOL", "BTCUSD")
    streams = [(f"wss://api.gemini.com/v1/marketdata/{symbol}?top_of_book=true&trades=true&heartbeat=true", [])]
    silence_s = 20

    def check(self, data) -> None:
        if isinstance(data, dict) and "socket_sequence" in data:
            self.seq_check("socket", data.get("socket_sequence"))


class BullishRecorder(SpotRecorder):
    """Unauthenticated JSON-RPC market data: anonymous trades and level-1 book, on two sockets.
    Bullish's institutional BTC market is quoted in USDC as well as USD, so both are taken."""
    source = "bullish"
    symbols = [s.strip() for s in os.getenv("TAU_TICK_BULLISH_SYMBOLS", "BTCUSD,BTCUSDC").split(",") if s.strip()]
    base = "wss://api.exchange.bullish.com/trading-api/v1/market-data"
    streams = [
        (base + "/trades", [{"jsonrpc": "2.0", "type": "command", "method": "subscribe",
                             "params": {"topic": "anonymousTrades", "symbol": s}, "id": str(i + 1)}
                            for i, s in enumerate(symbols)]),
        (base + "/orderbook", [{"jsonrpc": "2.0", "type": "command", "method": "subscribe",
                                "params": {"topic": "l1Orderbook", "symbol": s}, "id": str(i + 101)}
                               for i, s in enumerate(symbols)]),
    ]
    silence_s = 60
    keepalive_s = 60

    def kind(self, data) -> str:
        if isinstance(data, dict):
            return str(data.get("dataType") or data.get("type") or data.get("method") or "?")[:40]
        return "list"

    def keepalive(self) -> Optional[Dict]:
        return {"jsonrpc": "2.0", "type": "command", "method": "keepalivePing", "params": {}, "id": str(_ns())}


class CryptoComRecorder(SpotRecorder):
    """Exchange v1 market socket: trade.BTC_USD prints (side = taker) and ticker.BTC_USD best
    bid/ask. The venue wants a 1s pause before the first request and an answer to every
    public/heartbeat, or it drops the socket."""
    source = "cryptocom"
    instrument = os.getenv("TAU_TICK_CRYPTOCOM_INSTRUMENT", "BTC_USD")
    streams = [("wss://stream.crypto.com/exchange/v1/market", [
        {"id": 1, "method": "subscribe", "params": {"channels": ["trade." + instrument, "ticker." + instrument]}},
    ])]
    subscribe_delay_s = 1.1
    silence_s = 45

    def kind(self, data) -> str:
        if isinstance(data, dict):
            res = data.get("result") or {}
            return str((res.get("channel") if isinstance(res, dict) else None) or data.get("method") or "?")
        return "list"

    def reply(self, data) -> Optional[Dict]:
        if isinstance(data, dict) and data.get("method") == "public/heartbeat":
            return {"id": data.get("id"), "method": "public/respond-heartbeat"}
        return None


class LmaxRecorder(SpotRecorder):
    """LMAX Digital public market data: TICKER (last trade, best bid/ask) and ORDER_BOOK."""
    source = "lmax"
    instrument = os.getenv("TAU_TICK_LMAX_INSTRUMENT", "btc-usd")
    streams = [("wss://public-data-api.london-digital.lmax.com/v1/web-socket", [
        {"type": "SUBSCRIBE", "channels": [{"name": "TICKER", "instruments": [instrument]},
                                           {"name": "ORDER_BOOK", "instruments": [instrument]}]},
    ])]
    silence_s = 60


SPOT_RECORDERS = {c.source: c for c in (KrakenRecorder, BitstampRecorder, GeminiRecorder, BullishRecorder,
                                        CryptoComRecorder, LmaxRecorder)}


async def spot_heartbeat_loop() -> None:
    """tick_recorder_spot: the process heartbeat, with each venue's recorder state inside. The
    alerter pages only when the whole process stops; one venue's outage shows in its entry."""
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        state = {"host": socket.gethostname(), "venues": dict(SPOT_STATE),
                 "live": sorted(v for v, st in SPOT_STATE.items()
                                if st.get("last_msg_age_s") is not None and st["last_msg_age_s"] < 60)}
        await asyncio.to_thread(write_heartbeat, "tick_recorder_spot", state)


async def run_spot(venues: List[str]) -> None:
    await asyncio.gather(spot_heartbeat_loop(),
                         *(SPOT_RECORDERS[v]().run() for v in venues if v in SPOT_RECORDERS))


def main(argv: List[str]) -> None:
    which = argv[1] if len(argv) > 1 else "kalshi"
    if which == "spot":
        print(f"tick recorder spot {SPOT_VENUES} -> {TICK_DIR}", flush=True)
        asyncio.run(run_spot(SPOT_VENUES))
        return
    rec = {"kalshi": KalshiRecorder, "coinbase": CoinbaseRecorder, **SPOT_RECORDERS}[which]()
    print(f"tick recorder {which} -> {TICK_DIR}", flush=True)
    asyncio.run(rec.run())


if __name__ == "__main__":
    main(sys.argv)
