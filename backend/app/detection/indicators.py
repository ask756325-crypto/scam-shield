"""Observable indicators (URLs, domains, contacts, handles, developer IDs) extracted from stored candidate fields.

Used to show *overlaps* between candidates. An overlap is an observed fact ("both listings link to X"); it is
never treated as proof of common ownership or a coordinated campaign.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .normalize import handle_local_part
from .urls import MESSAGING, SHORTENERS, extract_urls, is_official_host, registrable_domain

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Phone numbers written with a leading + or as a long digit run with separators.
PHONE_RE = re.compile(r"(?<![\w/])\+?\d[\d\s().-]{7,}\d(?![\w/])")

# Hosts so widely shared that a common *domain* says nothing; their full URLs can still be compared.
GENERIC_HOSTS = {
    "bsky.app", "bsky.social", "apps.apple.com", "itunes.apple.com", "play.google.com", "linktr.ee", "x.com", "twitter.com",
    "instagram.com", "facebook.com", "youtube.com", "tiktok.com", "github.com", "google.com", "apple.com", "medium.com",
    "mastodon.social", "wikipedia.org", "linkedin.com", "discord.com", "reddit.com",
} | MESSAGING | SHORTENERS

KIND_LABELS = {
    "url": "Same URL",
    "domain": "Same web domain",
    "email": "Same email address",
    "phone": "Same phone number",
    "messaging": "Same messaging contact",
    "handle": "Same handle on another platform",
    "publisher_id": "Same developer account",
}


@dataclass(frozen=True)
class Indicator:
    kind: str
    value: str  # normalized comparison key
    display: str  # as it should be shown to analysts
    field: str  # where it was observed: links | description | handle | publisher_id


def canonical_url(url: str) -> str | None:
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    host = (p.hostname or "").lower().removeprefix("www.")
    if not host:
        return None
    return f"{host}{p.path.rstrip('/')}".lower()


def extract(c, official_domains: list[str] | None = None) -> list[Indicator]:
    """Indicators observable in a stored candidate (any object with Candidate's attributes)."""
    official_domains = official_domains or []
    out: dict[tuple[str, str], Indicator] = {}

    def add(i: Indicator):
        out.setdefault((i.kind, i.value), i)

    own_profile = canonical_url(c.url) if c.url else None
    link_sources = [(u, "links") for u in (c.external_links or [])] + [(u, "description") for u in extract_urls(c.description)]
    for raw, field in link_sources:
        cu = canonical_url(raw)
        if not cu or cu == own_profile:
            continue
        host = cu.split("/", 1)[0]
        if is_official_host(host, official_domains):
            continue  # pointing at the brand's own site is expected, not an indicator
        path = cu[len(host):]
        if host in MESSAGING and path.strip("/"):
            add(Indicator("messaging", cu, cu, field))
            continue
        if path.strip("/"):
            add(Indicator("url", cu, cu, field))
        dom = registrable_domain(host)
        if dom not in GENERIC_HOSTS and host not in GENERIC_HOSTS:
            add(Indicator("domain", dom, dom, field))

    text = c.description or ""
    for m in EMAIL_RE.finditer(text):
        email = m.group(0).lower()
        if not is_official_host(email.split("@", 1)[1], official_domains):
            add(Indicator("email", email, m.group(0), "description"))
    for m in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 9 <= len(digits) <= 15:
            add(Indicator("phone", digits, m.group(0).strip(), "description"))

    if c.kind == "domain" and c.external_id:
        host = c.external_id.lower()
        dom = registrable_domain(host)
        if dom not in GENERIC_HOSTS and not is_official_host(host, official_domains):
            add(Indicator("domain", dom, dom, "hostname"))
    if c.kind == "account" and c.handle:
        local = (handle_local_part(c.handle, c.source) or "").lower()
        if len(local) >= 4:
            add(Indicator("handle", local, f"@{local}", "handle"))
    if c.kind == "app" and c.publisher_id:
        store = (c.extra or {}).get("platform") or c.source
        add(Indicator("publisher_id", f"{store}:{c.publisher_id}", f"{c.publisher_name or 'Developer'} (ID {c.publisher_id})", "publisher_id"))
    return list(out.values())
