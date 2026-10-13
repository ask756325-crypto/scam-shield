"""Source adapter (collector) contract and shared HTTP handling.

Adding a platform
-----------------
1. Subclass `SourceAdapter`, set `info` (be explicit about how access works and its limits).
2. Implement `search(term, client)` returning normalized `CandidateRecord`s. Raise `SourceError` with one of
   `OUTCOME_KINDS` for failures; return `[]` for a successful search with no matches.
3. Use `get_json(..., adapter=self)` so HTTP status codes, timeouts and rate-limit headers are classified
   consistently.
4. Register it in `services/registry.LIVE_ADAPTERS`.
Only use public or properly authorized endpoints; never work around access controls.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import ClassVar

import httpx

from ..candidate import CandidateRecord

# Outcome of a single query. "ok" and "empty" are successes; the rest are failures shown verbatim to users.
OUTCOME_KINDS = ("ok", "empty", "rate_limited", "timeout", "unavailable", "auth_required", "error")
FAILURE_KINDS = ("rate_limited", "timeout", "unavailable", "auth_required", "error")


class SourceError(Exception):
    """A query failed. `kind` drives the status shown to users."""

    def __init__(self, message: str, kind: str = "error", retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind if kind in FAILURE_KINDS else "error"
        self.retry_after = retry_after


@dataclass
class SourceInfo:
    name: str
    label: str
    category: str  # social | app_store | demo | import
    source_type: str  # live | simulated | imported
    integration: str  # how it is accessed
    reliability: str  # official public API | unofficial | synthetic
    docs_url: str | None = None
    notes: str = ""
    auth: str = "none"  # none | token | oauth
    rate_limit: str = ""  # documented limit, or what is known about it


@dataclass
class RateLimitState:
    limit: int | None = None
    remaining: int | None = None
    reset_in: float | None = None  # seconds
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"limit": self.limit, "remaining": self.remaining, "reset_in": self.reset_in}


def _int(v: str | None) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except ValueError:
        return None


def parse_rate_limit(headers: httpx.Headers) -> RateLimitState | None:
    """Mastodon: X-RateLimit-Limit/Remaining/Reset (ISO time). IETF draft / atproto PDS: RateLimit-* (reset in s or epoch)."""
    limit = _int(headers.get("x-ratelimit-limit") or headers.get("ratelimit-limit"))
    remaining = _int(headers.get("x-ratelimit-remaining") or headers.get("ratelimit-remaining"))
    reset_raw = headers.get("x-ratelimit-reset") or headers.get("ratelimit-reset")
    if limit is None and remaining is None and reset_raw is None:
        return None
    reset_in = None
    if reset_raw:
        n = _int(reset_raw)
        if n is not None:
            reset_in = float(n - time.time()) if n > 10_000_000 else float(n)  # epoch seconds vs delta seconds
        else:
            try:
                from datetime import datetime, timezone

                reset_in = (datetime.fromisoformat(reset_raw.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()
            except ValueError:
                reset_in = None
        if reset_in is not None:
            reset_in = max(0.0, reset_in)
    return RateLimitState(limit=limit, remaining=remaining, reset_in=reset_in)


def _retry_after(resp: httpx.Response) -> float | None:
    ra = resp.headers.get("Retry-After")
    if ra:
        try:
            return max(0.0, float(ra))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(ra).timestamp() - time.time())
            except (TypeError, ValueError):
                pass
    rl = parse_rate_limit(resp.headers)
    return rl.reset_in if rl else None


class SourceAdapter:
    info: ClassVar[SourceInfo]
    max_results_per_query: int = 25
    # Minimum spacing between requests to one source, to stay well inside documented limits.
    min_interval_seconds: float = 0.0

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.rate_limit: RateLimitState | None = None

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:  # pragma: no cover
        raise NotImplementedError

    async def enrich(self, records: list[CandidateRecord], client: httpx.AsyncClient) -> list[CandidateRecord]:
        """Optional second pass (e.g. fetch details for the most relevant records)."""
        return records


def raise_for_response(resp: httpx.Response, source: str) -> None:
    if resp.status_code == 429 or (source == "apple_app_store" and resp.status_code == 403):
        raise SourceError(f"{source} rate limited (HTTP {resp.status_code})", "rate_limited", _retry_after(resp))
    if resp.status_code == 401:
        raise SourceError(f"{source} requires authentication (HTTP 401)", "auth_required")
    if resp.status_code == 403:
        raise SourceError(f"{source} denied access (HTTP 403) — the endpoint may block this network or require credentials", "auth_required")
    if resp.status_code >= 500:
        raise SourceError(f"{source} unavailable (HTTP {resp.status_code})", "unavailable")
    if resp.status_code >= 400:
        raise SourceError(f"{source} rejected the request (HTTP {resp.status_code})", "error")


async def get_json(client: httpx.AsyncClient, url: str, params: dict, source: str, adapter: SourceAdapter | None = None,
                   headers: dict | None = None):
    try:
        resp = await client.get(url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise SourceError(f"{source} timed out", "timeout") from exc
    except httpx.HTTPError as exc:
        raise SourceError(f"{source} network error: {type(exc).__name__}", "unavailable") from exc
    if adapter is not None:
        rl = parse_rate_limit(resp.headers)
        if rl:
            adapter.rate_limit = rl
    raise_for_response(resp, source)
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError(f"{source} returned invalid JSON", "error") from exc
