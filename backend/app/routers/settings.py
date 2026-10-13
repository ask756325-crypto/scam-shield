from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import audit as audit_log
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
    before = org.name
    org.name = body.name.strip()
    audit_log.record(db, p, "organization.renamed", "organization", org.id, f"Renamed “{before}” → “{org.name}”")
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
    audit_log.record(db, p, "detection.updated", "organization", org.id, "Detection weights/thresholds changed", {"overrides": org.detection_config})
    db.commit()
    return {"effective": merge_config(org.detection_config), "defaults": DEFAULT_CONFIG, "overrides": org.detection_config}


@router.delete("/detection")
def reset_detection(p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    org = db.get(Organization, p.org.id)
    org.detection_config = {}
    audit_log.record(db, p, "detection.reset", "organization", org.id, "Detection settings reset to defaults")
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
    audit_log.record(db, p, "monitoring.updated", "organization", org.id, "Monitoring settings changed", {"changed": clean})
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
    deleted = retention.purge(db, db.get(Organization, p.org.id))
    audit_log.record(db, p, "data.purged", "organization", p.org.id, f"Deleted {deleted['scans']} scan(s) older than {deleted['days']} days", deleted)
    db.commit()
    return {"deleted": deleted}


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
    audit_log.record(db, p, "data.exported", "decisions", None, f"Exported review audit trail ({len(rows)} decisions)")
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="scamshield-review-audit-{stamp}.csv"'})


# ---------------------------------------------------------------- organization audit log


def _audit_query(p: Principal, action: str | None, actor: str | None):
    from ..models import AuditEvent

    q = select(AuditEvent).where(AuditEvent.organization_id == p.org.id)
    if action:
        q = q.where(AuditEvent.action.startswith(action))
    if actor:
        q = q.where(AuditEvent.actor_email == actor.lower())
    return q.order_by(AuditEvent.id.desc())


def _audit_out(e) -> dict:
    return {"id": e.id, "action": e.action, "actor": e.actor_email, "target_type": e.target_type, "target_id": e.target_id,
            "summary": e.summary, "details": e.details or {}, "ip": e.ip, "created_at": iso(e.created_at)}


@router.get("/audit")
def audit_events(action: str | None = None, actor: str | None = None, limit: int = 100, offset: int = 0,
                 p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """Who changed what in this organization. Owners only."""
    from sqlalchemy import func

    q = _audit_query(p, action, actor)
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = db.scalars(q.limit(min(max(limit, 1), 500)).offset(max(offset, 0))).all()
    return {"total": total, "items": [_audit_out(e) for e in rows]}


@router.get("/audit.csv")
def audit_csv(action: str | None = None, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    import csv
    import io
    import json
    from datetime import datetime, timezone

    from ..routers.findings import _safe_cell

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "created_at", "actor", "ip", "action", "target_type", "target_id", "summary", "details"])
    for e in db.scalars(_audit_query(p, action, None).limit(20000)).all():
        w.writerow([_safe_cell(x) for x in [e.id, iso(e.created_at), e.actor_email, e.ip, e.action, e.target_type, e.target_id, e.summary,
                                            json.dumps(e.details or {}, ensure_ascii=False)]])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="scamshield-audit-log-{stamp}.csv"'})
