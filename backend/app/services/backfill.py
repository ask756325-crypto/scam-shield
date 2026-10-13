"""One-off data backfills run at startup (idempotent)."""
from __future__ import annotations

import logging

from sqlalchemy import select

from ..db import SessionLocal
from ..detection.scoring import detection_type
from ..detection.signals import Signal
from ..models import Brand, Candidate, Finding, MonitoringSchedule

log = logging.getLogger("scamshield.backfill")


def backfill_detection_types() -> int:
    """Findings created before detection types existed: derive the type from their stored signals."""
    with SessionLocal() as db:
        rows = db.execute(select(Finding, Candidate.kind).join(Candidate, Finding.candidate_id == Candidate.id).where(Finding.detection_type.is_(None))).all()
        for f, kind in rows:
            stored = (f.signals or {}).get("signals", {})
            by_name = {
                n: Signal(name=n, evaluated=bool(s.get("evaluated")), score=float(s.get("score") or 0), data=s.get("data") or {})
                for n, s in stored.items()
            }
            same_pub = bool(by_name.get("publisher") and by_name["publisher"].data.get("same_official_publisher"))
            f.detection_type = detection_type(kind, f.risk_level != "info", by_name, list(f.corroborating_groups or []), same_pub)
        db.commit()
        if rows:
            log.info("Backfilled detection_type for %d finding(s)", len(rows))
        return len(rows)


def migrate_legacy_schedules() -> int:
    """Brands scheduled with the old per-brand interval fields get an equivalent interval schedule (once)."""
    from datetime import datetime, timedelta, timezone

    with SessionLocal() as db:
        brands = db.scalars(select(Brand).where(Brand.schedule_enabled.is_(True))).all()
        n = 0
        for b in brands:
            if b.schedule is None:
                interval = max(1, b.schedule_interval_hours or 24)
                db.add(MonitoringSchedule(
                    brand_id=b.id, state="active", frequency="interval", interval_hours=interval, timezone="UTC",
                    next_run_at=b.next_scheduled_at or datetime.now(timezone.utc) + timedelta(hours=interval),
                ))
                n += 1
            b.schedule_enabled = False  # legacy fields are no longer read
        db.commit()
        if n:
            log.info("Migrated %d legacy schedule(s)", n)
        return n


def migrate_legacy_source_tests() -> int:
    """Connection tests stored in organizations.source_config["last_tests"] become SourceCheck rows (once)."""
    from datetime import datetime

    from ..models import Organization, SourceCheck

    with SessionLocal() as db:
        n = 0
        for org in db.scalars(select(Organization)).all():
            cfg = dict(org.source_config or {})
            tests = cfg.pop("last_tests", None)
            if not tests:
                continue
            for source, t in tests.items():
                try:
                    at = datetime.fromisoformat(t["at"])
                except (KeyError, ValueError):
                    continue
                outcome = t.get("outcome") or {"ok": "ok", "empty": "empty", "rate_limited": "rate_limited"}.get(t.get("status"), "error")
                db.add(SourceCheck(organization_id=org.id, source=source, outcome=outcome, detail=t.get("detail", ""),
                                   latency_ms=t.get("latency_ms"), created_at=at))
                n += 1
            org.source_config = cfg
        db.commit()
        if n:
            log.info("Migrated %d legacy connection test result(s)", n)
        return n
