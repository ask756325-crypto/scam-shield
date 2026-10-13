"""Brand autofill from a website: extraction, store lookup, logo, and every refusal path. Network is mocked."""
import asyncio
import base64
import io

import httpx
import pytest
import respx
from PIL import Image

from app.netsafe import UnsafeURL
from app.services import autofill as af
from conftest import CSRF, signup

SITE = "https://www.acme-wallet.example/"
PAGE = """<html><head>
<title>Acme Wallet — Pay Anywhere | Official</title>
<meta name="description" content="Acme Wallet makes instant payments simple.">
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/static/touch-180.png" sizes="180x180">
<meta property="og:image" content="/static/share.png">
</head><body>
<a href="https://x.com/AcmeWallet">X</a>
<a href="https://bsky.app/profile/acmewallet.example">Bluesky</a>
<a rel="me" href="https://social.example/@acmewallet">Mastodon</a>
<a href="https://apps.apple.com/us/app/acme-wallet/id1234567890">iOS</a>
<a href="https://play.google.com/store/apps/details?id=com.acme.wallet&hl=en">Android</a>
</body></html>"""

ITUNES = {"resultCount": 1, "results": [{"trackName": "Acme Wallet", "bundleId": "com.acme.ios", "trackId": 1234567890,
                                         "artistName": "Acme Wallet Inc", "artistId": 555, "trackViewUrl": "https://apps.apple.com/us/app/id1234567890"}]}


def png(size=(180, 180)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (31, 77, 58)).save(buf, format="PNG")
    return buf.getvalue()


def public_dns(monkeypatch):
    async def public(host):
        return None
    monkeypatch.setattr(af, "resolve_public", public)


@respx.mock
def test_extracts_profile_from_public_website(monkeypatch):
    public_dns(monkeypatch)
    respx.get(SITE).mock(return_value=httpx.Response(200, text=PAGE, headers={"content-type": "text/html; charset=utf-8"}))
    respx.get("https://www.acme-wallet.example/static/touch-180.png").mock(return_value=httpx.Response(200, content=png(), headers={"content-type": "image/png"}))
    respx.get("https://itunes.apple.com/lookup").mock(return_value=httpx.Response(200, json=ITUNES))

    d = asyncio.run(af.autofill(SITE, "us"))
    assert d["fields"]["name"] == "Acme Wallet" and "instant payments" in d["fields"]["description"]
    assert d["fields"]["website_url"] == "https://www.acme-wallet.example/"
    assert d["official_domains"] == ["acme-wallet.example"]  # www is the same organization, listed once
    kinds = {(a["platform"], a["handle"]) for a in d["official_accounts"]}
    assert ("x", "AcmeWallet") in kinds and ("bluesky", "acmewallet.example") in kinds and ("mastodon", "acmewallet@social.example") in kinds
    app = next(a for a in d["official_apps"] if a["store"] == "apple")
    assert app["app_id"] == "com.acme.ios" and app["publisher_name"] == "Acme Wallet Inc" and app["publisher_id"] == "555"
    assert any(a["store"] == "google_play" and a["app_id"] == "com.acme.wallet" for a in d["official_apps"])
    assert d["logo"]["width"] == 180 and base64.b64decode(d["logo"]["data_base64"])[:4] == b"\x89PNG"
    assert not any(m.startswith("logo") for m in d["missing"])


@respx.mock
def test_missing_pieces_are_reported_not_invented(monkeypatch):
    public_dns(monkeypatch)
    respx.get(SITE).mock(return_value=httpx.Response(200, text="<html><head><title>Plain</title></head><body>hi</body></html>",
                                                    headers={"content-type": "text/html"}))
    respx.get("https://www.acme-wallet.example/favicon.ico").mock(return_value=httpx.Response(404))
    d = asyncio.run(af.autofill(SITE))
    assert d["logo"] is None and d["official_accounts"] == [] and d["official_apps"] == []
    assert "description" in d["missing"] and any(m.startswith("logo") for m in d["missing"])
    assert d["fields"]["name"] == "Plain"


def test_refuses_unsafe_addresses(monkeypatch):
    async def private(host):
        raise UnsafeURL(f"{host} resolves to a non-public address")
    monkeypatch.setattr(af, "resolve_public", private)
    with pytest.raises(UnsafeURL):
        asyncio.run(af.autofill("https://intranet.example/"))
    with pytest.raises(UnsafeURL):
        asyncio.run(af.autofill("http://plain.example/"))
    with pytest.raises(UnsafeURL):
        asyncio.run(af.autofill("https://user:pw@example.com/"))
    with pytest.raises(UnsafeURL):
        asyncio.run(af.autofill("https://example.com:8443/"))


@respx.mock
def test_refuses_redirect_to_private_host_and_oversized_pages(monkeypatch):
    async def public_then_private(host):
        if host.startswith("hop."):
            raise UnsafeURL(f"{host} resolves to a non-public address")
    monkeypatch.setattr(af, "resolve_public", public_then_private)
    respx.get(SITE).mock(return_value=httpx.Response(302, headers={"location": "https://hop.internal.example/"}))
    with pytest.raises(UnsafeURL):
        asyncio.run(af.autofill(SITE))

    public_dns(monkeypatch)
    respx.get("https://big.example/").mock(return_value=httpx.Response(200, content=b"x" * (af.MAX_PAGE_BYTES + 10), headers={"content-type": "text/html"}))
    with pytest.raises(UnsafeURL):
        asyncio.run(af.autofill("https://big.example/"))


def test_endpoint_requires_login_and_csrf(client):
    assert client.post("/api/brands/autofill", json={"url": SITE}, headers=CSRF).status_code == 401
    assert client.post("/api/brands/autofill", json={"url": SITE}).status_code == 403  # CSRF header required
    signup(client)
    assert client.post("/api/brands/autofill", json={"url": SITE}).status_code == 403


def test_endpoint_turns_unsafe_input_into_422(client, monkeypatch):
    signup(client)

    async def private(host):
        raise UnsafeURL("refused")
    monkeypatch.setattr(af, "resolve_public", private)
    assert client.post("/api/brands/autofill", json={"url": "https://192.168.1.1/"}, headers=CSRF).status_code == 422
    assert client.post("/api/brands/autofill", json={"url": "http://example.com/"}, headers=CSRF).status_code == 422
