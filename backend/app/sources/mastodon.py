"""Mastodon account search via instance /api/v2/search (unauthenticated, accounts only)."""
from __future__ import annotations

import asyncio
import html
import re
from urllib.parse import urlsplit

import httpx

from ..candidate import CandidateRecord
from ..config import get_settings
from ..detection.urls import extract_urls
from .base import SourceAdapter, SourceError, SourceInfo, get_json

_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r'href="([^"]+)"')
_INSTANCE_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")
DEFAULT_INSTANCES = ["mastodon.social"]


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<br\s*/?>|</p>", "\n", value)
    return html.unescape(_TAG_RE.sub("", value)).strip()


def valid_instance(host: str) -> bool:
    return bool(_INSTANCE_RE.match(host or "")) and not host.endswith((".local", ".internal", ".localhost"))


class MastodonAdapter(SourceAdapter):
    info = SourceInfo(
        name="mastodon",
        label="Mastodon",
        category="social",
        source_type="live",
        integration="Instance REST API GET /api/v2/search?type=accounts (unauthenticated)",
        reliability="official public API",
        docs_url="https://docs.joinmastodon.org/methods/search/",
        notes="Accounts only: unauthenticated search cannot use resolve/offset and cannot search posts. Results reflect what the configured instance(s) know about; federation is not exhaustive.",
        auth="none",
        rate_limit="Default 300 requests / 5 min per IP per instance; tracked via X-RateLimit-* headers.",
    )

    @property
    def instances(self) -> list[str]:
        inst = [i.strip().lower() for i in self.config.get("mastodon_instances", DEFAULT_INSTANCES)]
        return [i for i in inst if valid_instance(i)][:3] or DEFAULT_INSTANCES

    # Stop querying an instance once its remaining budget drops this low (leave headroom for other clients).
    RATE_LIMIT_FLOOR = 10

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.instance_rate_limits: dict[str, dict] = {}
        self.warnings: list[str] = []  # per-instance failures when other instances still succeeded

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        instances = self.instances
        results = await asyncio.gather(*(self._search_instance(i, term, client) for i in instances), return_exceptions=True)
        out: list[CandidateRecord] = []
        errors: list[tuple[str, Exception]] = [(i, r) for i, r in zip(instances, results) if isinstance(r, Exception)]
        for r in results:
            if not isinstance(r, Exception):
                out.extend(r)
        if errors and len(errors) == len(results):
            e = errors[0][1]
            raise e if isinstance(e, SourceError) else SourceError(str(e))
        for inst, e in errors:  # partial: report instead of silently dropping
            msg = f"{inst}: {e}"
            if msg not in self.warnings:
                self.warnings.append(msg)
        return out

    async def _search_instance(self, instance: str, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        state = self.instance_rate_limits.get(instance)
        if state and state.get("remaining") is not None and state["remaining"] <= self.RATE_LIMIT_FLOOR:
            raise SourceError(f"mastodon {instance}: rate limit nearly exhausted ({state['remaining']} left)", "rate_limited", state.get("reset_in"))
        endpoint = f"https://{instance}/api/v2/search"
        # resolve/offset are not allowed without a user token (Mastodon ≥ 4.0), so they are never sent.
        # An optional server-side token (SCAMSHIELD_MASTODON_ACCESS_TOKENS) is sent only to its own instance.
        token = get_settings().mastodon_tokens().get(instance)
        headers = {"Authorization": f"Bearer {token}"} if token else None
        try:
            data = await get_json(client, endpoint, {"q": term, "type": "accounts", "limit": 40}, "mastodon", adapter=self, headers=headers)
        finally:
            if self.rate_limit:
                self.instance_rate_limits[instance] = self.rate_limit.to_dict()
                self.rate_limit = None
        return [self.normalize(a, instance, term, endpoint) for a in data.get("accounts", []) if a.get("url")]

    @staticmethod
    def normalize(a: dict, instance: str, term: str, endpoint: str) -> CandidateRecord:
        acct = a.get("acct") or a.get("username") or ""
        if "@" not in acct:
            acct = f"{acct}@{instance}"
        note = html_to_text(a.get("note"))
        links, verified = [], []
        for f in a.get("fields") or []:
            hrefs = _HREF_RE.findall(f.get("value") or "")
            links.extend(hrefs)
            if f.get("verified_at"):
                verified.extend(hrefs)
        links.extend(extract_urls(note))
        url = a.get("url")
        return CandidateRecord(
            source="mastodon",
            source_type="live",
            kind="account",
            external_id=url,
            name=a.get("display_name") or a.get("username") or acct,
            handle=acct,
            url=url,
            description=note,
            avatar_url=a.get("avatar_static") or a.get("avatar"),
            external_links=list(dict.fromkeys(links)),
            metadata={
                "platform": "mastodon",
                "home_instance": urlsplit(url).hostname if url else None,
                "searched_instance": instance,
                "followers": a.get("followers_count"),
                "statuses": a.get("statuses_count"),
                "bot": a.get("bot"),
                "verified_links": verified,
            },
            source_created_at=a.get("created_at"),
            provenance={"adapter": "mastodon", "endpoint": endpoint, "query": term},
        )
