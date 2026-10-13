"""Official asset protection: exclude known official accounts/apps before scoring.

Only exact, reliable identifiers are used. A matching *display name* (account or developer) is never
sufficient — impersonators copy display names freely.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from ..candidate import CandidateRecord
from .urls import domain_covers


@dataclass(frozen=True)
class OfficialAccountRef:
    platform: str
    handle: str
    profile_url: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class OfficialAppRef:
    store: str
    app_id: str
    track_id: str | None = None
    publisher_id: str | None = None
    publisher_name: str | None = None


@dataclass
class ExclusionMatch:
    rule: str
    matched_value: str


# Map source adapters to the platform/store names used in brand profiles.
SOURCE_PLATFORM = {
    "bluesky": "bluesky",
    "mastodon": "mastodon",
    "apple_app_store": "apple",
    "google_play": "google_play",
}


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    path = parts.path.rstrip("/").lower()
    return f"{host}{path}"


def canonical_handle(handle: str | None) -> str:
    return (handle or "").strip().lstrip("@").lower()


def platform_for(candidate: CandidateRecord) -> str:
    base = candidate.metadata.get("platform") if candidate.metadata else None
    return base or SOURCE_PLATFORM.get(candidate.source, candidate.source)


# Exclusion rules, evaluated in this order. Every rule compares an *exact* identifier; none uses fuzzy
# similarity. `default` is the setting for brands that have not customised their rules.
EXCLUSION_RULES: list[dict] = [
    {"id": "official_account_id", "kind": "account", "default": True, "label": "Account ID",
     "description": "The account's platform ID (e.g. a Bluesky DID) equals an official account ID."},
    {"id": "official_platform_handle", "kind": "account", "default": True, "label": "Platform + handle",
     "description": "Same platform and the exact handle of an official account (case-insensitive)."},
    {"id": "official_profile_url", "kind": "account", "default": True, "label": "Profile URL",
     "description": "The canonical profile URL equals an official profile URL."},
    {"id": "bluesky_verified_domain_handle", "kind": "account", "default": True, "label": "Bluesky domain handle",
     "description": "A Bluesky handle that is an official domain or its subdomain. Bluesky verifies domain handles via DNS or .well-known."},
    {"id": "mastodon_verified_link", "kind": "account", "default": True, "label": "Mastodon verified link",
     "description": "A Mastodon profile link to an official domain that the instance marked verified (rel=me back-link)."},
    {"id": "official_app_id", "kind": "app", "default": True, "label": "Bundle / package ID",
     "description": "Same store and the exact bundle or package ID of an official app."},
    {"id": "official_track_id", "kind": "app", "default": True, "label": "Apple track ID",
     "description": "The App Store numeric track ID of an official app."},
    {"id": "official_publisher_id", "kind": "app", "default": False, "label": "Official publisher ID (opt-in)",
     "description": "Any app on the same store published by an official publisher ID. Off by default: a compromised or "
                    "sub-licensed developer account would hide its apps. When off, these apps are scored but capped at Low."},
]
RULE_IDS = [r["id"] for r in EXCLUSION_RULES]
DEFAULT_RULES = {r["id"]: r["default"] for r in EXCLUSION_RULES}


def effective_rules(overrides: dict | None) -> dict[str, bool]:
    rules = dict(DEFAULT_RULES)
    for k, v in (overrides or {}).items():
        if k in rules and isinstance(v, bool):
            rules[k] = v
    return rules


class OfficialIndex:
    def __init__(self, accounts: list[OfficialAccountRef], apps: list[OfficialAppRef], official_domains: list[str], rules: dict | None = None):
        self.rules = effective_rules(rules)
        self.handles = {(a.platform, canonical_handle(a.handle)) for a in accounts if a.handle}
        self.account_ids = {(a.platform, a.external_id) for a in accounts if a.external_id}
        self.urls = {canonical_url(a.profile_url) for a in accounts if a.profile_url} - {None}
        self.app_ids = {(a.store, a.app_id.strip().lower()) for a in apps if a.app_id}
        self.track_ids = {(a.store, str(a.track_id)) for a in apps if a.track_id}
        self.publisher_ids = {(a.store, a.publisher_id) for a in apps if a.publisher_id}
        self.domains = [d.lower().strip().lstrip(".").removeprefix("www.") for d in official_domains if d.strip()]

    def match(self, c: CandidateRecord) -> ExclusionMatch | None:
        on = self.rules
        platform = platform_for(c)
        native_id = (c.metadata or {}).get("native_id") or c.external_id
        if c.kind == "app":
            if on["official_app_id"] and (platform, (native_id or "").lower()) in self.app_ids:
                return ExclusionMatch("official_app_id", f"{platform}:{native_id}")
            track = c.metadata.get("track_id") if c.metadata else None
            if on["official_track_id"] and track and (platform, str(track)) in self.track_ids:
                return ExclusionMatch("official_track_id", f"{platform}:{track}")
            if on["official_publisher_id"] and c.publisher_id and (platform, c.publisher_id) in self.publisher_ids:
                return ExclusionMatch("official_publisher_id", f"{platform}:publisher {c.publisher_id}")
            return None
        handle = canonical_handle(c.handle)
        if on["official_account_id"] and (platform, native_id) in self.account_ids:
            return ExclusionMatch("official_account_id", f"{platform}:{native_id}")
        if on["official_platform_handle"] and handle and (platform, handle) in self.handles:
            return ExclusionMatch("official_platform_handle", f"{platform}:@{handle}")
        cu = canonical_url(c.url)
        if on["official_profile_url"] and cu and cu in self.urls:
            return ExclusionMatch("official_profile_url", cu)
        # Bluesky domain handles are cryptographically bound to DNS/.well-known on that domain.
        if on["bluesky_verified_domain_handle"] and platform == "bluesky" and handle:
            for d in self.domains:
                if domain_covers(handle, d):
                    return ExclusionMatch("bluesky_verified_domain_handle", f"@{handle} ⊂ {d}")
        # Mastodon rel=me verified links prove the official site links back to this profile.
        if on["mastodon_verified_link"] and platform == "mastodon":
            for link in c.metadata.get("verified_links", []) if c.metadata else []:
                host = (urlsplit(link).hostname or "").lower().removeprefix("www.")
                for d in self.domains:
                    if domain_covers(host, d):
                        return ExclusionMatch("mastodon_verified_link", f"{link} (rel=me verified)")
        return None
