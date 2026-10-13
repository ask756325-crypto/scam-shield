"""Alerts: new high-risk findings, repeated source failures, schedule auto-pause, digests, webhook safety, honest log."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.candidate import CandidateRecord
from app.db import SessionLocal
from app.models import NotificationLog, NotificationPreference
from app.services import notifications, scanner
from app.sources.base import SourceAdapter, SourceError, SourceInfo
from conftest import CSRF, signup, wait_for_scan
from test_api import create_brand

HOOK = "https://hooks.example.com/services/T000/B000/secrettoken"


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """Webhook hosts in tests are fictional: make them resolve to a public address."""
    real = notifications.socket.getaddrinfo

    def fake(host, *a, **k):
        if host.endswith(".example.com"):
            return [(2, 1, 6, "", ("93.184.215.14", 443))]
        if host == "internal.example.org":
            return [(2, 1, 6, "", ("10.0.0.5", 443))]
        return real(host, *a, **k)

    monkeypatch.setattr(notifications.socket, "getaddrinfo", fake)


def log_rows(org_id, wait_for: int = 0, timeout: float = 10.0):
    """Alerts are sent just after a scan is marked finished, so optionally wait until `wait_for` rows exist."""
    import time

    deadline = time.time() + timeout
    while True:
        with SessionLocal() as db:
            rows = db.query(NotificationLog).filter(NotificationLog.organization_id == org_id).order_by(NotificationLog.id).all()
        if len(rows) >= wait_for or time.time() > deadline:
            return rows
        time.sleep(0.1)


def org_id(client):
    return client.get("/api/settings/organization").json()["id"]


class Flaky(SourceAdapter):
    info = SourceInfo("flaky", "Flaky", "social", "live", "test", "test")
    mode = "hit"

    def __init__(self, name):
        super().__init__({})
        self.name = name

    async def search(self, term, client):
        if Flaky.mode == "fail":
            raise SourceError(f"{self.name} unavailable (HTTP 503)", "unavailable")
        return [CandidateRecord(self.name, "live", "account", "x-1", "Acme Wallet Support", handle="acmewallet-support",
                                description="Official Acme Wallet support. Verify your wallet at acmewallet-verify.top/login or message us on Telegram t.me/acmehelp",
                                external_links=["https://acmewallet-verify.top/login"], provenance={"adapter": self.name, "query": term})]


def scan(client, brand_id):
    scanner.adapter_factory = lambda name, cfg, names, epoch: Flaky(name)
    s = client.post(f"/api/brands/{brand_id}/scans", json={"sources": ["bluesky"]}, headers=CSRF).json()
    return wait_for_scan(client, s["id"])


@respx.mock
def test_new_high_risk_finding_alerts_email_and_webhook(authed):
    prefs = authed.get("/api/notifications/preferences").json()
    assert prefs["email_new_critical"] and not prefs["email_new_high"]  # defaults: critical on, high off
    authed.put("/api/notifications/preferences", json={**{k: prefs[k] for k in ("email_new_critical", "email_source_failure", "digest", "digest_hour", "timezone")},
                                                       "email_new_high": True}, headers=CSRF)
    route = respx.post(HOOK).mock(return_value=httpx.Response(200))
    r = authed.put("/api/notifications/webhook", json={"url": HOOK, "enabled": True}, headers=CSRF)
    assert r.status_code == 200 and "secrettoken" not in r.text and r.json()["url_masked"].startswith("https://hooks.example.com/")
    b = create_brand(authed, name="Alert Co", aliases=["Acme Wallet"])
    Flaky.mode = "hit"
    s = scan(authed, b["id"])
    rows = [r for r in log_rows(org_id(authed), wait_for=2) if r.event == "new_threat"]
    assert {r.channel for r in rows} == {"email", "webhook"}
    email = next(r for r in rows if r.channel == "email")
    assert email.status == "logged" and "server log" in email.detail  # dev mode without SMTP: never claimed as sent
    assert "Alert Co" in email.subject and email.scan_id == s["id"]
    assert next(r for r in rows if r.channel == "webhook").status == "sent"
    payload = route.calls.last.request.content.decode()
    assert "Acme Wallet Support" in payload and ('"high"' in payload or '"critical"' in payload)
    # A rescan with no new/raised findings sends nothing new.
    scan(authed, b["id"])
    assert len([r for r in log_rows(org_id(authed)) if r.event == "new_threat"]) == 2


def test_preferences_control_email(authed):
    r = authed.put("/api/notifications/preferences", json={"email_new_critical": False, "email_new_high": False, "email_source_failure": False,
                                                            "digest": "off", "digest_hour": 8, "timezone": "Europe/Berlin"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["timezone"] == "Europe/Berlin"
    assert authed.put("/api/notifications/preferences", json={"email_new_critical": True, "email_new_high": True, "email_source_failure": True,
                                                                "digest": "hourly", "digest_hour": 8, "timezone": "UTC"}, headers=CSRF).status_code == 422
    b = create_brand(authed, name="Quiet Co", aliases=["Acme Wallet"])
    Flaky.mode = "hit"
    scan(authed, b["id"])
    assert [r for r in log_rows(org_id(authed)) if r.channel == "email"] == []


def test_source_failing_twice_alerts_once(authed):
    b = create_brand(authed, name="Failing Alerts Co")
    Flaky.mode = "fail"
    scan(authed, b["id"])
    assert [r for r in log_rows(org_id(authed)) if r.event == "source_failure"] == []  # one failure: no alert yet
    scan(authed, b["id"])
    scan(authed, b["id"])
    rows = [r for r in log_rows(org_id(authed), wait_for=1) if r.event == "source_failure"]
    assert len(rows) == 1 and "bluesky failing" in rows[0].subject  # de-duplicated for 24 h


def test_daily_digest_respects_local_hour(authed):
    authed.put("/api/notifications/preferences", json={"email_new_critical": True, "email_new_high": False, "email_source_failure": True,
                                                       "digest": "daily", "digest_hour": 9, "timezone": "Asia/Tokyo"}, headers=CSRF)
    create_brand(authed, name="Digest Co")
    oid = org_id(authed)
    early = datetime(2027, 5, 1, 23, 0, tzinfo=timezone.utc)  # 08:00 in Tokyo
    notifications.send_due_digests(early)
    assert [r for r in log_rows(oid) if r.event == "digest"] == []
    notifications.send_due_digests(early + timedelta(hours=1))  # 09:00 Tokyo
    notifications.send_due_digests(early + timedelta(hours=2))  # same local day: not again
    rows = [r for r in log_rows(oid) if r.event == "digest"]
    assert len(rows) == 1 and "daily digest" in rows[0].subject


def test_webhook_validation_and_owner_only(authed):
    for bad in ("http://hooks.example.com/x", "https://user:pw@hooks.example.com/x", "https://127.0.0.1/x", "https://internal.example.org/hook"):
        r = authed.put("/api/notifications/webhook", json={"url": bad, "enabled": True}, headers=CSRF)
        assert r.status_code == 422, bad
    assert authed.put("/api/notifications/webhook", json={"enabled": True}, headers=CSRF).status_code == 422  # no URL yet
    org = org_id(authed)
    with SessionLocal() as db:
        from app.models import Membership

        for m in db.query(Membership).filter(Membership.organization_id == org).all():
            m.role = "analyst"
        db.commit()
    assert authed.put("/api/notifications/webhook", json={"url": HOOK, "enabled": True}, headers=CSRF).status_code == 403


@respx.mock
def test_test_send_reports_real_outcome(authed):
    r = authed.post("/api/notifications/test", params={"channel": "email"}, headers=CSRF).json()
    assert r["status"] == "logged"
    assert authed.post("/api/notifications/test", params={"channel": "webhook"}, headers=CSRF).status_code == 400
    respx.post(HOOK).mock(return_value=httpx.Response(500))
    authed.put("/api/notifications/webhook", json={"url": HOOK, "enabled": True}, headers=CSRF)
    r = authed.post("/api/notifications/test", params={"channel": "webhook"}, headers=CSRF).json()
    assert r["status"] == "failed" and r["detail"] == "HTTP 500"
    log = authed.get("/api/notifications/log").json()
    assert log[0]["status"] == "failed" and "secrettoken" not in str(log)


def test_log_is_org_scoped(authed, client):
    authed.post("/api/notifications/test", params={"channel": "email"}, headers=CSRF)
    client.cookies.clear()
    signup(client, org="Other Notif Org")
    assert client.get("/api/notifications/log").json() == []
