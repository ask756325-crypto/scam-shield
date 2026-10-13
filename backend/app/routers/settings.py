from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_principal, require_owner
from ..detection.scoring import DEFAULT_CONFIG, merge_config
from ..models import Membership, Organization
from ..schemas import DetectionConfigIn, MonitoringConfigIn, OrgIn, PurgeIn
from ..serializers import iso

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/organization")
def get_org(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    members = db.execute(select(Membership).where(Membership.organization_id == p.org.id)).scalars().all()
    return {
        "id": p.org.id,
        "name": p.org.name,
        "role": p.role,
        "created_at": iso(p.org.created_at),
        "members": [{"user_id": m.user_id, "name": m.user.name, "email": m.user.email, "role": m.role, "joined_at": iso(m.created_at)} for m in members],
    }


@router.patch("/organization")
def update_org(body: OrgIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    org = db.get(Organization, p.org.id)
    org.name = body.name.strip()
    db.commit()
    return {"id": org.id, "name": org.name}


@router.get("/detection")
def get_detection(p: Principal = Depends(get_principal)):
    return {"effective": merge_config(p.org.detection_config), "defaults": DEFAULT_CONFIG, "overrides": p.org.detection_config or {}}


@router.put("/detection")
def put_detection(body: DetectionConfigIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    org = db.get(Organization, p.org.id)
    effective = merge_config(body.overrides)  # validates & drops unknown keys
    # Store only values that differ from defaults.
    overrides: dict = {"groups": {}, "relevance": {}, "levels": {}}
    for g, vals in effective["groups"].items():
        diff = {k: vals[k] for k in ("weight", "threshold") if vals[k] != DEFAULT_CONFIG["groups"][g][k]}
        if diff:
            overrides["groups"][g] = diff
    for k, v in effective["relevance"].items():
        if v != DEFAULT_CONFIG["relevance"][k]:
            overrides["relevance"][k] = v
    for lvl, vals in effective["levels"].items():
        diff = {k: vals[k] for k in ("min_score", "min_corroboration") if vals[k] != DEFAULT_CONFIG["levels"][lvl][k]}
        if diff:
            overrides["levels"][lvl] = diff
    org.detection_config = {k: v for k, v in overrides.items() if v}
    db.commit()
    return {"effective": merge_config(org.detection_config), "defaults": DEFAULT_CONFIG, "overrides": org.detection_config}


@router.delete("/detection")
def reset_detection(p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    org = db.get(Organization, p.org.id)
    org.detection_config = {}
    db.commit()
    return {"effective": merge_config({}), "defaults": DEFAULT_CONFIG, "overrides": {}}


# ---------------------------------------------------------------- monitoring


def _monitoring_out(org: Organization) -> dict:
    from ..services.org_settings import LIMITS, RETENTION_CHOICES, defaults, monitoring_settings

    return {
        "values": monitoring_settings(org),
        "defaults": defaults(),
        "limits": {k: {"min": lo, "max": hi, "description": d} for k, (lo, hi, d) in LIMITS.items()},
        "retention_choices": list(RETENTION_CHOICES),
    }


@router.get("/monitoring")
def get_monitoring(p: Principal = Depends(get_principal)):
    return _monitoring_out(p.org)


@router.put("/monitoring")
def put_monitoring(body: MonitoringConfigIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    from ..services.org_settings import validate

    clean, errors = validate(body.model_dump())
    if errors:
        field, msg = next(iter(errors.items()))
        raise HTTPException(422, {"field": field, "message": msg, "errors": errors})
    org = db.get(Organization, p.org.id)
    org.monitoring_config = {**(org.monitoring_config or {}), **clean}
    db.commit()
    return _monitoring_out(org)


# ---------------------------------------------------------------- data management


@router.get("/data")
def data_summary(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from sqlalchemy import func

    from ..models import Brand, Decision, Finding, Scan, SourceCheck
    from ..services import retention

    brand_ids = select(Brand.id).where(Brand.organization_id == p.org.id)
    count = lambda q: db.scalar(select(func.count()).select_from(q.subquery())) or 0  # noqa: E731
    return {
        "counts": {
            "brands": count(select(Brand.id).where(Brand.organization_id == p.org.id)),
            "findings": count(select(Finding.id).where(Finding.brand_id.in_(brand_ids))),
            "decisions": count(select(Decision.id).join(Finding).where(Finding.brand_id.in_(brand_ids))),
            "scans": count(select(Scan.id).where(Scan.brand_id.in_(brand_ids))),
            "connectivity_tests": count(select(SourceCheck.id).where(SourceCheck.organization_id == p.org.id)),
        },
        "retention": retention.preview(db, p.org),
    }


@router.post("/data/purge")
def purge_now(body: PurgeIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """Apply the saved retention policy now. Requires the typed confirmation "DELETE"."""
    from ..services import retention
    from ..services.org_settings import monitoring_settings

    if not monitoring_settings(p.org)["scan_history_days"]:
        raise HTTPException(400, "No retention period is set — scan history is kept forever.")
    if body.confirm != "DELETE":
        raise HTTPException(422, {"field": "confirm", "message": "Type DELETE to confirm"})
    return {"deleted": retention.purge(db, db.get(Organization, p.org.id))}


@router.get("/data/decisions.csv")
def export_decisions(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Review audit trail for the caller's organization only."""
    import csv
    import io
    from datetime import datetime, timezone

    from ..models import Brand, Candidate, Decision, Finding, User
    from ..routers.findings import _safe_cell

    rows = db.execute(
        select(Decision, Finding, Brand.name, Candidate.name, User.email)
        .join(Finding, Decision.finding_id == Finding.id).join(Brand, Finding.brand_id == Brand.id)
        .join(Candidate, Finding.candidate_id == Candidate.id).outerjoin(User, Decision.user_id == User.id)
        .where(Brand.organization_id == p.org.id).order_by(Decision.id)
    ).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["decision_id", "created_at", "brand", "finding_id", "candidate", "action", "from_status", "to_status", "analyst", "note"])
    for d, f, bname, cname, email in rows:
        w.writerow([_safe_cell(x) for x in [d.id, d.created_at.isoformat(), bname, f.id, cname, d.action, d.from_status, d.to_status,
                                            email or "System", d.note]])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="scamshield-review-audit-{stamp}.csv"'})
