from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_brand_for, get_principal, get_scan_for
from ..models import Brand, Candidate, Finding, FindingChange, Scan, ScanSource
from ..schemas import ScanIn
from ..serializers import candidate_out, scan_out
from ..services import scanner

router = APIRouter(prefix="/api", tags=["scans"])


@router.post("/brands/{brand_id}/scans", status_code=202)
async def start_scan(brand_id: int, body: ScanIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    brand = get_brand_for(db, p, brand_id)
    running = scanner.active_scan(db, brand.id)
    if running:
        raise HTTPException(409, {"message": "A scan is already running for this brand", "scan_id": running.id})
    try:
        sources = scanner.resolve_sources(brand, p.org, body.sources)
        scan = scanner.create_scan(db, brand, sources, "manual", p.user.id)
    except scanner.ScanConflict as e:
        raise HTTPException(409, {"message": "A scan is already running for this brand", "scan_id": e.scan_id})
    except ValueError as e:
        raise HTTPException(400, str(e))
    scanner.launch(scan.id)
    return scan_out(scan, brand.name)


SCAN_STATUSES = ("queued", "running", "completed", "partial", "failed")
TRIGGERS = ("manual", "scheduled", "import")


@router.get("/scans")
def list_scans(
    response: Response,
    brand_id: int | None = None,
    trigger: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    source: str | None = None,
    has_failures: bool | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Scan history, newest first. The total matching count is returned in the X-Total-Count header."""
    q = select(Scan, Brand.name).join(Brand).where(Brand.organization_id == p.org.id)
    if brand_id is not None:
        q = q.where(Scan.brand_id == brand_id)
    if trigger:
        bad = set(trigger) - set(TRIGGERS)
        if bad:
            raise HTTPException(422, f"Unknown trigger: {', '.join(sorted(bad))}")
        q = q.where(Scan.trigger.in_(trigger))
    if status:
        bad = set(status) - set(SCAN_STATUSES)
        if bad:
            raise HTTPException(422, f"Unknown status: {', '.join(sorted(bad))}")
        q = q.where(Scan.status.in_(status))
    if source:
        q = q.where(Scan.id.in_(select(ScanSource.scan_id).where(ScanSource.source == source)))
    if has_failures is not None:
        failing = select(ScanSource.scan_id).where(ScanSource.status.in_(["failed", "partial"]))
        q = q.where(Scan.id.in_(failing) if has_failures else Scan.id.not_in(failing))
    if since:
        q = q.where(Scan.created_at >= since)
    if until:
        q = q.where(Scan.created_at <= until)
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(q.subquery())))
    rows = db.execute(q.order_by(Scan.id.desc()).limit(min(max(limit, 1), 200)).offset(max(offset, 0))).all()
    return [scan_out(s, name) for s, name in rows]


@router.get("/scans/export.csv")
def export_scans(brand_id: int | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Scan history for the caller's organization (optionally one brand)."""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    from .findings import _safe_cell

    q = select(Scan, Brand.name).join(Brand).where(Brand.organization_id == p.org.id)
    if brand_id is not None:
        q = q.where(Scan.brand_id == brand_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["scan_id", "brand", "trigger", "mode", "status", "started_at", "finished_at", "sources", "failed_sources", "candidates_unique",
                "official_excluded", "findings_new", "findings_changed", "findings_recurring", "findings_missing", "findings_resolved",
                "findings_unverified", "error"])
    for s, name in db.execute(q.order_by(Scan.id.desc()).limit(10000)).all():
        w.writerow([_safe_cell(x) for x in [
            s.id, name, s.trigger, s.mode, s.status, s.started_at.isoformat() if s.started_at else "", s.finished_at.isoformat() if s.finished_at else "",
            " ".join(x.source for x in s.sources), " ".join(x.source for x in s.sources if x.status in ("failed", "partial")), s.candidates_unique,
            s.excluded_official, s.findings_new, s.findings_changed, s.findings_recurring, s.findings_missing or 0, s.findings_resolved,
            s.findings_unverified or 0, s.error or "",
        ]])
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="scamshield-scans-{stamp}.csv"'})


@router.get("/scans/{scan_id}")
def get_scan(scan_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    s = get_scan_for(db, p, scan_id)
    db.refresh(s)
    return scan_out(s, s.brand.name)


CHANGE_KINDS = ("new", "changed", "recurring", "reappeared", "missing", "resolved", "unverified")


@router.get("/scans/{scan_id}/changes")
def scan_changes(scan_id: int, change: list[str] | None = Query(None), limit: int = 200, offset: int = 0,
                 p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """What this scan concluded about each finding, with field-level diffs for changed metadata."""
    scan = get_scan_for(db, p, scan_id)
    q = (select(FindingChange, Finding, Candidate).join(Finding, FindingChange.finding_id == Finding.id)
         .join(Candidate, Finding.candidate_id == Candidate.id).where(FindingChange.scan_id == scan.id))
    if change:
        bad = set(change) - set(CHANGE_KINDS)
        if bad:
            raise HTTPException(422, f"Unknown change: {', '.join(sorted(bad))}")
        q = q.where(FindingChange.change.in_(change))
    counts = dict(db.execute(select(FindingChange.change, func.count()).where(FindingChange.scan_id == scan.id).group_by(FindingChange.change)).all())
    rows = db.execute(q.order_by(FindingChange.id).limit(min(max(limit, 1), 500)).offset(max(offset, 0))).all()
    items = []
    for ch, f, c in rows:
        cand = candidate_out(c)
        items.append({
            "change": ch.change, "changed_fields": ch.changed_fields or [], "previous": ch.previous or {}, "current": ch.current or {},
            "risk_before": ch.risk_before, "risk_after": ch.risk_after, "missed_scans": ch.missed_scans,
            "finding": {"id": f.id, "status": f.status, "risk_level": f.risk_level, "risk_score": f.risk_score, "change_state": f.change_state,
                        "classification": f.classification},
            "candidate": {k: cand[k] for k in ("name", "handle", "platform", "kind", "source", "source_type", "avatar_url", "external_id")},
        })
    return {"counts": {k: counts.get(k, 0) for k in CHANGE_KINDS}, "items": items}
