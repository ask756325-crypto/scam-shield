"""Module 10: review workflow, account & sessions, monitoring settings, data management, exports, isolation."""
import csv
import io
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Membership, Scan
from app.services import retention
from conftest import CSRF, signup, wait_for_scan
from test_api import create_brand

PW = "correct-horse-42"


def demo_scan(client, times=1):
    demo = client.post("/api/demo/brand", headers=CSRF).json()
    scans = [wait_for_scan(client, client.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()["id"]) for _ in range(times)]
    return demo, scans


def make_analyst(client):
    org = client.get("/api/settings/organization").json()["id"]
    with SessionLocal() as db:
        for m in db.query(Membership).filter(Membership.organization_id == org).all():
            m.role = "analyst"
        db.commit()


class TestReviewQueue:
    def test_filters_summary_and_decisions_persist(self, authed):
        demo, _ = demo_scan(authed)
        s0 = authed.get("/api/findings/review-summary", params={"brand_id": demo["id"]}).json()
        assert s0["open_total"] > 0 and s0["oldest_open_at"] and s0["decided_by_me_last_7_days"] == 0
        q = authed.get("/api/findings", params={"brand_id": demo["id"], "status": ["open", "escalated"], "level": ["critical"], "source": ["bluesky"]}).json()
        assert q["items"] and all(f["risk_level"] == "critical" and f["candidate"]["platform"] == "bluesky" for f in q["items"])
        fid = q["items"][0]["id"]
        assert authed.post(f"/api/findings/{fid}/decision", json={"action": "escalate", "note": "check"}, headers=CSRF).json()["status"] == "escalated"
        s1 = authed.get("/api/findings/review-summary", params={"brand_id": demo["id"]}).json()
        assert s1["escalated"] == 1 and s1["open_total"] == s0["open_total"]  # escalated stays outstanding
        authed.post(f"/api/findings/{fid}/decision", json={"action": "confirm"}, headers=CSRF)
        s2 = authed.get("/api/findings/review-summary", params={"brand_id": demo["id"]}).json()
        assert s2["open_total"] == s0["open_total"] - 1 and s2["decided_by_me_last_7_days"] == 2
        assert authed.get(f"/api/findings/{fid}").json()["status"] == "confirmed"  # persisted

    def test_summary_is_org_scoped(self, authed, client):
        demo_scan(authed)
        client.cookies.clear()
        signup(client, org="Empty Org")
        s = client.get("/api/findings/review-summary").json()
        assert s["open_total"] == 0 and s["decided_last_7_days"] == 0


class TestSessions:
    def test_list_revoke_and_logout_others(self, client):
        email = signup(client)
        other = client.__class__(client.app)  # a second device
        assert other.post("/api/auth/login", json={"email": email, "password": PW}, headers=CSRF).status_code == 200
        sessions = client.get("/api/auth/sessions").json()
        assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
        assert all("token" not in str(k) for s in sessions for k in s)
        current = next(s for s in sessions if s["current"])
        assert client.delete(f"/api/auth/sessions/{current['id']}", headers=CSRF).status_code == 400
        assert client.post("/api/auth/logout-others", headers=CSRF).json()["revoked"] == 1
        assert other.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me").status_code == 200

    def test_cannot_revoke_someone_elses_session(self, client):
        signup(client)
        theirs = client.get("/api/auth/sessions").json()[0]["id"]
        client.cookies.clear()
        signup(client)
        assert client.delete(f"/api/auth/sessions/{theirs}", headers=CSRF).status_code == 404
        assert all(s["id"] != theirs for s in client.get("/api/auth/sessions").json())

    def test_logout_revokes_server_side(self, client):
        signup(client)
        token = client.cookies.get("ss_session")
        assert client.post("/api/auth/logout", headers=CSRF).status_code == 200
        client.cookies.set("ss_session", token)  # replaying the old cookie must not work
        assert client.get("/api/auth/me").status_code == 401

    def test_password_change_validation(self, authed):
        assert authed.post("/api/auth/change-password", json={"current_password": "wrong-pass-1", "new_password": "an0ther-good-pass"}, headers=CSRF).status_code == 400
        assert authed.post("/api/auth/change-password", json={"current_password": PW, "new_password": "short"}, headers=CSRF).status_code == 422
        assert authed.post("/api/auth/change-password", json={"current_password": PW, "new_password": "an0ther-good-pass"}, headers=CSRF).status_code == 200


class TestMonitoringSettings:
    def test_persist_validate_and_apply_limits(self, authed):
        r = authed.get("/api/settings/monitoring").json()
        assert r["values"]["max_queries_per_source"] == 8 and r["limits"]["max_queries_per_source"] == {"min": 1, "max": 8, "description": r["limits"]["max_queries_per_source"]["description"]}
        bad = authed.put("/api/settings/monitoring", json={"max_queries_per_source": 50}, headers=CSRF)
        assert bad.status_code == 422 and bad.json()["detail"]["field"] == "max_queries_per_source"
        assert authed.put("/api/settings/monitoring", json={"surprise": 1}, headers=CSRF).status_code == 422
        ok = authed.put("/api/settings/monitoring", json={"max_queries_per_source": 2, "max_image_fetches": 0}, headers=CSRF).json()
        assert ok["values"]["max_queries_per_source"] == 2 and ok["values"]["resolve_after_misses"] == 2
        assert authed.get("/api/settings/monitoring").json()["values"]["max_image_fetches"] == 0  # persisted
        _, (scan,) = demo_scan(authed)
        assert len(scan["search_terms"]) == 2 and all(x["queries_total"] == 2 for x in scan["sources"])

    def test_only_owners_change_settings(self, authed):
        make_analyst(authed)
        assert authed.put("/api/settings/monitoring", json={"max_queries_per_source": 3}, headers=CSRF).status_code == 403
        assert authed.put("/api/settings/monitoring", json={"scan_history_days": 30}, headers=CSRF).status_code == 403
        assert authed.post("/api/settings/data/purge", json={"confirm": "DELETE"}, headers=CSRF).status_code == 403
        assert authed.get("/api/settings/monitoring").status_code == 200  # analysts can read


class TestDataManagement:
    def test_retention_preview_confirm_and_purge_keeps_findings(self, authed):
        demo, scans = demo_scan(authed, times=3)
        findings_before = authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 200}).json()["total"]
        with SessionLocal() as db:  # age the two older scans
            for s in scans[:2]:
                db.get(Scan, s["id"]).created_at = datetime.now(timezone.utc) - timedelta(days=40)
            db.commit()
        assert authed.post("/api/settings/data/purge", json={"confirm": "DELETE"}, headers=CSRF).status_code == 400  # no policy set
        assert authed.put("/api/settings/monitoring", json={"scan_history_days": 45}, headers=CSRF).status_code == 422
        authed.put("/api/settings/monitoring", json={"scan_history_days": 30}, headers=CSRF)
        prev = authed.get("/api/settings/data").json()["retention"]
        assert prev["scans"] == 2 and prev["observations"] > 0
        assert authed.post("/api/settings/data/purge", json={"confirm": "yes"}, headers=CSRF).status_code == 422
        out = authed.post("/api/settings/data/purge", json={"confirm": "DELETE"}, headers=CSRF).json()["deleted"]
        assert out["scans"] == 2
        assert [s["id"] for s in authed.get("/api/scans", params={"brand_id": demo["id"]}).json()] == [scans[2]["id"]]
        assert authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 200}).json()["total"] == findings_before
        f = authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 1}).json()["items"][0]
        assert authed.get(f"/api/findings/{f['id']}").status_code == 200  # evidence still opens

    def test_newest_scan_is_always_kept(self, authed):
        demo, (only,) = demo_scan(authed)
        with SessionLocal() as db:
            db.get(Scan, only["id"]).created_at = datetime.now(timezone.utc) - timedelta(days=400)
            db.commit()
            from app.models import Organization

            org = db.get(Organization, authed.get("/api/settings/organization").json()["id"])
            org.monitoring_config = {"scan_history_days": 30}
            db.commit()
            assert retention.purge(db, org)["scans"] == 0

    def test_exports_are_org_scoped(self, authed, client):
        demo, _ = demo_scan(authed)
        fid = authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 1}).json()["items"][0]["id"]
        authed.post(f"/api/findings/{fid}/decision", json={"action": "confirm", "note": "=HYPERLINK(1)"}, headers=CSRF)
        audit = list(csv.DictReader(io.StringIO(authed.get("/api/settings/data/decisions.csv").text)))
        assert len(audit) == 1 and audit[0]["note"] == "'=HYPERLINK(1)" and audit[0]["to_status"] == "confirmed"
        scans_csv = list(csv.DictReader(io.StringIO(authed.get("/api/scans/export.csv").text)))
        assert scans_csv and all(r["brand"] == "Northvale Pay" for r in scans_csv)
        client.cookies.clear()
        signup(client, org="Other Org")
        create_brand(client, name="Other Brand")
        assert list(csv.DictReader(io.StringIO(client.get("/api/settings/data/decisions.csv").text))) == []
        assert list(csv.DictReader(io.StringIO(client.get("/api/scans/export.csv").text))) == []
        assert list(csv.DictReader(io.StringIO(client.get("/api/findings/export.csv").text))) == []
        assert client.get("/api/scans/export.csv", params={"brand_id": demo["id"]}).text.count("\n") == 1  # header only
        assert client.get("/api/settings/data").json()["counts"]["findings"] == 0
