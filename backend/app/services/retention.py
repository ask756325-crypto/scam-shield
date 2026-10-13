"""Data retention: remove old scan history for one organization, never findings or the review audit trail.

Deleted (finished scans older than the retention window):
    scans, per-source results, observations, per-scan change records, official-asset exclusion log rows.
Kept:
    brands, findings with their latest evidence, analyst decisions (audit trail), connectivity tests, schedules.
The most recent finished scan of every brand is always kept, so current state can still be explained.
Queued/running scans are never touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..models import Brand, Exclusion, Finding, FindingChange, Observation, Organization, Scan, ScanSource
from .org_settings import monitoring_settings


def _expired_scan_ids(db: Session, org_id: int, days: int, now: datetime) -> list[int]:
    cutoff = now - timedelta(days=days)
    brand_ids = select(Brand.id).where(Brand.organization_id == org_id)
    newest = select(func.max(Scan.id)).where(Scan.brand_id.in_(brand_ids), Scan.status.in_(["completed", "partial", "failed"])).group_by(Scan.brand_id)
    return list(db.scalars(
        select(Scan.id).where(
            Scan.brand_id.in_(brand_ids), Scan.status.in_(["completed", "partial", "failed"]),
            Scan.created_at < cutoff, Scan.id.not_in(newest),
        )
    ))


def preview(db: Session, org: Organization, days: int | None = None, now: datetime | None = None) -> dict:
    days = days if days is not None else monitoring_settings(org)["scan_history_days"]
    if not days:
        return {"days": None, "scans": 0, "observations": 0, "changes": 0, "exclusions": 0}
    ids = _expired_scan_ids(db, org.id, days, now or datetime.now(timezone.utc))
    if not ids:
        return {"days": days, "scans": 0, "observations": 0, "changes": 0, "exclusions": 0}
    count = lambda model: db.scalar(select(func.count()).select_from(model).where(model.scan_id.in_(ids))) or 0  # noqa: E731
    return {"days": days, "scans": len(ids), "observations": count(Observation), "changes": count(FindingChange), "exclusions": count(Exclusion)}


def purge(db: Session, org: Organization, now: datetime | None = None) -> dict:
    days = monitoring_settings(org)["scan_history_days"]
    summary = preview(db, org, days, now)
    if not days or not summary["scans"]:
        return summary
    ids = _expired_scan_ids(db, org.id, days, now or datetime.now(timezone.utc))
    for model in (Observation, FindingChange, Exclusion, ScanSource):
        db.execute(delete(model).where(model.scan_id.in_(ids)))
    # Findings keep existing; only their links to deleted scans are cleared.
    db.execute(update(Finding).where(Finding.first_seen_scan_id.in_(ids)).values(first_seen_scan_id=None))
    db.execute(update(Finding).where(Finding.last_seen_scan_id.in_(ids)).values(last_seen_scan_id=None))
    db.execute(delete(Scan).where(Scan.id.in_(ids)))
    db.commit()
    return summary


def apply_all(db: Session, now: datetime | None = None) -> int:
    """Apply every organization's retention policy (called by the scheduler at most once a day)."""
    total = 0
    for org in db.scalars(select(Organization)).all():
        if monitoring_settings(org)["scan_history_days"]:
            total += purge(db, org, now)["scans"]
    return total
