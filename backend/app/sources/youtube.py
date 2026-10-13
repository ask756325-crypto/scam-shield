"""YouTube channel search via the official YouTube Data API v3 (requires an API key).

`search.list` with type=channel costs 100 quota units; the default project quota is 10,000 units/day, i.e. about
100 searches per day across all scans. The key is a server-side secret (SCAMSHIELD_YOUTUBE_API_KEY): it is sent
only to googleapis.com and is never returned by the API, shown in the UI or logged.
"""
from __future__ import annotations

import httpx

from ..candidate import CandidateRecord
from ..config import get_settings
from .base import SourceAdapter, SourceError, SourceInfo, parse_rate_limit

ENDPOINT = "https://www.googleapis.com/youtube/v3/search"


class YouTubeAdapter(SourceAdapter):
    info = SourceInfo(
        name="youtube",
        label="YouTube",
        category="social",
        source_type="live",
        integration="YouTube Data API v3 search.list (type=channel), API key",
        reliability="official public API",
        docs_url="https://developers.google.com/youtube/v3/docs/search/list",
        notes="Searches channel names and descriptions. Needs SCAMSHIELD_YOUTUBE_API_KEY on the server. Each search costs 100 of the default 10,000 daily quota units.",
        auth="api_key",
        rate_limit="Quota: 10,000 units/day per Google Cloud project by default; one search = 100 units (≈100 searches/day).",
    )
    max_results_per_query = 25

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        key = get_settings().youtube_key()
        if not key:
            raise SourceError("youtube requires an API key (SCAMSHIELD_YOUTUBE_API_KEY is not set)", "auth_required")
        params = {"part": "snippet", "type": "channel", "q": term, "maxResults": self.max_results_per_query}
        try:
            # The key goes in a header, not the query string: request URLs are logged (e.g. by httpx at INFO level).
            resp = await client.get(ENDPOINT, params=params, headers={"X-goog-api-key": key})
        except httpx.TimeoutException as exc:
            raise SourceError("youtube timed out", "timeout") from exc
        except httpx.HTTPError as exc:
            raise SourceError(f"youtube network error: {type(exc).__name__}", "unavailable") from exc
        rl = parse_rate_limit(resp.headers)
        if rl:
            self.rate_limit = rl
        if resp.status_code >= 400:
            reason = ""
            try:
                reason = (resp.json().get("error", {}).get("errors") or [{}])[0].get("reason", "")
            except ValueError:
                pass
            if resp.status_code == 403 and reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
                raise SourceError(f"youtube quota exhausted ({reason})", "rate_limited")
            if resp.status_code == 429:
                raise SourceError("youtube rate limited (HTTP 429)", "rate_limited")
            if resp.status_code in (400, 401, 403):
                # Never echo the request URL: it contains the key.
                raise SourceError(f"youtube rejected the API key or request (HTTP {resp.status_code}{', ' + reason if reason else ''})", "auth_required")
            if resp.status_code >= 500:
                raise SourceError(f"youtube unavailable (HTTP {resp.status_code})", "unavailable")
            raise SourceError(f"youtube error (HTTP {resp.status_code})", "error")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SourceError("youtube returned invalid JSON", "error") from exc
        return [self.normalize(i, term) for i in data.get("items", []) if (i.get("id") or {}).get("channelId")]

    @staticmethod
    def normalize(item: dict, term: str) -> CandidateRecord:
        cid = item["id"]["channelId"]
        sn = item.get("snippet") or {}
        thumbs = sn.get("thumbnails") or {}
        avatar = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
        return CandidateRecord(
            source="youtube", source_type="live", kind="account", external_id=cid, name=sn.get("channelTitle") or sn.get("title") or cid,
            handle=None, url=f"https://www.youtube.com/channel/{cid}", description=sn.get("description") or "", avatar_url=avatar,
            metadata={"platform": "youtube", "channel_id": cid}, source_created_at=sn.get("publishedAt"),
            provenance={"adapter": "youtube", "endpoint": ENDPOINT, "query": term},
        )
