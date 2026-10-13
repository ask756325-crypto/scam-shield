"""Takedown workflow: eligibility, generated report, lifecycle, scan verification, isolation, audit."""
import pytest

from conftest import CSRF, signup, wait_for_scan


def scan(client, brand_id):
    return wait_for_scan(client, client.post(f"/api/brands/{brand_id}/scans", json={}, headers=CSRF).json()["id"])


@pytest.fixture
def demo(authed):
    b = authed.post("/api/demo/brand", headers=CSRF).json()
    scan(authed, b["id"])
    items = authed.get("/api/findings", params={"brand_id": b["id"], "limit": 200}).json()["items"]
    return b, {f["candidate"]["name"]: f for f in items}


def test_lifecycle_and_scan_verification(authed, demo):
    b, by = demo
    fid = by["N0rthvale Pay"]["id"]
    assert authed.post(f"/api/findings/{fid}/takedown", headers=CSRF).status_code == 409  # not confirmed yet
    assert authed.get(f"/api/findings/{fid}/takedown").json() == {"case": None, "eligible": False}
    authed.post(f"/api/findings/{fid}/decision", json={"action": "confirm", "note": "giveaway scam"}, headers=CSRF)
    case = authed.post(f"/api/findings/{fid}/takedown", headers=CSRF).json()
    assert case["status"] == "draft" and case["platform"] == "bluesky" and "Bluesky" in case["channel_label"]
    assert "Impersonation of Northvale Pay" in case["report_text"] and "N0rthvale Pay" in case["report_text"]
    assert "giveaway" in case["report_text"].lower()  # evidence-backed reasons
    assert authed.post(f"/api/findings/{fid}/takedown", headers=CSRF).status_code == 409  # one case per finding

    cid = case["id"]
    assert authed.patch(f"/api/takedowns/{cid}", json={"report_text": "Edited report"}, headers=CSRF).json()["report_text"] == "Edited report"
    assert authed.patch(f"/api/takedowns/{cid}", json={"status": "removed"}, headers=CSRF).status_code == 409  # draft → removed not allowed
    assert authed.patch(f"/api/takedowns/{cid}", json={"status": "reported"}, headers=CSRF).status_code == 422  # needs reference or note
    r = authed.patch(f"/api/takedowns/{cid}", json={"status": "reported", "reference": "BSKY-1234"}, headers=CSRF).json()
    assert r["status"] == "reported" and r["reference"] == "BSKY-1234" and r["reported_at"]
    assert authed.patch(f"/api/takedowns/{cid}", json={"report_text": "late edit"}, headers=CSRF).status_code == 409

    scan(authed, b["id"])  # epoch 1: giveaway account still present
    assert authed.get(f"/api/findings/{fid}/takedown").json()["case"]["verification"] == "still_observed"
    scan(authed, b["id"])  # epoch 2: gone — one clean miss, not enough evidence
    assert authed.get(f"/api/findings/{fid}/takedown").json()["case"]["verification"] == "still_observed"
    scan(authed, b["id"])  # second clean miss → resolved
    c = authed.get(f"/api/findings/{fid}/takedown").json()["case"]
    assert c["verification"] == "not_observed" and c["verified_scan_id"]
    done = authed.patch(f"/api/takedowns/{cid}", json={"status": "removed", "note": "Account suspended"}, headers=CSRF).json()
    assert done["status"] == "removed" and done["closed_at"] and [e["status"] for e in done["events"]] == ["draft", "reported", "removed"]
    listing = authed.get("/api/takedowns").json()
    assert listing["counts"] == {"removed": 1} and listing["items"][0]["brand_name"] == "Northvale Pay"
    audit_actions = [e["action"] for e in authed.get("/api/settings/audit").json()["items"]]
    assert "takedown.opened" in audit_actions and audit_actions.count("takedown.status") == 2


def test_app_listing_uses_store_route(authed, demo):
    _, by = demo
    fid = by["Northvale Pay - Wallet Login"]["id"]
    authed.post(f"/api/findings/{fid}/decision", json={"action": "confirm"}, headers=CSRF)
    case = authed.post(f"/api/findings/{fid}/takedown", headers=CSRF).json()
    assert case["platform"] == "google_play" and case["channel_url"].startswith("https://support.google.com/")
    assert "com.nvpay.wallet.login" in case["report_text"]


def test_cases_are_org_scoped(authed, client, demo):
    _, by = demo
    fid = by["N0rthvale Pay"]["id"]
    authed.post(f"/api/findings/{fid}/decision", json={"action": "confirm"}, headers=CSRF)
    cid = authed.post(f"/api/findings/{fid}/takedown", headers=CSRF).json()["id"]
    client.cookies.clear()
    signup(client, org="Takedown Intruder")
    assert client.patch(f"/api/takedowns/{cid}", json={"status": "withdrawn"}, headers=CSRF).status_code == 404
    assert client.get(f"/api/findings/{fid}/takedown").status_code == 404
    assert client.get("/api/takedowns").json()["items"] == []
