"""Overview dashboard.

Two kinds of numbers, labelled as such in the UI:
* Current state (not date-filtered): open findings needing review, high-risk open findings, official assets
  excluded, source availability, review queue.
* Period activity (filtered by `days`): candidates scanned, scans, findings observed per severity/platform,
  scan history and per-scan series.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import Principal, get_brand_for, get_principal
from ..models import REVIEW_STATUSES, Brand, Candidate, Exclusion, Finding, Scan
from ..serializers import finding_out, iso, scan_out
from ..services.health import source_health
from .findings import LEVEL_RANK

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

LEVELS = ("critical", "high", "medium", "low")
ALLOWED_DAYS = {1, 7, 30, 90}


@router.get("")
def dashboard(brand_id: int | None = None, days: int | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if days is not None and days not in ALLOWED_DAYS:
        raise HTTPException(422, f"days must be one of {sorted(ALLOWED_DAYS)} or omitted for all time")
    if brand_id is not None:
        brand = get_brand_for(db, p, brand_id)
        brand_ids, is_demo = [brand_id], brand.is_demo
    else:
        brands = db.scalars(select(Brand).where(Brand.organization_id == p.org.id)).all()
        brand_ids, is_demo = [b.id for b in brands], any(b.is_demo for b in brands)
    if not brand_ids:
        return {"empty": True, "brands": 0}
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days) if days else None

    # ---------------------------------------------------------------- period activity
    scan_q = select(Scan).where(Scan.brand_id.in_(brand_ids))
    if since:
        scan_q = scan_q.where(Scan.created_at >= since)
    period_scans = db.scalars(scan_q).all()
    candidates_scanned = sum(s.candidates_unique for s in period_scans)
    scans_in_period = len(period_scans)

    platform = Candidate.extra["platform"].as_string()
    grid_q = (
        select(platform, Candidate.source, Finding.risk_level, func.count())
        .join(Finding, Finding.candidate_id == Candidate.id)
        .where(Finding.brand_id.in_(brand_ids), Finding.status.in_(REVIEW_STATUSES), Finding.risk_level.in_(LEVELS))
    )
    if since:
        grid_q = grid_q.where(Candidate.last_observed_at >= since)
    grid: dict[str, dict[str, int]] = {}
    for pl, src, lvl, n in db.execute(grid_q.group_by(platform, Candidate.source, Finding.risk_level)).all():
        key = {"apple": "apple_app_store"}.get(pl or src, pl or src)
        row = grid.setdefault(key, {l: 0 for l in LEVELS})
        row[lvl] += n
    severity_by_platform = [{"platform": k, **v, "total": sum(v.values())} for k, v in sorted(grid.items(), key=lambda kv: -sum(kv[1].values()))]
    severity_period = {l: sum(r[l] for r in severity_by_platform) for l in LEVELS}

    recent_scans_q = select(Scan, Brand.name).join(Brand).where(Scan.brand_id.in_(brand_ids))
    if since:
        recent_scans_q = recent_scans_q.where(Scan.created_at >= since)
    recent_scans = db.execute(recent_scans_q.order_by(Scan.id.desc()).limit(8)).all()
    series_q = select(Scan).where(Scan.brand_id.in_(brand_ids), Scan.status.in_(["completed", "partial"]))
    if since:
        series_q = series_q.where(Scan.created_at >= since)
    series_scans = db.scalars(series_q.order_by(Scan.id.desc()).limit(14)).all()

    # ---------------------------------------------------------------- current state
    by_level = dict(
        db.execute(
            select(Finding.risk_level, func.count()).where(Finding.brand_id.in_(brand_ids), Finding.status.in_(REVIEW_STATUSES)).group_by(Finding.risk_level)
        ).all()
    )
    by_status = dict(db.execute(select(Finding.status, func.count()).where(Finding.brand_id.in_(brand_ids)).group_by(Finding.status)).all())
    excluded_assets = db.scalar(
        select(func.count()).select_from(select(Exclusion.source, Exclusion.external_id).where(Exclusion.brand_id.in_(brand_ids)).distinct().subquery())
    ) or 0
    review_levels = ("critical", "high", "medium")
    oldest_open = db.scalar(
        select(func.min(Finding.created_at)).where(Finding.brand_id.in_(brand_ids), Finding.status.in_(REVIEW_STATUSES), Finding.risk_level.in_(review_levels))
    )
    top_review = db.execute(
        select(Finding, Brand.name)
        .join(Brand, Finding.brand_id == Brand.id)
        .where(Finding.brand_id.in_(brand_ids), Finding.status.in_(REVIEW_STATUSES), Finding.risk_level.in_(review_levels))
        .options(selectinload(Finding.candidate))
        .order_by(LEVEL_RANK.asc(), Finding.risk_score.desc())
        .limit(4)
    ).all()
    new_since_last = db.scalar(
        select(func.count()).select_from(Finding).where(
            Finding.brand_id.in_(brand_ids), Finding.status.in_(REVIEW_STATUSES), Finding.change_state.in_(["new", "changed"]), Finding.risk_level.in_(review_levels)
        )
    ) or 0

    health = source_health(db, p.org, brand_ids, include_demo=is_demo)
    # A demo-only brand never uses live sources; don't report those as unavailable for it.
    relevant_health = [h for h in health if h["name"] == "demo"] if (brand_id is not None and is_demo) else [h for h in health if h["name"] != "demo"]
    unavailable = [h for h in relevant_health if h["unavailable"]]
    degraded = [h for h in relevant_health if h["enabled"] and h["health"] == "degraded"]

    last_scan = db.scalar(select(Scan).where(Scan.brand_id.in_(brand_ids)).order_by(Scan.id.desc()).limit(1))
    last_completed = db.scalar(
        select(Scan).where(Scan.brand_id.in_(brand_ids), Scan.status.in_(["completed", "partial"])).order_by(Scan.id.desc()).limit(1)
    )
    scans_total = db.scalar(select(func.count()).select_from(Scan).where(Scan.brand_id.in_(brand_ids))) or 0

    return {
        "empty": False,
        "brands": len(brand_ids),
        "period": {"days": days, "since": iso(since)},
        "metrics": {
            # period
            "candidates_scanned": candidates_scanned,
            "scans_in_period": scans_in_period,
            # current
            "scans_total": scans_total,
            "candidates_last_scan": last_completed.candidates_unique if last_completed else 0,
            "review_required": sum(by_level.get(l, 0) for l in review_levels),
            "high_risk_open": by_level.get("critical", 0) + by_level.get("high", 0),
            "critical_open": by_level.get("critical", 0),
            "official_excluded": excluded_assets,
            "sources_enabled": sum(1 for h in relevant_health if h["enabled"]),
            "sources_unavailable": len(unavailable),
            "sources_degraded": len(degraded),
            "confirmed": by_status.get("confirmed", 0),
            "marked_safe": by_status.get("safe", 0),
        },
        "severity": {l: by_level.get(l, 0) for l in LEVELS},
        "severity_period": severity_period,
        "severity_by_platform": severity_by_platform,
        "review": {
            "open_by_level": {l: by_level.get(l, 0) for l in review_levels},
            "oldest_open_at": iso(oldest_open),
            "new_or_changed": new_since_last,
            "top": [finding_out(f, n) for f, n in top_review],
        },
        "source_health": relevant_health,
        "unavailable_sources": [h["label"] for h in unavailable],
        "recent_scans": [scan_out(s, n) for s, n in recent_scans],
        "scan_series": [
            {"scan_id": s.id, "at": iso(s.finished_at or s.created_at), "candidates": s.candidates_unique, "new": s.findings_new,
             "changed": s.findings_changed, "resolved": s.findings_resolved, "excluded": s.excluded_official, "mode": s.mode,
             "status": s.status}
            for s in reversed(series_scans)
        ],
        "last_scan": scan_out(last_scan) if last_scan else None,
        "last_completed_scan": scan_out(last_completed) if last_completed else None,
    }
