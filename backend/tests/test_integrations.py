"""Sources & Integrations: registry status from real evidence only, connectivity tests (success, empty,
invalid configuration, timeout, rate limit), disabled integrations, config validation, secrets, dashboard."""
import logging

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.candidate import CandidateRecord
from app.config import get_settings
from app.db import SessionLocal
from app.models import Organization, SourceCheck
from app.routers import sources as sources_router
from app.services import scanner
from app.sources.base import SourceAdapter, SourceError, SourceInfo
from conftest import CSRF, signup, wait_for_scan
from test_api import create_brand

APPLE = "https://itunes.apple.com/search"
BSKY = "https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors"
APP = {"bundleId": "com.news.app", "trackId": 1, "trackName": "Daily News", "artistName": "News Co", "artistId": 9,
       "description": "News", "trackViewUrl": "https://apps.apple.com/app/id1"}


def registry(client):
    return {s["name"]: s for s in client.get("/api/sources").json()["sources"]}


def probe(client, name):
    return client.post(f"/api/sources/{name}/test", headers=CSRF)


def org_id(client) -> int:
    return client.get("/api/settings/organization").json()["id"]


def set_raw_config(client, **cfg):
    with SessionLocal() as db:
        org = db.get(Organization, org_id(client))
        org.source_config = {**(org.source_config or {}), **cfg}
        db.commit()


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from app.security import rate_limiter

    rate_limiter.reset()
    sources_router._verified_instances.clear()


class TestRegistry:
    def test_fresh_org_reports_not_tested_never_invented(self, authed):
        reg = registry(authed)
        assert set(reg) == {"bluesky", "mastodon", "apple_app_store", "google_play", "youtube", "ct_domains", "demo"}
        assert reg["youtube"]["state"] == reg["ct_domains"]["state"] == "disabled"  # opt-in sources
        for name in ("bluesky", "mastodon", "apple_app_store", "google_play"):
            s = reg[name]
            assert s["state"] == "live" and s["health"] == "not_tested" and s["enabled"]
            assert s["last_success"] is None and s["last_error"] is None and s["last_attempted_scan"] is None and s["last_test"] is None
            assert s["config"]["valid"] and s["auth"]["status"] == "not_required"
            assert s["rate_limit"]["documented"]
        assert reg["demo"]["state"] == "simulated" and reg["demo"]["integration_type"] == "Synthetic dataset"
        assert reg["google_play"]["integration_type"] == "Unofficial scraper"
        assert reg["apple_app_store"]["integration_type"] == "Official public API"

    def test_demo_has_no_connectivity_test_and_unknown_is_404(self, authed):
        assert probe(authed, "demo").status_code == 400
        assert probe(authed, "myspace").status_code == 404


class TestConnectivity:
    @respx.mock
    def test_success(self, authed):
        respx.get(APPLE).mock(return_value=httpx.Response(200, json={"results": [APP]}))
        r = probe(authed, "apple_app_store").json()
        assert r["outcome"] == "ok" and r["result_count"] == 1 and r["latency_ms"] is not None
        s = registry(authed)["apple_app_store"]
        assert s["state"] == "live" and s["health"] == "operational" and s["observed_via"] == "test"
        assert s["last_success"]["via"] == "test" and s["last_error"] is None

    @respx.mock
    def test_empty_response_is_a_genuine_success(self, authed):
        respx.get(APPLE).mock(return_value=httpx.Response(200, json={"results": []}))
        r = probe(authed, "apple_app_store").json()
        assert r["outcome"] == "empty" and r["result_count"] == 0 and "responded" in r["detail"]
        s = registry(authed)["apple_app_store"]
        assert s["health"] == "no_results" and s["state"] == "live" and s["last_success"] is not None

    @respx.mock
    def test_timeout(self, authed):
        respx.get(APPLE).mock(return_value=httpx.Response(200, json={"results": [APP]}))
        probe(authed, "apple_app_store")  # earlier success
        respx.get(BSKY).mock(side_effect=httpx.ReadTimeout("slow"))
        r = probe(authed, "bluesky").json()
        assert r["outcome"] == "timeout" and r["status"] == "failed"
        s = registry(authed)["bluesky"]
        assert s["state"] == "unavailable" and s["health"] == "failing" and s["last_error"]["kind"] == "timeout"
        assert s["last_success"] is None  # a failure is never shown as success
        assert registry(authed)["apple_app_store"]["state"] == "live"  # other sources unaffected

    @respx.mock
    def test_rate_limit(self, authed):
        respx.get(APPLE).mock(return_value=httpx.Response(429, headers={"Retry-After": "60"}))
        r = probe(authed, "apple_app_store").json()
        assert r["outcome"] == "rate_limited" and r["status"] == "rate_limited"
        s = registry(authed)["apple_app_store"]
        assert s["state"] == "unavailable" and s["health"] == "rate_limited" and s["rate_limit"]["last_rate_limited_at"]

    @respx.mock
    def test_observed_rate_limit_headers_are_recorded(self, authed):
        respx.get("https://mastodon.social/api/v2/search").mock(return_value=httpx.Response(
            200, json={"accounts": []}, headers={"X-RateLimit-Limit": "300", "X-RateLimit-Remaining": "287", "X-RateLimit-Reset": "2030-01-01T00:00:00Z"}))
        probe(authed, "mastodon")
        rl = registry(authed)["mastodon"]["rate_limit"]["observed"]
        assert rl["via"] == "test" and rl["values"]["mastodon.social"]["remaining"] == 287 and rl["values"]["mastodon.social"]["limit"] == 300

    def test_invalid_configuration(self, authed):
        set_raw_config(authed, store_country="zz")  # e.g. edited directly in the database
        r = probe(authed, "apple_app_store").json()
        assert r["outcome"] == "invalid_config" and "ISO 3166" in r["detail"]
        s = registry(authed)["apple_app_store"]
        assert s["state"] == "unavailable" and s["health"] == "invalid_config" and not s["config"]["valid"]
        d = authed.get("/api/dashboard").json()
        if not d.get("empty"):
            assert "Apple App Store" in d["unavailable_sources"]

    def test_history_is_kept_newest_first(self, authed):
        with respx.mock:
            respx.get(APPLE).mock(side_effect=[httpx.Response(200, json={"results": []}), httpx.Response(503)])
            probe(authed, "apple_app_store")
            probe(authed, "apple_app_store")
        hist = authed.get("/api/sources/apple_app_store/checks").json()
        assert [h["outcome"] for h in hist[:2]] == ["unavailable", "empty"]


class TestDisabledAndConfig:
    @respx.mock
    def test_disabled_integration_is_not_scanned_but_can_be_tested(self, authed):
        r = authed.put("/api/sources/config", json={"enabled_sources": ["bluesky", "apple_app_store"], "mastodon_instances": ["mastodon.social"], "store_country": "us"}, headers=CSRF)
        assert r.status_code == 200
        reg = registry(authed)
        assert reg["google_play"]["state"] == "disabled" and reg["mastodon"]["state"] == "disabled" and not reg["google_play"]["enabled"]
        b = create_brand(authed, name="Disabled Co")
        bad = authed.post(f"/api/brands/{b['id']}/scans", json={"sources": ["google_play"]}, headers=CSRF)
        assert bad.status_code == 400 and "not available" in bad.json()["detail"]
        respx.get(BSKY).mock(return_value=httpx.Response(200, json={"actors": []}))
        respx.get(APPLE).mock(return_value=httpx.Response(200, json={"results": []}))
        s = wait_for_scan(authed, authed.post(f"/api/brands/{b['id']}/scans", json={}, headers=CSRF).json()["id"])
        assert {x["source"] for x in s["sources"]} == {"bluesky", "apple_app_store"}
        respx.get("https://mastodon.social/api/v2/search").mock(return_value=httpx.Response(200, json={"accounts": []}))
        t = probe(authed, "mastodon").json()  # validate before enabling
        assert t["outcome"] == "empty" and t["enabled"] is False
        assert registry(authed)["mastodon"]["state"] == "disabled"  # testing never enables
        d = authed.get("/api/dashboard", params={"brand_id": b["id"]}).json()
        assert d["metrics"]["sources_enabled"] == 2

    def test_config_validation(self, authed, monkeypatch):
        put = lambda **body: authed.put("/api/sources/config", json={"enabled_sources": ["mastodon"], "mastodon_instances": ["mastodon.social"], "store_country": "us", **body}, headers=CSRF)
        assert put(store_country="zz").status_code == 422
        assert put(enabled_sources=["nope"]).status_code == 422
        r = put(mastodon_instances=[])
        assert r.status_code == 422 and "No Mastodon instance" in r.json()["detail"]["message"]
        assert put(mastodon_instances=["localhost"]).status_code == 422

        async def private(host):
            from app.netsafe import UnsafeURL

            raise UnsafeURL(f"{host} resolves to a non-public address")

        monkeypatch.setattr(sources_router, "resolve_public", private)
        r = put(mastodon_instances=["intranet.example.com"])
        assert r.status_code == 422 and "non-public" in r.json()["detail"]["message"]

    @respx.mock
    def test_new_instance_must_be_a_mastodon_server(self, authed, monkeypatch):
        async def public(host):
            return None

        monkeypatch.setattr(sources_router, "resolve_public", public)
        respx.get("https://notmastodon.example.org/api/v2/instance").mock(return_value=httpx.Response(404, text="nope"))
        r = authed.put("/api/sources/config", json={"enabled_sources": ["mastodon"], "mastodon_instances": ["notmastodon.example.org"], "store_country": "us"}, headers=CSRF)
        assert r.status_code == 422 and "not a Mastodon-compatible server" in r.json()["detail"]["message"]
        respx.get("https://fosstodon.org/api/v2/instance").mock(return_value=httpx.Response(200, json={"domain": "fosstodon.org"}))
        r = authed.put("/api/sources/config", json={"enabled_sources": ["mastodon"], "mastodon_instances": ["fosstodon.org"], "store_country": "us"}, headers=CSRF)
        assert r.status_code == 200 and r.json()["mastodon_instances"] == ["fosstodon.org"]

    def test_only_owners_change_configuration(self, client):
        signup(client)
        with SessionLocal() as db:
            from app.models import Membership

            m = db.query(Membership).filter(Membership.organization_id == org_id(client)).first()
            m.role = "analyst"
            db.commit()
        r = client.put("/api/sources/config", json={"enabled_sources": ["bluesky"], "mastodon_instances": ["mastodon.social"], "store_country": "us"}, headers=CSRF)
        assert r.status_code == 403


class TestSecretsAndScans:
    @respx.mock
    def test_token_is_sent_only_to_its_instance_and_never_exposed(self, authed, monkeypatch, caplog):
        secret = "s3cr3t-token-value-123"
        monkeypatch.setattr(get_settings(), "mastodon_access_tokens", SecretStr(f"mastodon.social={secret}"))
        route = respx.get("https://mastodon.social/api/v2/search").mock(return_value=httpx.Response(200, json={"accounts": []}))
        with caplog.at_level(logging.DEBUG):
            r = probe(authed, "mastodon")
            listing = authed.get("/api/sources")
        assert route.calls.last.request.headers["Authorization"] == f"Bearer {secret}"
        assert secret not in r.text and secret not in listing.text and secret not in caplog.text
        auth = {s["name"]: s for s in listing.json()["sources"]}["mastodon"]["auth"]
        assert auth["status"] == "configured" and auth["credentials"][0] == {"instance": "mastodon.social", "configured": True,
                                                                            "source": "environment (SCAMSHIELD_MASTODON_ACCESS_TOKENS)"}
        assert secret not in repr(get_settings())

    def test_error_messages_are_redacted(self, monkeypatch):
        from app.services.source_status import redact

        monkeypatch.setattr(get_settings(), "mastodon_access_tokens", SecretStr("a.example=tok-abc-999"))
        assert redact("server echoed tok-abc-999 back") == "server echoed [redacted] back"

    def test_transient_failure_is_retried_once_and_other_sources_continue(self, authed):
        calls: dict[str, int] = {}

        class Flaky(SourceAdapter):
            info = SourceInfo("flaky", "Flaky", "social", "live", "test", "test")

            def __init__(self, name):
                super().__init__({})
                self.name = name

            async def search(self, term, client):
                calls[self.name] = calls.get(self.name, 0) + 1
                if self.name == "bluesky" and calls[self.name] % 2 == 1:
                    raise SourceError("bluesky unavailable (HTTP 503)", "unavailable")
                if self.name == "mastodon":
                    raise SourceError("mastodon auth", "auth_required")
                return [CandidateRecord(self.name, "live", "account", f"{self.name}-{term}", "Someone", handle="someone")] if self.name == "bluesky" else []

        scanner.adapter_factory = lambda name, cfg, names, epoch: Flaky(name)
        b = create_brand(authed, name="Retry Co")
        s = wait_for_scan(authed, authed.post(f"/api/brands/{b['id']}/scans", json={"sources": ["bluesky", "mastodon", "apple_app_store"]}, headers=CSRF).json()["id"])
        by = {x["source"]: x for x in s["sources"]}
        assert by["bluesky"]["status"] in ("ok", "empty") and by["bluesky"]["queries_failed"] == 0  # every 503 recovered on retry
        assert calls["bluesky"] == 2 * by["bluesky"]["queries_total"]
        assert by["mastodon"]["status"] == "failed" and calls["mastodon"] == 1  # auth errors are not retried; stop early
        assert by["apple_app_store"]["status"] == "empty"  # kept scanning despite the Mastodon failure
        reg = registry(authed)
        assert reg["mastodon"]["state"] == "unavailable" and reg["mastodon"]["last_attempted_scan"]["scan_id"] == s["id"]
        assert reg["bluesky"]["last_success"]["via"] == "scan" and reg["bluesky"]["last_success"]["scan_id"] == s["id"]
        d = authed.get("/api/dashboard", params={"brand_id": b["id"]}).json()
        assert d["metrics"]["sources_unavailable"] >= 1 and "Mastodon" in d["unavailable_sources"]


def test_legacy_test_results_are_migrated(authed):
    from app.services.backfill import migrate_legacy_source_tests

    set_raw_config(authed, last_tests={"bluesky": {"status": "ok", "outcome": "ok", "detail": "Live query returned 3 result(s)", "latency_ms": 120,
                                                   "at": "2026-10-01T10:00:00+00:00"}})
    assert migrate_legacy_source_tests() >= 1
    with SessionLocal() as db:
        rows = db.query(SourceCheck).filter(SourceCheck.organization_id == org_id(authed), SourceCheck.source == "bluesky").all()
        assert [r.outcome for r in rows] == ["ok"]
    assert registry(authed)["bluesky"]["last_success"]["via"] == "test"
