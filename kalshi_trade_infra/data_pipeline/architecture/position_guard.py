"""Pre-trade guard: a sell may never take the account past flat.

The events/orders endpoint speaks only the YES leg, and Kalshi nets it: an
``ask`` against a YES position you do not hold does not fail, it OPENS a short
(a NO position). So a sell sized from our own book is only as safe as our book.
On 2026-09-27 the book held phantom positions (cancelled IOC orders recorded as
fills), the engine "closed" them, and the strategy - which only ever buys YES -
ended up short. The exchange knew what we held the whole time; nothing asked it.

This guard asks it, immediately before every SELL child the kernel sends, and
sizes the sell to what the exchange says is held:

  * held >= qty   -> sent unchanged
  * 0 < held < qty -> sent for ``held`` only (the exit still gets flat)
  * held <= 0     -> refused, reported as a clean ``unfilled``
  * read fails    -> refused (fail closed: an unread position is an unknown one)

It can only ever SHRINK or refuse a sell, never enlarge one, and it never
touches a BUY, so it cannot weaken any other guard. A refused or shrunk exit
leaves the engine's book row in place, which is exactly what the reconciler
(``live_alerter.position_mismatches``) then flags.

Exchange position reads can lag a fill by a moment, and the kernel sends an
exit's escalating children back to back. So after a sell fills, the guard
remembers what should now be held and, for ``memory_seconds``, trusts the
LOWER of that and the exchange's answer. That can only under-sell (the next
tick sells the rest); it can never let a stale read oversell.

Signs follow ``/portfolio/positions``: + is YES, - is NO. Selling YES needs a
positive net; selling NO needs a negative one.
"""
import threading
import time
from typing import Callable, Dict, Optional, Tuple

from data_pipeline.common import api_get_auth

POSITIONS_PATH = "/trade-api/v2/portfolio/positions"


def _held_on_side(net: int, side: str) -> int:
    """Contracts of ``side`` held, from the exchange's signed net."""
    return max(0, -net) if str(side).lower() == "no" else max(0, net)


def _filled(res: dict) -> int:
    try:
        return int(float(((res or {}).get("resp") or {}).get("fill_count") or 0))
    except (TypeError, ValueError):
        return 0


def _refused(client_order_id: Optional[str], reason: str) -> Dict:
    """A result the kernel's fill parser reads as a clean no-fill (fill_count 0)."""
    return {"client_order_id": client_order_id, "resp": {"fill_count": "0.00"},
            "position_guard_blocked": reason}


class PositionGuard:
    """Wraps a kernel submitter; ``read_net(ticker)`` returns the exchange's
    signed net position for that ticker (+ YES, - NO, 0 flat)."""

    def __init__(self, read_net: Callable[[str], int], memory_seconds: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._read_net = read_net
        self.memory_seconds = float(memory_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        # (ticker, side) -> (contracts expected held after our last sell fill, when)
        self._expected: Dict[Tuple[str, str], Tuple[int, float]] = {}

    def _held(self, ticker: str, side: str) -> Tuple[int, int]:
        """(contracts of ``side`` we may sell, the exchange's signed net)."""
        net = int(self._read_net(ticker))
        held = _held_on_side(net, side)
        with self._lock:
            mem = self._expected.get((ticker, str(side).lower()))
            if mem is not None and self._clock() - mem[1] <= self.memory_seconds:
                held = min(held, mem[0])  # a lagging read can never oversell
        return held, net

    def wrap(self, submit: Callable[..., dict]) -> Callable[..., dict]:
        def guarded(ticker: str, action: str, side: str, qty: int, price: float,
                    client_order_id: Optional[str] = None) -> dict:
            if str(action).lower() != "sell":
                return self._send(submit, ticker, action, side, qty, price, client_order_id)
            try:
                held, net = self._held(ticker, side)
            except Exception as e:
                print("[position_guard] SELL refused, could not read Kalshi position for %s: %s"
                      % (ticker, e), flush=True)
                return _refused(client_order_id, "position_unreadable")
            if held <= 0:
                print("[position_guard] SELL refused: %s %s %d but Kalshi holds net %d - would go short"
                      % (ticker, side, qty, net), flush=True)
                return _refused(client_order_id, "nothing_held")
            send_qty = min(int(qty), held)
            if send_qty < int(qty):
                print("[position_guard] SELL shrunk %s %s %d -> %d to Kalshi's held position"
                      % (ticker, side, qty, send_qty), flush=True)
            res = self._send(submit, ticker, action, side, send_qty, price, client_order_id)
            f = _filled(res)
            if f > 0:
                with self._lock:
                    self._expected[(ticker, str(side).lower())] = (max(0, held - f), self._clock())
            return res

        return guarded

    @staticmethod
    def _send(submit, ticker, action, side, qty, price, client_order_id):
        # Only pass the id when there is one, so a submitter that does not take
        # it (SimulatedVenue, legacy callers) is never called with it.
        if client_order_id is None:
            return submit(ticker, action, side, qty, price)
        return submit(ticker, action, side, qty, price, client_order_id=client_order_id)


def net_from_positions_response(body: dict, ticker: str) -> int:
    """The signed net for ``ticker`` out of a ``/portfolio/positions`` body; 0 if absent."""
    for p in (body or {}).get("market_positions") or []:
        if p.get("ticker") == ticker:
            return int(float(p.get("position_fp") or p.get("position") or 0))
    return 0


def exchange_net_reader(credentials=None) -> Callable[[str], int]:
    """``read_net`` for PositionGuard against production Kalshi, as ``credentials``
    (None = the operator key from the environment, as the old engine signs)."""

    def read(ticker: str) -> int:
        body = api_get_auth(POSITIONS_PATH, params={"ticker": ticker}, credentials=credentials, timeout=5)
        return net_from_positions_response(body, ticker)

    return read


def position_guarded_submitter(submit: Callable[..., dict], read_net: Callable[[str], int]) -> Callable[..., dict]:
    """Wrap ``submit`` so no SELL can take the account past flat on its ticker."""
    return PositionGuard(read_net).wrap(submit)
