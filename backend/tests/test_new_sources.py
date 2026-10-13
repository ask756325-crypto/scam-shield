"""Certificate Transparency look-alike domains and YouTube channel search (HTTP mocked; no network)."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.candidate import CandidateRecord
from app.config import get_settings
from app.detection import indicators as ind
from app.detection.engine import BrandContext, evaluate
from app.sources.base import SourceError
from app.sources.ct_domains import ENDPOINT as CT, CTDomainsAdapter
from app.sources.youtube import ENDPOINT as YT, YouTubeAdapter
from conftest import CSRF, wait_for_scan
from test_api import create_brand

NOW = datetime.now(timezone.utc)


def cert(i, names, days_ago=10, issuer='C=US, O="Let\'s Encrypt", CN=R10'):
    return {"id": i, "issuer_name": issuer, "common_name": names[0], "name_value": "\n".join(names),
            "not_before": (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")}


CERTS = [
    cert(1, ["acmewallet-verify-account.top", "*.acmewallet-verify-account.top"]),
    cert(2, ["www.acmewallet.example"]),
    cert(3, ["acmewalletfans.blog"], days_ago=5),
    cert(4, ["acmewallet-old.net"], days_ago=900),
]


def run(coro):
    return asyncio.run(coro)


class TestCertificateTransparency:
    @respx.mock
    def test_search_normalizes_recent_unique_hosts(self):
        respx.get(CT).mock(return_value=httpx.Response(200, json=CERTS))

        async def go():
            async with httpx.AsyncClient() as c:
                return await CTDomainsAdapter().search("acme wallet", c)
        recs = run(go())
        hosts = [r.external_id for r in recs]
        assert set(hosts) == {"acmewallet-verify-account.top", "www.acmewallet.example", "acmewalletfans.blog"}  # wildcard deduped, old cert dropped
        r = next(r for r in recs if r.external_id == "acmewallet-verify-account.top")
        assert r.kind == "domain" and r.metadata["platform"] == "domain" and "Let's Encrypt" in r.description
        assert respx.calls.last.request.url.params["q"] == "%acmewallet%"

    @respx.mock
    def test_outage_is_reported_not_hidden(self):
        respx.get(CT).mock(return_value=httpx.Response(502, text="<html>Bad Gateway</html>"))

        async def go():
            async with httpx.AsyncClient() as c:
                return await CTDomainsAdapter().search("acme wallet", c)
        with pytest.raises(SourceError) as e:
            run(go())
        assert e.value.kind == "unavailable"

    def test_short_tokens_are_not_searched(self):
        async def go():
            async with httpx.AsyncClient() as c:
                return await CTDomainsAdapter().search("nv", c)
        assert run(go()) == []

    def test_scoring_and_official_exclusion(self):
        recs = CTDomainsAdapter.normalize_all(CERTS, "acme wallet", "acmewallet", NOW)
        brand = BrandContext(name="Acme Wallet", official_domains=["acmewallet.example"])
        out = {e.record.external_id: e for e in evaluate(brand, recs)}
        assert out["www.acmewallet.example"].excluded.rule == "official_domain"
        phish = out["acmewallet-verify-account.top"].assessment
        assert phish.detection_type == "phishing_domain" and phish.risk_level in ("high", "critical")
        assert "logo" in " ".join(phish.not_evaluated).lower() or phish.signals["logo"]["evaluated"] is False
        fan = out["acmewalletfans.blog"].assessment
        assert fan.detection_type == "lookalike_domain" and fan.risk_level != "critical"

    def test_domain_links_to_accounts_through_shared_indicator(self):
        domain = CandidateRecord("ct_domains", "live", "domain", "acmewallet-verify-account.top", "acmewallet-verify-account.top", metadata={"platform": "domain"})
        from app.models import Candidate

        c = Candidate(kind="domain", source="ct_domains", external_id=domain.external_id, extra={}, external_links=[], description="", url=None, handle=None)
        a = Candidate(kind="account", source="bluesky", handle="x.bsky.social", external_links=["https://login.acmewallet-verify-account.top/x"],
                      description="", url=None, extra={})
        assert {i.value for i in ind.extract(c) if i.kind == "domain"} & {i.value for i in ind.extract(a) if i.kind == "domain"} == {"acmewallet-verify-account.top"}

    @respx.mock
    def test_end_to_end_domain_scan(self, authed):
        authed.put("/api/sources/config", json={"enabled_sources": ["ct_domains"], "mastodon_instances": ["mastodon.social"], "store_country": "us"}, headers=CSRF)
        respx.get(CT).mock(return_value=httpx.Response(200, json=CERTS))
        b = create_brand(authed, name="Acme Wallet", official_domains=["acmewallet.example"])
        s = wait_for_scan(authed, authed.post(f"/api/brands/{b['id']}/scans", json={"sources": ["ct_domains"]}, headers=CSRF).json()["id"], timeout=120)
        assert s["sources"][0]["status"] == "ok" and s["excluded_official"] >= 1
        items = authed.get("/api/findings", params={"brand_id": b["id"], "kind": "domain", "level": ["critical", "high", "medium", "low"]}).json()["items"]
        assert "acmewallet-verify-account.top" in {f["candidate"]["external_id"] for f in items}
        reg = {x["name"]: x for x in authed.get("/api/sources").json()["sources"]}
        assert reg["ct_domains"]["state"] == "live" and reg["ct_domains"]["last_success"]["via"] == "scan"


class TestYouTube:
    def test_not_configured_without_key(self, authed):
        reg = {x["name"]: x for x in authed.get("/api/sources").json()["sources"]}
        yt = reg["youtube"]
        assert yt["enabled"] is False and yt["state"] == "disabled" and yt["auth"]["status"] == "missing"
        assert not yt["config"]["valid"] and "SCAMSHIELD_YOUTUBE_API_KEY" in yt["config"]["problems"][0]
        r = authed.put("/api/sources/config", json={"enabled_sources": ["youtube"], "mastodon_instances": ["mastodon.social"], "store_country": "us"}, headers=CSRF)
        assert r.status_code == 422  # cannot enable an invalid configuration
        assert authed.post("/api/sources/youtube/test", headers=CSRF).json()["outcome"] == "invalid_config"

    @respx.mock
    def test_search_quota_and_secret_handling(self, authed, monkeypatch, caplog):
        key = "AIzaFAKE-test-key-0123456789"
        monkeypatch.setattr(get_settings(), "youtube_api_key", SecretStr(key))
        route = respx.get(YT).mock(side_effect=[
            httpx.Response(200, json={"items": [{"id": {"kind": "youtube#channel", "channelId": "UC123"},
                                                 "snippet": {"channelTitle": "Acme Wallet Support", "description": "Recover your wallet: t.me/acmehelp",
                                                             "thumbnails": {"high": {"url": "https://yt3.ggpht.com/abc"}}, "publishedAt": "2026-01-01T00:00:00Z"}}]}),
            httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}}),
            httpx.Response(400, json={"error": {"errors": [{"reason": "keyInvalid"}]}}),
        ])

        async def search():
            async with httpx.AsyncClient() as c:
                return await YouTubeAdapter().search("acme wallet", c)
        recs = run(search())
        assert recs[0].external_id == "UC123" and recs[0].url == "https://www.youtube.com/channel/UC123" and recs[0].metadata["platform"] == "youtube"
        assert route.calls.last.request.url.params["type"] == "channel"
        with pytest.raises(SourceError) as quota:
            run(search())
        assert quota.value.kind == "rate_limited"
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(SourceError) as bad:
                run(search())
        assert bad.value.kind == "auth_required" and key not in str(bad.value) and key not in caplog.text
        listing = authed.get("/api/sources").text
        assert key not in listing and '"configured"' in listing
