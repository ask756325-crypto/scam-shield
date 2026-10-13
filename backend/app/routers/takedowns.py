"""Takedown cases for confirmed impersonations (organization-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_finding_for, get_principal
from ..models import Brand, Finding, TakedownCase
from ..services import audit
from ..services.takedowns import STATUSES, apply_status, case_out, create_case

router = APIRouter(prefix="/api", tags=["takedowns"])


class TakedownPatch(BaseModel):
    status: str | None = None
    reference: str | None = Field(default=None, max_length=200)
    report_text: str | None = Field(default=None, max_length=20000)
    note: str = Field(default="", max_length=1000)


def _case_for(db: Session, p: Principal, case_id: int) -> TakedownCase:
    case = db.scalar(select(TakedownCase).where(TakedownCase.id == case_id, TakedownCase.organization_id == p.org.id))
    if not case:
        raise HTTPException(404, "Takedown case not found")
    return case


@router.get("/findings/{finding_id}/takedown")
def get_for_finding(finding_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    f = get_finding_for(db, p, finding_id)
    case = db.scalar(select(TakedownCase).where(TakedownCase.finding_id == f.id))
    return {"case": case_out(case, f) if case else None, "eligible": f.status == "confirmed"}


@router.post("/findings/{finding_id}/takedown", status_code=201)
def open_case(finding_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    f = get_finding_for(db, p, finding_id)
    if f.status != "confirmed":
        raise HTTPException(409, "Confirm the impersonation before opening a takedown case")
    if db.scalar(select(TakedownCase.id).where(TakedownCase.finding_id == f.id)):
        raise HTTPException(409, "A takedown case already exists for this finding")
    case = create_case(db, f, p.user)
    db.flush()
    audit.record(db, p, "takedown.opened", "takedown", case.id, f"Takedown case opened for “{f.candidate.name}” ({case.platform})", {"finding_id": f.id})
    db.commit()
    return case_out(case, f)


@router.patch("/takedowns/{case_id}")
def update_case(case_id: int, body: TakedownPatch, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    case = _case_for(db, p, case_id)
    f = db.get(Finding, case.finding_id)
    if body.report_text is not None:
        if case.status != "draft":
            raise HTTPException(409, "The report text can only be edited while the case is a draft")
        case.report_text = body.report_text
    if body.status:
        if body.status not in STATUSES:
            raise HTTPException(422, "Unknown status")
        if body.status == "reported" and not (body.reference or case.reference or body.note.strip()):
            raise HTTPException(422, {"field": "reference", "message": "Add the platform's case/ticket reference or a note on how it was reported"})
        try:
            apply_status(case, body.status, body.note, body.reference, p.user.email)
        except ValueError as e:
            raise HTTPException(409, str(e))
        audit.record(db, p, "takedown.status", "takedown", case.id, f"Takedown for “{f.candidate.name}” → {body.status}",
                     {"finding_id": f.id, "reference": case.reference})
    elif body.reference is not None:
        case.reference = body.reference.strip()
    db.commit()
    db.refresh(case)
    return case_out(case, f)


@router.get("/takedowns")
def list_cases(status: list[str] | None = None, brand_id: int | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = (select(TakedownCase, Finding, Brand.name).join(Finding, TakedownCase.finding_id == Finding.id).join(Brand, Finding.brand_id == Brand.id)
         .where(TakedownCase.organization_id == p.org.id))
    if status:
        q = q.where(TakedownCase.status.in_(status))
    if brand_id:
        q = q.where(Finding.brand_id == brand_id)
    rows = db.execute(q.order_by(TakedownCase.updated_at.desc()).limit(500)).all()
    items = [case_out(c, f, b) for c, f, b in rows]
    counts: dict[str, int] = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return {"items": items, "counts": counts}
