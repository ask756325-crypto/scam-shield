"""Overview dashboard: metrics from persisted data, date filtering, source availability, empty states."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.db import SessionLocal
from app.models import Candidate, Scan
from app.services import scanner
from conftest import CSRF, signup, wait_for_scan
from test_api import FakeAdapter, create_brand


def demo_scan(client):
    demo = client.post("/api/demo/brand", headers=CSRF).json()
    s = client.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()
    return demo, wait_for_scan(client, s["id"])


def test_new_brand_dashboard_has_zeros_not_invented_numbers(client):
    signup(client)
    b = create_brand(client, name="Fresh Brand")
    d = client.get("/api/dashboard", params={"brand_id": b["id"]}).json()
    m = d["metrics"]
    assert m["candidates_scanned"] == m["review_required"] == m["high_risk_open"] == m["official_excluded"] == 0
    assert d["last_completed_scan"] is None and d["recent_scans"] == [] and d["severity_by_platform"] == []
    assert all(h["last_success_at"] is None for h in d["source_health"])


def test_metrics_match_persisted_findings(client):
    signup(client)
    demo, scan = demo_scan(client)
    d = client.get("/api/dashboard", params={"brand_id": demo["id"]}).json()
    findings = client.get("/api/findings", params={"brand_id": demo["id"], "status": "open", "limit": 200}).json()["items"]
    levels = [f["risk_level"] for f in findings]
    m = d["metrics"]
    assert m["candidates_scanned"] == scan["candidates_unique"]
    assert m["review_required"] == sum(l in ("critical", "high", "medium") for l in levels)
    assert m["high_risk_open"] == sum(l in ("critical", "high") for l in levels)
    assert m["official_excluded"] == scan["excluded_official"] == 4
    # Severity × platform grid sums to the open findings it covers.
    grid_total = sum(r["total"] for r in d["severity_by_platform"])
    assert grid_total == sum(l in ("critical", "high", "medium", "low") for l in levels)
    assert {r["platform"] for r in d["severity_by_platform"]} <= {"bluesky", "mastodon", "apple_app_store", "google_play"}
    # Review queue summary
    assert sum(d["review"]["open_by_level"].values()) == m["review_required"]
    assert d["review"]["top"][0]["risk_level"] == "critical"
    # Demo brands report the synthetic source, not live ones.
    assert [h["name"] for h in d["source_health"]] == ["demo"]
    assert d["source_health"][0]["last_success_scan_id"] == scan["id"]
    assert d["last_completed_scan"]["id"] == scan["id"]


def test_date_filter_scopes_period_activity_only(client):
    signup(client)
    demo, scan = demo_scan(client)
    old = datetime.now(timezone.utc) - timedelta(days=40)
    with SessionLocal() as db:
        db.execute(update(Scan).where(Scan.id == scan["id"]).values(created_at=old))
        db.execute(update(Candidate).where(Candidate.brand_id == demo["id"]).values(last_observed_at=old))
        db.commit()
    all_time = client.get("/api/dashboard", params={"brand_id": demo["id"]}).json()
    week = client.get("/api/dashboard", params={"brand_id": demo["id"], "days": 7}).json()
    quarter = client.get("/api/dashboard", params={"brand_id": demo["id"], "days": 90}).json()
    assert week["metrics"]["candidates_scanned"] == 0 and week["recent_scans"] == [] and week["severity_by_platform"] == []
    assert quarter["metrics"]["candidates_scanned"] == all_time["metrics"]["candidates_scanned"] > 0
    # Current-state numbers are not hidden by the period filter.
    assert week["metrics"]["review_required"] == all_time["metrics"]["review_required"] > 0
    assert week["metrics"]["official_excluded"] == 4
    # The findings list honours the same window.
    assert client.get("/api/findings", params={"brand_id": demo["id"], "since_days": 7}).json()["total"] == 0
    assert client.get("/api/findings", params={"brand_id": demo["id"], "since_days": 90}).json()["total"] > 0
    assert client.get("/api/dashboard", params={"days": 3}).status_code == 422
    assert client.get("/api/findings", params={"since_days": 3}).status_code == 422


def test_unavailable_sources_counted_from_real_scan_outcomes(client):
    signup(client)
    b = create_brand(client, name="Partial Co", aliases=["Acme Wallet"])
    behaviours = {"bluesky": "ok", "mastodon": "fail", "apple_app_store": "ok", "google_play": "ratelimit"}
    scanner.adapter_factory = lambda name, cfg, names, epoch: FakeAdapter(name, behaviours[name])
    s = client.post(f"/api/brands/{b['id']}/scans", json={}, headers=CSRF).json()
    s = wait_for_scan(client, s["id"])
    d = client.get("/api/dashboard", params={"brand_id": b["id"]}).json()
    assert d["metrics"]["sources_enabled"] == 4
    assert d["metrics"]["sources_unavailable"] == 2
    assert set(d["unavailable_sources"]) == {"Mastodon", "Google Play"}
    by = {h["name"]: h for h in d["source_health"]}
    assert by["bluesky"]["last_success_scan_id"] == s["id"] and by["mastodon"]["last_success_at"] is None
    assert d["last_completed_scan"]["status"] == "partial"
    # Still useful: the healthy sources' findings are present.
    assert d["metrics"]["review_required"] >= 1


def test_dashboard_isolated_per_organization(client):
    signup(client, org="Org One")
    demo, _ = demo_scan(client)
    client.cookies.clear()
    signup(client, org="Org Two")
    assert client.get("/api/dashboard", params={"brand_id": demo["id"]}).status_code == 404
    assert client.get("/api/dashboard").json() == {"empty": True, "brands": 0}
