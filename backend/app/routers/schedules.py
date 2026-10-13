"""Monitoring schedules: configure, pause, resume, disable; scheduler health."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_brand_for, get_principal
from ..models import Brand, MonitoringSchedule
from ..schemas import ScheduleIn
from ..serializers import schedule_out
from ..services import registry
from ..services.schedule_calc import ScheduleError, ScheduleSpec, upcoming, validate
from ..services.scheduler import planned_next, scheduler_status, spec_of

router = APIRouter(prefix="/api", tags=["schedules"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _out(s: MonitoringSchedule) -> dict:
    preview = upcoming(spec_of(s), _now(), 3, s.next_run_at if s.frequency == "interval" else None) if s.state == "active" else []
    if s.state == "active" and s.next_run_at and preview and preview[0] != s.next_run_at:
        preview = [s.next_run_at, *upcoming(spec_of(s), s.next_run_at, 2, s.next_run_at)]
    return schedule_out(s, preview)


def _validate_sources(brand: Brand, p: Principal, sources: list[str] | None) -> list[str] | None:
    if not sources:
        return None
    enabled = set(registry.source_config(p.org)["enabled_sources"]) | ({"demo"} if brand.is_demo else set())
    bad = [x for x in sources if x not in enabled]
    if bad:
        raise HTTPException(422, {"field": "sources", "message": f"Not enabled for this organization: {', '.join(bad)}"})
    return list(dict.fromkeys(sources))


@router.get("/brands/{brand_id}/schedule")
def get_schedule(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    brand = get_brand_for(db, p, brand_id)
    return {"configured": brand.schedule is not None, "schedule": _out(brand.schedule) if brand.schedule else None}


@router.put("/brands/{brand_id}/schedule")
def put_schedule(brand_id: int, body: ScheduleIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Create or replace the schedule. Saving (re)activates it and computes the next run from now."""
    brand = get_brand_for(db, p, brand_id)
    try:
        spec = validate(ScheduleSpec(body.frequency, body.interval_hours, body.time_of_day, list(body.weekdays), body.timezone))
    except ScheduleError as e:
        raise HTTPException(422, {"field": e.field, "message": str(e)})
    sources = _validate_sources(brand, p, body.sources)
    s = brand.schedule or MonitoringSchedule(brand_id=brand.id)
    s.frequency, s.interval_hours, s.time_of_day = spec.frequency, int(spec.interval_hours), spec.time_of_day
    s.weekdays, s.timezone, s.sources = spec.weekdays if spec.frequency == "weekly" else [], spec.timezone, sources
    s.state, s.paused_reason, s.consecutive_failures = "active", None, 0
    s.next_run_at = None
    s.next_run_at = planned_next(s, _now())
    s.version = (s.version or 0) + 1
    s.updated_by_id = p.user.id
    if brand.schedule is None:
        db.add(s)
    db.commit()
    db.refresh(s)
    return _out(s)


def _transition(brand_id: int, p: Principal, db: Session, target: str) -> dict:
    brand = get_brand_for(db, p, brand_id)
    s = brand.schedule
    if s is None:
        raise HTTPException(404, "This brand has no monitoring schedule")
    if s.state == target:
        raise HTTPException(409, f"Schedule is already {target}")
    if target == "active":
        # Resume from now: missed runs while paused are skipped, not replayed.
        s.next_run_at = None
        s.next_run_at = planned_next(s, _now())
        s.consecutive_failures, s.paused_reason = 0, None
    else:
        s.paused_reason = "Paused by an analyst" if target == "paused" else "Disabled by an analyst"
    s.state = target
    s.version += 1
    s.updated_by_id = p.user.id
    db.commit()
    db.refresh(s)
    return _out(s)


@router.post("/brands/{brand_id}/schedule/pause")
def pause(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _transition(brand_id, p, db, "paused")


@router.post("/brands/{brand_id}/schedule/resume")
def resume(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _transition(brand_id, p, db, "active")


@router.post("/brands/{brand_id}/schedule/disable")
def disable(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _transition(brand_id, p, db, "disabled")


@router.get("/schedules")
def list_schedules(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.execute(
        select(MonitoringSchedule, Brand.name).join(Brand).where(Brand.organization_id == p.org.id).order_by(Brand.name)
    ).all()
    return {"scheduler": scheduler_status(db), "items": [{**_out(s), "brand_name": name} for s, name in rows]}


@router.get("/scheduler/status")
def status(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return scheduler_status(db)
