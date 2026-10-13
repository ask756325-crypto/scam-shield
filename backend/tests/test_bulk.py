"""Bulk review actions and assignment."""
import pytest

from conftest import CSRF, signup, wait_for_scan


@pytest.fixture
def demo(authed):
    b = authed.post("/api/demo/brand", headers=CSRF).json()
    wait_for_scan(authed, authed.post(f"/api/brands/{b['id']}/scans", json={}, headers=CSRF).json()["id"])
    items = authed.get("/api/findings", params={"brand_id": b["id"], "limit": 200, "level": ["critical", "high", "medium", "low"]}).json()["items"]
    return b, items


def test_bulk_actions_apply_per_item(authed, demo):
    _, items = demo
    ids = [f["id"] for f in items[:4]]
    r = authed.post("/api/findings/bulk", json={"ids": ids, "action": "escalate", "note": "batch triage"}, headers=CSRF).json()
    assert r["applied"] == 4 and r["failed"] == 0
    # Mixed: two already confirmed → "confirm" fails for those, succeeds for the rest; nothing is all-or-nothing.
    authed.post("/api/findings/bulk", json={"ids": ids[:2], "action": "confirm"}, headers=CSRF)
    r = authed.post("/api/findings/bulk", json={"ids": ids, "action": "confirm"}, headers=CSRF).json()
    assert r["applied"] == 2 and r["failed"] == 2 and all("Cannot confirm" in x["error"] for x in r["results"] if not x["ok"])
    f = authed.get(f"/api/findings/{ids[3]}").json()
    assert f["status"] == "confirmed" and [d["action"] for d in f["decisions"]] == ["escalate", "confirm"]
    assert f["decisions"][0]["note"] == "batch triage"


def test_bulk_validation(authed, demo):
    _, items = demo
    assert authed.post("/api/findings/bulk", json={"ids": [], "action": "confirm"}, headers=CSRF).status_code == 422
    assert authed.post("/api/findings/bulk", json={"ids": list(range(1, 202)), "action": "confirm"}, headers=CSRF).status_code == 422
    assert authed.post("/api/findings/bulk", json={"ids": [items[0]["id"]], "action": "delete"}, headers=CSRF).status_code == 422
    assert authed.post("/api/findings/bulk", json={"ids": [items[0]["id"]], "action": "note", "note": " "}, headers=CSRF).status_code == 422


def test_assignment_and_filters(authed, demo):
    _, items = demo
    me = authed.get("/api/auth/me").json()["user"]["id"]
    fid = items[0]["id"]
    r = authed.patch(f"/api/findings/{fid}/assignee", json={"user_id": me}, headers=CSRF).json()
    assert r["assignee"]["id"] == me and r["decisions"][-1]["action"] == "assign"
    authed.post("/api/findings/bulk", json={"ids": [items[1]["id"], items[2]["id"]], "action": "assign", "assignee_id": me}, headers=CSRF)
    mine = authed.get("/api/findings", params={"assignee": "me", "level": ["critical", "high", "medium", "low"]}).json()
    assert {f["id"] for f in mine["items"]} == {fid, items[1]["id"], items[2]["id"]}
    un = authed.get("/api/findings", params={"assignee": "unassigned", "level": ["critical", "high", "medium", "low"]}).json()
    assert fid not in {f["id"] for f in un["items"]}
    assert authed.patch(f"/api/findings/{fid}/assignee", json={"user_id": None}, headers=CSRF).json()["assignee"] is None
    assert authed.get("/api/findings", params={"assignee": "bogus"}).status_code == 422


def test_cannot_assign_or_bulk_across_orgs(authed, client, demo):
    _, items = demo
    victim_ids = [f["id"] for f in items[:3]]
    victim_user = authed.get("/api/auth/me").json()["user"]["id"]
    client.cookies.clear()
    signup(client, org="Bulk Attacker")
    r = client.post("/api/findings/bulk", json={"ids": victim_ids, "action": "mark_safe"}, headers=CSRF).json()
    assert r["applied"] == 0 and all(x["error"] == "Finding not found" for x in r["results"])
    me = client.get("/api/auth/me").json()["user"]["id"]
    b = client.post("/api/demo/brand", headers=CSRF).json()
    wait_for_scan(client, client.post(f"/api/brands/{b['id']}/scans", json={}, headers=CSRF).json()["id"])
    own = client.get("/api/findings", params={"brand_id": b["id"], "limit": 1}).json()["items"][0]["id"]
    assert client.patch(f"/api/findings/{own}/assignee", json={"user_id": victim_user}, headers=CSRF).status_code == 422  # not a member
    assert client.post("/api/findings/bulk", json={"ids": [own], "action": "assign", "assignee_id": victim_user}, headers=CSRF).status_code == 422
    assert client.patch(f"/api/findings/{own}/assignee", json={"user_id": me}, headers=CSRF).status_code == 200
