"""Mobile app monitoring: package-ID signal, publisher-mismatch evidence rule, official exclusion, store failures, export."""
import csv
import io

from app.candidate import CandidateRecord
from app.detection.engine import BrandContext, evaluate
from app.detection.exclusion import OfficialAppRef
from app.detection.scoring import assess
from app.detection.signals import Signal
from app.detection.similarity import package_similarity
from app.services import scanner
from app.sources.apple import AppleAppStoreAdapter
from app.sources.base import SourceAdapter, SourceError, SourceInfo
from conftest import CSRF, wait_for_scan
from test_api import create_brand

OFFICIAL = OfficialAppRef("apple", "com.acmewallet.ios", "111", "500", "Acme Wallet Inc")


def app(external_id, name, publisher="Someone Else", publisher_id="999", description="", platform="apple", source="apple_app_store"):
    return CandidateRecord(source, "live", "app", external_id, name, description=description, publisher_name=publisher,
                           publisher_id=publisher_id, metadata={"platform": platform}, url=f"https://apps.apple.com/app/{external_id}")


class TestPackageSignal:
    def test_typo_and_embedded_brand_in_package_id(self):
        assert package_similarity("com.acmewa11et.app", ["Acme Wallet"]).score >= 0.8
        s = package_similarity("io.helpdesk.acmewallet", ["Acme Wallet"])
        assert s.score >= 0.9 and s.data["segment"] == "acmewallet"

    def test_boilerplate_segments_do_not_match(self):
        assert package_similarity("com.android.app", ["Android"]).score == 0.0  # stopwords are ignored
        assert package_similarity("com.northwind.payments", ["Acme Wallet"]).score < 0.5

    def test_reuse_of_official_namespace_is_flagged(self):
        s = package_similarity("com.acmewallet.rewards", ["Acme Wallet"], ["com.acmewallet.ios"])
        assert s.data["official_namespace"] == "com.acmewallet" and any("namespace" in e for e in s.evidence)

    def test_missing_package_is_not_evaluated(self):
        assert not package_similarity("", ["Acme"]).evaluated
        assert not package_similarity("1234567", ["Acme"]).evaluated  # not a reverse-DNS identifier


class TestPublisherMismatchIsNotProof:
    def test_name_plus_different_publisher_only_stays_low(self):
        sigs = [Signal("name", True, 1.0, data={"risky_terms": []}), Signal("package", True, 0.9),
                Signal("publisher", True, 0.9), Signal("description", True, 0.05), Signal("scam", True, 0.0, data={"categories": []}),
                Signal("urls", True, 0.0), Signal.missing("logo", "no logo")]
        a = assess(sigs, "app")
        assert a.risk_level == "low" and a.detection_type == "lookalike_app"
        assert a.corroborating_groups == ["provenance"]
        assert a.classification.startswith("Different publisher only")

    def test_publisher_mismatch_strengthens_independent_evidence(self):
        sigs = [Signal("name", True, 1.0, data={"risky_terms": []}), Signal("publisher", True, 0.9),
                Signal("logo", True, 0.9), Signal("description", True, 0.5), Signal("scam", True, 0.0, data={"categories": []}),
                Signal("urls", True, 0.0)]
        a = assess(sigs, "app")
        assert a.risk_level in ("medium", "high") and a.detection_type == "suspicious_app"
        assert "provenance" in a.corroborating_groups and "visual" in a.corroborating_groups

    def test_engine_end_to_end_unrelated_namesake_app(self):
        brand = BrandContext(name="Acme Wallet", description="Send money and pay bills with Acme Wallet.", official_apps=[OFFICIAL])
        [res] = evaluate(brand, [app("com.fanmade.acmewallet", "Acme Wallet Tips", publisher="Fan Studio",
                                     description="Unofficial tips and tricks guide. Not affiliated.")])
        assert res.excluded is None and res.assessment.risk_level == "low"
        assert res.assessment.signals["package"]["evaluated"]


class TestOfficialExclusion:
    def test_official_bundle_id_excluded_even_under_another_name(self):
        brand = BrandContext(name="Acme Wallet", official_apps=[OFFICIAL])
        out = evaluate(brand, [app("com.acmewallet.ios", "Totally Different Name", publisher_id="500"),
                               app("com.acmewallet.ios.clone", "Acme Wallet", publisher="Acme Wallet Inc", publisher_id="777")])
        assert out[0].excluded and out[0].excluded.rule
        # Copied developer *name* is not trusted: the clone is scored, and the namespace reuse is evidence.
        assert out[1].excluded is None and out[1].assessment.signals["package"]["data"]["official_namespace"] == "com.acmewallet"


class TestAppleNormalization:
    def test_itunes_result_fields(self):
        r = AppleAppStoreAdapter.normalize({
            "bundleId": "com.acme.x", "trackId": 42, "trackName": "Acme X", "artistName": "Acme", "artistId": 7,
            "description": "d", "artworkUrl512": "https://is1.mzstatic.com/x.png", "trackViewUrl": "https://apps.apple.com/app/id42",
            "sellerUrl": "https://acme.example", "primaryGenreName": "Finance",
        }, "acme", "us")
        assert (r.external_id, r.name, r.publisher_name, r.publisher_id) == ("com.acme.x", "Acme X", "Acme", "7")
        assert r.avatar_url.endswith("x.png") and r.url.endswith("id42") and r.metadata["platform"] == "apple"
        assert r.provenance["query"] == "acme"


class _StoreAdapter(SourceAdapter):
    info = SourceInfo("store", "Store", "app_store", "live", "test", "test")

    def __init__(self, name, behaviour):
        super().__init__({})
        self.name, self.behaviour = name, behaviour

    async def search(self, term, client):
        if self.behaviour == "hit":
            return [CandidateRecord(self.name, "live", "app", "com.evil.acmewallet", "Acme Wallet - Login", publisher_name="Evil Ltd",
                                    publisher_id="13", description="Verify your Acme Wallet account to unlock funds. Contact support on Telegram.",
                                    url="https://apps.apple.com/app/id13", metadata={"platform": "apple"}, provenance={"adapter": self.name, "query": term}),
                    CandidateRecord(self.name, "live", "app", "com.acmewallet.ios", "Acme Wallet", publisher_name="Acme Wallet Inc",
                                    publisher_id="500", url="https://apps.apple.com/app/id111", metadata={"platform": "apple"},
                                    provenance={"adapter": self.name, "query": term})]
        raise SourceError(f"{self.name} {self.behaviour}", self.behaviour)


def _scan(authed, brand_id, behaviours):
    scanner.adapter_factory = lambda name, cfg, names, epoch: _StoreAdapter(name, behaviours[name])
    s = authed.post(f"/api/brands/{brand_id}/scans", json={"sources": list(behaviours)}, headers=CSRF).json()
    return wait_for_scan(authed, s["id"])


class TestAppScans:
    def test_scan_excludes_official_and_scores_candidate(self, authed):
        b = create_brand(authed, name="Acme Wallet", official_apps=[{"store": "apple", "app_id": "com.acmewallet.ios", "publisher_id": "500"}])
        s = _scan(authed, b["id"], {"apple_app_store": "hit"})
        assert s["excluded_official"] == 1
        items = authed.get("/api/findings", params={"brand_id": b["id"], "kind": "app", "include_signals": "true"}).json()["items"]
        assert [f["candidate"]["external_id"] for f in items] == ["com.evil.acmewallet"]
        f = items[0]
        assert {"name", "package", "logo", "description", "publisher", "urls", "scam"} <= set(f["signal_scores"])
        assert f["risk_level"] in ("critical", "high", "medium") and f["detection_type"] == "suspicious_app"

    def test_store_failures_produce_no_fabricated_results(self, authed):
        b = create_brand(authed, name="Fail Wallet")
        s = _scan(authed, b["id"], {"apple_app_store": "rate_limited", "google_play": "unavailable"})
        by = {x["source"]: x for x in s["sources"]}
        assert by["apple_app_store"]["status"] == "failed" and by["apple_app_store"]["failure_kind"] == "rate_limited"
        assert by["google_play"]["status"] == "failed" and by["google_play"]["failure_kind"] == "unavailable"
        assert s["status"] == "failed" and s["candidates_unique"] == 0
        assert authed.get("/api/findings", params={"brand_id": b["id"]}).json()["total"] == 0

    def test_csv_export_of_app_findings(self, authed):
        b = create_brand(authed, name="Acme Wallet", official_apps=[{"store": "apple", "app_id": "com.acmewallet.ios", "publisher_id": "500"}])
        _scan(authed, b["id"], {"apple_app_store": "hit"})
        r = authed.get("/api/findings/export.csv", params={"brand_id": b["id"], "kind": "app", "level": ["critical", "high", "medium", "low"]})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert [x["handle"] or x["name"] for x in rows] == ["Acme Wallet - Login"]
        assert rows[0]["kind"] == "app" and rows[0]["publisher_id"] == "13"


def test_demo_app_outcomes(authed):
    demo = authed.post("/api/demo/brand", headers=CSRF).json()
    wait_for_scan(authed, authed.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()["id"])
    items = authed.get("/api/findings", params={"brand_id": demo["id"], "kind": "app", "limit": 50}).json()["items"]
    by = {f["candidate"]["name"]: f for f in items}
    assert "Northvale Pay" not in by  # the official apps are excluded, not scored
    assert by["Northvale Pay - Wallet Login"]["risk_level"] in ("critical", "high")
    assert by["Northvale Pay Business"]["detection_type"] == "official_publisher_app" and by["Northvale Pay Business"]["risk_level"] == "low"
    calc = by.get("Bill Split Calculator for Northvale")
    assert calc is None or calc["risk_level"] == "low"
