import asyncio
import base64
import json
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

import requests
from requests.exceptions import HTTPError

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

import websockets
import ssl
import certifi


class Environment(Enum):
    DEMO = "demo"
    PROD = "prod"


class KalshiBaseClient:
    """Base client class for interacting with the Kalshi API."""

    def __init__(
        self,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.DEMO,
    ):
        """
        Args:
            key_id: Your Kalshi API key ID.
            private_key: Your RSA private key.
            environment: DEMO or PROD.
        """
        self.key_id = key_id
        self.private_key = private_key
        self.environment = environment
        self.last_api_call = datetime.now()

        if self.environment == Environment.DEMO:
            self.HTTP_BASE_URL = "https://demo-api.kalshi.co"
            self.WS_BASE_URL = "wss://demo-api.kalshi.co"
        elif self.environment == Environment.PROD:
            self.HTTP_BASE_URL = "https://api.elections.kalshi.com"
            self.WS_BASE_URL = "wss://api.elections.kalshi.com"
        else:
            raise ValueError("Invalid environment")

    def request_headers(self, method: str, path: str) -> Dict[str, Any]:
        """Generates the required authentication headers for API requests."""
        current_time_milliseconds = int(time.time() * 1000)
        timestamp_str = str(current_time_milliseconds)

        # Remove query params from path for signing
        path_parts = path.split("?")
        msg_string = timestamp_str + method + path_parts[0]
        signature = self.sign_pss_text(msg_string)

        headers = {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
        }
        return headers

    def sign_pss_text(self, text: str) -> str:
        """Signs the text using RSA-PSS and returns base64 encoded signature."""
        message = text.encode("utf-8")
        try:
            signature = self.private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )
            return base64.b64encode(signature).decode("utf-8")
        except InvalidSignature as e:
            raise ValueError("RSA sign PSS failed") from e


class KalshiHttpClient(KalshiBaseClient):
    """Client for handling HTTP connections to the Kalshi API."""

    def __init__(
        self,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.DEMO,
    ):
        super().__init__(key_id, private_key, environment)
        self.host = self.HTTP_BASE_URL
        self.exchange_url = "/trade-api/v2/exchange"
        self.markets_url = "/trade-api/v2/markets"
        self.portfolio_url = "/trade-api/v2/portfolio"

    def rate_limit(self) -> None:
        """Built-in rate limiter to prevent exceeding API rate limits."""
        THRESHOLD_IN_MILLISECONDS = 100
        now = datetime.now()
        threshold_in_microseconds = 1000 * THRESHOLD_IN_MILLISECONDS
        threshold_in_seconds = THRESHOLD_IN_MILLISECONDS / 1000
        if now - self.last_api_call < timedelta(
            microseconds=threshold_in_microseconds
        ):
            time.sleep(threshold_in_seconds)
        self.last_api_call = datetime.now()

    def raise_if_bad_response(self, response: requests.Response) -> None:
        """Raises an HTTPError if the response status code indicates an error."""
        if response.status_code not in range(200, 299):
            # Raise with body for easier debugging
            try:
                body = response.json()
            except Exception:
                body = response.text
            raise HTTPError(
                f"HTTP {response.status_code} for {response.request.method} {response.url}: {body}"
            )

    def post(self, path: str, body: dict) -> Any:
        """Performs an authenticated POST request to the Kalshi API."""
        self.rate_limit()
        response = requests.post(
            self.host + path, json=body, headers=self.request_headers("POST", path)
        )
        self.raise_if_bad_response(response)
        return response.json()

    def get(self, path: str, params: Dict[str, Any] = {}) -> Any:
        """Performs an authenticated GET request to the Kalshi API."""
        self.rate_limit()
        response = requests.get(
            self.host + path, headers=self.request_headers("GET", path), params=params
        )
        self.raise_if_bad_response(response)
        return response.json()

    def delete(self, path: str, params: Dict[str, Any] = {}) -> Any:
        """Performs an authenticated DELETE request to the Kalshi API."""
        self.rate_limit()
        response = requests.delete(
            self.host + path, headers=self.request_headers("DELETE", path), params=params
        )
        self.raise_if_bad_response(response)
        return response.json()

    def get_balance(self) -> Dict[str, Any]:
        """Retrieves the account balance."""
        return self.get(self.portfolio_url + "/balance")

    def get_exchange_status(self) -> Dict[str, Any]:
        """Retrieves the exchange status."""
        return self.get(self.exchange_url + "/status")

    def get_trades(
        self,
        ticker: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        max_ts: Optional[int] = None,
        min_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Retrieves trades based on provided filters."""
        params = {
            "ticker": ticker,
            "limit": limit,
            "cursor": cursor,
            "max_ts": max_ts,
            "min_ts": min_ts,
        }
        params = {k: v for k, v in params.items() if v is not None}
        return self.get(self.markets_url + "/trades", params=params)


class KalshiWebSocketClient(KalshiBaseClient):
    """Client for handling WebSocket connections to the Kalshi API."""

    def __init__(
        self,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.DEMO,
    ):
        super().__init__(key_id, private_key, environment)
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.url_suffix = "/trade-api/ws/v2"
        self.message_id = 1

        # Prepare a verified SSL context once and reuse it
        self._ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        self._ssl_ctx.check_hostname = True
        self._ssl_ctx.verify_mode = ssl.CERT_REQUIRED

        # Reasonable defaults; tweak as needed
        self._open_timeout = 15
        self._close_timeout = 10
        self._ping_interval = 20
        self._ping_timeout = 20
        self._max_queue = 1024

    async def connect(self):
        """Establishes a WebSocket connection using authentication."""
        host = self.WS_BASE_URL + self.url_suffix
        auth_headers = self.request_headers("GET", self.url_suffix)

        try:
            async with websockets.connect(
                host,
                additional_headers=auth_headers,
                ssl=self._ssl_ctx,
                open_timeout=self._open_timeout,
                close_timeout=self._close_timeout,
                ping_interval=self._ping_interval,
                ping_timeout=self._ping_timeout,
                max_queue=self._max_queue,
            ) as websocket:
                self.ws = websocket
                await self.on_open()
                await self.handler()
        except websockets.InvalidStatusCode as e:
            await self.on_error(f"WebSocket HTTP error: {e.status_code}")
            raise
        except ssl.SSLError as e:
            await self.on_error(f"TLS/SSL error during handshake: {e}")
            raise
        except Exception as e:
            await self.on_error(e)
            raise

    async def on_open(self):
        """Callback when WebSocket connection is opened."""
        print("WebSocket connection opened.")
        await self.subscribe_to_tickers()

    async def subscribe_to_tickers(self):
        """Subscribe to ticker updates for all markets."""
        if not self.ws:
            raise RuntimeError("WebSocket is not connected")
        subscription_message = {
            "id": self.message_id,
            "cmd": "subscribe",
            "params": {"channels": ["ticker"]},
        }
        await self.ws.send(json.dumps(subscription_message))
        self.message_id += 1

    async def handler(self):
        """Handle incoming messages."""
        try:
            assert self.ws is not None
            async for message in self.ws:
                await self.on_message(message)
        except websockets.ConnectionClosed as e:
            await self.on_close(e.code, e.reason)
        except ssl.SSLError as e:
            await self.on_error(f"TLS/SSL error: {e}")
        except Exception as e:
            await self.on_error(e)

    async def on_message(self, message: str):
        """Callback for handling incoming messages."""
        print("Received message:", message)

    async def on_error(self, error: Any):
        """Callback for handling errors."""
        print("WebSocket error:", error)

    async def on_close(self, close_status_code: int, close_msg: Optional[str]):
        """Callback when WebSocket connection is closed."""
        print(
            "WebSocket connection closed with code:",
            close_status_code,
            "and message:",
            close_msg,
        )


