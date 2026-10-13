"""Source adapter normalization and failure handling (HTTP mocked with respx; no network)."""
import httpx
import pytest
import respx

from app.netsafe import UnsafeURL, ip_is_public, validate_url
from app.sources.apple import ENDPOINT as APPLE, AppleAppStoreAdapter
from app.sources.base import SourceError
from app.sources.bluesky import ENDPOINT as BSKY, BlueskyAdapter
from app.sources.google_play import GooglePlayAdapter
from app.sources.importer import ImportError_, parse_csv
from app.sources.mastodon import MastodonAdapter


@respx.mock
async def test_bluesky_normalizes_actor():
    respx.get(BSKY).mock(return_value=httpx.Response(200, json={"actors": [{
        "did": "did:plc:abc", "handle": "acme-help.bsky.social", "displayName": "Acme Help",
        "description": "Support at acme-help.xyz", "avatar": "https://cdn.bsky.app/img/a.jpg", "createdAt": "2025-01-01T00:00:00Z",
    }]}))
    async with httpx.AsyncClient() as c:
        recs = await BlueskyAdapter().search("acme", c)
    r = recs[0]
    assert (r.source, r.source_type, r.kind, r.external_id) == ("bluesky", "live", "account", "did:plc:abc")
    assert r.url == "https://bsky.app/profile/acme-help.bsky.social"
    assert "https://acme-help.xyz" in r.external_links
    assert r.provenance["query"] == "acme" and r.source_created_at


@respx.mock
async def test_mastodon_normalizes_and_detects_verified_links():
    respx.get("https://mastodon.social/api/v2/search").mock(return_value=httpx.Response(200, json={"accounts": [{
        "id": "1", "username": "acme", "acct": "acme", "display_name": "Acme", "note": "<p>Hello &amp; welcome</p>",
        "url": "https://mastodon.social/@acme", "avatar_static": "https://files.mastodon.social/a.png",
        "fields": [{"name": "web", "value": '<a href="https://acme.com" rel="me">acme.com</a>', "verified_at": "2024-01-01"}],
    }]}))
    async with httpx.AsyncClient() as c:
        r = (await MastodonAdapter().search("acme", c))[0]
    assert r.handle == "acme@mastodon.social" and r.description == "Hello & welcome"
    assert r.metadata["verified_links"] == ["https://acme.com"]


@respx.mock
async def test_apple_normalizes_listing():
    respx.get(APPLE).mock(return_value=httpx.Response(200, json={"results": [{
        "trackId": 42, "bundleId": "com.fake.acme", "trackName": "Acme Wallet", "artistName": "Fake Dev", "artistId": 7,
        "description": "desc", "artworkUrl512": "https://is1-ssl.mzstatic.com/x.png", "trackViewUrl": "https://apps.apple.com/app/id42",
        "sellerUrl": "https://fake.example",
    }]}))
    async with httpx.AsyncClient() as c:
        r = (await AppleAppStoreAdapter({"store_country": "gb"}).search("acme", c))[0]
    assert (r.external_id, r.publisher_id, r.metadata["track_id"], r.metadata["country"]) == ("com.fake.acme", "7", "42", "gb")


@respx.mock
async def test_rate_limit_and_server_errors_raise_source_error():
    respx.get(APPLE).mock(return_value=httpx.Response(403))
    respx.get(BSKY).mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceError) as e:
            await AppleAppStoreAdapter().search("x", c)
        assert e.value.kind == "rate_limited"
        with pytest.raises(SourceError) as e:
            await BlueskyAdapter().search("x", c)
        assert e.value.kind == "unavailable"


@respx.mock
async def test_timeout_raises_source_error():
    respx.get(BSKY).mock(side_effect=httpx.ReadTimeout("slow"))
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceError) as e:
            await BlueskyAdapter().search("x", c)
    assert e.value.kind == "timeout"


async def test_google_play_skips_missing_ids_and_enriches():
    def fake_search(term, n, lang, country):
        return [{"appId": None, "title": "Acme"}, {"appId": "com.fake.acme", "title": "Acme Wallet", "developer": "Fake", "icon": "https://play-lh.googleusercontent.com/x"}]

    def fake_details(app_id, lang, country):
        return {"developerId": "123", "developer": "Fake Dev", "url": f"https://play.google.com/store/apps/details?id={app_id}", "developerWebsite": "https://fake.example"}

    a = GooglePlayAdapter(search_fn=fake_search, details_fn=fake_details, brand_names=["Acme"])
    recs = await a.search("acme", None)
    assert len(recs) == 1 and a.skipped_without_id == 1
    recs = await a.enrich(recs, None)
    assert recs[0].publisher_id == "123" and "https://fake.example" in recs[0].external_links


async def test_google_play_scraper_failure_is_source_error():
    def boom(*a):
        raise RuntimeError("markup changed")

    with pytest.raises(SourceError):
        await GooglePlayAdapter(search_fn=boom).search("acme", None)


def test_csv_import_parsing():
    data = b"platform,kind,external_id,name,handle,url,description,links\nbluesky,account,did:1,Acme Help,acme.bsky.social,https://bsky.app/profile/acme,Hi,https://a.example http://b.example\n"
    recs = parse_csv(data)
    assert recs[0].source_type == "imported" and recs[0].external_links == ["https://a.example", "http://b.example"]
    with pytest.raises(ImportError_):
        parse_csv(b"name\nx\n")
    with pytest.raises(ImportError_):
        parse_csv(b"platform,kind,external_id,name,url\nbluesky,account,1,x,javascript:alert(1)\n")


def test_ssrf_guards():
    with pytest.raises(UnsafeURL):
        validate_url("http://cdn.bsky.app/a.png")  # not https
    with pytest.raises(UnsafeURL):
        validate_url("https://169.254.169.254/latest")  # not allowlisted
    with pytest.raises(UnsafeURL):
        validate_url("https://evil.example/cdn.bsky.app")
    with pytest.raises(UnsafeURL):
        validate_url("https://user:pw@cdn.bsky.app/a.png")
    assert validate_url("https://cdn.bsky.app/img/a.jpg") == "cdn.bsky.app"
    assert not ip_is_public("10.0.0.5") and not ip_is_public("127.0.0.1") and ip_is_public("8.8.8.8")


def test_google_play_transport_restores_tls_verification_and_sets_timeout(monkeypatch):
    import ssl

    import google_play_scraper.utils.request as gp_request

    from app.sources import google_play as gp

    gp._transport_installed = False
    gp._install_safe_transport()
    assert ssl._create_default_https_context is ssl.create_default_context  # library's global override undone
    seen = {}

    class Resp:
        def read(self):
            return b"ok"

    def fake_urlopen(obj, timeout=None, context=None):
        seen.update(timeout=timeout, verify=context.verify_mode)
        return Resp()

    monkeypatch.setattr(gp, "urlopen", fake_urlopen)
    assert gp_request._urlopen("https://play.google.com/x") == "ok"
    assert seen["timeout"] == gp.SCRAPER_HTTP_TIMEOUT and seen["verify"] == ssl.CERT_REQUIRED


async def test_google_play_details_are_cached_between_scans():
    from app.sources import google_play as gp

    gp._details_cache.clear()
    calls = []

    def fake_search(term, n, lang, country):
        return [{"appId": "com.cache.test", "title": "Acme Wallet", "developer": "X"}]

    def fake_details(app_id, lang, country):
        calls.append(app_id)
        return {"developerId": "777", "developer": "X Ltd"}

    for _ in range(2):
        a = gp.GooglePlayAdapter(search_fn=fake_search, details_fn=fake_details, brand_names=["Acme"])
        recs = await a.enrich(await a.search("acme", None), None)
        assert recs[0].publisher_id == "777"
    assert calls == ["com.cache.test"] and a.cache_hits == 1


def test_google_play_error_classification():
    from app.sources.google_play import _classify

    assert _classify(Exception("com.google.play.gateway.proto.PlayGatewayError")) == "rate_limited"
    assert _classify(Exception("Status code 429 returned.")) == "rate_limited"
    assert _classify(TimeoutError("timed out")) == "timeout"
    assert _classify(Exception("Status code 403 returned.")) == "auth_required"
    assert _classify(ValueError("markup changed")) == "unavailable"
