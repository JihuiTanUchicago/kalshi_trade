import os
import time
import base64
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

import pymysql
import requests
from dateutil import parser as date_parser
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

KALSHI_BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
# Host for authenticated calls. Configurable so the order path can be proven
# against Kalshi's demo environment before it is pointed at real money.
KALSHI_API_HOST = os.getenv("KALSHI_API_HOST", "https://api.elections.kalshi.com").rstrip("/")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "kalshi_trade")
KALSHI_KEY_ID = os.getenv("KALSHI_WS_KEY_ID") or os.getenv("PROD_KEYID")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_WS_PRIVATE_KEY_PATH") or os.getenv("PROD_KEYFILE")
_KALSHI_PRIVATE_KEY = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sleep_with_jitter(base_seconds: float) -> None:
    time.sleep(base_seconds + (0.2 * base_seconds))


def get_db_conn():
    if not all([MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE]):
        raise RuntimeError("Missing MySQL env vars: MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        # A wide-window history load (partition math / run_forever backtests) legitimately reads
        # for minutes; the old 30s fired the socket read-timeout MID-RESULT, desyncing the socket
        # so the NEXT query died with "Packet sequence number wrong". 600s safely exceeds the
        # longest legitimate read and matches the Bedrock budget, while connect_timeout stays short
        # so a dead host still fails fast.
        read_timeout=600,
        write_timeout=600,
    )


def parse_iso_to_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return date_parser.isoparse(value)
    except Exception:
        # Best-effort fallback for malformed fractional seconds
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)


def api_get(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    url = f"{KALSHI_BASE_URL}{path}"
    retries = 0
    while True:
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 429:
            retries += 1
            if retries > 8:
                raise RuntimeError(f"429 persisted for {url} params={params}")
            sleep_with_jitter(min(1.0 * retries, 8.0))
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"GET {url} failed {resp.status_code}: {resp.text[:400]}")
        return resp.json()


def _get_private_key():
    global _KALSHI_PRIVATE_KEY
    if _KALSHI_PRIVATE_KEY is not None:
        return _KALSHI_PRIVATE_KEY
    if not KALSHI_PRIVATE_KEY_PATH or not os.path.exists(KALSHI_PRIVATE_KEY_PATH):
        raise RuntimeError("Missing Kalshi private key file for authenticated endpoints")
    with open(KALSHI_PRIVATE_KEY_PATH, "rb") as f:
        _KALSHI_PRIVATE_KEY = serialization.load_pem_private_key(f.read(), password=None)
    return _KALSHI_PRIVATE_KEY


# (key_id, loaded private key). None means the house account from the env -
# the customer app passes each user's own key so their orders and balance
# never touch the house account.
KalshiCredentials = Tuple[str, Any]


def kalshi_auth_headers(method: str, path: str, credentials: Optional[KalshiCredentials] = None) -> Dict[str, str]:
    if credentials is None:
        if not KALSHI_KEY_ID:
            raise RuntimeError("Missing Kalshi key id for authenticated endpoints")
        key_id, pk = KALSHI_KEY_ID, _get_private_key()
    else:
        key_id, pk = credentials
    ts = str(int(time.time() * 1000))
    signing_path = path.split("?", 1)[0]
    msg = ts + method.upper() + signing_path
    sig = base64.b64encode(
        pk.sign(
            msg.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    ).decode("utf-8")
    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def api_post_auth(
    path: str, body: Dict[str, Any], timeout: int = 20, credentials: Optional[KalshiCredentials] = None,
    timing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """`timing` (opt): when a dict is passed, this fills it with `sign_ms` (local encode+RSA-PSS
    sign), `net_ms` (the request round-trip = network RTT + exchange processing) and `http_status`.
    Purely additive measurement for the order path (Execution P2); every other caller omits it and is
    unaffected. Measured around the existing calls — it never changes what is sent or when."""
    url = f"{KALSHI_API_HOST}{path}"
    _t0 = time.perf_counter()
    headers = kalshi_auth_headers("POST", path, credentials)
    _t1 = time.perf_counter()
    resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    _t2 = time.perf_counter()
    if timing is not None:
        timing["sign_ms"] = (_t1 - _t0) * 1000.0
        timing["net_ms"] = (_t2 - _t1) * 1000.0
        timing["http_status"] = resp.status_code
    if resp.status_code >= 400:
        raise RuntimeError(f"POST {url} failed {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def api_get_auth(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 20,
    credentials: Optional[KalshiCredentials] = None,
) -> Dict[str, Any]:
    url = f"{KALSHI_API_HOST}{path}"
    headers = kalshi_auth_headers("GET", path, credentials)
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} failed {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def get_kalshi_cash_balance_dollars(credentials: Optional[KalshiCredentials] = None) -> Optional[float]:
    """
    Best-effort account cash balance fetch for live equity marking.
    Returns None when auth/endpoint fields are unavailable.
    """
    candidates = [
        "/trade-api/v2/portfolio/balance",
        "/trade-api/v2/portfolio",
    ]
    field_scales = {
        "available_cash_dollars": 1.0,
        "cash_dollars": 1.0,
        "balance_dollars": 1.0,
        "available_balance_dollars": 1.0,
        "available_cash_cents": 0.01,
        "cash_cents": 0.01,
        "balance_cents": 0.01,
        "available_balance_cents": 0.01,
    }
    generic_fields = {"available_cash", "cash", "balance", "available_balance"}
    for path in candidates:
        try:
            data = api_get_auth(path, credentials=credentials)
        except Exception:
            continue
        objs = []
        if isinstance(data, dict):
            objs.append(data)
            for v in data.values():
                if isinstance(v, dict):
                    objs.append(v)
        for obj in objs:
            for field, scale in field_scales.items():
                if field not in obj:
                    continue
                try:
                    return float(obj[field]) * scale
                except Exception:
                    continue
            for field in generic_fields:
                if field not in obj:
                    continue
                try:
                    raw = float(obj[field])
                    # Heuristic: integer-like values >= 100 are usually cents.
                    if abs(raw) >= 100 and abs(raw - round(raw)) < 1e-9:
                        return raw / 100.0
                    return raw
                except Exception:
                    continue
    return None


def next_20s_mark(now: Optional[datetime] = None) -> datetime:
    """Next :00/:20/:40 wall-clock mark. Four collectors ticked on their own
    copy of this; they now share one."""
    now = (now or utc_now()).replace(microsecond=0)
    return now + timedelta(seconds=20 - (now.second % 20))


