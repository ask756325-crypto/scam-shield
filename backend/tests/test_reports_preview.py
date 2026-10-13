"""Executive report and look-alike preview."""
from conftest import CSRF, signup, wait_for_scan


def test_executive_report_counts_live_data_only(authed):
    b = authed.post("/api/demo/brand", headers=CSRF).json()
    wait_for_scan(authed, authed.post(f"/api/brands/{b['id']}/scans", json={}, headers=CSRF).json()["id"])
    r = authed.get("/api/reports/executive", params={"days": 30})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    t = r.text
    assert "Brand protection report" in t and "synthetic demo findings are excluded" in t
    assert "New critical / high findings" in t and "0 / 0" in t  # demo findings never counted as live threats
    assert "Print / save as PDF" in t and "<script" not in t
    assert authed.get("/api/reports/executive", params={"days": 3}).status_code == 422
    assert any(e["action"] == "data.exported" and "Executive" in e["summary"] for e in authed.get("/api/settings/audit").json()["items"])


def test_report_is_org_scoped(authed, client):
    b = authed.post("/api/demo/brand", headers=CSRF).json()
    client.cookies.clear()
    signup(client, org="Report Outsider")
    assert client.get("/api/reports/executive", params={"brand_id": b["id"]}).status_code == 404
    assert "Northvale" not in client.get("/api/reports/executive").text


def test_lookalike_preview(authed):
    r = authed.get("/api/brands/preview-variants", params={"name": "Northvale Pay", "aliases": ["NV Pay"]}).json()
    assert "northvale pay" in r["search_terms"] and "nv pay" in r["search_terms"]
    ex = {x["text"]: x for x in r["examples"]}
    assert ex["N0rthvale Pay"]["flagged"] and ex["Northvale Pay Support"]["flagged"]
    assert any(x["kind"] == "domain" for x in r["examples"]) and "not accounts that exist" in r["note"]
    assert authed.get("/api/brands/preview-variants", params={"name": "x"}).status_code == 422
