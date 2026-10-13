"""Operational features: request IDs, readiness, metrics auth/content, shared rate limiter, error handling."""
import logging

from pydantic import SecretStr

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import RateLimitEvent
from app.security import DatabaseRateLimiter, rate_limiter
from conftest import CSRF, signup


def test_request_ids(client):
    r = client.get("/api/health")
    assert len(r.headers["x-request-id"]) == 32
    assert client.get("/api/health", headers={"X-Request-ID": "lb-abc_123"}).headers["x-request-id"] == "lb-abc_123"
    assert client.get("/api/health", headers={"X-Request-ID": "bad id\nwith newline"}).headers["x-request-id"] != "bad id\nwith newline"


def test_readiness(client):
    assert client.get("/api/health/ready").json() == {"status": "ready", "database": "ok"}


def test_metrics_requires_token_and_uses_route_templates(client, monkeypatch):
    assert client.get("/api/metrics").status_code == 404  # disabled without a token
    monkeypatch.setattr(get_settings(), "metrics_token", SecretStr("m3trics-token"))
    assert client.get("/api/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    signup(client)
    client.get("/api/findings/987654")  # a 404 with a raw ID in the URL
    r = client.get("/api/metrics", headers={"Authorization": "Bearer m3trics-token"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert 'route="/api/findings/{finding_id}"' in body and "987654" not in body  # templates, never raw IDs
    assert "scamshield_http_request_duration_seconds_bucket" in body and "scamshield_scheduler_last_tick_age_seconds" in body


def test_database_rate_limiter_is_shared_and_hashes_keys():
    rate_limiter.reset()
    a, b = DatabaseRateLimiter(), DatabaseRateLimiter()  # e.g. two API replicas
    key = "login:203.0.113.9:victim@example.com"
    for _ in range(3):
        assert a.hit(key, 5, 60)[0]
    assert b.hit(key, 5, 60)[0] and b.hit(key, 5, 60)[0]
    ok, retry = a.hit(key, 5, 60)
    assert not ok and 0 < retry <= 60
    with SessionLocal() as db:
        stored = [e.key_hash for e in db.query(RateLimitEvent).all()]
    assert stored and all("victim" not in k and len(k) == 64 for k in stored)
    rate_limiter.reset()


def test_login_rate_limit_uses_shared_backend(client):
    rate_limiter.reset()
    email = signup(client)
    client.cookies.clear()
    codes = [client.post("/api/auth/login", json={"email": email, "password": "wrong-password-9"}, headers=CSRF).status_code for _ in range(9)]
    assert codes[-1] == 429 and 401 in codes
    with SessionLocal() as db:
        assert db.query(RateLimitEvent).count() > 0
    rate_limiter.reset()


def test_unhandled_errors_return_request_id_without_details(client, caplog):
    def boom():
        raise RuntimeError("secret internal detail")

    app.add_api_route("/api/__boom", boom, methods=["GET"])
    try:
        with caplog.at_level(logging.ERROR):
            r = client.get("/api/__boom")
        assert r.status_code == 500 and r.json()["detail"] == "Internal server error"
        assert "secret internal detail" not in r.text and r.json()["request_id"] == r.headers["x-request-id"]
        assert any("unhandled error" in rec.getMessage() for rec in caplog.records)
    finally:
        app.router.routes[:] = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/api/__boom"]
