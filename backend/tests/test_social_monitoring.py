"""Social monitoring: query outcomes, rate limits, Mastodon specifics, dedup, detection types, list API."""
import time

import httpx
import pytest
import respx

from app.candidate import CandidateRecord
from app.services import scanner
from app.sources.base import SourceAdapter, SourceError, SourceInfo, parse_rate_limit
from app.sources.mastodon import MastodonAdapter
from conftest import CSRF, wait_for_scan
from test_api import create_brand


class ScriptedAdapter(SourceAdapter):
    """Replays a list of per-query behaviours: 'hit', 'empty', or a SourceError kind."""

    info = SourceInfo("scripted", "Scripted", "social", "live", "test", "test")

    def __init__(self, name, script):
        super().__init__({})
        self.name, self.script, self.calls = name, list(script), 0

    async def search(self, term, client):
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if step == "hit":
            return [CandidateRecord(self.name, "live", "account", f"{self.name}-dup", "Acme Wallet Support", handle="acmewallet-support",
                                    description="Verify your wallet on Telegram", url="https://example.test/x", provenance={"adapter": self.name, "query": term})]
        if step == "empty":
            return []
        raise SourceError(f"{self.name} {step}", step, retry_after=60)


def run(authed, brand_id, scripts: dict[str, list[str]]):
    scanner.adapter_factory = lambda name, cfg, names, epoch: ScriptedAdapter(name, scripts[name])
    s = authed.post(f"/api/brands/{brand_id}/scans", json={"sources": list(scripts)}, headers=CSRF).json()
    return wait_for_scan(authed, s["id"])


class TestQueryOutcomes:
    def test_each_failure_kind_is_reported_distinctly(self, authed):
        b = create_brand(authed, name="Outcome Co", aliases=["Acme Wallet"])
        s = run(authed, b["id"], {
            "bluesky": ["hit"],
            "mastodon": ["empty"],
            "apple_app_store": ["timeout"],
            "google_play": ["unavailable"],
        })
        by = {x["source"]: x for x in s["sources"]}
        assert by["bluesky"]["status"] == "ok" and by["bluesky"]["query_outcomes"]["ok"] == by["bluesky"]["queries_total"]
        assert by["mastodon"]["status"] == "empty" and by["mastodon"]["query_outcomes"] == {"empty": by["mastodon"]["queries_total"]}
        assert by["apple_app_store"]["status"] == "failed" and by["apple_app_store"]["failure_kind"] == "timeout"
        assert by["google_play"]["status"] == "failed" and by["google_play"]["failure_kind"] == "unavailable"
        assert s["status"] == "partial"  # other sources kept running despite failures

    def test_rate_limit_and_auth_stop_further_queries(self, authed):
        b = create_brand(authed, name="Limit Co", aliases=["Acme Wallet"])
        s = run(authed, b["id"], {"bluesky": ["hit", "rate_limited"], "mastodon": ["auth_required"]})
        by = {x["source"]: x for x in s["sources"]}
        bs = by["bluesky"]
        assert bs["status"] == "partial" and bs["failure_kind"] == "rate_limited"
        assert bs["query_outcomes"]["ok"] == 1 and bs["query_outcomes"]["rate_limited"] == bs["queries_total"] - 1
        assert "not attempted" in bs["error"]
        assert by["mastodon"]["status"] == "failed" and by["mastodon"]["failure_kind"] == "auth_required"
        assert by["mastodon"]["queries_done"] == by["mastodon"]["queries_total"]

    def test_empty_source_counts_as_clean_for_resolution(self, authed):
        b = create_brand(authed, name="Resolve Co", aliases=["Acme Wallet"])
        first = run(authed, b["id"], {"bluesky": ["hit"]})
        assert first["findings_new"] == 1
        second = run(authed, b["id"], {"bluesky": ["empty"]})
        assert second["sources"][0]["status"] == "empty" and second["findings_missing"] == 1 and second["findings_resolved"] == 0
        third = run(authed, b["id"], {"bluesky": ["empty"]})
        assert third["findings_resolved"] == 1  # two consecutive clean misses
        fourth = run(authed, b["id"], {"bluesky": ["hit"]})
        # A failed search must NOT count as a miss: run failures after re-observing.
        fifth = run(authed, b["id"], {"bluesky": ["unavailable"]})
        sixth = run(authed, b["id"], {"bluesky": ["unavailable"]})
        assert fourth["findings_resolved"] == 0 and fifth["findings_resolved"] == sixth["findings_resolved"] == 0
        assert fifth["findings_unverified"] == 1 and fifth["findings_missing"] == 0

    def test_duplicates_across_queries_are_merged(self, authed):
        b = create_brand(authed, name="Dup Co", aliases=["Acme Wallet"])
        s = run(authed, b["id"], {"bluesky": ["hit"], "mastodon": ["hit"]})
        # The same account returned by every query counts once per source.
        assert s["candidates_unique"] == 2 and all(x["candidates"] == 1 for x in s["sources"])
        f = authed.get("/api/findings", params={"brand_id": b["id"]}).json()["items"]
        bluesky = next(x for x in f if x["candidate"]["source"] == "bluesky")
        detail = authed.get(f"/api/findings/{bluesky['id']}").json()
        assert len(detail["observations"]) == 1
        assert len(detail["candidate"]["provenance"].get("queries", [])) == s["sources"][0]["queries_total"]


class TestMastodonAdapter:
    @respx.mock
    async def test_never_sends_resolve_and_requests_documented_limit(self):
        route = respx.get("https://mastodon.social/api/v2/search").mock(return_value=httpx.Response(200, json={"accounts": []}))
        async with httpx.AsyncClient() as c:
            assert await MastodonAdapter().search("acme", c) == []
        params = route.calls.last.request.url.params
        assert "resolve" not in params and "offset" not in params and params["limit"] == "40" and params["type"] == "accounts"

    @respx.mock
    async def test_partial_instance_failure_is_reported_not_swallowed(self):
        respx.get("https://mastodon.social/api/v2/search").mock(return_value=httpx.Response(200, json={"accounts": [
            {"id": "1", "username": "acme", "acct": "acme", "display_name": "Acme", "url": "https://mastodon.social/@acme"}]}))
        respx.get("https://broken.example/api/v2/search").mock(return_value=httpx.Response(503))
        a = MastodonAdapter({"mastodon_instances": ["mastodon.social", "broken.example"]})
        async with httpx.AsyncClient() as c:
            recs = await a.search("acme", c)
        assert len(recs) == 1 and any("broken.example" in w and "503" in w for w in a.warnings)

    @respx.mock
    async def test_rate_limit_headers_tracked_and_floor_respected(self):
        reset = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 120))
        respx.get("https://mastodon.social/api/v2/search").mock(return_value=httpx.Response(
            200, json={"accounts": []}, headers={"X-RateLimit-Limit": "300", "X-RateLimit-Remaining": "5", "X-RateLimit-Reset": reset}))
        a = MastodonAdapter()
        async with httpx.AsyncClient() as c:
            await a.search("acme", c)
            assert a.instance_rate_limits["mastodon.social"]["remaining"] == 5
            with pytest.raises(SourceError) as e:
                await a.search("acme 2", c)
        assert e.value.kind == "rate_limited" and 0 < e.value.retry_after <= 120

    def test_parse_ietf_ratelimit_headers(self):
        rl = parse_rate_limit(httpx.Headers({"ratelimit-limit": "3000", "ratelimit-remaining": "2990", "ratelimit-reset": "42"}))
        assert (rl.limit, rl.remaining, rl.reset_in) == (3000, 2990, 42.0)
        assert parse_rate_limit(httpx.Headers({})) is None

    @respx.mock
    async def test_http_status_classification(self):
        from app.sources.bluesky import ENDPOINT, BlueskyAdapter

        for status, kind in [(401, "auth_required"), (403, "auth_required"), (429, "rate_limited"), (502, "unavailable"), (400, "error")]:
            respx.get(ENDPOINT).mock(return_value=httpx.Response(status, headers={"Retry-After": "3"}))
            async with httpx.AsyncClient() as c:
                with pytest.raises(SourceError) as e:
                    await BlueskyAdapter().search("x", c)
            assert e.value.kind == kind, status
            if kind == "rate_limited":
                assert e.value.retry_after == 3.0


class TestDetectionTypesAndList:
    def test_demo_findings_carry_detection_types(self, authed):
        demo = authed.post("/api/demo/brand", headers=CSRF).json()
        wait_for_scan(authed, authed.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()["id"])
        items = authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 200}).json()["items"]
        by = {f["candidate"]["name"]: f["detection_type"] for f in items}
        assert by["Northvale Pay"] == "fake_brand_page"
        assert by["N0rthvale Pay"] == "scam_account"
        assert by["Northvale Rewards"] == "fake_profile"
        assert by["Northvale Hiking Club"] == "lookalike_account"
        assert by["Northvale Pay - Wallet Login"] == "suspicious_app"
        assert by["Northvale Pay Business"] == "official_publisher_app"

    def test_list_filters_by_type_and_includes_signal_scores(self, authed):
        demo = authed.post("/api/demo/brand", headers=CSRF).json()
        wait_for_scan(authed, authed.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()["id"])
        r = authed.get("/api/findings", params={"brand_id": demo["id"], "kind": "account", "detection_type": ["scam_account", "fake_brand_page"], "include_signals": "true"}).json()
        assert r["total"] >= 2 and {f["detection_type"] for f in r["items"]} <= {"scam_account", "fake_brand_page"}
        f = r["items"][0]
        assert {"name", "handle", "logo", "description", "urls", "scam"} <= set(f["signal_scores"])
        assert f["reasons"] and isinstance(f["not_evaluated"], list)
        plain = authed.get("/api/findings", params={"brand_id": demo["id"]}).json()["items"][0]
        assert "signal_scores" not in plain


def test_link_only_corroboration_is_not_called_a_fake_profile():
    """Regression from live data: an artist named 'Dj Paypal' linking to their own domain."""
    from app.detection.scoring import assess
    from app.detection.signals import Signal

    sigs = [Signal("name", True, 0.91, data={"risky_terms": []}), Signal("handle", True, 0.85, data={"risky_terms": []}),
            Signal("urls", True, 0.96), Signal("scam", True, 0.0, data={"categories": []}), Signal.missing("logo", "no logo")]
    assert assess(sigs, "account").detection_type == "lookalike_account"
    staff = [Signal("name", True, 0.9, data={"risky_terms": ["support"]}), Signal("urls", True, 0.96), Signal("scam", True, 0.0, data={"categories": []})]
    assert assess(staff, "account").detection_type == "fake_profile"


def test_backfill_assigns_types_to_legacy_findings(authed):
    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import Finding
    from app.services.backfill import backfill_detection_types

    demo = authed.post("/api/demo/brand", headers=CSRF).json()
    wait_for_scan(authed, authed.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()["id"])
    before = {f["candidate"]["name"]: f["detection_type"] for f in authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 200}).json()["items"]}
    with SessionLocal() as db:
        db.execute(update(Finding).where(Finding.brand_id == demo["id"]).values(detection_type=None))
        db.commit()
    assert backfill_detection_types() >= len(before)
    after = {f["candidate"]["name"]: f["detection_type"] for f in authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 200}).json()["items"]}
    assert after == before
