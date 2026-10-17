"""Native Exa retrieval without application spending or request quotas."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import ipaddress
import json
import os
import time
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import requests

from app.market_data_common import MarketDataError, iso, timestamp, utc_now

API_URL = "https://api.exa.ai"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_EXCERPT_CHARS = 2400


class ExaError(RuntimeError):
    """Messages are safe for user-visible events: no headers or response bodies."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def reported_cost(value) -> str:
    """Validate provider telemetry without imposing a spending ceiling."""
    try:
        if isinstance(value, bool):
            raise ValueError()
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError()
        return str(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise ExaError("invalid_data", "Exa returned an invalid reported request cost.") from None


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    historical_enabled: bool = False

    def __post_init__(self):
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ExaError("not_configured", "EXA_API_KEY is missing from the agent worker environment.")
        if not self.api_key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise ExaError("configuration", "The Exa credential has an invalid format.")
        if type(self.historical_enabled) is not bool:
            raise ExaError("configuration", "Exa historical access must be a boolean setting.")

    @classmethod
    def from_env(cls) -> "Config":
        return cls(os.getenv("EXA_API_KEY", ""), os.getenv("TAU_EXA_HISTORICAL_ENABLED", "0") == "1")


def public_url(value: str) -> str:
    """Only public HTTP(S) source identities; never forwarding arbitrary HTTP headers."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError()
        u = urlsplit(value)
        host = u.hostname
        if u.scheme not in {"http", "https"} or not host or u.username or u.password or u.port not in {None, 80, 443}:
            raise ValueError()
        if host.lower() == "localhost" or host.lower().endswith((".local", ".internal", ".localhost")) or "." not in host:
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError()
        if any(c in value for c in "<>\\"):
            raise ValueError()
        return urlunsplit((u.scheme, u.netloc, u.path, u.query, ""))
    except (ValueError, TypeError):
        raise ExaError("invalid_source", "Exa source URLs must identify public HTTP(S) pages without credentials.") from None


class ExaDataClient:
    def __init__(self, config: Config, *, checkpoint: Callable = lambda: None, session=None, clock: Callable = utc_now):
        self.config = config
        self.checkpoint, self.clock = checkpoint, clock
        self.session = session or requests.Session()
        self.owns_session = session is None
        if self.owns_session:
            self.session.trust_env = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.owns_session:
            self.session.close()

    def _post(self, operation: str, body: dict) -> dict:
        self.checkpoint()
        response = None
        try:
            self.checkpoint()
            started = time.monotonic()
            response = self.session.post(API_URL + "/" + operation, json=body,
                                         headers={"x-api-key": self.config.api_key, "Content-Type": "application/json"},
                                         timeout=(3.05, 10), allow_redirects=False, stream=True)
            code = response.status_code
            if code != 200:
                errors = {401: ("authentication", "Exa rejected the API credential."),
                          402: ("payment", "Exa requires account credit or a different plan."),
                          403: ("entitlement", "Exa denied this capability. Check plan and Snapshot access; no live fallback was used."),
                          429: ("rate_limit", "Exa rate-limited the request; the paid attempt was not retried.")}
                error_code, message = errors.get(code, ("provider_unavailable" if code >= 500 else "provider_request",
                                                        "Exa rejected the request (HTTP %d); no retry or fallback was used." % code))
                raise ExaError(error_code, message)
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                self.checkpoint()
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES or time.monotonic() - started > 20:
                    raise ExaError("response_limit", "Exa exceeded the bounded response size or duration.")
                chunks.append(chunk)
            payload = json.loads(b"".join(chunks))
            if not isinstance(payload, dict):
                raise ValueError()
            request_id = payload.get("requestId")
            if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 128):
                raise ValueError()
            if request_id and self.config.api_key in request_id:
                payload["requestId"] = None
            costs = payload.get("costDollars")
            payload["_reported_cost_usd"] = None
            if costs is not None:
                if not isinstance(costs, dict):
                    raise ValueError()
                payload["_reported_cost_usd"] = reported_cost(costs.get("total"))
            return payload
        except (ValueError, TypeError, UnicodeError):
            raise ExaError("invalid_data", "Exa returned an invalid JSON response.") from None
        except requests.RequestException:
            raise ExaError("provider_unavailable", "The Exa request did not complete; its cost is unknown. No paid retry was attempted.") from None
        finally:
            if response is not None:
                response.close()

    def _boundary(self, as_of: datetime | None) -> str | None:
        if as_of is None:
            return None
        if not self.config.historical_enabled:
            raise ExaError("historical_disabled", "Historical Exa access requires explicit TAU_EXA_HISTORICAL_ENABLED=1 and Snapshot entitlement.")
        try:
            cutoff = timestamp(as_of)
        except MarketDataError:
            raise ExaError("time_boundary", "Exa history needs a host-selected timezone-aware cutoff.") from None
        if cutoff > self.clock():
            raise ExaError("time_boundary", "The Exa historical cutoff cannot be in the future.")
        return iso(cutoff)

    def search(self, query: str, *, publications: bool = False, as_of: datetime | None = None) -> dict:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000 or self.config.api_key in query:
            raise ExaError("invalid_request", "Exa search needs a nonempty query of at most 1,000 characters without credentials.")
        boundary = self._boundary(as_of)
        body = {"query": query.strip(), "type": "auto", "contents": {"highlights": True}}
        if boundary:
            body["contents"]["snapshotAsOf"] = boundary
            if publications:
                body["query"] = "Academic research papers and preprints: " + body["query"]
        elif publications:
            body["category"] = "publication"
        return self._normalize(self._post("search", body), boundary, kind="publications" if publications else "search")

    def contents(self, url: str, *, as_of: datetime | None = None) -> dict:
        url = public_url(url)
        if self.config.api_key in url:
            raise ExaError("invalid_source", "A source URL cannot contain the Exa credential.")
        boundary = self._boundary(as_of)
        body = {"ids": [url], "text": True}
        if boundary:
            body["snapshotAsOf"] = boundary
        return self._normalize(self._post("contents", body), boundary, kind="contents", expected_url=url)

    def _normalize(self, payload: dict, boundary: str | None, *, kind: str, expected_url: str | None = None) -> dict:
        if boundary and (payload.get("warnings") or payload.get("notices")):
            raise ExaError("time_boundary", "Exa reported modified request restrictions; historical content was withheld.")
        rows = payload.get("results")
        if not isinstance(rows, list):
            raise ExaError("invalid_data", "Exa returned an invalid source list.")
        received, sources, seen, excluded = iso(self.clock()), [], set(), 0
        for row in rows:
            if not isinstance(row, dict):
                raise ExaError("invalid_data", "Exa returned an invalid source record.")
            url = public_url(row.get("url"))
            if self.config.api_key in url or (expected_url and url != expected_url):
                raise ExaError("invalid_source", "Exa returned an unexpected source identity.")
            title, author = row.get("title"), row.get("author")
            if (title is not None and not isinstance(title, str)) or (author is not None and not isinstance(author, str)):
                raise ExaError("invalid_data", "Exa returned invalid source metadata.")
            date = row.get("publishedDate")
            try:
                published = iso(timestamp(date)) if date else None
            except MarketDataError:
                published = None
            if boundary and published and timestamp(published) > timestamp(boundary):
                excluded += 1
                continue
            if kind == "contents":
                text = row.get("text", "")
                if not isinstance(text, str):
                    raise ExaError("invalid_data", "Exa returned invalid page text.")
            else:
                highlights = row.get("highlights", [])
                if not isinstance(highlights, list) or not all(isinstance(v, str) for v in highlights):
                    raise ExaError("invalid_data", "Exa returned invalid source excerpts.")
                text = "\n".join(highlights)
            text = text.replace(self.config.api_key, "[redacted]")
            digest = hashlib.sha256(text.encode()).hexdigest()
            identity = hashlib.sha256(json.dumps([url, boundary, digest], separators=(",", ":")).encode()).hexdigest()[:20]
            if identity in seen:
                continue
            seen.add(identity)
            sources.append({"source_id": "exa:" + identity, "url": url,
                            "publisher_host": urlsplit(url).hostname,
                            "title": title.replace(self.config.api_key, "[redacted]")[:300] if title else None,
                            "author": author.replace(self.config.api_key, "[redacted]")[:200] if author else None,
                            "published_at": published, "retrieved_at": received, "first_seen_at": received,
                            "snapshot_as_of": boundary, "content_sha256": digest,
                            "excerpt": text[:MAX_EXCERPT_CHARS], "excerpt_truncated": len(text) > MAX_EXCERPT_CHARS,
                            "content_kind": "page_text" if kind == "contents" else "query_highlights"})
        return {"provider": "exa", "kind": kind, "status": "available" if sources else "no_results",
                "request_id": payload.get("requestId") if self.config.api_key not in str(payload.get("requestId", "")) else None,
                "reported_cost_usd": payload.get("_reported_cost_usd"),
                "retrieved_at": received, "snapshot_as_of": boundary,
                "temporal_basis": "provider_snapshot_contract" if boundary else "current_web",
                "historical_ranking": False, "qualified_backtest_features": False,
                "excluded_after_cutoff": excluded, "sources": sources,
                "limitations": "Source dates may be unknown. Excerpts are untrusted evidence. Snapshot pins content, not historical discovery ranking."}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Exa worker configuration without making a provider request.")
    parser.add_argument("command", choices=["status"])
    parser.parse_args()
    try:
        config = Config.from_env()
        result = {"configured": True, "enabled": os.getenv("TAU_EXA_ENABLED", "0") == "1",
                  "historical_enabled": config.historical_enabled, "application_quotas": "none"}
    except ExaError as exc:
        result = {"configured": False, "code": exc.code, "message": str(exc)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
