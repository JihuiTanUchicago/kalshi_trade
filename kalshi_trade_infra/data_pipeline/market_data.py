"""The live book, as of now.

Everything that touches money must price against this module and never against
`model_features_1m`. That table holds completed one-minute bars: the live
engine used to read `rows[-1]` and build its order from it, which on
2026-09-27 meant quoting bid 0.58 / ask 0.59 into a book that was actually
0.70 / 0.71. Buys priced under the real ask never crossed and were cancelled;
sells priced under the real bid crossed instantly and gave the difference
away. Same root cause, opposite symptoms.

The split this module enforces:

    model features  ->  the 1-minute bar   (what the model was trained on)
    prices and edge ->  the live book      (what you can actually trade at)

A websocket quote is used when it is fresh, and REST is both the fallback and
the freshness backstop. A socket that silently stops updating looks exactly
like a calm market, so staleness is always measured, never assumed.
"""
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from data_pipeline.common import api_get, utc_now

# Kalshi's ticker channel pushes on every top-of-book change. Anything older
# than this is re-fetched over REST before it is allowed to price an order.
DEFAULT_MAX_QUOTE_AGE_SECONDS = 2.0


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


@dataclass(frozen=True)
class Quote:
    """Top of book for one market. Prices in dollars, sizes in contracts."""

    ticker: str
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    yes_bid_size: Optional[float]
    yes_ask_size: Optional[float]
    as_of: datetime
    source: str  # "websocket" or "rest"

    def age_seconds(self, now: Optional[datetime] = None) -> float:
        now = now or utc_now()
        as_of = self.as_of
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return max(0.0, (now - as_of).total_seconds())

    @property
    def tradable(self) -> bool:
        return bool(self.yes_bid and self.yes_ask and self.yes_bid > 0 and self.yes_ask > 0)

    @property
    def spread(self) -> Optional[float]:
        if not self.tradable:
            return None
        return self.yes_ask - self.yes_bid


class MarketFeed:
    """Current top of book, websocket-first with a REST backstop.

    `ws_feed` is anything exposing `get_latest(ticker) -> dict | None` - in
    production that is the KalshiWsFeed the forward collector already runs, so
    this adds a reader rather than a second socket. Omit it and every read is
    a REST call, which is slower but always correct.
    """

    def __init__(
        self,
        ws_feed: Any = None,
        max_quote_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS,
    ) -> None:
        self._ws_feed = ws_feed
        self._max_age = float(max_quote_age_seconds)
        self._lock = threading.Lock()
        self._last_rest: Dict[str, Quote] = {}
        self.stats = {"websocket": 0, "rest": 0, "miss": 0}

    # -- sources ---------------------------------------------------------
    def _from_websocket(self, ticker: str) -> Optional[Quote]:
        if self._ws_feed is None:
            return None
        try:
            msg = self._ws_feed.get_latest(ticker)
        except Exception:
            return None
        if not msg:
            return None
        # The socket carries no receive time of its own, so the feed's own
        # message timestamp is used when present and "now" otherwise. An
        # absent timestamp must not read as fresh forever.
        as_of = None
        raw_ts = msg.get("ts") or msg.get("time")
        if isinstance(raw_ts, (int, float)):
            as_of = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
        if as_of is None:
            return None
        return Quote(
            ticker=ticker,
            yes_bid=_to_float(msg.get("yes_bid_dollars")),
            yes_ask=_to_float(msg.get("yes_ask_dollars")),
            yes_bid_size=_to_float(msg.get("yes_bid_size_fp") or msg.get("yes_bid_size")),
            yes_ask_size=_to_float(msg.get("yes_ask_size_fp") or msg.get("yes_ask_size")),
            as_of=as_of,
            source="websocket",
        )

    def _from_rest(self, ticker: str) -> Optional[Quote]:
        try:
            market = (api_get(f"/markets/{ticker}") or {}).get("market") or {}
        except Exception as e:
            print(f"[WARN] market feed REST lookup failed for {ticker}: {e}")
            return None
        if not market:
            return None
        return Quote(
            ticker=ticker,
            yes_bid=_to_float(market.get("yes_bid_dollars")),
            yes_ask=_to_float(market.get("yes_ask_dollars")),
            yes_bid_size=_to_float(market.get("yes_bid_size_fp") or market.get("yes_bid_size")),
            yes_ask_size=_to_float(market.get("yes_ask_size_fp") or market.get("yes_ask_size")),
            as_of=utc_now(),
            source="rest",
        )

    # -- public ----------------------------------------------------------
    def quote(self, ticker: str, max_age_seconds: Optional[float] = None) -> Optional[Quote]:
        """Top of book no older than `max_age_seconds`, or None.

        Returning None is a valid and expected answer: no quote means no
        order. Pricing from whatever happened to be lying around is what this
        module exists to prevent.
        """
        limit = self._max_age if max_age_seconds is None else float(max_age_seconds)
        ws_quote = self._from_websocket(ticker)
        if ws_quote is not None and ws_quote.tradable and ws_quote.age_seconds() <= limit:
            with self._lock:
                self.stats["websocket"] += 1
            return ws_quote
        rest_quote = self._from_rest(ticker)
        with self._lock:
            if rest_quote is not None and rest_quote.tradable:
                self._last_rest[ticker] = rest_quote
                self.stats["rest"] += 1
            else:
                self.stats["miss"] += 1
        if rest_quote is not None and rest_quote.tradable:
            return rest_quote
        return None
