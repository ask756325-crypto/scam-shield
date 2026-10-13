from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..services import audit as audit_log
from ..deps import Principal, get_finding_for, get_principal
from ..models import Brand, Candidate, Decision, Finding
from ..schemas import DecisionIn
from ..serializers import finding_out
from ..services import evidence

router = APIRouter(prefix="/api/findings", tags=["findings"])

LEVEL_RANK = case(
    (Finding.risk_level == "critical", 0), (Finding.risk_level == "high", 1), (Finding.risk_level == "medium", 2),
    (Finding.risk_level == "low", 3), else_=4,
)
SORTS = {
    "risk": Finding.risk_score,
    "level": LEVEL_RANK,
    "updated": Finding.updated_at,
    "first_seen": Candidate.first_observed_at,
    "last_seen": Candidate.last_observed_at,
    "name": Candidate.name,
}


def _query(p: Principal, brand_id, level, status, source, kind, change_state, source_type, q, since_days=None, detection_type=None, assignee=None):
    stmt = (
        select(Finding, Brand.name)
        .join(Brand, Finding.brand_id == Brand.id)
        .join(Candidate, Finding.candidate_id == Candidate.id)
        .where(Brand.organization_id == p.org.id)
    )
    if brand_id:
        stmt = stmt.where(Finding.brand_id == brand_id)
    if level:
        stmt = stmt.where(Finding.risk_level.in_(level))
    if status:
        stmt = stmt.where(Finding.status.in_(status))
    if change_state:
        stmt = stmt.where(Finding.change_state.in_(change_state))
    if kind:
        stmt = stmt.where(Candidate.kind == kind)
    if source_type:
        stmt = stmt.where(Candidate.source_type == source_type)
    if source:
        # Matches either the collecting adapter or the platform (demo/imported records carry a platform).
        conds = [Candidate.source.in_(source)]
        for s in source:
            conds.append(Candidate.extra["platform"].as_string() == {"apple_app_store": "apple"}.get(s, s))
        stmt = stmt.where(or_(*conds))
    if detection_type:
        stmt = stmt.where(Finding.detection_type.in_(detection_type))
    if assignee:
        if assignee == "me":
            stmt = stmt.where(Finding.assignee_id == p.user.id)
        elif assignee == "unassigned":
            stmt = stmt.where(Finding.assignee_id.is_(None))
        elif assignee.isdigit():
            stmt = stmt.where(Finding.assignee_id == int(assignee))
        else:
            raise HTTPException(422, "assignee must be me, unassigned or a user id")
    if since_days:
        if since_days not in (1, 7, 30, 90):
            raise HTTPException(422, "since_days must be 1, 7, 30 or 90")
        stmt = stmt.where(Candidate.last_observed_at >= datetime.now(timezone.utc) - timedelta(days=since_days))
    if q:
        like = f"%{q.strip().lower()[:100]}%"
        stmt = stmt.where(or_(func.lower(Candidate.name).like(like), func.lower(Candidate.handle).like(like), func.lower(Candidate.external_id).like(like)))
    return stmt


@router.get("")
def list_findings(
    brand_id: int | None = None,
    level: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    source: list[str] | None = Query(None),
    change_state: list[str] | None = Query(None),
    kind: str | None = None,
    source_type: str | None = None,
    q: str | None = None,
    since_days: int | None = None,
    detection_type: list[str] | None = Query(None),
    assignee: str | None = None,
    include_signals: bool = False,
    sort: str = "risk",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    stmt = _query(p, brand_id, level, status, source, kind, change_state, source_type, q, since_days, detection_type, assignee)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    if sort in ("risk", "level"):
        # Severity level first (critical requires extra evidence, so raw score alone can mis-order), then score.
        cols = [LEVEL_RANK.desc(), Finding.risk_score.asc()] if order == "asc" else [LEVEL_RANK.asc(), Finding.risk_score.desc()]
    else:
        col = SORTS.get(sort, Finding.risk_score)
        cols = [col.asc() if order == "asc" else col.desc()]
    rows = db.execute(
        stmt.options(selectinload(Finding.candidate)).order_by(*cols, Finding.id.desc()).limit(min(max(limit, 1), 200)).offset(max(offset, 0))
    ).all()
    items = []
    for f, name in rows:
        out = finding_out(f, name)
        if include_signals:
            # Compact per-signal scores + top reasons for list views ("why flagged?") without N extra requests.
            sig = (f.signals or {}).get("signals", {})
            out["signal_scores"] = {k: {"score": v.get("score", 0), "evaluated": v.get("evaluated", False), "detail": v.get("detail", "")} for k, v in sig.items()}
            out["reasons"] = (f.reasons or [])[:4]
            out["not_evaluated"] = (f.signals or {}).get("not_evaluated", [])
        items.append(out)
    return {"total": total, "items": items}


def _safe_cell(v) -> str:
    """Neutralize spreadsheet formula injection."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/export.csv")
def export_csv(
    brand_id: int | None = None,
    level: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    source: list[str] | None = Query(None),
    change_state: list[str] | None = Query(None),
    kind: str | None = None,
    source_type: str | None = None,
    q: str | None = None,
    since_days: int | None = None,
    detection_type: list[str] | None = Query(None),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    stmt = _query(p, brand_id, level, status, source, kind, change_state, source_type, q, since_days, detection_type)
    rows = db.execute(stmt.options(selectinload(Finding.candidate)).order_by(LEVEL_RANK.asc(), Finding.risk_score.desc(), Finding.id).limit(10000)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "finding_id", "brand", "risk_level", "risk_score", "classification", "status", "change_state", "source", "platform",
        "source_type", "kind", "name", "handle", "publisher", "publisher_id", "url", "corroborating_evidence", "explanation",
        "first_observed_at", "last_observed_at",
    ])
    for f, bname in rows:
        c = f.candidate
        w.writerow([_safe_cell(x) for x in [
            f.id, bname, f.risk_level, f.risk_score, f.classification, f.status, f.change_state, c.source,
            (c.extra or {}).get("platform", c.source), c.source_type, c.kind, c.name, c.handle, c.publisher_name, c.publisher_id,
            c.url, "; ".join(f.corroborating_groups or []), f.explanation, c.first_observed_at.isoformat(), c.last_observed_at.isoformat(),
        ]])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    audit_log.record(db, p, "data.exported", "findings", None, f"Exported {len(rows)} finding(s) as CSV", {"brand_id": brand_id})
    db.commit()
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="scamshield-findings-{stamp}.csv"'},
    )


@router.get("/review-summary")
def review_summary(brand_id: int | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Outstanding reviews for the queue header (organization scope, optionally one brand)."""
    from ..models import REVIEW_STATUSES

    base = select(Finding).join(Brand, Finding.brand_id == Brand.id).where(Brand.organization_id == p.org.id)
    if brand_id:
        base = base.where(Finding.brand_id == brand_id)
    open_q = base.where(Finding.status.in_(REVIEW_STATUSES), Finding.risk_level.in_(["critical", "high", "medium", "low"])).subquery()
    by_level = dict(db.execute(select(open_q.c.risk_level, func.count()).group_by(open_q.c.risk_level)).all())
    by_status = dict(db.execute(select(open_q.c.status, func.count()).group_by(open_q.c.status)).all())
    oldest = db.scalar(select(func.min(open_q.c.created_at)))
    since = datetime.now(timezone.utc) - timedelta(days=7)
    decided = (select(func.count()).select_from(Decision).join(Finding).join(Brand, Finding.brand_id == Brand.id)
               .where(Brand.organization_id == p.org.id, Decision.created_at >= since, Decision.action != "note"))
    if brand_id:
        decided = decided.where(Finding.brand_id == brand_id)
    mine = decided.where(Decision.user_id == p.user.id)
    return {
        "open_by_level": {lvl: by_level.get(lvl, 0) for lvl in ("critical", "high", "medium", "low")},
        "open_total": sum(by_level.values()),
        "escalated": by_status.get("escalated", 0),
        "oldest_open_at": oldest.isoformat() if oldest else None,
        "decided_last_7_days": db.scalar(decided) or 0,
        "decided_by_me_last_7_days": db.scalar(mine) or 0,
    }


@router.get("/{finding_id}")
def get_finding(finding_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    f = get_finding_for(db, p, finding_id)
    from ..models import Observation, Scan

    history = db.execute(
        select(Observation, Scan).join(Scan, Observation.scan_id == Scan.id).where(Observation.candidate_id == f.candidate_id).order_by(Observation.id.desc()).limit(50)
    ).all()
    brand = db.get(Brand, f.brand_id)
    out = finding_out(f, brand.name, detail=True)
    out["observations"] = [
        {"scan_id": s.id, "observed_at": o.observed_at.isoformat(), "risk_score": o.risk_score, "content_hash": o.content_hash[:12], "trigger": s.trigger}
        for o, s in history
    ]
    out["evidence"] = evidence.build_evidence(db, f, brand)
    return out


@router.get("/{finding_id}/related")
def related(finding_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Observable indicators this candidate shares with other findings in the organization (no ownership inference)."""
    f = get_finding_for(db, p, finding_id)
    return {
        "groups": evidence.shared_indicators(db, p.org.id, f),
        "indicators": evidence.build_evidence(db, f, db.get(Brand, f.brand_id))["indicators"],
        "note": "Shared values are observations. They do not by themselves show common ownership or a coordinated campaign.",
    }


@router.get("/{finding_id}/report")
def report(finding_id: int, format: str = "html", p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    f = get_finding_for(db, p, finding_id)
    if format not in ("html", "json"):
        raise HTTPException(422, "format must be html or json")
    data = evidence.report_data(db, f, p.org.name, p.user.name)
    name = f"scamshield-evidence-finding-{f.id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"}
    audit_log.record(db, p, "data.exported", "finding", f.id, f"Evidence report ({format}) for “{f.candidate.name}”")
    db.commit()
    if format == "json":
        return JSONResponse(data, headers=headers)
    return HTMLResponse(evidence.report_html(data), headers=headers)


# action → resulting status; which current statuses each action may be applied to.
TRANSITIONS = {
    "confirm": ("confirmed", {"open", "escalated", "safe", "resolved"}),
    "mark_safe": ("safe", {"open", "escalated", "confirmed", "resolved"}),
    "escalate": ("escalated", {"open", "resolved"}),
    "reopen": ("open", {"confirmed", "safe", "escalated", "resolved"}),
}


def _member_user(db: Session, p: Principal, user_id: int):
    from ..models import Membership, User

    m = db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.organization_id == p.org.id))
    if not m:
        raise ValueError("Assignee is not a member of this organization")
    return db.get(User, user_id)


def apply_decision(db: Session, p: Principal, f: Finding, action: str, note: str, assignee_id: int | None = None) -> None:
    """One review action on one finding, with the same rules for single and bulk requests. Raises ValueError (409)."""
    note = note.strip()
    before = f.status
    after = before
    if action == "note":
        if not note:
            raise ValueError("A note cannot be empty")
    elif action == "assign":
        if assignee_id is None:
            f.assignee_id = None
            note = note or "Unassigned"
        else:
            user = _member_user(db, p, assignee_id)
            f.assignee_id = user.id
            note = note or f"Assigned to {user.name}"
    else:
        after, allowed = TRANSITIONS[action]
        if before not in allowed:
            raise ValueError(f"Cannot {action.replace('_', ' ')} a finding that is {evidence.STATUS_LABELS.get(before, before).lower()}")
        f.status = after
    f.decisions.append(Decision(user_id=p.user.id, action=action, note=note, from_status=before, to_status=after))
    f.updated_at = datetime.now(timezone.utc)


@router.post("/{finding_id}/decision")
def decide(finding_id: int, body: DecisionIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    f = get_finding_for(db, p, finding_id)
    if body.action == "assign":
        raise HTTPException(422, "Use PATCH /api/findings/{id}/assignee to assign")
    try:
        apply_decision(db, p, f, body.action, body.note)
    except ValueError as e:
        raise HTTPException(422 if "empty" in str(e) else 409, str(e))
    db.commit()
    db.refresh(f)
    return finding_out(f, db.get(Brand, f.brand_id).name, detail=True)


class AssigneeIn(BaseModel):
    user_id: int | None = None


@router.patch("/{finding_id}/assignee")
def assign(finding_id: int, body: AssigneeIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    f = get_finding_for(db, p, finding_id)
    try:
        apply_decision(db, p, f, "assign", "", body.user_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    db.refresh(f)
    return finding_out(f, db.get(Brand, f.brand_id).name, detail=True)


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    action: str
    note: str = Field(default="", max_length=2000)
    assignee_id: int | None = None


@router.post("/bulk")
def bulk(body: BulkIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Apply one action to many findings. Each finding is checked on its own; one invalid item never blocks the rest.
    Findings outside the caller's organization are reported as not found (their existence is not revealed)."""
    if body.action not in {"confirm", "mark_safe", "escalate", "reopen", "note", "assign"}:
        raise HTTPException(422, "Unknown action")
    if body.action == "note" and not body.note.strip():
        raise HTTPException(422, "A note cannot be empty")
    if body.action == "assign" and body.assignee_id is not None:
        try:
            _member_user(db, p, body.assignee_id)
        except ValueError as e:
            raise HTTPException(422, str(e))
    ids = list(dict.fromkeys(body.ids))
    found = {f.id: f for f in db.scalars(select(Finding).join(Brand, Finding.brand_id == Brand.id)
                                          .where(Finding.id.in_(ids), Brand.organization_id == p.org.id)).all()}
    results = []
    for fid in ids:
        f = found.get(fid)
        if f is None:
            results.append({"id": fid, "ok": False, "error": "Finding not found"})
            continue
        try:
            apply_decision(db, p, f, body.action, body.note, body.assignee_id)
            results.append({"id": fid, "ok": True, "status": f.status})
        except ValueError as e:
            results.append({"id": fid, "ok": False, "error": str(e)})
    db.commit()
    ok = sum(1 for r in results if r["ok"])
    return {"applied": ok, "failed": len(results) - ok, "results": results}
