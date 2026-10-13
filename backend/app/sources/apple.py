"""Apple App Store discovery via the public iTunes Search API."""
from __future__ import annotations

import re

import httpx

from ..candidate import CandidateRecord
from .base import SourceAdapter, SourceInfo, get_json

ENDPOINT = "https://itunes.apple.com/search"
_COUNTRY_RE = re.compile(r"^[a-z]{2}$")


class AppleAppStoreAdapter(SourceAdapter):
    info = SourceInfo(
        name="apple_app_store",
        label="Apple App Store",
        category="app_store",
        source_type="live",
        integration="iTunes Search API (entity=software), unauthenticated",
        reliability="official public API",
        docs_url="https://performance-partners.apple.com/search-api",
        notes="Apple limits this API to roughly 20 requests/minute; HTTP 403/429 is reported as rate limited.",
        auth="none",
        rate_limit="~20 requests/minute (Apple guidance).",
    )
    max_results_per_query = 50

    @property
    def country(self) -> str:
        c = str(self.config.get("store_country", "us")).lower()
        return c if _COUNTRY_RE.match(c) else "us"

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        params = {"term": term, "entity": "software", "country": self.country, "limit": self.max_results_per_query}
        data = await get_json(client, ENDPOINT, params, "apple_app_store", adapter=self)
        return [self.normalize(r, term, self.country) for r in data.get("results", []) if r.get("bundleId")]

    @staticmethod
    def normalize(r: dict, term: str, country: str) -> CandidateRecord:
        return CandidateRecord(
            source="apple_app_store",
            source_type="live",
            kind="app",
            external_id=r["bundleId"],
            name=r.get("trackName") or "",
            handle=None,
            url=r.get("trackViewUrl"),
            description=r.get("description") or "",
            avatar_url=r.get("artworkUrl512") or r.get("artworkUrl100"),
            publisher_name=r.get("artistName") or r.get("sellerName"),
            publisher_id=str(r["artistId"]) if r.get("artistId") else None,
            external_links=[u for u in [r.get("sellerUrl")] if u],
            metadata={
                "platform": "apple",
                "track_id": str(r.get("trackId")) if r.get("trackId") else None,
                "bundle_id": r["bundleId"],
                "seller_name": r.get("sellerName"),
                "genre": r.get("primaryGenreName"),
                "version": r.get("version"),
                "rating": r.get("averageUserRating"),
                "rating_count": r.get("userRatingCount"),
                "price": r.get("formattedPrice"),
                "updated": r.get("currentVersionReleaseDate"),
                "country": country,
            },
            source_created_at=r.get("releaseDate"),
            provenance={"adapter": "apple_app_store", "endpoint": ENDPOINT, "query": term},
        )
