"""Brand profile & official-asset management: CRUD, validation, uploads, registry, rules, isolation, engine use."""
import io
import time

from PIL import Image

from app.config import get_settings
from app.db import SessionLocal
from app.models import Brand
from app.services.scanner import brand_context
from conftest import CSRF, signup, wait_for_scan

FULL = {
    "name": "Kestrel Bank",
    "aliases": ["Kestrel"],
    "description": "Kestrel Bank offers current accounts, savings and card payments.",
    "website_url": "https://www.kestrelbank.example/home",
    "official_domains": ["kestrel.example"],
    "keywords": ["Kestrel Card"],
    "additional_identifiers": ["Kestrel Bank plc"],
    "official_accounts": [
        {"platform": "bluesky", "handle": "kestrelbank.example", "profile_url": "https://bsky.app/profile/kestrelbank.example", "external_id": "did:plc:kestrel"},
        {"platform": "instagram", "handle": "kestrelbank"},
    ],
    "official_apps": [
        {"store": "apple", "name": "Kestrel Mobile", "app_id": "com.kestrel.mobile", "track_id": "id42", "publisher_id": "900", "publisher_name": "Kestrel Bank plc", "url": "https://apps.apple.com/app/id42"},
        {"store": "google_play", "name": "Kestrel Mobile", "app_id": "com.kestrel.mobile", "publisher_id": "Kestrel+Bank"},
    ],
}


def png(w=64, h=64, color=(20, 90, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def upload(client, bid, data, name="l.png", ctype="image/png"):
    return client.post(f"/api/brands/{bid}/logo", files={"file": (name, data, ctype)}, headers=CSRF)


class TestProfiles:
    def test_partial_profile_is_allowed(self, authed):
        r = authed.post("/api/brands", json={"name": "Just A Name"}, headers=CSRF)
        assert r.status_code == 201
        b = r.json()
        assert b["official_accounts"] == [] and b["official_apps"] == [] and b["website_url"] is None

    def test_full_profile_persists_every_section(self, authed):
        b = authed.post("/api/brands", json=FULL, headers=CSRF).json()
        got = authed.get(f"/api/brands/{b['id']}").json()
        assert got["website_url"] == FULL["website_url"]
        assert got["official_domains"][0] == "kestrelbank.example"  # website host added automatically
        assert "kestrel.example" in got["official_domains"]
        assert got["additional_identifiers"] == ["Kestrel Bank plc"]
        assert got["official_apps"][0]["name"] == "Kestrel Mobile" and got["official_apps"][0]["track_id"] == "42"
        assert {a["platform"] for a in got["official_accounts"]} == {"bluesky", "instagram"}
        assert got["exclusion_rules"]["official_app_id"] is True and got["exclusion_rules"]["official_publisher_id"] is False

    def test_edit_replaces_assets_and_keeps_logo(self, authed):
        b = authed.post("/api/brands", json={**FULL, "name": "Edit Co"}, headers=CSRF).json()
        assert upload(authed, b["id"], png()).status_code == 200
        body = {**FULL, "name": "Edit Co", "aliases": [], "official_accounts": [{"platform": "mastodon", "handle": "edit@mastodon.social"}],
                "official_apps": [], "website_url": None}
        r = authed.put(f"/api/brands/{b['id']}", json=body, headers=CSRF)
        assert r.status_code == 200
        got = authed.get(f"/api/brands/{b['id']}").json()
        assert [a["handle"] for a in got["official_accounts"]] == ["edit@mastodon.social"]
        assert got["official_apps"] == [] and got["aliases"] == [] and got["website_url"] is None
        assert got["has_logo"] and got["logo_phash"]  # profile edits never drop the logo

    def test_delete_removes_brand_and_logo_file(self, authed):
        b = authed.post("/api/brands", json={"name": "Delete Me"}, headers=CSRF).json()
        upload(authed, b["id"], png())
        with SessionLocal() as db:
            path = get_settings().upload_dir / db.get(Brand, b["id"]).logo_path
        assert path.exists()
        assert authed.delete(f"/api/brands/{b['id']}", headers=CSRF).status_code == 200
        assert authed.get(f"/api/brands/{b['id']}").status_code == 404
        assert not path.exists()

    def test_actionable_field_errors(self, authed):
        bad = {**FULL, "name": "Errors Co", "website_url": "ftp://x", "official_accounts": [{"platform": "bluesky", "handle": "ok", "profile_url": "notaurl"}],
               "official_apps": [{"store": "apple", "app_id": "nope"}]}
        r = authed.post("/api/brands", json=bad, headers=CSRF)
        assert r.status_code == 422
        fields = {e["field"] for e in r.json()["errors"]}
        assert {"website_url", "official_accounts.0.profile_url", "official_apps.0.app_id"} <= fields
        assert any("bundle/package identifier" in e["message"] for e in r.json()["errors"])
        dup = {**FULL, "name": "Dup Co", "official_apps": [FULL["official_apps"][0], FULL["official_apps"][0]]}
        assert "Duplicate official app" in authed.post("/api/brands", json=dup, headers=CSRF).json()["detail"]
        authed.post("/api/brands", json={"name": "Same Name"}, headers=CSRF)
        assert authed.post("/api/brands", json={"name": "same name"}, headers=CSRF).status_code == 409


class TestLogoUploads:
    def test_valid_png_and_jpeg_are_hashed(self, authed):
        b = authed.post("/api/brands", json={"name": "Logo Ok"}, headers=CSRF).json()
        r = upload(authed, b["id"], png())
        assert r.status_code == 200 and len(r.json()["logo_phash"]) == 16
        buf = io.BytesIO()
        img = Image.new("RGB", (80, 80), (240, 240, 240))
        img.paste((200, 40, 40), (0, 0, 40, 80))  # solid fills share a pHash; a shape makes it distinct
        img.save(buf, "JPEG")
        r2 = upload(authed, b["id"], buf.getvalue(), "l.jpg", "image/jpeg")
        assert r2.status_code == 200 and r2.json()["logo_phash"] != r.json()["logo_phash"]

    def test_limits_and_rejections(self, authed):
        b = authed.post("/api/brands", json={"name": "Logo Bad"}, headers=CSRF).json()
        tiny = upload(authed, b["id"], png(16, 16))
        assert tiny.status_code == 422 and "at least 32" in tiny.json()["detail"]
        huge = upload(authed, b["id"], png(4200, 40))
        assert huge.status_code == 422 and "maximum" in huge.json()["detail"]
        assert upload(authed, b["id"], b"\x89PNG not really", "x.png").status_code == 422
        assert upload(authed, b["id"], b"<svg/>", "x.svg", "image/svg+xml").status_code == 415
        big = upload(authed, b["id"], b"\x00" * (2 * 1024 * 1024 + 10))
        assert big.status_code == 413
        assert authed.get(f"/api/brands/{b['id']}").json()["has_logo"] is False  # nothing stored on failure


class TestRegistryAndRules:
    def test_registry_separates_exact_identifiers_from_similarity(self, authed):
        b = authed.post("/api/brands", json={**FULL, "name": "Registry Co"}, headers=CSRF).json()
        reg = authed.get(f"/api/brands/{b['id']}/registry").json()
        types = {(i["type"], i["value"]) for i in reg["exact_identifiers"]}
        assert ("handle", "@kestrelbank.example") in types and ("app_id", "com.kestrel.mobile") in types
        assert ("track_id", "42") in types and ("publisher_id", "900") in types and ("domain", "kestrelbank.example") in types
        assert reg["similarity_reference"]["names"] == ["Registry Co", "Kestrel"]
        assert "Kestrel Bank plc" in reg["similarity_reference"]["additional_identifiers"]
        assert "Never used to exclude" in reg["similarity_reference"]["note"]
        assert {r["id"] for r in reg["rules"]} >= {"official_app_id", "official_publisher_id"} and reg["can_edit_rules"] is True

    def test_dry_run_check(self, authed):
        b = authed.post("/api/brands", json={**FULL, "name": "Check Co"}, headers=CSRF).json()
        chk = lambda body: authed.post(f"/api/brands/{b['id']}/registry/check", json=body, headers=CSRF).json()
        assert chk({"platform": "bluesky", "handle": "KestrelBank.example"})["rule"] == "official_platform_handle"
        assert chk({"platform": "bluesky", "handle": "news.kestrel.example"})["rule"] == "bluesky_verified_domain_handle"
        assert chk({"platform": "apple", "app_id": "com.kestrel.mobile"})["rule"] == "official_app_id"
        assert chk({"platform": "bluesky", "handle": "kestrel-support.bsky.social"})["excluded"] is False
        r = chk({"platform": "apple", "app_id": "com.other.app", "publisher_id": "900"})
        assert r["excluded"] is False and r["disabled_rule_would_match"] == "official_publisher_id"
        assert authed.post(f"/api/brands/{b['id']}/registry/check", json={"platform": "apple"}, headers=CSRF).status_code == 422

    def test_rule_edits_persist_and_only_store_deviations(self, authed):
        b = authed.post("/api/brands", json={**FULL, "name": "Rules Co"}, headers=CSRF).json()
        r = authed.put(f"/api/brands/{b['id']}/exclusion-rules", json={"rules": {"official_publisher_id": True, "mastodon_verified_link": False}}, headers=CSRF)
        assert r.status_code == 200
        with SessionLocal() as db:
            assert db.get(Brand, b["id"]).exclusion_rules == {"official_publisher_id": True, "mastodon_verified_link": False}
        got = authed.get(f"/api/brands/{b['id']}").json()
        assert got["exclusion_rules"]["official_publisher_id"] is True and set(got["exclusion_rules_customised"]) == {"official_publisher_id", "mastodon_verified_link"}
        assert authed.post(f"/api/brands/{b['id']}/registry/check", json={"platform": "apple", "app_id": "com.other", "publisher_id": "900"}, headers=CSRF).json()["rule"] == "official_publisher_id"
        assert authed.put(f"/api/brands/{b['id']}/exclusion-rules", json={"rules": {"bogus": True}}, headers=CSRF).status_code == 422
        # Back to defaults → nothing stored
        authed.put(f"/api/brands/{b['id']}/exclusion-rules", json={"rules": {"official_publisher_id": False, "mastodon_verified_link": True}}, headers=CSRF)
        with SessionLocal() as db:
            assert db.get(Brand, b["id"]).exclusion_rules == {}

    def test_analysts_cannot_edit_rules(self, client):
        signup(client, org="Rule Org")
        b = client.post("/api/brands", json={**FULL, "name": "Analyst Co"}, headers=CSRF).json()
        inv = client.post("/api/settings/invites", json={"email": f"an-{time.time_ns()}@example.com", "role": "analyst"}, headers=CSRF).json()
        client.cookies.clear()
        client.post("/api/auth/accept-invite", json={"token": inv["link"].split("token=")[1], "name": "An", "password": "correct-horse-42"}, headers=CSRF)
        assert client.get(f"/api/brands/{b['id']}/registry").json()["can_edit_rules"] is False
        assert client.put(f"/api/brands/{b['id']}/exclusion-rules", json={"rules": {"official_app_id": False}}, headers=CSRF).status_code == 403
        # Analysts can still maintain the profile itself.
        assert client.put(f"/api/brands/{b['id']}", json={**FULL, "name": "Analyst Co", "keywords": ["x"]}, headers=CSRF).status_code == 200


class TestIsolationAndEngine:
    def test_other_org_cannot_reach_brand_registry_or_rules(self, client):
        signup(client, org="Owner Org")
        b = client.post("/api/brands", json={**FULL, "name": "Private Kestrel"}, headers=CSRF).json()
        client.cookies.clear()
        signup(client, org="Intruder Org")
        assert client.get(f"/api/brands/{b['id']}/registry").status_code == 404
        assert client.post(f"/api/brands/{b['id']}/registry/check", json={"platform": "apple", "app_id": "com.kestrel.mobile"}, headers=CSRF).status_code == 404
        assert client.put(f"/api/brands/{b['id']}/exclusion-rules", json={"rules": {"official_app_id": False}}, headers=CSRF).status_code == 404
        assert upload(client, b["id"], png()).status_code == 404
        assert client.get(f"/api/brands/{b['id']}/logo").status_code == 404
        assert all(x["name"] != "Private Kestrel" for x in client.get("/api/brands").json())

    def test_engine_reads_assets_and_rules_from_storage(self, authed):
        b = authed.post("/api/brands", json={**FULL, "name": "Engine Co"}, headers=CSRF).json()
        authed.put(f"/api/brands/{b['id']}/exclusion-rules", json={"rules": {"official_track_id": False}}, headers=CSRF)
        with SessionLocal() as db:
            ctx = brand_context(db.get(Brand, b["id"]))
        assert {(a.platform, a.handle) for a in ctx.official_accounts} == {("bluesky", "kestrelbank.example"), ("instagram", "kestrelbank")}
        assert {(a.store, a.app_id, a.publisher_id) for a in ctx.official_apps} == {("apple", "com.kestrel.mobile", "900"), ("google_play", "com.kestrel.mobile", "Kestrel+Bank")}
        assert ctx.exclusion_rules == {"official_track_id": False}
        assert "Kestrel Bank plc" in " ".join(ctx.corpus)

    def test_rules_change_real_scan_exclusions(self, authed):
        demo = authed.post("/api/demo/brand", headers=CSRF).json()
        run = lambda: wait_for_scan(authed, authed.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()["id"])
        assert run()["excluded_official"] == 4
        authed.put(f"/api/brands/{demo['id']}/exclusion-rules", json={"rules": {"official_app_id": False, "official_track_id": False}}, headers=CSRF)
        assert run()["excluded_official"] == 2  # official apps are now scored instead of excluded
        authed.put(f"/api/brands/{demo['id']}/exclusion-rules", json={"rules": {"official_app_id": True, "official_track_id": True, "official_publisher_id": True}}, headers=CSRF)
        s = run()
        assert s["excluded_official"] == 5  # + "Northvale Pay Business" (same official publisher ID)
        rules = {e["rule"] for e in authed.get(f"/api/brands/{demo['id']}/exclusions").json() if e["scan_id"] == s["id"]}
        assert "official_publisher_id" in rules
