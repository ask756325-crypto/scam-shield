"""Authentication module: remember-me, session expiry, logout revocation, email verification, redirects."""
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.db import SessionLocal
from app.models import AuthSession, User
from app.services import mailer
from conftest import CSRF, signup

PW = "correct-horse-42"


def login(client, email, remember=False, password=PW):
    return client.post("/api/auth/login", json={"email": email, "password": password, "remember": remember}, headers=CSRF)


def session_hours(email):
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        s = db.query(AuthSession).filter(AuthSession.user_id == user.id).order_by(AuthSession.id.desc()).first()
        return (s.expires_at - datetime.now(timezone.utc)).total_seconds() / 3600


def test_remember_me_controls_cookie_and_server_lifetime(client):
    email = signup(client)
    client.cookies.clear()
    r = login(client, email, remember=False)
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 200 and "max-age" not in cookie and "expires" not in cookie  # browser-session cookie
    assert 11 < session_hours(email) <= 12
    client.cookies.clear()
    r = login(client, email, remember=True)
    cookie = r.headers["set-cookie"].lower()
    assert "max-age=2592000" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert session_hours(email) > 24 * 29


def test_expired_session_is_rejected_and_cookie_cleared(client):
    email = signup(client)
    assert client.get("/api/auth/me").status_code == 200
    with SessionLocal() as db:
        uid = db.query(User).filter(User.email == email).one().id
        db.execute(update(AuthSession).where(AuthSession.user_id == uid).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        db.commit()
    r = client.get("/api/brands")
    assert r.status_code == 401
    assert r.headers.get("x-session-state") == "expired"
    assert 'ss_session=""' in r.headers.get("set-cookie", "") or "max-age=0" in r.headers.get("set-cookie", "").lower()


def test_unauthenticated_request_without_cookie_is_not_flagged_expired(client):
    r = client.get("/api/brands")
    assert r.status_code == 401 and "x-session-state" not in r.headers


def test_logout_revokes_server_session(client):
    signup(client)
    token = client.cookies.get("ss_session")
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 200
    client.cookies.set("ss_session", token)  # replay the old cookie
    assert client.get("/api/auth/me").status_code == 401


def test_logout_requires_csrf_header(client):
    signup(client)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.get("/api/auth/me").status_code == 200


def test_validation_errors_are_specific(client):
    r = client.post("/api/auth/signup", json={"email": "not-an-email", "password": "x", "name": "", "organization": "O"}, headers=CSRF)
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["errors"]}
    assert {"email", "name"} <= fields
    assert "x" not in r.json()["detail"].split()  # submitted password is never echoed
    r = client.post("/api/auth/signup", json={"email": "p@example.com", "password": "aaaaaaaaaaaa", "name": "P", "organization": "O"}, headers=CSRF)
    assert r.status_code == 422 and "letters and numbers" in r.json()["detail"]


def test_email_verification_flow(client, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_verification_link", lambda to, link: sent.append((to, link)))
    email = signup(client)
    assert sent and sent[-1][0] == email
    assert client.get("/api/auth/me").json()["user"]["email_verified"] is False
    token = sent[-1][1].split("token=")[1]
    assert client.post("/api/auth/verify-email", json={"token": "bogus-token-123"}, headers=CSRF).status_code == 400
    r = client.post("/api/auth/verify-email", json={"token": token}, headers=CSRF)
    assert r.status_code == 200
    assert client.get("/api/auth/me").json()["user"]["email_verified"] is True
    assert client.post("/api/auth/verify-email", json={"token": token}, headers=CSRF).status_code == 400  # single use
    assert client.post("/api/auth/resend-verification", headers=CSRF).json()["already_verified"] is True


def test_email_change_requires_reverification_and_old_link_dies(client, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_verification_link", lambda to, link: sent.append((to, link)))
    signup(client)
    old_token = sent[-1][1].split("token=")[1]
    new = f"changed-{time.time_ns()}@example.com"
    assert client.post("/api/auth/change-email", json={"new_email": new, "password": PW}, headers=CSRF).status_code == 200
    assert client.get("/api/auth/me").json()["user"]["email_verified"] is False
    assert sent[-1][0] == new
    assert client.post("/api/auth/verify-email", json={"token": old_token}, headers=CSRF).status_code == 400  # issued for old address
    assert client.post("/api/auth/verify-email", json={"token": sent[-1][1].split("token=")[1]}, headers=CSRF).status_code == 200


def test_resend_verification_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(mailer, "send_verification_link", lambda to, link: None)
    signup(client)
    codes = [client.post("/api/auth/resend-verification", headers=CSRF).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429


def test_auth_config_exposes_delivery_and_session_policy(client):
    cfg = client.get("/api/auth/config").json()
    assert cfg["email_delivery"] in ("email", "server_log", "unavailable")
    assert cfg["remember_me_days"] == 30 and cfg["session_hours"] == 12


def test_session_probe_never_errors_and_leaks_nothing(client):
    r = client.get("/api/auth/session")
    assert r.status_code == 200 and r.json() == {"authenticated": False}
    signup(client)
    r = client.get("/api/auth/session")
    assert r.json() == {"authenticated": True}
