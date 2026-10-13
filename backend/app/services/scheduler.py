"""Background scheduler for recurring monitoring scans.

How it runs
-----------
* Development: inside the API process (SCAMSHIELD_SCHEDULER_ENABLED=true, the default).
* Production: in a dedicated worker — `python -m app.worker` — with SCAMSHIELD_SCHEDULER_ENABLED=false on every
  API replica. Scheduled scans then execute in the worker; manual scans still run in the API process.
No browser needs to stay open: schedules, next-run times and scan state all live in the database.

Safety rules
------------
* Claiming is compare-and-set on `MonitoringSchedule.version`, so two scheduler processes never start the same run.
* A database unique index allows only one queued/running scan per brand; an overlapping run is skipped and recorded.
* At most `scheduler_max_concurrent_scans` scheduled scans run at once; extra due runs are deferred a few minutes.
* Failed scheduled scans back off exponentially (15 min → 24 h) and the schedule auto-pauses after
  `AUTO_PAUSE_AFTER_FAILURES` consecutive failures, so a broken source is not hammered indefinitely.
* Scans with no progress heartbeat for `STALL_MINUTES` are marked failed (e.g. a crashed worker).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import Brand, MonitoringSchedule, Organization, RuntimeState, Scan
from . import scanner
from .schedule_calc import ScheduleSpec, next_run

log = logging.getLogger("scamshield.scheduler")

AUTO_PAUSE_AFTER_FAILURES = 5
BACKOFF_BASE = timedelta(minutes=15)
BACKOFF_MAX = timedelta(hours=24)
DEFER_WHEN_BUSY = timedelta(minutes=5)
STALL_MINUTES = 20
HEARTBEAT_KEY = "scheduler"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def spec_of(s: MonitoringSchedule) -> ScheduleSpec:
    return ScheduleSpec(s.frequency, s.interval_hours, s.time_of_day, list(s.weekdays or []), s.timezone)


def planned_next(s: MonitoringSchedule, now: datetime) -> datetime:
    return next_run(spec_of(s), now, s.next_run_at if s.frequency == "interval" else None)


def backoff_for(failures: int) -> timedelta:
    return min(BACKOFF_BASE * (2 ** max(failures - 1, 0)), BACKOFF_MAX)


def _beat(db: Session, now: datetime, runner: str, extra: dict | None = None) -> None:
    row = db.get(RuntimeState, HEARTBEAT_KEY) or RuntimeState(key=HEARTBEAT_KEY)
    row.value = {"last_tick_at": now.isoformat(), "runner": runner, "pid": os.getpid(), "host": socket.gethostname(), **(extra or {})}
    row.updated_at = now
    db.merge(row)


def sweep_stalled(db: Session, now: datetime) -> int:
    cutoff = now - timedelta(minutes=STALL_MINUTES)
    stalled = db.scalars(
        select(Scan).where(Scan.status.in_(["queued", "running"]), func.coalesce(Scan.heartbeat_at, Scan.created_at) < cutoff)
    ).all()
    for s in stalled:
        if s.id in scanner._running:  # still alive in this process
            continue
        s.status, s.stage, s.finished_at = "failed", "Failed", now
        s.error = f"Stalled: no progress for {STALL_MINUTES} minutes (worker stopped or crashed)"
        for ss in s.sources:
            if ss.status in ("pending", "running"):
                ss.status, ss.error = "failed", "Scan stalled"
        if s.schedule_id:
            record_outcome(db, s, now)
    return len(stalled)


def schedule_tick(now: datetime | None = None, runner: str | None = None) -> list[int]:
    """Create scans for due schedules. Returns created scan IDs (the caller launches them)."""
    now = now or utcnow()
    settings = get_settings()
    runner = runner or settings.process_role
    created: list[int] = []
    with SessionLocal() as db:
        sweep_stalled(db, now)
        due = db.scalars(
            select(MonitoringSchedule).where(MonitoringSchedule.state == "active", MonitoringSchedule.next_run_at <= now)
            .order_by(MonitoringSchedule.next_run_at)
        ).all()
        busy = db.scalar(select(func.count()).select_from(Scan).where(Scan.trigger == "scheduled", Scan.status.in_(["queued", "running"]))) or 0
        for s in due:
            try:
                scan_id = _run_due(db, s, now, runner, busy)
                if scan_id:
                    created.append(scan_id)
                    busy += 1
            except Exception as exc:  # one bad schedule never stops the others
                db.rollback()
                log.exception("schedule %s failed to start", s.id)
                s = db.get(MonitoringSchedule, s.id)
                if s:
                    s.last_outcome, s.last_error = "error", f"{type(exc).__name__}: {exc}"[:500]
                    db.commit()
        _beat(db, now, runner, {"due": len(due), "started": len(created)})
        db.commit()
        _apply_retention_daily(db, now)
    try:
        from .notifications import send_due_digests

        send_due_digests(now)
    except Exception:
        log.exception("digest run failed")
    try:
        from ..security import DatabaseRateLimiter

        DatabaseRateLimiter.purge_older_than(24 * 3600)  # rate-limit windows are at most minutes long
    except Exception:
        log.exception("rate-limit cleanup failed")
    return created


def _apply_retention_daily(db: Session, now: datetime) -> None:
    """Organizations' scan-history retention policies, applied at most once every 24 hours."""
    from .retention import apply_all

    row = db.get(RuntimeState, "retention")
    last = datetime.fromisoformat(row.value["applied_at"]) if row and row.value.get("applied_at") else None
    if last and now - last < timedelta(hours=24):
        return
    try:
        removed = apply_all(db, now)
        db.merge(RuntimeState(key="retention", value={"applied_at": now.isoformat(), "scans_removed": removed}, updated_at=now))
        db.commit()
    except Exception:
        db.rollback()
        log.exception("retention run failed")


def _run_due(db: Session, s: MonitoringSchedule, now: datetime, runner: str, busy: int) -> int | None:
    settings = get_settings()
    # Claim this run (compare-and-set): if another scheduler already advanced the schedule, do nothing.
    claimed = db.execute(
        update(MonitoringSchedule)
        .where(MonitoringSchedule.id == s.id, MonitoringSchedule.version == s.version, MonitoringSchedule.state == "active")
        .values(next_run_at=planned_next(s, now), version=s.version + 1)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if claimed != 1:
        return None
    db.refresh(s)
    brand = db.get(Brand, s.brand_id)
    running = scanner.active_scan(db, brand.id)
    if running:
        s.last_outcome, s.last_error = "skipped_overlap", f"Skipped: scan #{running.id} was still {running.status}"
        db.commit()
        return None
    if busy >= settings.scheduler_max_concurrent_scans:
        s.next_run_at, s.version = now + DEFER_WHEN_BUSY, s.version + 1
        s.last_outcome, s.last_error = "deferred", f"Deferred: {busy} scheduled scan(s) already running"
        db.commit()
        return None
    org = db.get(Organization, brand.organization_id)
    try:
        enabled = scanner.resolve_sources(brand, org, None)
        sources = [x for x in (s.sources or enabled) if x in enabled] if s.sources else enabled
        if not sources:
            raise ValueError("None of this schedule's sources are enabled")
        scan = scanner.create_scan(db, brand, sources, "scheduled", None, schedule_id=s.id, runner=runner)
    except scanner.ScanConflict as e:
        s.last_outcome, s.last_error = "skipped_overlap", f"Skipped: scan #{e.scan_id} was already running"
        db.commit()
        return None
    except ValueError as e:
        s.last_outcome, s.last_error = "error", str(e)
        db.commit()
        return None
    s.last_run_at, s.last_scan_id, s.last_outcome, s.last_error = now, scan.id, "started", None
    db.commit()
    return scan.id


def record_outcome(db: Session, scan: Scan, now: datetime | None = None) -> bool:
    """Called when a scheduled scan finishes: success resets failures; failures back off and may auto-pause.
    Returns True if this outcome paused the schedule."""
    s = db.get(MonitoringSchedule, scan.schedule_id) if scan.schedule_id else None
    if not s or s.last_scan_id not in (None, scan.id):
        return False
    paused = False
    now = now or utcnow()
    s.last_outcome = scan.status
    if scan.status == "failed":
        s.consecutive_failures += 1
        s.last_error = scan.error or "Scan failed"
        retry_at = now + backoff_for(s.consecutive_failures)
        if s.next_run_at is None or s.next_run_at < retry_at:
            s.next_run_at = retry_at
        if s.consecutive_failures >= AUTO_PAUSE_AFTER_FAILURES and s.state == "active":
            s.state = "paused"
            s.paused_reason = f"Paused automatically after {s.consecutive_failures} consecutive failed scans. Check source health, then resume."
            paused = True
    else:
        s.consecutive_failures = 0
        failed = [ss.source for ss in scan.sources if ss.status in ("failed", "partial")]
        s.last_error = f"Incomplete sources: {', '.join(failed)}" if failed else None
    s.version += 1
    return paused


def on_scan_finished(scan_id: int) -> None:
    paused_schedule = None
    try:
        with SessionLocal() as db:
            scan = db.get(Scan, scan_id)
            if scan and scan.schedule_id:
                if record_outcome(db, scan):
                    paused_schedule = scan.schedule_id
                db.commit()
    except Exception:
        log.exception("could not record schedule outcome for scan %s", scan_id)
    if paused_schedule:
        from .notifications import notify_schedule_paused

        notify_schedule_paused(paused_schedule)


def scheduler_status(db: Session) -> dict:
    settings = get_settings()
    row = db.get(RuntimeState, HEARTBEAT_KEY)
    last = datetime.fromisoformat(row.value["last_tick_at"]) if row and row.value.get("last_tick_at") else None
    stale_after = max(3 * settings.scheduler_tick_seconds, 180)
    healthy = bool(last and (utcnow() - last).total_seconds() <= stale_after)
    return {
        "healthy": healthy,
        "last_tick_at": last.isoformat() if last else None,
        "runner": row.value.get("runner") if row else None,
        "tick_seconds": settings.scheduler_tick_seconds,
        "in_this_process": settings.scheduler_enabled,
        "max_concurrent_scans": settings.scheduler_max_concurrent_scans,
        "message": None if healthy else (
            "No scheduler heartbeat yet." if not last else
            "The scheduler has not run recently. Start it (API with SCAMSHIELD_SCHEDULER_ENABLED=true, or `python -m app.worker`)."
        ),
    }


async def scheduler_loop(tick_seconds: int, runner: str | None = None) -> None:
    while True:
        try:
            for scan_id in await asyncio.to_thread(schedule_tick, None, runner):
                scanner.launch(scan_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(tick_seconds)
