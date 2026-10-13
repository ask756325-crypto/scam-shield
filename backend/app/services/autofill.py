"""Brand autofill from a website URL.

Fetches the public page the analyst typed and extracts only what the page itself declares: name, description,
icons, linked social profiles and app-store links. Store lookups use the official public iTunes lookup API.
Nothing is saved here: the result is a draft the analyst reviews before anything reaches the brand profile.

Safety: https only, no credentials, DNS must resolve to public addresses (re-checked on each redirect), bounded
size and time, HTML or image content types only. Results list what was found and what was not.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from ..config import get_settings
from ..detection.logo import InvalidImage, load_image
from ..detection.urls import registrable_domain
from ..netsafe import UnsafeURL, resolve_public

MAX_PAGE_BYTES = 1_500_000
MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
SEPARATORS = re.compile(r"\s+[|\-–—·:]\s+")


@dataclass
class PageData:
    title: str = ""
    site_name: str = ""
    description: str = ""
    icons: list[str] = field(default_factory=list)  # ordered best-first
    links: list[str] = field(default_factory=list)
    rel_me: list[str] = field(default_factory=list)


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.d = PageData()
        self._in_title = False
        self._icons: list[tuple[int, str]] = []
        self._og_image: str | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            content = a.get("content", "").strip()
            if name in ("og:site_name",) and content:
                self.d.site_name = self.d.site_name or content
            elif name in ("og:title", "twitter:title") and content:
                self.d.title = self.d.title or content
            elif name in ("description", "og:description") and content:
                self.d.description = self.d.description or content
            elif name in ("og:image", "twitter:image") and content and not self._og_image:
                self._og_image = content
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            href = a.get("href", "").strip()
            if not href:
                return
            if "icon" in rel or "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
                rank = 0 if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel else 1
                size = int((a.get("sizes", "0x0").split("x")[0] or 0)) if a.get("sizes", "").split("x")[0].isdigit() else 0
                self._icons.append((rank * 1000 - size, href))
            if "me" in rel:
                self.d.rel_me.append(href)
        elif tag == "a":
            href = a.get("href", "").strip()
            if href.startswith("http"):
                self.d.links.append(href)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.d.title:
            self.d.title = data.strip()[:300]

    def finish(self, base: str) -> PageData:
        self.d.icons = [urljoin(base, h) for _, h in sorted(self._icons, key=lambda x: x[0])]
        if self._og_image:
            self.d.icons.append(urljoin(base, self._og_image))
        self.d.links = [urljoin(base, h) for h in self.d.links]
        self.d.rel_me = [urljoin(base, h) for h in self.d.rel_me]
        return self.d


def _brand_name(d: PageData, host: str) -> str:
    raw = d.site_name or (SEPARATORS.split(d.title)[0] if d.title else "")
    raw = raw.strip()[:120]
    if raw:
        return raw
    return host.split(".")[0].replace("-", " ").title()


async def _public_get(client: httpx.AsyncClient, url: str, limit: int, accept: tuple[str, ...]) -> tuple[bytes, str, str]:
    """GET with per-hop SSRF checks. Returns (body, content_type, final_url)."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        if parts.scheme != "https":
            raise UnsafeURL("Only https:// websites are supported")
        if parts.username or parts.password:
            raise UnsafeURL("Credentials in the address are not allowed")
        if parts.port not in (None, 443):
            raise UnsafeURL("Non-standard ports are not fetched")
        host = (parts.hostname or "").lower()
        if not host:
            raise UnsafeURL("The address has no host name")
        await resolve_public(host)
        async with client.stream("GET", current, follow_redirects=False) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise UnsafeURL("Redirect without a location")
                current = urljoin(current, loc)
                continue
            if resp.status_code != 200:
                raise UnsafeURL(f"The website returned HTTP {resp.status_code}")
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if not any(ctype.startswith(a) for a in accept):
                raise UnsafeURL(f"Unexpected content type {ctype or '(none)'}")
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise UnsafeURL("The response is too large")
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > limit:
                    raise UnsafeURL("The response is too large")
            return bytes(buf), ctype, current
    raise UnsafeURL("Too many redirects")


def _social(url: str) -> tuple[str, str] | None:
    """(platform, handle) for a profile URL on a supported platform."""
    p = urlsplit(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    parts = [x for x in p.path.split("/") if x]
    if host in ("x.com", "twitter.com") and parts and parts[0].lower() not in ("intent", "share", "home", "i"):
        return ("x", parts[0])
    if host == "bsky.app" and len(parts) >= 2 and parts[0] == "profile":
        return ("bluesky", parts[1])
    if host == "instagram.com" and parts:
        return ("instagram", parts[0])
    if host == "facebook.com" and parts:
        return ("facebook", parts[0])
    if host == "youtube.com" and parts and parts[0].startswith("@"):
        return ("youtube", parts[0])
    if host == "tiktok.com" and parts and parts[0].startswith("@"):
        return ("tiktok", parts[0])
    return None


def _mastodon(url: str) -> tuple[str, str] | None:
    p = urlsplit(url)
    parts = [x for x in p.path.split("/") if x]
    if parts and parts[0].startswith("@") and p.hostname and p.hostname.count(".") >= 1:
        return ("mastodon", f"{parts[0][1:]}@{p.hostname.lower()}")
    return None


def _app_links(url: str) -> dict | None:
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if host == "apps.apple.com":
        m = re.search(r"/id(\d{5,})", p.path)
        if m:
            return {"store": "apple", "track_id": m.group(1)}
    if host == "play.google.com" and p.path.startswith("/store/apps/details"):
        from urllib.parse import parse_qs

        pkg = parse_qs(p.query).get("id", [""])[0]
        if re.fullmatch(r"[a-zA-Z][\w]*(\.[\w]+)+", pkg):
            return {"store": "google_play", "app_id": pkg}
    return None


async def _itunes(client: httpx.AsyncClient, track_id: str, country: str) -> dict | None:
    """Official public lookup of an App Store listing (bundle ID, developer, name)."""
    try:
        r = await client.get(ITUNES_LOOKUP, params={"id": track_id, "country": country, "entity": "software"}, timeout=10)
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
    except (httpx.HTTPError, ValueError):
        return None
    if not results:
        return None
    x = results[0]
    return {"store": "apple", "name": x.get("trackName"), "app_id": x.get("bundleId"), "track_id": str(x.get("trackId") or track_id),
            "publisher_name": x.get("artistName"), "publisher_id": str(x.get("artistId")) if x.get("artistId") else None,
            "url": x.get("trackViewUrl")}


async def autofill(url: str, country: str = "us") -> dict:
    url = url.strip()
    if not url.lower().startswith("http"):
        url = "https://" + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    found: list[str] = []
    missing: list[str] = []
    warnings: list[str] = []
    s = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=6.0), headers={"User-Agent": s.user_agent}) as client:
        body, ctype, final = await _public_get(client, url, MAX_PAGE_BYTES, ("text/html", "application/xhtml"))
        charset = "utf-8"
        m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', body[:4096])
        if m:
            charset = m.group(1).decode("ascii", "ignore") or "utf-8"
        try:
            text = body.decode(charset, errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        parser = _PageParser()
        parser.feed(text)
        page = parser.finish(final)
        final_host = (urlsplit(final).hostname or host).lower().removeprefix("www.")

        result: dict = {"source_url": final, "fields": {}, "official_domains": [], "official_accounts": [], "official_apps": [],
                        "logo": None, "found": found, "missing": missing, "warnings": warnings}
        name = _brand_name(page, final_host)
        result["fields"]["name"] = name
        found.append("name")
        if page.description:
            result["fields"]["description"] = page.description[:4000]
            found.append("description")
        else:
            missing.append("description")
        result["fields"]["website_url"] = final
        domains = sorted({final_host, registrable_domain(final_host)})
        result["official_domains"] = domains
        found.append(f"domains ({', '.join(domains)})")

        seen_accounts: set[tuple[str, str]] = set()
        for link in [*page.rel_me, *page.links]:
            social = _social(link) or _mastodon(link)
            if social and social not in seen_accounts:
                seen_accounts.add(social)
                platform, handle = social
                result["official_accounts"].append({"platform": platform, "handle": handle, "profile_url": link if platform != "bluesky" else None,
                                                    "external_id": None})
        if result["official_accounts"]:
            found.append(f"{len(result['official_accounts'])} social account(s): " + ", ".join(f"{a['platform']} {a['handle']}" for a in result["official_accounts"]))
        else:
            missing.append("social accounts (none linked from the website)")

        store_hits = {}
        for link in page.links:
            app = _app_links(link)
            if app and (app["store"], app.get("track_id") or app.get("app_id")) not in store_hits:
                store_hits[(app["store"], app.get("track_id") or app.get("app_id"))] = app
        for app in list(store_hits.values())[:5]:
            if app["store"] == "apple":
                looked_up = await _itunes(client, app["track_id"], country)
                if looked_up:
                    result["official_apps"].append(looked_up)
                else:
                    warnings.append(f"App Store listing {app['track_id']} could not be looked up")
            else:
                result["official_apps"].append({"store": "google_play", "app_id": app["app_id"], "name": None, "publisher_name": None, "publisher_id": None})
        if result["official_apps"]:
            found.append(f"{len(result['official_apps'])} app(s) linked from the website")
        else:
            missing.append("apps (no App Store or Google Play links on the page)")

        for icon in page.icons[:6]:
            try:
                data, ictype, _ = await _public_get(client, icon, MAX_LOGO_BYTES, ("image/png", "image/jpeg", "image/webp", "image/gif", "image/x-icon", "image/vnd.microsoft.icon"))
                img = load_image(data)
                if min(img.size) < 32:
                    continue
                result["logo"] = {"filename": "website-logo.png", "data_base64": base64.b64encode(data).decode(), "source": icon,
                                  "width": img.size[0], "height": img.size[1]}
                found.append(f"logo ({img.size[0]}×{img.size[1]} from the website)")
                break
            except (UnsafeURL, InvalidImage, httpx.HTTPError):
                continue
        if not result["logo"]:
            missing.append("logo (no suitable icon or image found)")
    result["found"], result["missing"] = found, missing
    return result
