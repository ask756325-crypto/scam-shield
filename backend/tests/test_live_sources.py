"""LIVE integration checks against real public endpoints. Opt-in: SCAMSHIELD_LIVE_TESTS=1 pytest tests/test_live_sources.py

These hit Bluesky's public AppView and mastodon.social with a handful of unauthenticated requests (well inside
documented limits). If a source can't be reached from this network, the test fails with the real reason —
it is never faked or skipped silently.
"""
import os

import httpx
import pytest

from app.detection.engine import BrandContext, evaluate, record_key
from app.detection.exclusion import OfficialAccountRef
from app.sources.base import SourceError
from app.sources.bluesky import BlueskyAdapter
from app.sources.mastodon import MastodonAdapter
from conftest import CSRF, signup, wait_for_scan

pytestmark = pytest.mark.skipif(os.environ.get("SCAMSHIELD_LIVE_TESTS") != "1", reason="live network tests are opt-in (SCAMSHIELD_LIVE_TESTS=1)")

# A single letters-only token: Bluesky tokenizes on punctuation/digits, so "abc-123" style strings still match.
NONSENSE = "zqxjvkbnmwqptlxr"
UA = {"User-Agent": "ScamShieldAI/1.0 (live integration test)"}


async def _client():
    return httpx.AsyncClient(timeout=15, headers=UA)


async def test_bluesky_real_query_normalizes_profiles():
    async with await _client() as c:
        recs = await BlueskyAdapter().search("bluesky", c)
    assert recs, "Bluesky returned no actors for 'bluesky'"
    r = recs[0]
    assert r.external_id.startswith("did:") and r.handle and r.url.startswith("https://bsky.app/profile/")
    assert r.source_type == "live" and r.provenance["query"] == "bluesky"


async def test_mastodon_real_query_normalizes_accounts():
    a = MastodonAdapter({"mastodon_instances": ["mastodon.social"]})
    async with await _client() as c:
        recs = await a.search("mastodon", c)
    assert recs, "mastodon.social returned no accounts for 'mastodon'"
    assert all(r.url.startswith("https://") and "@" in (r.handle or "") for r in recs)
    assert a.instance_rate_limits.get("mastodon.social", {}).get("limit"), "expected X-RateLimit headers from mastodon.social"


async def test_empty_results_are_success_not_failure():
    async with await _client() as c:
        assert await BlueskyAdapter().search(NONSENSE, c) == []
        assert await MastodonAdapter({"mastodon_instances": ["mastodon.social"]}).search(NONSENSE, c) == []


async def test_official_accounts_excluded_on_real_data():
    async with await _client() as c:
        bsky = await BlueskyAdapter().search("bluesky", c)
        masto = await MastodonAdapter({"mastodon_instances": ["mastodon.social"]}).search("mastodon", c)
    bsky_brand = BrandContext(name="Bluesky", official_accounts=[OfficialAccountRef("bluesky", "bsky.app")], official_domains=["bsky.app"])
    excluded = {e.record.handle: e.excluded.rule for e in evaluate(bsky_brand, bsky) if e.excluded}
    assert "bsky.app" in excluded, f"@bsky.app not found/excluded in live results: {[r.handle for r in bsky][:10]}"
    masto_brand = BrandContext(name="Mastodon", official_accounts=[OfficialAccountRef("mastodon", "mastodon@mastodon.social", "https://mastodon.social/@Mastodon")])
    excluded_m = [e for e in evaluate(masto_brand, masto) if e.excluded]
    assert excluded_m and excluded_m[0].excluded.rule in ("official_platform_handle", "official_profile_url")


async def test_same_account_across_instances_is_deduplicated():
    a = MastodonAdapter({"mastodon_instances": ["mastodon.social", "mastodon.online"]})
    async with await _client() as c:
        recs = await a.search("Mastodon", c)
    keys = [record_key(r) for r in recs]
    official = [k for k in keys if k.endswith("https://mastodon.social/@Mastodon")]
    assert len(official) >= 1
    assert len(set(keys)) < len(keys) or a.warnings, "expected the same account from both instances (deduplicated by profile URL in the scanner)"


async def test_unreachable_instance_reports_unavailable():
    a = MastodonAdapter({"mastodon_instances": ["no-such-instance-scamshield.example"]})
    async with await _client() as c:
        with pytest.raises(SourceError) as e:
            await a.search("acme", c)
    assert e.value.kind == "unavailable"


def test_end_to_end_live_social_scan(client):
    signup(client)
    b = client.post("/api/brands", json={
        "name": "Bluesky", "official_domains": ["bsky.app", "bsky.social"],
        "official_accounts": [{"platform": "bluesky", "handle": "bsky.app"}, {"platform": "mastodon", "handle": "bluesky@mastodon.social"}],
    }, headers=CSRF).json()
    s = client.post(f"/api/brands/{b['id']}/scans", json={"sources": ["bluesky", "mastodon"]}, headers=CSRF).json()
    s = wait_for_scan(client, s["id"], timeout=150)
    by = {x["source"]: x for x in s["sources"]}
    assert by["bluesky"]["status"] in ("ok", "partial"), by["bluesky"]
    assert by["mastodon"]["status"] in ("ok", "partial", "empty"), by["mastodon"]
    assert s["excluded_official"] >= 1  # @bsky.app (and *.bsky.app domain handles)
    assert s["candidates_unique"] > 0
    exc = client.get(f"/api/brands/{b['id']}/exclusions").json()
    assert any(e["rule"] in ("official_platform_handle", "bluesky_verified_domain_handle") for e in exc)
    items = client.get("/api/findings", params={"brand_id": b["id"], "include_signals": "true", "limit": 5}).json()["items"]
    assert all(f["candidate"]["source_type"] == "live" and f["detection_type"] for f in items)


async def test_google_play_real_query_over_verified_tls():
    import ssl

    from app.sources.google_play import GooglePlayAdapter

    a = GooglePlayAdapter(brand_names=["PayPal"])
    recs = await a.search("paypal", None)
    assert ssl._create_default_https_context is ssl.create_default_context  # scraper's unverified-TLS override undone
    assert recs and all(r.external_id and r.url.startswith("https://play.google.com/") for r in recs)
    enriched = await a.enrich(recs[:3], None)
    assert any(r.publisher_id for r in enriched), "detail lookups returned no developer IDs"


async def test_apple_real_catalog_through_engine_excludes_official_app():
    from app.detection.exclusion import OfficialAppRef
    from app.sources.apple import AppleAppStoreAdapter

    async with await _client() as c:
        recs = await AppleAppStoreAdapter().search("paypal", c)
    assert recs and all(r.kind == "app" and r.external_id and r.url and r.publisher_name for r in recs)
    official = [r for r in recs if (r.publisher_name or "").lower().startswith("paypal")]
    assert official, f"no PayPal-published app in live results: {[(r.name, r.publisher_name) for r in recs][:10]}"
    o = official[0]
    brand = BrandContext(name="PayPal", official_domains=["paypal.com"],
                         official_apps=[OfficialAppRef("apple", o.external_id, o.metadata.get("track_id"), o.publisher_id, o.publisher_name)])
    out = evaluate(brand, recs)
    assert any(e.excluded and e.record.external_id == o.external_id for e in out)
    scored = [e for e in out if e.assessment]
    assert scored and all("package" in e.assessment.signals and "publisher" in e.assessment.signals for e in scored)
    # Other apps by the official developer account are recognised, not rated as impersonation.
    for e in scored:
        if e.record.publisher_id == o.publisher_id:
            assert e.assessment.risk_level in ("low", "info")


def test_end_to_end_live_app_scan(client):
    signup(client)
    b = client.post("/api/brands", json={"name": "PayPal", "official_domains": ["paypal.com"]}, headers=CSRF).json()
    s = client.post(f"/api/brands/{b['id']}/scans", json={"sources": ["apple_app_store", "google_play"]}, headers=CSRF).json()
    s = wait_for_scan(client, s["id"], timeout=240)
    by = {x["source"]: x for x in s["sources"]}
    assert by["apple_app_store"]["status"] in ("ok", "partial"), by["apple_app_store"]
    assert by["google_play"]["status"] in ("ok", "partial"), by["google_play"]
    assert s["candidates_unique"] > 0
    items = client.get("/api/findings", params={"brand_id": b["id"], "kind": "app", "include_signals": "true", "limit": 50,
                                                "level": ["critical", "high", "medium", "low"]}).json()["items"]
    assert items and all(f["candidate"]["source_type"] == "live" and "package" in f["signal_scores"] for f in items)


def test_release_end_to_end_workflow_live(client):
    """Register → brand with official accounts/apps → live scan of all four sources → normalized, de-duplicated,
    officials excluded, scored, persisted → review → export → rescan and compare."""
    import csv
    import io

    signup(client)
    b = client.post("/api/brands", json={
        "name": "Bluesky", "official_domains": ["bsky.app", "bsky.social", "blueskyweb.xyz"],
        "official_accounts": [{"platform": "bluesky", "handle": "bsky.app"}],
        "official_apps": [{"store": "apple", "app_id": "xyz.blueskyweb.app"}, {"store": "google_play", "app_id": "xyz.blueskyweb.app"}],
    }, headers=CSRF).json()
    official_ids = {"xyz.blueskyweb.app", "bsky.app"}
    s1 = wait_for_scan(client, client.post(f"/api/brands/{b['id']}/scans", json={}, headers=CSRF).json()["id"], timeout=300)
    by = {x["source"]: x for x in s1["sources"]}
    assert set(by) == {"bluesky", "mastodon", "apple_app_store", "google_play"}
    assert s1["status"] in ("completed", "partial"), s1
    assert sum(1 for x in by.values() if x["status"] in ("ok", "partial")) >= 3, {k: (v["status"], v["error"]) for k, v in by.items()}
    assert s1["candidates_collected"] >= s1["candidates_unique"] > 0  # de-duplicated
    assert s1["excluded_official"] >= 2
    excl = client.get(f"/api/brands/{b['id']}/exclusions").json()
    assert {"official_platform_handle", "official_app_id"} & {e["rule"] for e in excl}
    items = client.get("/api/findings", params={"brand_id": b["id"], "limit": 200, "include_signals": "true",
                                                "level": ["critical", "high", "medium", "low"]}).json()["items"]
    assert items, "no findings persisted"
    for f in items:  # officials never appear as findings; every finding carries evidence and is live
        c = f["candidate"]
        native = c["metadata"].get("bundle_id") or c["metadata"].get("package") or c["handle"]
        assert native not in official_ids, c
        assert c["source_type"] == "live" and f["signal_scores"] and f["explanation"]
    keys = [(f["candidate"]["source"], f["candidate"]["external_id"]) for f in items]
    assert len(keys) == len(set(keys)), "duplicate findings"
    detail = client.get(f"/api/findings/{items[0]['id']}").json()
    assert detail["evidence"]["observed_facts"] and detail["observations"][0]["scan_id"] == s1["id"]
    r = client.post(f"/api/findings/{items[0]['id']}/decision", json={"action": "escalate", "note": "release check"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["status"] == "escalated"
    rows = list(csv.DictReader(io.StringIO(client.get("/api/findings/export.csv", params={"brand_id": b["id"]}).text)))
    assert len(rows) >= 1 and all(r["source_type"] == "live" for r in rows)
    assert client.get(f"/api/findings/{items[0]['id']}/report").status_code == 200
    s2 = wait_for_scan(client, client.post(f"/api/brands/{b['id']}/scans", json={}, headers=CSRF).json()["id"], timeout=300)
    changes = client.get(f"/api/scans/{s2['id']}/changes").json()["counts"]
    assert changes["recurring"] + changes["changed"] + changes["new"] > 0
    assert changes["resolved"] == 0  # one clean miss never resolves
    assert client.get(f"/api/findings/{items[0]['id']}").json()["status"] == "escalated"  # review decision survives rescans
    from collections import Counter

    levels = Counter(f["risk_level"] for f in items)
    top = [(f["risk_level"], f["candidate"]["name"], f["candidate"]["source"], f["corroborating_groups"]) for f in items if f["risk_level"] in ("critical", "high")][:8]
    print(f"\nLEVELS {dict(levels)} TOP {top}")
    print(f"\nLIVE RELEASE CHECK scan1={s1['id']} sources={ {k: v['status'] for k, v in by.items()} } unique={s1['candidates_unique']} "
          f"excluded={s1['excluded_official']} findings={len(items)} scan2 changes={changes}")


async def test_ct_domains_real_query():
    """crt.sh is a free community service with frequent outages; when it is down this fails with the real error."""
    from app.sources.ct_domains import CTDomainsAdapter

    async with httpx.AsyncClient(timeout=60, headers=UA) as c:
        recs = await CTDomainsAdapter().search("paypal", c)
    assert all(r.kind == "domain" and "paypal" in r.external_id.replace("-", "").replace(".", "") for r in recs)
