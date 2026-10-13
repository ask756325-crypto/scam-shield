"""Google Play discovery through the unofficial `google-play-scraper` package.

Google offers no public search API for Play listings. This adapter parses public store pages via the
open-source google-play-scraper library; it can break whenever Google changes its markup, and is
labelled "unofficial" everywhere in the product.
"""
from __future__ import annotations

import asyncio
import functools
import ssl
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import urlopen

import certifi
import httpx

from ..candidate import CandidateRecord
from ..detection.similarity import _pair_score
from .base import SourceAdapter, SourceError, SourceInfo

DETAILS_LIMIT = 12  # detail lookups (developer ID, URL) per scan, for the most brand-relevant listings
DETAILS_CONCURRENCY = 4
DETAILS_TIMEOUT = 12.0
SCRAPER_HTTP_TIMEOUT = 10.0  # the library passes no timeout to urlopen; a stalled socket would pin a thread forever
DETAILS_CACHE_TTL = 6 * 3600  # developer IDs / listing URLs change rarely; repeat scans skip the lookups
DETAILS_CACHE_MAX = 5000

# Dedicated, bounded pool: blocking scraper calls never starve the shared default executor (image hashing etc.).
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gplay")
_details_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_transport_lock = threading.Lock()
_transport_installed = False


def _install_safe_transport() -> None:
    """google-play-scraper globally disables TLS verification at import
    (`ssl._create_default_https_context = ssl._create_unverified_context`) and calls urlopen without a timeout.
    Undo the global override and route its requests through a verified context with a timeout."""
    global _transport_installed
    with _transport_lock:
        if _transport_installed:
            return
        import google_play_scraper.utils.request as gp_request
        from google_play_scraper.exceptions import ExtraHTTPError, NotFoundError

        ssl._create_default_https_context = ssl.create_default_context  # restore process-wide verification
        ctx = ssl.create_default_context(cafile=certifi.where())

        def _verified_urlopen(obj):
            try:
                resp = urlopen(obj, timeout=SCRAPER_HTTP_TIMEOUT, context=ctx)
            except HTTPError as e:
                if e.code == 404:
                    raise NotFoundError("App not found(404).")
                raise ExtraHTTPError(f"App not found. Status code {e.code} returned.")
            return resp.read().decode("UTF-8")

        gp_request._urlopen = _verified_urlopen
        _transport_installed = True


def _default_search(term: str, n: int, lang: str, country: str):
    _install_safe_transport()
    from google_play_scraper import search

    return search(term, n_hits=n, lang=lang, country=country)


def _default_details(app_id: str, lang: str, country: str):
    _install_safe_transport()
    from google_play_scraper import app

    return app(app_id, lang=lang, country=country)


def _cache_get(key: tuple[str, str]) -> dict | None:
    with _cache_lock:
        hit = _details_cache.get(key)
        if hit and time.monotonic() - hit[0] < DETAILS_CACHE_TTL:
            return hit[1]
        _details_cache.pop(key, None)
        return None


def _cache_put(key: tuple[str, str], value: dict) -> None:
    with _cache_lock:
        if len(_details_cache) >= DETAILS_CACHE_MAX:
            _details_cache.pop(next(iter(_details_cache)))  # evict oldest insertion
        _details_cache[key] = (time.monotonic(), value)


def _classify(exc: Exception) -> str:
    msg = f"{type(exc).__name__} {exc}"
    if "429" in msg or "PlayGatewayError" in msg:
        return "rate_limited"
    if isinstance(exc, (TimeoutError, OSError)) or "timed out" in msg.lower():
        return "timeout" if "timed out" in msg.lower() or isinstance(exc, TimeoutError) else "unavailable"
    if "403" in msg:
        return "auth_required"
    return "unavailable"


class GooglePlayAdapter(SourceAdapter):
    info = SourceInfo(
        name="google_play",
        label="Google Play",
        category="app_store",
        source_type="live",
        integration="google-play-scraper (unofficial parser of public store pages)",
        reliability="unofficial",
        docs_url="https://github.com/JoMingyu/google-play-scraper",
        notes="Not an official API and may stop working without notice. Results whose package ID cannot be parsed are skipped and counted. Developer details are cached for 6 hours.",
        auth="none",
        rate_limit="Undocumented; Google may return 429 or a PlayGatewayError, reported as rate limited.",
    )
    max_results_per_query = 30

    def __init__(self, config: dict | None = None, search_fn: Callable | None = None, details_fn: Callable | None = None, brand_names: list[str] | None = None):
        super().__init__(config)
        self._search = search_fn or _default_search
        self._details = details_fn or _default_details
        self.brand_names = brand_names or []
        self.skipped_without_id = 0

    @property
    def country(self) -> str:
        c = str(self.config.get("store_country", "us")).lower()
        return c if len(c) == 2 and c.isalpha() else "us"

    async def _run(self, fn: Callable, *args):
        return await asyncio.get_running_loop().run_in_executor(_EXECUTOR, functools.partial(fn, *args))

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        try:
            raw = await self._run(self._search, term, self.max_results_per_query, "en", self.country)
        except Exception as exc:  # library raises assorted exceptions on markup/HTTP changes
            kind = _classify(exc)
            raise SourceError(f"google_play scraper failed: {type(exc).__name__}{' (rate limited by Google)' if kind == 'rate_limited' else ''}", kind) from exc
        out = []
        for r in raw or []:
            if not r.get("appId"):
                self.skipped_without_id += 1
                continue
            out.append(self.normalize(r, term, self.country))
        return out

    async def enrich(self, records: list[CandidateRecord], client: httpx.AsyncClient) -> list[CandidateRecord]:
        """Fetch developer IDs for the most brand-relevant listings (search results omit them)."""
        ranked = sorted(records, key=lambda r: max((_pair_score(r.name, b)[0] for b in self.brand_names), default=0), reverse=True)
        sem = asyncio.Semaphore(DETAILS_CONCURRENCY)
        self.cache_hits = 0

        async def lookup(r: CandidateRecord):
            key = (r.external_id, self.country)
            cached = _cache_get(key)
            if cached is not None:
                self.cache_hits += 1
                return r, cached
            async with sem:
                try:
                    d = await asyncio.wait_for(self._run(self._details, r.external_id, "en", self.country), DETAILS_TIMEOUT)
                except Exception:
                    r.metadata["details_error"] = "detail lookup failed or timed out"
                    return r, None
            _cache_put(key, d)
            return r, d

        for r, d in await asyncio.gather(*(lookup(r) for r in ranked[:DETAILS_LIMIT])):
            if d is None:
                continue
            r.publisher_id = d.get("developerId") or r.publisher_id
            r.publisher_name = d.get("developer") or r.publisher_name
            r.url = d.get("url") or r.url
            if d.get("description"):
                r.description = d["description"]
            links = [u for u in [d.get("developerWebsite"), d.get("privacyPolicy")] if u]
            r.external_links = list(dict.fromkeys([*r.external_links, *links]))
            r.metadata.update(
                {
                    "developer_email": d.get("developerEmail"),
                    "developer_website": d.get("developerWebsite"),
                    "released": d.get("released"),
                    "updated": d.get("updated"),
                    "installs": d.get("installs") or r.metadata.get("installs"),
                    "rating": d.get("score"),
                    "details_fetched": True,
                }
            )
            r.source_created_at = d.get("released") or r.source_created_at
        return records

    @staticmethod
    def normalize(r: dict, term: str, country: str) -> CandidateRecord:
        app_id = r["appId"]
        return CandidateRecord(
            source="google_play",
            source_type="live",
            kind="app",
            external_id=app_id,
            name=r.get("title") or "",
            url=f"https://play.google.com/store/apps/details?id={app_id}",
            description=r.get("description") or "",
            avatar_url=r.get("icon"),
            publisher_name=r.get("developer"),
            publisher_id=None,  # filled by enrich() for relevant listings
            metadata={
                "platform": "google_play",
                "package": app_id,
                "genre": r.get("genre"),
                "installs": r.get("installs"),
                "rating": r.get("score"),
                "free": r.get("free"),
                "country": country,
            },
            provenance={"adapter": "google_play", "endpoint": "google-play-scraper search()", "query": term},
        )
