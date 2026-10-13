"""Scan history & scheduled monitoring: schedule math, persistence, controls, duplicate prevention, failures,
change detection and the missing-vs-resolved rules."""
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.candidate import CandidateRecord
from app.db import SessionLocal
from app.models import Brand, FindingChange, MonitoringSchedule, Scan
from app.services import scanner, scheduler
from app.services.schedule_calc import ScheduleError, ScheduleSpec, next_run, upcoming, validate
from app.sources.base import SourceAdapter, SourceError, SourceInfo
from conftest import CSRF, signup, wait_for_scan
from test_api import create_brand

UTC = timezone.utc


# ------------------------------------------------------------------ helpers

class Scripted(SourceAdapter):
    """Each scan pops one step: 'hit', 'hit2' (changed description), 'empty', or a failure kind."""

    info = SourceInfo("scripted", "Scripted", "social", "live", "test", "test")
    steps: dict[str, list[str]] = {}

    def __init__(self, name):
        super().__init__({})
        self.name = name
        self.step = Scripted.steps[name].pop(0) if len(Scripted.steps[name]) > 1 else Scripted.steps[name][0]

    async def search(self, term, client):
        if self.step in ("hit", "hit2"):
            desc = "Acme Wallet help desk. DM us." if self.step == "hit" else "Acme Wallet help desk. Verify your wallet at acme-verify.top now!"
            return [CandidateRecord(self.name, "live", "account", f"{self.name}-1", "Acme Wallet Support", handle="acmewallet-support",
                                    description=desc, url="https://example.test/acme", provenance={"adapter": self.name, "query": term})]
        if self.step == "empty":
            return []
        raise SourceError(f"{self.name} {self.step}", self.step)


@pytest.fixture(autouse=True)
def _isolate_schedules():
    """Schedules share the test database: disable them and fail leftover queued scans after each test."""
    yield
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as db:
            for s in db.scalars(select(MonitoringSchedule)).all():
                s.state = "disabled"
            for sc in db.scalars(select(Scan).where(Scan.status.in_(["queued", "running"]))).all():
                sc.status = "failed"
            db.commit()
    except OperationalError:  # pure unit tests ran before the app created the database
        pass


@pytest.fixture
def scripted():
    Scripted.steps = {}
    scanner.adapter_factory = lambda name, cfg, names, epoch: Scripted(name)
    return Scripted.steps


def manual_scan(client, brand_id, sources):
    s = client.post(f"/api/brands/{brand_id}/scans", json={"sources": sources}, headers=CSRF).json()
    return wait_for_scan(client, s["id"])


def run_now(scan_ids):
    for sid in scan_ids:
        asyncio.run(scanner.run_scan(sid))


def schedule(client, brand_id, **body):
    r = client.put(f"/api/brands/{brand_id}/schedule", json=body, headers=CSRF)
    assert r.status_code == 200, r.text
    return r.json()


def force_due(brand_id, when=None):
    with SessionLocal() as db:
        s = db.scalar(select(MonitoringSchedule).where(MonitoringSchedule.brand_id == brand_id))
        s.next_run_at = when or datetime.now(UTC) - timedelta(minutes=1)
        db.commit()


def sched_row(brand_id) -> MonitoringSchedule:
    with SessionLocal() as db:
        s = db.scalar(select(MonitoringSchedule).where(MonitoringSchedule.brand_id == brand_id))
        db.expunge(s)
        return s


def my_ids(client, ids):
    return [i for i in ids if client.get(f"/api/scans/{i}").status_code == 200]


# ------------------------------------------------------------------ schedule math

class TestScheduleCalc:
    def test_daily_keeps_local_time_across_dst(self):
        spec = ScheduleSpec("daily", time_of_day="09:00", timezone="Europe/London")
        runs = upcoming(spec, datetime(2027, 3, 26, 12, tzinfo=UTC), 3)  # DST starts 2027-03-28
        assert [r.astimezone(ZoneInfo("Europe/London")).hour for r in runs] == [9, 9, 9]
        assert [r.hour for r in runs] == [9, 8, 8]  # UTC shifts by an hour, local time does not

    def test_spring_forward_gap_and_fall_back_ambiguity(self):
        ny = ZoneInfo("America/New_York")
        gap = next_run(ScheduleSpec("daily", time_of_day="02:30", timezone="America/New_York"), datetime(2027, 3, 14, 1, tzinfo=UTC))
        assert gap.astimezone(ny).strftime("%H:%M") == "03:30"
        amb = upcoming(ScheduleSpec("daily", time_of_day="01:30", timezone="America/New_York"), datetime(2027, 11, 6, 12, tzinfo=UTC), 2)
        assert (amb[1] - amb[0]) == timedelta(hours=25)  # runs once on the 25-hour day, at the first 01:30

    def test_weekly_and_interval(self):
        weekly = ScheduleSpec("weekly", time_of_day="08:15", weekdays=[0, 3], timezone="Asia/Kolkata")
        runs = upcoming(weekly, datetime(2027, 1, 6, 0, tzinfo=UTC), 3)  # Wed
        assert [r.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%a %H:%M") for r in runs] == ["Thu 08:15", "Mon 08:15", "Thu 08:15"]
        iv = ScheduleSpec("interval", interval_hours=6)
        prev = datetime(2027, 1, 1, 0, tzinfo=UTC)
        assert next_run(iv, datetime(2027, 1, 1, 1, tzinfo=UTC), prev) == prev + timedelta(hours=6)
        # Scheduler was down for 20 h: skip missed slots, no burst of catch-up runs.
        assert next_run(iv, datetime(2027, 1, 1, 20, tzinfo=UTC), prev) == datetime(2027, 1, 2, 0, tzinfo=UTC)

    @pytest.mark.parametrize("spec,field", [
        (ScheduleSpec("hourly"), "frequency"),
        (ScheduleSpec("daily", timezone="Mars/Olympus"), "timezone"),
        (ScheduleSpec("daily", time_of_day="25:00"), "time_of_day"),
        (ScheduleSpec("weekly", weekdays=[]), "weekdays"),
        (ScheduleSpec("interval", interval_hours=0), "interval_hours"),
    ])
    def test_validation(self, spec, field):
        with pytest.raises(ScheduleError) as e:
            validate(spec)
        assert e.value.field == field


# ------------------------------------------------------------------ persistence & controls

class TestSchedulePersistenceAndControls:
    def test_schedule_is_persisted_with_local_times(self, authed):
        b = create_brand(authed, name="Sched Persist")
        assert authed.get(f"/api/brands/{b['id']}/schedule").json() == {"configured": False, "schedule": None}
        out = schedule(authed, b["id"], frequency="weekly", time_of_day="07:45", weekdays=[4, 0], timezone="America/Sao_Paulo", sources=["bluesky"])
        assert out["state"] == "active" and out["weekdays"] == [0, 4] and out["description"] == "Weekly on Mon, Fri at 07:45 (America/Sao_Paulo)"
        assert len(out["upcoming"]) == 3 and all(u["local"].endswith("-03:00") and "T07:45" in u["local"] for u in out["upcoming"])
        again = authed.get(f"/api/brands/{b['id']}/schedule").json()["schedule"]
        assert again["next_run_at"] == out["next_run_at"] and again["sources"] == ["bluesky"]
        row = sched_row(b["id"])  # stored in the database, not in process memory
        assert row.timezone == "America/Sao_Paulo" and row.next_run_at.tzinfo is not None
        assert authed.get(f"/api/brands/{b['id']}").json()["schedule"]["state"] == "active"

    def test_invalid_schedules_rejected_with_field(self, authed):
        b = create_brand(authed, name="Sched Invalid")
        r = authed.put(f"/api/brands/{b['id']}/schedule", json={"frequency": "daily", "timezone": "Nowhere/City"}, headers=CSRF)
        assert r.status_code == 422 and r.json()["detail"]["field"] == "timezone"
        r = authed.put(f"/api/brands/{b['id']}/schedule", json={"frequency": "daily", "sources": ["myspace"]}, headers=CSRF)
        assert r.status_code == 422 and r.json()["detail"]["field"] == "sources"

    def test_pause_resume_disable(self, authed, scripted):
        scripted["bluesky"] = ["empty"]
        b = create_brand(authed, name="Sched Controls")
        schedule(authed, b["id"], frequency="interval", interval_hours=2, sources=["bluesky"])
        assert authed.post(f"/api/brands/{b['id']}/schedule/pause", headers=CSRF).json()["state"] == "paused"
        assert authed.post(f"/api/brands/{b['id']}/schedule/pause", headers=CSRF).status_code == 409
        force_due(b["id"], datetime.now(UTC) - timedelta(days=3))
        assert not my_ids(authed, scheduler.schedule_tick())  # paused schedules never run
        resumed = authed.post(f"/api/brands/{b['id']}/schedule/resume", headers=CSRF).json()
        # Resuming plans from now: the 3 days of missed runs are not replayed.
        assert resumed["state"] == "active" and datetime.fromisoformat(resumed["next_run_at"]) > datetime.now(UTC) + timedelta(hours=1)
        assert not my_ids(authed, scheduler.schedule_tick())
        dis = authed.post(f"/api/brands/{b['id']}/schedule/disable", headers=CSRF).json()
        assert dis["state"] == "disabled" and dis["next_run_at"] is None and dis["paused_reason"] == "Disabled by an analyst"
        force_due(b["id"])
        assert not my_ids(authed, scheduler.schedule_tick())

    def test_other_org_cannot_read_or_change_schedule(self, authed, client):
        b = create_brand(authed, name="Sched Private")
        schedule(authed, b["id"], frequency="daily")
        client.cookies.clear()
        signup(client, org="Intruder Org")
        assert client.get(f"/api/brands/{b['id']}/schedule").status_code == 404
        assert client.post(f"/api/brands/{b['id']}/schedule/pause", headers=CSRF).status_code == 404
        assert all(s["brand_id"] != b["id"] for s in client.get("/api/schedules").json()["items"])


# ------------------------------------------------------------------ scheduled execution

class TestScheduledExecution:
    def test_repeated_scheduled_scans_detect_changes(self, authed, scripted):
        scripted["bluesky"] = ["hit", "hit", "hit2"]
        b = create_brand(authed, name="Repeat Co", aliases=["Acme Wallet"])
        schedule(authed, b["id"], frequency="interval", interval_hours=1, sources=["bluesky"])
        results = []
        for _ in range(3):
            force_due(b["id"])
            ids = my_ids(authed, scheduler.schedule_tick())
            assert len(ids) == 1
            run_now(ids)
            results.append(authed.get(f"/api/scans/{ids[0]}").json())
        assert [r["trigger"] for r in results] == ["scheduled"] * 3 and all(r["schedule_id"] for r in results)
        assert (results[0]["findings_new"], results[1]["findings_recurring"], results[2]["findings_changed"]) == (1, 1, 1)
        ch = authed.get(f"/api/scans/{results[2]['id']}/changes").json()
        assert ch["counts"]["changed"] == 1
        item = ch["items"][0]
        assert item["changed_fields"] == ["description"]
        assert "DM us" in item["previous"]["description"] and "acme-verify.top" in item["current"]["description"]
        row = sched_row(b["id"])
        assert row.last_outcome == "completed" and row.last_scan_id == results[2]["id"] and row.consecutive_failures == 0

    def test_overlapping_run_is_skipped_not_duplicated(self, authed, scripted):
        scripted["bluesky"] = ["empty"]
        b = create_brand(authed, name="Overlap Co")
        schedule(authed, b["id"], frequency="interval", interval_hours=1, sources=["bluesky"])
        with SessionLocal() as db:  # a scan is already queued for this brand
            brand = db.get(Brand, b["id"])
            existing = scanner.create_scan(db, brand, ["bluesky"], "manual", None)
            existing_id = existing.id
            # The database itself refuses a second active scan for the brand.
            with pytest.raises(scanner.ScanConflict) as e:
                scanner.create_scan(db, brand, ["bluesky"], "manual", None)
            assert e.value.scan_id == existing_id
        force_due(b["id"])
        assert not my_ids(authed, scheduler.schedule_tick())
        row = sched_row(b["id"])
        assert row.last_outcome == "skipped_overlap" and f"#{existing_id}" in row.last_error
        assert authed.post(f"/api/brands/{b['id']}/scans", json={"sources": ["bluesky"]}, headers=CSRF).status_code == 409
        run_now([existing_id])

    def test_concurrent_schedulers_claim_a_run_once(self, authed, scripted):
        scripted["bluesky"] = ["empty"]
        b = create_brand(authed, name="Claim Co")
        schedule(authed, b["id"], frequency="interval", interval_hours=1, sources=["bluesky"])
        force_due(b["id"])
        now = datetime.now(UTC)
        with SessionLocal() as db1, SessionLocal() as db2:
            s1 = db1.scalar(select(MonitoringSchedule).where(MonitoringSchedule.brand_id == b["id"]))
            s2 = db2.scalar(select(MonitoringSchedule).where(MonitoringSchedule.brand_id == b["id"]))  # same stale version
            first = scheduler._run_due(db1, s1, now, "worker", 0)
            second = scheduler._run_due(db2, s2, now, "api", 0)
        assert first and second is None
        run_now([first])

    def test_concurrency_cap_defers_extra_runs(self, authed, scripted, monkeypatch):
        scripted["bluesky"] = ["empty"]
        monkeypatch.setattr(scheduler.get_settings(), "scheduler_max_concurrent_scans", 1)
        brands = [create_brand(authed, name=f"Cap Co {i}") for i in range(2)]
        for b in brands:
            schedule(authed, b["id"], frequency="interval", interval_hours=1, sources=["bluesky"])
            force_due(b["id"])
        ids = my_ids(authed, scheduler.schedule_tick())
        assert len(ids) == 1
        deferred = [sched_row(b["id"]) for b in brands if sched_row(b["id"]).last_outcome == "deferred"]
        assert len(deferred) == 1 and deferred[0].next_run_at <= datetime.now(UTC) + timedelta(minutes=6)
        run_now(ids)

    def test_failed_scans_back_off_then_auto_pause(self, authed, scripted):
        scripted["bluesky"] = ["unavailable"]
        b = create_brand(authed, name="Failing Co")
        schedule(authed, b["id"], frequency="interval", interval_hours=1, sources=["bluesky"])
        for n in range(1, scheduler.AUTO_PAUSE_AFTER_FAILURES + 1):
            force_due(b["id"])
            ids = my_ids(authed, scheduler.schedule_tick())
            assert len(ids) == 1, n
            run_now(ids)
            assert authed.get(f"/api/scans/{ids[0]}").json()["status"] == "failed"
            row = sched_row(b["id"])
            assert row.consecutive_failures == n and row.last_outcome == "failed"
            if n == 1:
                assert row.next_run_at >= datetime.now(UTC) + timedelta(minutes=14)  # backoff, not an immediate retry
        assert row.state == "paused" and "consecutive failed scans" in row.paused_reason
        force_due(b["id"])
        assert not my_ids(authed, scheduler.schedule_tick())
        # Resume + a successful scan resets the failure count.
        scripted["bluesky"] = ["empty"]
        authed.post(f"/api/brands/{b['id']}/schedule/resume", headers=CSRF)
        force_due(b["id"])
        run_now(my_ids(authed, scheduler.schedule_tick()))
        assert sched_row(b["id"]).consecutive_failures == 0

    def test_stalled_scan_is_failed_and_restart_only_touches_own_role(self, authed):
        b = create_brand(authed, name="Stall Co")
        with SessionLocal() as db:
            brand = db.get(Brand, b["id"])
            s = scanner.create_scan(db, brand, ["bluesky"], "scheduled", None, runner="worker")
            assert scanner.mark_interrupted_scans("api") == 0 or db.get(Scan, s.id).status == "queued"
            db.refresh(s)
            assert s.status == "queued"  # the API restarting leaves the worker's scan alone
            s.heartbeat_at = datetime.now(UTC) - timedelta(minutes=scheduler.STALL_MINUTES + 1)
            db.commit()
            sid = s.id
        scheduler.schedule_tick()
        scan = authed.get(f"/api/scans/{sid}").json()
        assert scan["status"] == "failed" and scan["error"].startswith("Stalled")

    def test_scheduler_heartbeat_reports_health(self, authed):
        scheduler.schedule_tick()
        st = authed.get("/api/scheduler/status").json()
        assert st["healthy"] and st["last_tick_at"] and st["message"] is None


# ------------------------------------------------------------------ missing vs resolved

class TestResolutionRules:
    def test_failures_and_partial_results_never_resolve(self, authed, scripted):
        b = create_brand(authed, name="Unknown Co", aliases=["Acme Wallet"])
        scripted["bluesky"] = ["hit", "timeout", "rate_limited", "unavailable"]
        assert manual_scan(authed, b["id"], ["bluesky"])["findings_new"] == 1
        for _ in range(3):
            s = manual_scan(authed, b["id"], ["bluesky"])
            assert s["findings_unverified"] == 1 and s["findings_missing"] == 0 and s["findings_resolved"] == 0
        f = authed.get("/api/findings", params={"brand_id": b["id"]}).json()["items"][0]
        assert f["status"] == "open" and f["change_state"] == "new"
        changes = authed.get(f"/api/scans/{s['id']}/changes", params={"change": ["unverified"]}).json()
        assert changes["counts"]["unverified"] == 1

    def test_partial_source_is_not_clean(self, authed, scripted):
        class Half(Scripted):
            async def search(self, term, client):
                if "support" in term:
                    raise SourceError("boom", "timeout")
                return []
        b = create_brand(authed, name="Half Co", aliases=["Acme Wallet"])
        scripted["bluesky"] = ["hit"]
        manual_scan(authed, b["id"], ["bluesky"])
        scanner.adapter_factory = lambda name, cfg, names, epoch: Half(name)
        s = manual_scan(authed, b["id"], ["bluesky"])
        assert s["sources"][0]["status"] == "partial" and s["findings_unverified"] == 1 and s["findings_missing"] == 0

    def test_missing_then_resolved_then_reappeared(self, authed, scripted):
        b = create_brand(authed, name="Lifecycle Co", aliases=["Acme Wallet"])
        scripted["bluesky"] = ["hit", "empty", "unavailable", "empty", "hit"]
        manual_scan(authed, b["id"], ["bluesky"])
        miss = manual_scan(authed, b["id"], ["bluesky"])
        assert miss["findings_missing"] == 1
        f = authed.get("/api/findings", params={"brand_id": b["id"]}).json()["items"][0]
        assert f["change_state"] == "missing" and f["status"] == "open"
        manual_scan(authed, b["id"], ["bluesky"])  # failure in between: count unchanged, not reset
        res = manual_scan(authed, b["id"], ["bluesky"])
        assert res["findings_resolved"] == 1
        f = authed.get(f"/api/findings/{f['id']}").json()
        assert f["change_state"] == "resolved" and f["status"] == "resolved"
        back = manual_scan(authed, b["id"], ["bluesky"])
        ch = authed.get(f"/api/scans/{back['id']}/changes").json()["items"]
        assert [c["change"] for c in ch] == ["reappeared"] and ch[0]["missed_scans"] == 2
        assert authed.get(f"/api/findings/{f['id']}").json()["status"] == "open"

    def test_threshold_is_configurable_and_other_sources_untouched(self, authed, scripted):
        assert authed.put("/api/settings/monitoring", json={"resolve_after_misses": 1}, headers=CSRF).json()["values"]["resolve_after_misses"] == 1
        b = create_brand(authed, name="Threshold Co", aliases=["Acme Wallet"])
        scripted["bluesky"] = ["hit"]
        scripted["mastodon"] = ["empty"]
        manual_scan(authed, b["id"], ["bluesky"])
        # Mastodon completing cleanly says nothing about a Bluesky account.
        assert manual_scan(authed, b["id"], ["mastodon"])["findings_resolved"] == 0
        scripted["bluesky"] = ["empty"]
        assert manual_scan(authed, b["id"], ["bluesky"])["findings_resolved"] == 1
        assert authed.put("/api/settings/monitoring", json={"resolve_after_misses": 9}, headers=CSRF).status_code == 422


# ------------------------------------------------------------------ history API

class TestScanHistory:
    def test_filters_counts_and_fields(self, authed, scripted):
        b = create_brand(authed, name="History Co", aliases=["Acme Wallet"])
        scripted["bluesky"] = ["hit", "unavailable"]
        ok = manual_scan(authed, b["id"], ["bluesky"])
        bad = manual_scan(authed, b["id"], ["bluesky"])
        schedule(authed, b["id"], frequency="interval", interval_hours=1, sources=["bluesky"])
        scripted["bluesky"] = ["empty"]
        force_due(b["id"])
        run_now(my_ids(authed, scheduler.schedule_tick()))
        r = authed.get("/api/scans", params={"brand_id": b["id"]})
        assert r.headers["x-total-count"] == "3"
        sched = authed.get("/api/scans", params={"brand_id": b["id"], "trigger": "scheduled"}).json()
        assert len(sched) == 1 and sched[0]["schedule_id"]
        failing = authed.get("/api/scans", params={"brand_id": b["id"], "has_failures": "true"}).json()
        assert [s["id"] for s in failing] == [bad["id"]] and failing[0]["source_failures"] == ["bluesky"]
        assert [s["id"] for s in authed.get("/api/scans", params={"brand_id": b["id"], "status": ["completed"], "trigger": ["manual"]}).json()] == [ok["id"]]
        page = authed.get("/api/scans", params={"brand_id": b["id"], "limit": 1, "offset": 1})
        assert len(page.json()) == 1 and page.headers["x-total-count"] == "3"
        s = authed.get(f"/api/scans/{ok['id']}").json()
        for k in ("started_at", "finished_at", "duration_ms", "trigger", "sources_attempted", "candidates_unique", "findings_new",
                  "findings_updated", "excluded_official", "source_failures", "status"):
            assert k in s, k
        assert authed.get("/api/scans", params={"status": ["exploded"]}).status_code == 422


def test_legacy_interval_schedules_are_migrated(authed):
    from app.services.backfill import migrate_legacy_schedules

    b = create_brand(authed, name="Legacy Co")
    with SessionLocal() as db:
        brand = db.get(Brand, b["id"])
        brand.schedule_enabled, brand.schedule_interval_hours = True, 12
        db.commit()
    assert migrate_legacy_schedules() >= 1
    row = sched_row(b["id"])
    assert (row.frequency, row.interval_hours, row.state) == ("interval", 12, "active")
    assert migrate_legacy_schedules() == 0  # idempotent
