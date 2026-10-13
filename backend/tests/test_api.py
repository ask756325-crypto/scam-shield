"""API integration tests: auth, access control, brands, scans, findings, exports, scheduling."""
import csv
import io
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from PIL import Image

from app.candidate import CandidateRecord
from app.db import SessionLocal
from app.models import Brand
from app.services import mailer, scanner, scheduler
from app.sources.base import SourceAdapter, SourceError, SourceInfo
from conftest import CSRF, signup, wait_for_scan

BRAND = {
    "name": "Acme Wallet",
    "aliases": ["Acme"],
    "description": "Acme Wallet offers instant payments, contactless cards and international money transfers.",
    "official_domains": ["https://www.acmewallet.com/", "acme.example"],
    "keywords": ["instant payments"],
    "official_accounts": [{"platform": "bluesky", "handle": "@AcmeWallet.com"}],
    "official_apps": [{"store": "apple", "app_id": "com.acme.wallet", "track_id": "id123", "publisher_id": "900", "publisher_name": "Acme Inc"}],
}


def create_brand(client, **over):
    r = client.post("/api/brands", json={**BRAND, **over}, headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------- authentication


class TestAuth:
    def test_signup_login_logout_cycle(self, client):
        email = signup(client)
        me = client.get("/api/auth/me")
        assert me.status_code == 200 and me.json()["user"]["email"] == email and me.json()["role"] == "owner"
        assert "password" not in str(me.json()).lower()
        assert client.post("/api/auth/logout", headers=CSRF).status_code == 200
        assert client.get("/api/auth/me").status_code == 401
        r = client.post("/api/auth/login", json={"email": email.upper(), "password": "correct-horse-42"}, headers=CSRF)
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie

    def test_wrong_password_generic_error(self, client):
        email = signup(client)
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"email": email, "password": "nope-nope-nope"}, headers=CSRF)
        r2 = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "nope-nope-nope"}, headers=CSRF)
        assert r.status_code == r2.status_code == 401
        assert r.json()["detail"] == r2.json()["detail"]

    def test_weak_password_and_duplicate_email(self, client):
        r = client.post("/api/auth/signup", json={"email": "w@example.com", "password": "short", "name": "W", "organization": "O"}, headers=CSRF)
        assert r.status_code == 422
        email = signup(client)
        client.cookies.clear()
        r = client.post("/api/auth/signup", json={"email": email, "password": "another-pass-9", "name": "W", "organization": "O"}, headers=CSRF)
        assert r.status_code == 409

    def test_login_rate_limited(self, client):
        email = signup(client)
        client.cookies.clear()
        codes = [client.post("/api/auth/login", json={"email": email, "password": "bad-password-1"}, headers=CSRF).status_code for _ in range(10)]
        assert codes[-1] == 429 and 401 in codes

    def test_csrf_header_required(self, client):
        r = client.post("/api/auth/login", json={"email": "a@example.com", "password": "x"})
        assert r.status_code == 403

    def test_protected_endpoints_require_session(self, client):
        for path in ("/api/brands", "/api/findings", "/api/scans", "/api/dashboard", "/api/sources", "/api/settings/detection"):
            assert client.get(path).status_code == 401, path
        client.cookies.set("ss_session", "forged-token")
        assert client.get("/api/brands").status_code == 401

    def test_password_reset_flow(self, client, monkeypatch):
        sent = {}
        monkeypatch.setattr(mailer, "send_reset_link", lambda to, link: sent.update(to=to, link=link))
        email = signup(client)
        client.cookies.clear()
        assert client.post("/api/auth/password-reset/request", json={"email": "ghost@example.com"}, headers=CSRF).json()["ok"]
        assert "link" not in sent
        assert client.post("/api/auth/password-reset/request", json={"email": email}, headers=CSRF).status_code == 200
        token = sent["link"].split("token=")[1]
        r = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "brand-new-pass-7"}, headers=CSRF)
        assert r.status_code == 200
        # Token is single-use
        assert client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "brand-new-pass-8"}, headers=CSRF).status_code == 400
        assert client.post("/api/auth/login", json={"email": email, "password": "brand-new-pass-7"}, headers=CSRF).status_code == 200

    def test_change_password(self, authed):
        r = authed.post("/api/auth/change-password", json={"current_password": "wrong-one-11", "new_password": "next-pass-123"}, headers=CSRF)
        assert r.status_code == 400
        r = authed.post("/api/auth/change-password", json={"current_password": "correct-horse-42", "new_password": "next-pass-123"}, headers=CSRF)
        assert r.status_code == 200


# ---------------------------------------------------------------------------- brands & isolation


class TestBrands:
    def test_create_validates_and_normalizes(self, authed):
        b = create_brand(authed)
        assert b["official_domains"] == ["acmewallet.com", "acme.example"]
        assert b["official_accounts"][0]["handle"] == "acmewallet.com"
        assert b["official_apps"][0]["track_id"] == "123"
        got = authed.get(f"/api/brands/{b['id']}").json()
        assert got["name"] == "Acme Wallet"

    @pytest.mark.parametrize("bad", [
        {"name": "A"},
        {"official_domains": ["not a domain"]},
        {"official_apps": [{"store": "apple", "app_id": "not an id"}]},
        {"official_apps": [{"store": "windows", "app_id": "com.a.b"}]},
        {"official_accounts": [{"platform": "bluesky", "handle": "a b"}]},
        {"official_accounts": [{"platform": "bluesky", "handle": "x", "profile_url": "javascript:alert(1)"}]},
    ])
    def test_invalid_input_rejected(self, authed, bad):
        r = authed.post("/api/brands", json={**BRAND, **bad}, headers=CSRF)
        assert r.status_code == 422, r.text
        assert r.json()["detail"]

    def test_update_and_delete(self, authed):
        b = create_brand(authed, name="Zeta Pay")
        r = authed.put(f"/api/brands/{b['id']}", json={**BRAND, "name": "Zeta Pay", "aliases": ["Zeta"], "official_accounts": []}, headers=CSRF)
        assert r.status_code == 200 and r.json()["aliases"] == ["Zeta"] and r.json()["official_accounts"] == []
        assert authed.delete(f"/api/brands/{b['id']}", headers=CSRF).status_code == 200
        assert authed.get(f"/api/brands/{b['id']}").status_code == 404

    def test_logo_upload_hashes_and_rejects_bad_files(self, authed):
        b = create_brand(authed, name="Logo Co")
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (10, 120, 80)).save(buf, "PNG")
        r = authed.post(f"/api/brands/{b['id']}/logo", files={"file": ("l.png", buf.getvalue(), "image/png")}, headers=CSRF)
        assert r.status_code == 200 and r.json()["logo_phash"]
        assert authed.get(f"/api/brands/{b['id']}/logo").headers["content-type"] == "image/png"
        r = authed.post(f"/api/brands/{b['id']}/logo", files={"file": ("x.png", b"<?php evil ?>", "image/png")}, headers=CSRF)
        assert r.status_code == 422
        r = authed.post(f"/api/brands/{b['id']}/logo", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")}, headers=CSRF)
        assert r.status_code == 415

    def test_cross_organization_isolation(self, client):
        signup(client, org="Org A")
        brand = create_brand(client, name="Private Brand")
        demo = client.post("/api/demo/brand", headers=CSRF).json()
        scan = client.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()
        wait_for_scan(client, scan["id"])
        finding_id = client.get("/api/findings", params={"brand_id": demo["id"]}).json()["items"][0]["id"]
        client.cookies.clear()
        signup(client, org="Org B")
        assert client.get(f"/api/brands/{brand['id']}").status_code == 404
        assert client.put(f"/api/brands/{brand['id']}", json=BRAND, headers=CSRF).status_code == 404
        assert client.delete(f"/api/brands/{brand['id']}", headers=CSRF).status_code == 404
        assert client.post(f"/api/brands/{brand['id']}/scans", json={}, headers=CSRF).status_code == 404
        assert client.get(f"/api/scans/{scan['id']}").status_code == 404
        assert client.get(f"/api/findings/{finding_id}").status_code == 404
        assert client.post(f"/api/findings/{finding_id}/decision", json={"action": "mark_safe"}, headers=CSRF).status_code == 404
        assert client.get("/api/findings").json()["total"] == 0
        assert client.get("/api/brands").json() == []
        assert "Private Brand" not in client.get("/api/findings/export.csv").text


# ---------------------------------------------------------------------------- scans & findings (demo data)


def demo_setup(client):
    demo = client.post("/api/demo/brand", headers=CSRF).json()
    assert demo["is_demo"] and demo["has_logo"]
    return demo


def run_scan(client, brand_id, body=None):
    r = client.post(f"/api/brands/{brand_id}/scans", json=body or {}, headers=CSRF)
    assert r.status_code == 202, r.text
    return wait_for_scan(client, r.json()["id"])


class TestDemoScan:
    def test_full_workflow(self, authed):
        demo = demo_setup(authed)
        s = run_scan(authed, demo["id"])
        assert s["status"] == "completed" and s["mode"] == "demo" and s["progress"] == 1.0
        assert s["sources"][0]["status"] == "ok" and s["sources"][0]["queries_done"] == s["sources"][0]["queries_total"]
        assert s["excluded_official"] == 4 and s["findings_new"] > 0

        items = authed.get("/api/findings", params={"brand_id": demo["id"], "sort": "risk"}).json()["items"]
        names = {f["candidate"]["name"]: f for f in items}
        assert names["N0rthvale Pay"]["risk_level"] == "critical"
        assert names["Northvale Pay - Wallet Login"]["risk_level"] == "critical"
        assert names["Northvale Rewards"]["risk_level"] in ("high", "critical")
        assert names["Northvale Hiking Club"]["risk_level"] == "low"  # false-positive control
        assert names["Northvale Pay Business"]["risk_level"] == "low"  # official publisher, different app
        assert "Maya Okafor" not in names  # unrelated → not retained
        assert all(f["candidate"]["source_type"] == "simulated" for f in items)
        official_ids = {"bluesky:did:plc:demo-official-nv", "mastodon:https://mastodon.example/@northvale", "apple_app_store:com.northvale.pay", "google_play:com.northvale.pay"}
        assert not official_ids & {f["candidate"]["external_id"] for f in items}  # officials excluded by exact ID
        assert names["Northvale Pay"]["detection_type"] == "fake_brand_page"  # same name, unofficial account

        exc = authed.get(f"/api/brands/{demo['id']}/exclusions").json()
        assert {e["rule"] for e in exc} == {"official_platform_handle", "official_app_id"}

        crit = names["N0rthvale Pay"]
        detail = authed.get(f"/api/findings/{crit['id']}").json()
        assert detail["signals"]["signals"]["logo"]["evaluated"] and detail["observations"]
        assert "review required" in detail["classification"]

        r = authed.post(f"/api/findings/{crit['id']}/decision", json={"action": "confirm", "note": "Reported"}, headers=CSRF)
        assert r.json()["status"] == "confirmed" and r.json()["decisions"][-1]["note"] == "Reported"
        fan = names["Northvale Pay Fans"]
        assert authed.post(f"/api/findings/{fan['id']}/decision", json={"action": "mark_safe"}, headers=CSRF).json()["status"] == "safe"
        assert authed.post(f"/api/findings/{fan['id']}/decision", json={"action": "delete"}, headers=CSRF).status_code == 422

        # Filtering & sorting
        crit_only = authed.get("/api/findings", params={"brand_id": demo["id"], "level": "critical"}).json()
        assert crit_only["total"] >= 2 and all(f["risk_level"] == "critical" for f in crit_only["items"])
        apps = authed.get("/api/findings", params={"brand_id": demo["id"], "kind": "app"}).json()["items"]
        assert apps and all(f["candidate"]["kind"] == "app" for f in apps)
        apple = authed.get("/api/findings", params={"brand_id": demo["id"], "source": "apple_app_store"}).json()["items"]
        assert apple and all(f["candidate"]["platform"] == "apple" for f in apple)
        by_name = authed.get("/api/findings", params={"brand_id": demo["id"], "sort": "name", "order": "asc"}).json()["items"]
        assert [f["candidate"]["name"] for f in by_name] == sorted(f["candidate"]["name"] for f in by_name)

        # Dashboard metrics come from persisted data
        d = authed.get("/api/dashboard", params={"brand_id": demo["id"]}).json()
        assert d["metrics"]["candidates_scanned"] == s["candidates_unique"]
        assert d["metrics"]["official_excluded"] == 4 and d["metrics"]["confirmed"] == 1
        assert sum(d["severity"].values()) == len([f for f in items if f["status"] == "open" and f["id"] not in (crit["id"], fan["id"])])

    def test_csv_export(self, authed):
        demo = demo_setup(authed)
        run_scan(authed, demo["id"])
        r = authed.get("/api/findings/export.csv", params={"brand_id": demo["id"], "level": ["critical", "high"]})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert rows and {row["risk_level"] for row in rows} <= {"critical", "high"}
        assert {"finding_id", "url", "explanation", "source_type"} <= set(rows[0])

    def test_csv_injection_neutralized(self):
        from app.routers.findings import _safe_cell

        assert _safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and _safe_cell("Acme") == "Acme"

    def test_rescan_comparisons_new_changed_recurring_resolved(self, authed):
        demo = demo_setup(authed)
        first = run_scan(authed, demo["id"])
        assert first["findings_changed"] == first["findings_recurring"] == first["findings_resolved"] == 0
        second = run_scan(authed, demo["id"])
        assert second["findings_new"] == 1  # "Nortvale Pay Help" appears
        assert second["findings_changed"] >= 1  # support account description changed
        assert second["findings_recurring"] >= 5
        third = run_scan(authed, demo["id"])
        # Giveaway account disappeared: one clean miss → "missing", not yet resolved.
        assert third["findings_missing"] == 1 and third["findings_resolved"] == 0
        items = {f["candidate"]["name"]: f for f in authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 200}).json()["items"]}
        assert items["N0rthvale Pay"]["change_state"] == "missing" and items["N0rthvale Pay"]["status"] == "open"
        assert items["Northvale Pay Support"]["risk_level"] == "critical"
        fourth = run_scan(authed, demo["id"])
        assert fourth["findings_resolved"] == 1  # second consecutive clean miss
        items = {f["candidate"]["name"]: f for f in authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 200}).json()["items"]}
        assert items["N0rthvale Pay"]["change_state"] == "resolved" and items["N0rthvale Pay"]["status"] == "resolved"
        history = authed.get("/api/scans", params={"brand_id": demo["id"]}).json()
        assert [h["id"] for h in history][:4] == [fourth["id"], third["id"], second["id"], first["id"]]

    def test_safe_finding_reopens_when_listing_changes(self, authed):
        demo = demo_setup(authed)
        run_scan(authed, demo["id"])
        f = next(x for x in authed.get("/api/findings", params={"brand_id": demo["id"]}).json()["items"] if x["candidate"]["name"] == "Northvale Pay Support")
        authed.post(f"/api/findings/{f['id']}/decision", json={"action": "mark_safe"}, headers=CSRF)
        run_scan(authed, demo["id"])
        after = authed.get(f"/api/findings/{f['id']}").json()
        assert after["status"] == "open" and after["decisions"][-1]["action"] == "reopen"

    def test_concurrent_scan_rejected_and_demo_source_restricted(self, authed):
        b = create_brand(authed, name="Real Brand")
        r = authed.post(f"/api/brands/{b['id']}/scans", json={"sources": ["demo"]}, headers=CSRF)
        assert r.status_code == 400  # synthetic data is never available to non-demo brands


# ---------------------------------------------------------------------------- live-source pipeline with fakes


class FakeAdapter(SourceAdapter):
    info = SourceInfo("fake", "Fake", "social", "live", "test", "test")

    def __init__(self, name, behaviour):
        super().__init__({})
        self.name, self.behaviour = name, behaviour

    async def search(self, term, client):
        if self.behaviour == "fail":
            raise SourceError(f"{self.name} unavailable (HTTP 503)", "unavailable")
        if self.behaviour == "crash":
            raise KeyError("unexpected payload")
        if self.behaviour == "ratelimit":
            raise SourceError("rate limited", "rate_limited", retry_after=60)
        return [CandidateRecord(self.name, "live", "account", f"{self.name}-1", "Acme Wallet Support", handle="acmewallet-support",
                                description="Verify your wallet now, DM us on Telegram", url="https://example.test/1")]


class TestSourceFailures:
    def test_one_failing_source_does_not_stop_others(self, authed):
        b = create_brand(authed, name="Failure Co", aliases=["Acme Wallet"])
        behaviours = {"bluesky": "ok", "mastodon": "fail", "apple_app_store": "crash", "google_play": "ratelimit"}
        scanner.adapter_factory = lambda name, cfg, names, epoch: FakeAdapter(name, behaviours[name])
        s = run_scan(authed, b["id"])
        by = {x["source"]: x for x in s["sources"]}
        assert s["status"] == "partial"
        assert by["bluesky"]["status"] == "ok" and by["bluesky"]["candidates"] == 1
        assert by["mastodon"]["status"] == "failed" and "503" in by["mastodon"]["error"]
        assert by["apple_app_store"]["status"] == "failed" and "KeyError" in by["apple_app_store"]["error"]
        assert by["google_play"]["status"] == "failed" and by["google_play"]["queries_done"] == by["google_play"]["queries_total"]
        f = authed.get("/api/findings", params={"brand_id": b["id"]}).json()["items"]
        assert len(f) == 1 and f[0]["candidate"]["source_type"] == "live"
        # No synthetic substitution for failed sources
        assert not any(x["candidate"]["source"] == "demo" for x in f)

    def test_all_sources_failing_marks_scan_failed(self, authed):
        b = create_brand(authed, name="Down Co")
        scanner.adapter_factory = lambda name, cfg, names, epoch: FakeAdapter(name, "fail")
        s = run_scan(authed, b["id"])
        assert s["status"] == "failed" and s["error"]
        # Failed sources do not resolve existing findings
        assert s["findings_resolved"] == 0

    def test_live_scan_dedupes_across_queries(self, authed):
        b = create_brand(authed, name="Dedupe Co", aliases=["Acme Wallet"])
        scanner.adapter_factory = lambda name, cfg, names, epoch: FakeAdapter(name, "ok")
        s = run_scan(authed, b["id"], {"sources": ["bluesky"]})
        assert s["sources"][0]["queries_total"] > 1
        assert s["candidates_unique"] == 1


# ---------------------------------------------------------------------------- scheduling & import


class TestSchedulingAndImport:
    def test_scheduler_creates_due_scans_only(self, authed):
        demo = demo_setup(authed)
        r = authed.put(f"/api/brands/{demo['id']}/schedule", json={"frequency": "interval", "interval_hours": 6}, headers=CSRF)
        assert r.status_code == 200
        now = datetime.now(timezone.utc)
        assert not [sid for sid in scheduler.schedule_tick(now) if authed.get(f"/api/scans/{sid}").status_code == 200]  # not due yet
        created = scheduler.schedule_tick(now + timedelta(hours=6, minutes=1))
        mine = [sid for sid in created if authed.get(f"/api/scans/{sid}").status_code == 200]
        assert len(mine) == 1
        scanner_scan = authed.get(f"/api/scans/{mine[0]}").json()
        assert scanner_scan["trigger"] == "scheduled" and scanner_scan["status"] == "queued"
        sched = authed.get(f"/api/brands/{demo['id']}/schedule").json()["schedule"]
        assert datetime.fromisoformat(sched["next_run_at"]) > now + timedelta(hours=11)
        scanner.mark_interrupted_scans()

    def test_csv_import_is_scored_and_labelled(self, authed):
        b = create_brand(authed, name="Import Co", aliases=["Acme Wallet"])
        data = ("platform,kind,external_id,name,handle,url,description,links\n"
                "bluesky,account,did:x,Acme Wallet Help,acmewallet-help.bsky.social,https://bsky.app/profile/x,"
                "Verify your wallet now on Telegram,https://acmewallet-verify.top\n")
        r = authed.post(f"/api/brands/{b['id']}/import", files={"file": ("c.csv", data.encode(), "text/csv")}, headers=CSRF)
        assert r.status_code == 202, r.text
        s = wait_for_scan(authed, r.json()["scan_id"])
        assert s["mode"] == "import" and s["status"] == "completed"
        f = authed.get("/api/findings", params={"brand_id": b["id"]}).json()["items"]
        assert f[0]["candidate"]["source_type"] == "imported" and f[0]["risk_level"] in ("medium", "high", "critical")


# ---------------------------------------------------------------------------- settings & sources


def test_detection_settings_roundtrip(authed):
    r = authed.put("/api/settings/detection", json={"overrides": {"groups": {"visual": {"weight": 0.3}}, "levels": {"medium": {"min_score": 40}}}}, headers=CSRF)
    assert r.status_code == 200
    body = r.json()
    assert body["effective"]["groups"]["visual"]["weight"] == 0.3 and body["overrides"]["levels"]["medium"]["min_score"] == 40
    assert authed.delete("/api/settings/detection", headers=CSRF).json()["overrides"] == {}


@respx.mock
def test_sources_listing_is_honest(authed, monkeypatch):
    from app.routers import sources as sources_router

    async def public(host):
        return None

    monkeypatch.setattr(sources_router, "resolve_public", public)
    respx.get("https://fosstodon.org/api/v2/instance").mock(return_value=httpx.Response(200, json={"domain": "fosstodon.org"}))
    body = authed.get("/api/sources").json()
    by = {s["name"]: s for s in body["sources"]}
    assert by["google_play"]["reliability"] == "unofficial"
    assert by["demo"]["source_type"] == "simulated"
    assert {u["name"] for u in body["unavailable"]} >= {"x", "instagram"}
    r = authed.put("/api/sources/config", json={"enabled_sources": ["bluesky", "nope"], "mastodon_instances": ["mastodon.social"]}, headers=CSRF)
    assert r.status_code == 422
    r = authed.put("/api/sources/config", json={"enabled_sources": ["bluesky"], "mastodon_instances": ["localhost"]}, headers=CSRF)
    assert r.status_code == 422
    r = authed.put("/api/sources/config", json={"enabled_sources": ["bluesky", "apple_app_store"], "mastodon_instances": ["fosstodon.org"], "store_country": "GB"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["store_country"] == "gb"
