"""Team invites, roles, member removal and email change."""
import time

from conftest import CSRF, signup

PW = "correct-horse-42"


def invite(client, email, role="analyst"):
    r = client.post("/api/settings/invites", json={"email": email, "role": role}, headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()


def token_of(inv):
    return inv["link"].split("token=")[1]


def test_invite_accept_flow_and_org_scoping(client):
    signup(client, org="Team Org")
    brand = client.post("/api/brands", json={"name": "Shared Brand"}, headers=CSRF).json()
    email = f"mate-{time.time_ns()}@example.com"
    inv = invite(client, email)
    assert "token_hash" not in inv and inv["role"] == "analyst"
    assert len(client.get("/api/settings/invites").json()) == 1

    client.cookies.clear()
    info = client.get(f"/api/auth/invite/{token_of(inv)}").json()
    assert info["email"] == email and info["organization"] == "Team Org"
    r = client.post("/api/auth/accept-invite", json={"token": token_of(inv), "name": "Mate", "password": PW}, headers=CSRF)
    assert r.status_code == 201 and r.json()["role"] == "analyst"

    # Teammate sees the org's brand but cannot manage the team or settings.
    assert client.get(f"/api/brands/{brand['id']}").status_code == 200
    assert client.post("/api/settings/invites", json={"email": "x@example.com"}, headers=CSRF).status_code == 403
    assert client.put("/api/settings/detection", json={"overrides": {}}, headers=CSRF).status_code == 403
    assert client.get("/api/settings/invites").status_code == 403

    # Invites are single-use.
    client.cookies.clear()
    assert client.get(f"/api/auth/invite/{token_of(inv)}").status_code == 404
    assert client.post("/api/auth/accept-invite", json={"token": token_of(inv), "name": "X", "password": PW}, headers=CSRF).status_code == 400


def test_invite_validation_and_revocation(client):
    owner = signup(client)
    assert client.post("/api/settings/invites", json={"email": owner}, headers=CSRF).status_code == 409  # existing account
    assert client.post("/api/settings/invites", json={"email": "a@example.com", "role": "admin"}, headers=CSRF).status_code == 422
    email = f"rev-{time.time_ns()}@example.com"
    first = invite(client, email)
    second = invite(client, email)  # supersedes the first link
    client.cookies.clear()
    assert client.get(f"/api/auth/invite/{token_of(first)}").status_code == 404
    assert client.get(f"/api/auth/invite/{token_of(second)}").status_code == 200
    client.post("/api/auth/login", json={"email": owner, "password": PW}, headers=CSRF)
    assert client.delete(f"/api/settings/invites/{second['id']}", headers=CSRF).status_code == 200
    client.cookies.clear()
    assert client.get(f"/api/auth/invite/{token_of(second)}").status_code == 404
    weak = invite_with_login(client, owner)
    r = client.post("/api/auth/accept-invite", json={"token": weak, "name": "W", "password": "short"}, headers=CSRF)
    assert r.status_code == 422


def invite_with_login(client, owner):
    client.post("/api/auth/login", json={"email": owner, "password": PW}, headers=CSRF)
    inv = invite(client, f"weak-{time.time_ns()}@example.com")
    client.cookies.clear()
    return token_of(inv)


def test_cannot_use_other_orgs_invite_management(client):
    signup(client, org="A")
    inv = invite(client, f"cross-{time.time_ns()}@example.com")
    client.cookies.clear()
    signup(client, org="B")
    assert client.get("/api/settings/invites").json() == []
    assert client.delete(f"/api/settings/invites/{inv['id']}", headers=CSRF).status_code == 404


def test_roles_and_member_removal(client):
    owner = signup(client)
    mate = f"m-{time.time_ns()}@example.com"
    inv = invite(client, mate)
    client.cookies.clear()
    client.post("/api/auth/accept-invite", json={"token": token_of(inv), "name": "M", "password": PW}, headers=CSRF)
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": owner, "password": PW}, headers=CSRF)
    members = client.get("/api/settings/organization").json()["members"]
    me = next(m for m in members if m["email"] == owner)
    other = next(m for m in members if m["email"] == mate)
    assert client.patch(f"/api/settings/members/{me['user_id']}", json={"role": "analyst"}, headers=CSRF).status_code == 409  # last owner
    assert client.delete(f"/api/settings/members/{me['user_id']}", headers=CSRF).status_code == 409  # not yourself
    assert client.patch(f"/api/settings/members/{other['user_id']}", json={"role": "owner"}, headers=CSRF).status_code == 200
    assert client.delete(f"/api/settings/members/{other['user_id']}", headers=CSRF).status_code == 200
    assert len(client.get("/api/settings/organization").json()["members"]) == 1
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": mate, "password": PW}, headers=CSRF).status_code == 401  # removed


def test_change_email(client):
    old = signup(client)
    new = f"new-{time.time_ns()}@example.com"
    assert client.post("/api/auth/change-email", json={"new_email": new, "password": "wrong-pass-123"}, headers=CSRF).status_code == 400
    assert client.post("/api/auth/change-email", json={"new_email": old, "password": PW}, headers=CSRF).status_code == 422
    r = client.post("/api/auth/change-email", json={"new_email": new, "password": PW}, headers=CSRF)
    assert r.status_code == 200 and r.json()["user"]["email"] == new
    assert client.get("/api/auth/me").json()["user"]["email"] == new  # current session survives
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": old, "password": PW}, headers=CSRF).status_code == 401
    assert client.post("/api/auth/login", json={"email": new, "password": PW}, headers=CSRF).status_code == 200
    other = signup(client)
    assert client.post("/api/auth/change-email", json={"new_email": new, "password": PW}, headers=CSRF).status_code == 409
    assert other != new
