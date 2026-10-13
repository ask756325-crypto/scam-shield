"""Suspicious URL heuristics (pure string analysis — no network access)."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from rapidfuzz import fuzz

from .normalize import skeleton
from .signals import Signal

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
BARE_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|app|xyz|top|click|link|info|online|site|shop|support|live|co|me|ly|gg)\b(?:/[^\s<>\"')\]]*)?", re.IGNORECASE)

SUSPICIOUS_TLDS = {"xyz", "top", "click", "link", "online", "site", "shop", "live", "rest", "buzz", "gq", "tk", "ml", "cf", "ga", "zip", "mov", "support", "icu", "cam", "work"}
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rb.gy", "shorturl.at", "tiny.cc", "rebrand.ly", "s.id"}
MESSAGING = {"wa.me", "t.me", "telegram.me", "chat.whatsapp.com", "api.whatsapp.com", "discord.gg", "signal.me"}
CREDENTIAL_WORDS = {"login", "signin", "sign-in", "verify", "verification", "secure", "account", "wallet", "recover", "unlock", "connect", "claim", "update", "auth"}
# Benign hosts that commonly appear in profiles (link hubs are neutral, not suspicious by themselves).
_MULTI_LABEL_SUFFIXES = {"co.uk", "com.au", "co.in", "co.jp", "com.br", "co.nz", "org.uk", "com.mx", "co.za", "com.sg"}


def extract_urls(text: str | None) -> list[str]:
    if not text:
        return []
    found = [m.group(0).rstrip(".,;:!?") for m in URL_RE.finditer(text)]
    for m in BARE_DOMAIN_RE.finditer(text):
        v = m.group(0).rstrip(".,;:!?")
        if not any(v in f for f in found) and "@" not in text[max(0, m.start() - 1) : m.start()]:
            found.append(v)
    out = []
    for u in found:
        if not re.match(r"https?://", u, re.I):
            u = "https://" + u
        if u not in out:
            out.append(u)
    return out


def host_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def registrable_domain(host: str) -> str:
    labels = [l for l in host.split(".") if l]
    if len(labels) <= 2:
        return ".".join(labels)
    last2 = ".".join(labels[-2:])
    if last2 in _MULTI_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return last2


# Domains whose subdomains belong to *different* people (user handles, hosted sites). Listing one as an official
# domain must never make every subdomain official: "@anyone.bsky.social" is not owned by Bluesky the company.
SHARED_HOSTING_DOMAINS = {
    "bsky.social", "github.io", "gitlab.io", "netlify.app", "vercel.app", "pages.dev", "web.app", "firebaseapp.com",
    "herokuapp.com", "blogspot.com", "wordpress.com", "tumblr.com", "substack.com", "medium.com", "wixsite.com",
    "carrd.co", "notion.site", "myshopify.com", "glitch.me", "neocities.org", "linktr.ee", "beacons.ai",
}


def domain_covers(host: str, official: str) -> bool:
    """True if `host` is the official domain, or a subdomain of it that the domain owner controls."""
    d = official.lower().strip().lstrip(".")
    if d.startswith("www."):
        d = d[4:]
    host = host.lower().rstrip(".")
    if host == d:
        return True
    return host.endswith("." + d) and d not in SHARED_HOSTING_DOMAINS


def is_official_host(host: str, official_domains: list[str]) -> bool:
    return any(domain_covers(host, d) for d in official_domains)


def analyze_url(url: str, official_domains: list[str], brand_names: list[str]) -> tuple[float, list[str]]:
    host = host_of(url)
    if not host:
        return 0.0, []
    if is_official_host(host, official_domains):
        return 0.0, []
    reasons: list[tuple[float, str]] = []
    reg = registrable_domain(host)
    label = reg.split(".")[0] if reg else host
    try:
        ipaddress.ip_address(host)
        reasons.append((0.7, f"{host}: raw IP address link"))
    except ValueError:
        pass
    if "xn--" in host:
        reasons.append((0.6, f"{host}: punycode (possible homograph) domain"))
    tld = host.rsplit(".", 1)[-1]
    if tld in SUSPICIOUS_TLDS:
        reasons.append((0.35, f"{host}: high-abuse TLD .{tld}"))
    if host in SHORTENERS:
        reasons.append((0.4, f"{host}: URL shortener hides destination"))
    if host in MESSAGING:
        reasons.append((0.45, f"{host}: moves contact to a private messaging channel"))
    reg_skel = skeleton(reg.replace(".", " "))
    sub_skel = skeleton(host[: -len(reg)].replace(".", " ")) if reg and host != reg else ""
    for b in brand_names:
        bs = skeleton(b)
        if len(bs) < 4:
            continue
        if bs in reg_skel:
            reasons.append((0.75, f"{host}: unofficial domain containing brand name “{b}”"))
            break
        if bs in sub_skel:
            # e.g. brand-login.evil.top vs. a user page like djbrand.bandcamp.com — weaker on its own;
            # TLD / credential-keyword heuristics add to it via noisy-OR when present.
            reasons.append((0.4, f"{host}: brand name “{b}” in a subdomain of {reg}"))
            break
    for d in official_domains:
        od = registrable_domain(d.lower().lstrip(".").removeprefix("www."))
        o_label = od.split(".")[0]
        if od and reg != od and len(o_label) >= 4:
            sim = fuzz.ratio(skeleton(label), skeleton(o_label)) / 100.0
            if sim >= 0.8 and skeleton(label) != skeleton(o_label) or (skeleton(label) == skeleton(o_label) and label != o_label):
                reasons.append((0.85, f"{host}: look-alike of official domain {od} (similarity {sim:.2f})"))
                break
    path = (urlsplit(url).path or "").lower() + " " + host
    words = sorted(w for w in CREDENTIAL_WORDS if w in path)
    if words:
        reasons.append((0.3, f"{host}: credential/payment keywords in URL ({', '.join(words[:3])})"))
    if host.count("-") >= 2:
        reasons.append((0.2, f"{host}: multiple hyphens in domain"))
    score = 1.0
    for s, _ in reasons:
        score *= 1.0 - s
    return 1.0 - score, [r for _, r in reasons]


def url_signal(urls: list[str], official_domains: list[str], brand_names: list[str]) -> Signal:
    urls = [u for u in dict.fromkeys(urls) if u]
    if not urls:
        return Signal.missing("urls", "No external links found")
    best, evidence, per_url = 0.0, [], {}
    for u in urls[:20]:
        s, reasons = analyze_url(u, official_domains, brand_names)
        per_url[u] = round(s, 3)
        best = max(best, s)
        evidence.extend(reasons)
    official = [u for u in urls if is_official_host(host_of(u), official_domains)]
    detail = f"{len(urls)} link(s) analyzed; highest URL risk {best:.2f}"
    if official:
        detail += f"; {len(official)} point to official domains"
    return Signal(name="urls", evaluated=True, score=best, detail=detail, evidence=evidence[:8], data={"per_url": per_url})
