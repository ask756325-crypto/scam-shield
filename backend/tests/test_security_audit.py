"""Release security audit: every ID-addressed route is checked against another organization, unauthenticated
access is rejected everywhere, CSRF is enforced on every state-changing route, and collection endpoints never
leak another organization's records."""
import re

import pytest

from app.main import app
from conftest import CSRF, signup, wait_for_scan

PUBLIC = {"/api/health", "/api/auth/config", "/api/auth/signup", "/api/auth/login", "/api/auth/session", "/api/auth/verify-email",
          "/api/auth/password-reset/request", "/api/auth/password-reset/confirm", "/api/auth/accept-invite", "/api/auth/logout",
          "/api/auth/invite/{token}", "/api/demo/assets/{name}"}


def api_routes():
    for r in app.routes:
        methods = getattr(r, "methods", None) or set()
        if r.path.startswith("/api/") and r.path not in ("/api/docs", "/api/openapi.json"):
            for m in sorted(methods - {"HEAD", "OPTIONS"}):
                yield m, r.path


@pytest.fixture
def victim(client):
    """Org A with one of everything; returns IDs, then switches the client to a fresh org B."""
    signup(client, org="Victim Org")
    demo = client.post("/api/demo/brand", headers=CSRF).json()
    scan = wait_for_scan(client, client.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()["id"])
    finding = client.get("/api/findings", params={"brand_id": demo["id"], "limit": 1}).json()["items"][0]
    client.post(f"/api/findings/{finding['id']}/decision", json={"action": "note", "note": "victim secret note"}, headers=CSRF)
    client.put(f"/api/brands/{demo['id']}/schedule", json={"frequency": "daily"}, headers=CSRF)
    invite = client.post("/api/settings/invites", json={"email": "newhire@example.com", "role": "analyst"}, headers=CSRF).json()
    session_id = client.get("/api/auth/sessions").json()[0]["id"]
    me = client.get("/api/auth/me").json()
    ids = {"brand_id": demo["id"], "scan_id": scan["id"], "finding_id": finding["id"], "invite_id": invite.get("id") or invite.get("invite", {}).get("id", 1),
           "session_id": session_id, "user_id": me["user"]["id"] if "user" in me else me["id"]}
    client.cookies.clear()
    signup(client, org="Attacker Org")
    return ids


def fill(path: str, ids: dict) -> str | None:
    def sub(m):
        return str(ids.get(m.group(1), "x"))

    if "{token}" in path or "{name}" in path:
        return None
    return re.sub(r"\{(\w+)\}", sub, path)


def test_no_cross_organization_access_on_any_id_route(client, victim):
    checked = 0
    for method, path in api_routes():
        url = fill(path, victim)
        if url is None or "{" not in path:
            continue
        body = {"action": "confirm", "note": ""} if path.endswith("/decision") else {}
        r = client.request(method, url, json=body if method in ("POST", "PUT", "PATCH") else None, headers=CSRF)
        assert r.status_code in (403, 404, 405, 422), f"{method} {path} → {r.status_code}: {r.text[:200]}"
        assert "victim secret note" not in r.text and "Northvale" not in r.text, f"{method} {path} leaked data"
        checked += 1
    assert checked >= 25


def test_collections_never_include_another_orgs_records(client, victim):
    for path in ("/api/brands", "/api/findings", "/api/scans", "/api/schedules", "/api/dashboard", "/api/findings/export.csv",
                 "/api/scans/export.csv", "/api/settings/data/decisions.csv", "/api/findings/review-summary", "/api/settings/organization",
                 "/api/settings/invites", "/api/auth/sessions", "/api/sources"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "Northvale" not in r.text and "victim secret note" not in r.text and "newhire@example.com" not in r.text, path
        assert "Victim Org" not in r.text, path
    # Explicit filters for the other org's brand return nothing rather than its data.
    assert client.get("/api/findings", params={"brand_id": victim["brand_id"]}).json()["total"] == 0
    assert client.get("/api/scans", params={"brand_id": victim["brand_id"]}).json() == []


def test_every_private_route_requires_authentication(client):
    client.cookies.clear()
    for method, path in api_routes():
        if path in PUBLIC:
            continue
        url = re.sub(r"\{\w+\}", "1", path)
        r = client.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None, headers=CSRF)
        assert r.status_code == 401, f"{method} {path} → {r.status_code} without a session"


def test_every_state_changing_route_requires_csrf_header(client):
    signup(client)
    for method, path in api_routes():
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            continue
        url = re.sub(r"\{\w+\}", "1", path)
        r = client.request(method, url, json={})
        assert r.status_code == 403 and "CSRF" in r.text, f"{method} {path} accepted without CSRF header ({r.status_code})"
