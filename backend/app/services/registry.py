"""Source catalog and per-organization source configuration."""
from __future__ import annotations

from ..models import Organization
from ..sources.apple import AppleAppStoreAdapter
from ..sources.base import SourceAdapter, SourceInfo
from ..sources.bluesky import BlueskyAdapter
from ..sources.ct_domains import CTDomainsAdapter
from ..sources.demo import DemoAdapter
from ..sources.google_play import GooglePlayAdapter
from ..sources.mastodon import MastodonAdapter
from ..sources.youtube import YouTubeAdapter

LIVE_ADAPTERS: dict[str, type[SourceAdapter]] = {
    "bluesky": BlueskyAdapter,
    "mastodon": MastodonAdapter,
    "apple_app_store": AppleAppStoreAdapter,
    "google_play": GooglePlayAdapter,
    "youtube": YouTubeAdapter,
    "ct_domains": CTDomainsAdapter,
}
# Enabled for new organizations. YouTube needs an API key and CT search is slow, so both are opt-in.
DEFAULT_ENABLED = ["bluesky", "mastodon", "apple_app_store", "google_play"]

# Documented-but-not-integrated platforms, shown honestly in the Sources page.
UNAVAILABLE_SOURCES = [
    {"name": "x", "label": "X (Twitter)", "category": "social", "reason": "Search requires a paid API tier and credentials; not integrated."},
    {"name": "instagram", "label": "Instagram", "category": "social", "reason": "No public search API; Meta Graph API access requires app review. Not integrated."},
    {"name": "facebook", "label": "Facebook", "category": "social", "reason": "Page search requires approved Graph API permissions. Not integrated."},
    {"name": "tiktok", "label": "TikTok", "category": "social", "reason": "Research API is restricted to approved researchers. Not integrated."},
    {"name": "telegram", "label": "Telegram", "category": "social", "reason": "Searching public channels needs a logged-in user session (MTProto); the Bot API cannot search. Not integrated."},
]

DEFAULT_SOURCE_CONFIG = {
    "enabled_sources": DEFAULT_ENABLED,
    "mastodon_instances": ["mastodon.social"],
    "store_country": "us",
}


def source_config(org: Organization) -> dict:
    cfg = dict(DEFAULT_SOURCE_CONFIG)
    cfg.update({k: v for k, v in (org.source_config or {}).items() if k in DEFAULT_SOURCE_CONFIG})
    cfg["enabled_sources"] = [s for s in cfg["enabled_sources"] if s in LIVE_ADAPTERS]
    return cfg


def catalog() -> list[SourceInfo]:
    return [cls.info for cls in LIVE_ADAPTERS.values()] + [DemoAdapter.info]


def build_adapter(name: str, cfg: dict, brand_names: list[str], demo_epoch: int = 0) -> SourceAdapter:
    if name == "demo":
        return DemoAdapter(cfg, epoch=demo_epoch)
    if name == "google_play":
        return GooglePlayAdapter(cfg, brand_names=brand_names)
    return LIVE_ADAPTERS[name](cfg)
