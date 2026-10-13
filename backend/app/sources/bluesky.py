"""Bluesky actor search via the public AppView (no authentication required)."""
from __future__ import annotations

import httpx

from ..candidate import CandidateRecord
from ..detection.urls import extract_urls
from .base import SourceAdapter, SourceInfo, get_json

ENDPOINT = "https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors"


class BlueskyAdapter(SourceAdapter):
    info = SourceInfo(
        name="bluesky",
        label="Bluesky",
        category="social",
        source_type="live",
        integration="Public AppView XRPC app.bsky.actor.searchActors (unauthenticated)",
        reliability="official public API",
        docs_url="https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/actor/searchActors.json",
        notes="Searches account names, handles and bios (lexicon: no auth, limit 1–100). Periodic search, not a streaming firehose.",
        auth="none",
        rate_limit="No published quota for the public AppView; backs off on HTTP 429 and honours Retry-After / RateLimit-* headers when sent.",
    )

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        data = await get_json(client, ENDPOINT, {"q": term, "limit": self.max_results_per_query}, "bluesky", adapter=self)
        return [self.normalize(a, term) for a in data.get("actors", []) if a.get("did")]

    @staticmethod
    def normalize(a: dict, term: str) -> CandidateRecord:
        handle = a.get("handle") or ""
        description = a.get("description") or ""
        verification = a.get("verification") or {}
        return CandidateRecord(
            source="bluesky",
            source_type="live",
            kind="account",
            external_id=a["did"],
            name=a.get("displayName") or handle,
            handle=handle,
            url=f"https://bsky.app/profile/{handle or a['did']}",
            description=description,
            avatar_url=a.get("avatar"),
            external_links=extract_urls(description),
            metadata={
                "platform": "bluesky",
                "did": a["did"],
                "indexed_at": a.get("indexedAt"),
                "labels": [l.get("val") for l in a.get("labels", []) if isinstance(l, dict)],
                "bluesky_verified_status": verification.get("verifiedStatus"),
            },
            source_created_at=a.get("createdAt"),
            provenance={"adapter": "bluesky", "endpoint": ENDPOINT, "query": term},
        )
