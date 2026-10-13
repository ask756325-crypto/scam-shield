"""SSRF-resistant fetching of remote images (candidate avatars / app icons).

Defences: https only, host allowlist (known media CDNs of supported sources), DNS resolution with
rejection of private/loopback/link-local/reserved addresses, manual redirect handling with
re-validation, streamed size cap, content-type check, and a short timeout.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from .config import get_settings

DEFAULT_IMAGE_HOST_SUFFIXES = (
    "cdn.bsky.app",
    "mzstatic.com",
    "play-lh.googleusercontent.com",
    "files.mastodon.social",
    "cdn.masto.host",
)
MAX_REDIRECTS = 3


class UnsafeURL(ValueError):
    pass


def host_allowed(host: str, suffixes: tuple[str, ...] = DEFAULT_IMAGE_HOST_SUFFIXES, extra: list[str] | None = None) -> bool:
    host = host.lower().rstrip(".")
    for s in (*suffixes, *(extra or [])):
        s = s.lower().lstrip(".")
        if host == s or host.endswith("." + s):
            return True
    return False


def ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified
    )


async def resolve_public(host: str) -> None:
    try:
        ipaddress.ip_address(host)
        raise UnsafeURL("IP-literal hosts are not fetched")
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL(f"DNS resolution failed for {host}") from exc
    for info in infos:
        if not ip_is_public(info[4][0]):
            raise UnsafeURL(f"{host} resolves to a non-public address")


def validate_url(url: str, extra_hosts: list[str] | None = None) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise UnsafeURL("Only https URLs are fetched")
    if parts.username or parts.password:
        raise UnsafeURL("Credentials in URL are not allowed")
    host = (parts.hostname or "").lower()
    if not host or not host_allowed(host, extra=extra_hosts):
        raise UnsafeURL(f"Image host not in allowlist: {host or '(none)'}")
    if parts.port not in (None, 443):
        raise UnsafeURL("Non-standard ports are not fetched")
    return host


async def fetch_image(client: httpx.AsyncClient, url: str, extra_hosts: list[str] | None = None, max_bytes: int | None = None) -> bytes:
    limit = max_bytes or get_settings().max_remote_image_bytes
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        host = validate_url(current, extra_hosts)
        await resolve_public(host)
        async with client.stream("GET", current, follow_redirects=False) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise UnsafeURL("Redirect without location")
                current = urljoin(current, loc)
                continue
            if resp.status_code != 200:
                raise UnsafeURL(f"Image fetch returned HTTP {resp.status_code}")
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if not ctype.startswith("image/") or ctype == "image/svg+xml":
                raise UnsafeURL(f"Unexpected content type {ctype or '(none)'}")
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise UnsafeURL("Image exceeds size limit")
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > limit:
                    raise UnsafeURL("Image exceeds size limit")
            return bytes(buf)
    raise UnsafeURL("Too many redirects")
