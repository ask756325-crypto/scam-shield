"""Investigation workspace: retrieval, evidence accuracy, status transitions, audit trail, relationships, authorization, export."""
import pytest

from app.detection import indicators as ind
from app.models import Candidate
from conftest import CSRF, signup, wait_for_scan


@pytest.fixture
def demo(authed):
    b = authed.post("/api/demo/brand", headers=CSRF).json()
    wait_for_scan(authed, authed.post(f"/api/brands/{b['id']}/scans", json={}, headers=CSRF).json()["id"])
    items = authed.get("/api/findings", params={"brand_id": b["id"], "limit": 200}).json()["items"]
    return b, {f["candidate"]["name"]: f for f in items}


def decide(client, fid, action, note=""):
    return client.post(f"/api/findings/{fid}/decision", json={"action": action, "note": note}, headers=CSRF)


class TestRetrievalAndEvidence:
    def test_detail_separates_facts_and_inferences_from_stored_record(self, authed, demo):
        _, by = demo
        f = authed.get(f"/api/findings/{by['Northvale Pay - Wallet Login']['id']}").json()
        ev, c = f["evidence"], f["candidate"]
        facts = {x["label"]: x for x in ev["observed_facts"]}
        # Every fact equals the stored candidate field it cites.
        assert facts["Name"]["value"] == c["name"] and facts["Name"]["field"] == "name"
        assert facts["Developer / publisher"]["value"] == c["publisher_name"]
        assert facts["Developer ID"]["value"] == c["publisher_id"] == "8812773"
        assert facts["Source URL"]["value"] == c["url"]
        # Inferences mirror the stored assessment exactly.
        stored = f["signals"]["signals"]
        for x in ev["inferences"]:
            assert x["score"] == stored[x["signal"]]["score"] and x["statement"] == stored[x["signal"]]["detail"]
            assert x["corroborates"] == (x["group"] in f["corroborating_groups"] and x["evaluated"])
        assert {"name", "package", "logo", "description", "urls", "scam", "publisher"} <= {x["signal"] for x in ev["inferences"]}

    def test_comparison_uses_official_assets_from_profile(self, authed, demo):
        _, by = demo
        ev = authed.get(f"/api/findings/{by['Northvale Pay - Wallet Login']['id']}").json()["evidence"]
        cmp_ = ev["comparison"]
        assert cmp_["brand_name"] == "Northvale Pay" and cmp_["logo"]["available"]
        assert [a["app_id"] for a in cmp_["official_apps"] if a["same_store"]] == ["com.northvale.pay"]
        assert cmp_["official_accounts"] == []  # app finding: compared with apps, not accounts
        acct = authed.get(f"/api/findings/{by['Northvale Pay Support']['id']}").json()["evidence"]["comparison"]
        assert acct["official_apps"] == [] and {a["platform"] for a in acct["official_accounts"]} == {"bluesky"}

    def test_provenance_labels_synthetic_records(self, authed, demo):
        _, by = demo
        pv = authed.get(f"/api/findings/{by['N0rthvale Pay']['id']}").json()["evidence"]["provenance"]
        assert pv["source_type"] == "simulated" and "SYNTHETIC" in pv["source_type_note"]
        assert pv["endpoint"] == "bundled synthetic dataset" and pv["queries"] and pv["collected_at"]

    def test_unknown_or_foreign_finding_is_404(self, authed, client, demo):
        _, by = demo
        fid = by["N0rthvale Pay"]["id"]
        assert authed.get("/api/findings/999999").status_code == 404
        client.cookies.clear()
        signup(client, email="other-org@example.com", org="Other Org")
        for path in (f"/api/findings/{fid}", f"/api/findings/{fid}/related", f"/api/findings/{fid}/report"):
            assert client.get(path).status_code == 404, path
        assert decide(client, fid, "confirm").status_code == 404

    def test_unauthenticated_is_401(self, client):
        assert client.get("/api/findings/1/report").status_code == 401


class TestDecisions:
    def test_full_lifecycle_is_persisted_with_transitions(self, authed, demo):
        _, by = demo
        fid = by["Northvale Rewards"]["id"]
        assert decide(authed, fid, "escalate", "Ask the brand team").json()["status"] == "escalated"
        assert decide(authed, fid, "note", "Logo is a tinted copy").json()["status"] == "escalated"
        assert decide(authed, fid, "confirm", "Confirmed with brand team").json()["status"] == "confirmed"
        assert decide(authed, fid, "reopen").json()["status"] == "open"
        f = decide(authed, fid, "mark_safe", "Licensed partner").json()
        assert f["status"] == "safe"
        hist = [(d["action"], d["from_status"], d["to_status"], d["note"]) for d in f["decisions"]]
        assert hist == [
            ("escalate", "open", "escalated", "Ask the brand team"),
            ("note", "escalated", "escalated", "Logo is a tinted copy"),
            ("confirm", "escalated", "confirmed", "Confirmed with brand team"),
            ("reopen", "confirmed", "open", ""),
            ("mark_safe", "open", "safe", "Licensed partner"),
        ]
        assert all(d["user"] == "Analyst" or d["user"] for d in f["decisions"])
        # Persisted: a fresh read returns the same trail.
        assert len(authed.get(f"/api/findings/{fid}").json()["decisions"]) == 5

    def test_invalid_transitions_and_empty_notes_rejected(self, authed, demo):
        _, by = demo
        fid = by["Northvale Rewards"]["id"]
        assert decide(authed, fid, "reopen").status_code == 409  # already open
        assert decide(authed, fid, "note", "   ").status_code == 422
        assert decide(authed, fid, "delete").status_code == 422
        decide(authed, fid, "confirm")
        assert decide(authed, fid, "confirm").status_code == 409
        assert decide(authed, fid, "escalate").status_code == 409  # reopen first
        assert len(authed.get(f"/api/findings/{fid}").json()["decisions"]) == 1

    def test_escalated_findings_stay_in_review_counts(self, authed, demo):
        b, by = demo
        before = authed.get(f"/api/brands/{b['id']}").json()["stats"]["open_review"]
        decide(authed, by["Northvale Rewards"]["id"], "escalate")
        assert authed.get(f"/api/brands/{b['id']}").json()["stats"]["open_review"] == before
        q = authed.get("/api/findings", params={"brand_id": b["id"], "status": ["escalated"]}).json()
        assert [f["candidate"]["name"] for f in q["items"]] == ["Northvale Rewards"]


class TestRelationships:
    def test_shared_indicators_are_observed_overlaps_only(self, authed, demo):
        _, by = demo
        r = authed.get(f"/api/findings/{by['N0rthvale Pay']['id']}/related").json()
        assert "do not by themselves show common ownership" in r["note"]
        dom = [g for g in r["groups"] if g["kind"] == "domain" and g["value"] == "northvalepay-secure.example"]
        assert dom and [m["name"] for m in dom[0]["candidates"]] == ["Northvale Pay - Wallet Login"]
        # Verify against the stored records: both candidates really contain the value.
        for m in dom[0]["candidates"]:
            c = authed.get(f"/api/findings/{m['finding_id']}").json()["candidate"]
            assert any("northvalepay-secure.example" in u for u in c["external_links"]) or "northvalepay-secure.example" in c["description"]
        # Generic hosts (bit.ly) never count as a shared *domain*.
        assert not any(g["kind"] == "domain" and g["value"] == "bit.ly" for g in r["groups"])

    def test_no_overlaps_returns_empty(self, authed, demo):
        _, by = demo
        assert authed.get(f"/api/findings/{by['Northvale Hiking Club']['id']}/related").json()["groups"] == []

    def test_indicator_extraction(self):
        c = Candidate(kind="account", source="bluesky", handle="acme-help.bsky.social", url="https://bsky.app/profile/acme-help.bsky.social",
                      description="Write to help@acme-support.example or call +44 20 7946 0958. Visit acme.com/help and t.me/acmehelp",
                      external_links=["https://bit.ly/x1", "https://bsky.app/profile/acme-help.bsky.social"], extra={})
        got = {(i.kind, i.value) for i in ind.extract(c, ["acme.com"])}
        assert ("email", "help@acme-support.example") in got
        assert ("phone", "442079460958") in got
        assert ("messaging", "t.me/acmehelp") in got
        assert ("handle", "acme-help") in got
        assert ("url", "bit.ly/x1") in got and ("domain", "bit.ly") not in got
        assert not any(v.startswith("acme.com") for _, v in got)  # official domain is not an indicator
        assert not any("bsky.app/profile" in v for _, v in got)  # own profile URL ignored


class TestReport:
    def test_html_report(self, authed, demo):
        _, by = demo
        fid = by["Northvale Pay - Wallet Login"]["id"]
        decide(authed, fid, "note", "<script>alert(1)</script> checked listing")
        r = authed.get(f"/api/findings/{fid}/report")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert f'filename="scamshield-evidence-finding-{fid}.html"' in r.headers["content-disposition"]
        t = r.text
        for s in ("Potential impersonation — review required", "Observed facts", "Heuristic inferences", "Official assets used for comparison",
                  "com.northvale.pay", "8812773", "SYNTHETIC", "Review history", "Provenance"):
            assert s in t, s
        assert "<script>alert(1)</script>" not in t and "&lt;script&gt;" in t  # notes are escaped

    def test_json_report_matches_detail(self, authed, demo):
        _, by = demo
        fid = by["Northvale Pay Support"]["id"]
        decide(authed, fid, "confirm", "Support impersonation")
        data = authed.get(f"/api/findings/{fid}/report", params={"format": "json"}).json()
        detail = authed.get(f"/api/findings/{fid}").json()
        assert data["finding"]["risk_score"] == detail["risk_score"] and data["status_label"] == "Confirmed impersonation"
        assert data["evidence"]["observed_facts"] == detail["evidence"]["observed_facts"]
        assert data["review_history"][0]["action_label"] == "Confirmed impersonation" and data["review_history"][0]["to_status"] == "confirmed"
        assert data["observations"] and data["candidate"]["source_type"] == "simulated"
        assert authed.get(f"/api/findings/{fid}/report", params={"format": "pdf"}).status_code == 422
