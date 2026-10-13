"""Possible campaigns: clustering by shared observable indicators, honest labelling, isolation."""
from app.db import SessionLocal
from app.services.campaigns import find_campaigns
from conftest import CSRF, signup, wait_for_scan


def scan(client, brand_id):
    return wait_for_scan(client, client.post(f"/api/brands/{brand_id}/scans", json={}, headers=CSRF).json()["id"])


def test_demo_clusters_share_real_indicators(authed):
    b = authed.post("/api/demo/brand", headers=CSRF).json()
    scan(authed, b["id"])
    r = authed.get("/api/campaigns", params={"brand_id": b["id"]}).json()
    assert "does not by itself prove common ownership" in r["note"]
    by_names = {frozenset(f["name"] for f in c["findings"]): c for c in r["campaigns"]}
    c = by_names[frozenset({"N0rthvale Pay", "Northvale Pay - Wallet Login"})]  # same phishing URL in both
    assert c["label"].startswith("Possible campaign") and c["synthetic"] and set(c["platforms"]) == {"bluesky", "google_play"}
    kinds = {i["kind"] for i in c["shared_indicators"]}
    assert "url" in kinds and any(i["value"].startswith("northvalepay-secure.example") for i in c["shared_indicators"])
    # Every grouped finding really holds every listed shared indicator in at least two members.
    assert all(i["findings"] >= 2 for i in c["shared_indicators"])
    scan(authed, b["id"])  # epoch 1: the support account adds the WhatsApp number the help account also lists
    r2 = authed.get("/api/campaigns", params={"brand_id": b["id"]}).json()
    phone = [c for c in r2["campaigns"] if any(i["kind"] == "phone" for i in c["shared_indicators"])]
    assert phone and {"Northvale Pay Support", "Nortvale Pay Help"} <= {f["name"] for f in phone[0]["findings"]}


def test_unrelated_findings_are_not_grouped(authed):
    b = authed.post("/api/demo/brand", headers=CSRF).json()
    scan(authed, b["id"])
    names = {f["name"] for c in authed.get("/api/campaigns").json()["campaigns"] for f in c["findings"]}
    assert "Northvale Hiking Club" not in names and "Northvale Pay Fans" not in names


def test_campaigns_are_org_scoped(authed, client):
    b = authed.post("/api/demo/brand", headers=CSRF).json()
    scan(authed, b["id"])
    client.cookies.clear()
    signup(client, org="Campaign Outsider")
    assert client.get("/api/campaigns").json()["campaigns"] == []
    assert client.get("/api/campaigns", params={"brand_id": b["id"]}).status_code == 404
