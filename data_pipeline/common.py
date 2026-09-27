import os
import time
import base64
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import pymysql
import requests
from dateutil import parser as date_parser
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

KALSHI_BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
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
        read_timeout=30,
        write_timeout=30,
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


def kalshi_auth_headers(method: str, path: str) -> Dict[str, str]:
    if not KALSHI_KEY_ID:
        raise RuntimeError("Missing Kalshi key id for authenticated endpoints")
    ts = str(int(time.time() * 1000))
    signing_path = path.split("?", 1)[0]
    msg = ts + method.upper() + signing_path
    pk = _get_private_key()
    sig = base64.b64encode(
        pk.sign(
            msg.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    ).decode("utf-8")
    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KALSHI_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def api_post_auth(path: str, body: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    url = f"https://api.elections.kalshi.com{path}"
    headers = kalshi_auth_headers("POST", path)
    resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"POST {url} failed {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def api_get_auth(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    url = f"https://api.elections.kalshi.com{path}"
    headers = kalshi_auth_headers("GET", path)
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} failed {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def get_kalshi_cash_balance_dollars() -> Optional[float]:
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
            data = api_get_auth(path)
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


