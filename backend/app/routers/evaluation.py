"""Detection accuracy: analyst-labelled metrics (real decisions) and the synthetic regression benchmark."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_brand_for, get_principal
from ..services import evaluation

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("")
def analyst_metrics(brand_id: int | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if brand_id is not None:
        get_brand_for(db, p, brand_id)  # 404 for another organization's brand
    return evaluation.analyst_metrics(db, p.org.id, brand_id)


@router.get("/benchmark")
def benchmark(p: Principal = Depends(get_principal)):
    return evaluation.benchmark_metrics()


campaigns_router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


@campaigns_router.get("")
def campaigns(brand_id: int | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from ..services.campaigns import find_campaigns

    if brand_id is not None:
        get_brand_for(db, p, brand_id)
    return find_campaigns(db, p.org.id, brand_id)


reports_router = APIRouter(prefix="/api/reports", tags=["reports"])


@reports_router.get("/executive")
def executive_report(days: int = 30, brand_id: int | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Print-ready HTML summary for a period (save as PDF from the browser)."""
    from fastapi import HTTPException
    from fastapi.responses import HTMLResponse

    from ..config import get_settings
    from ..services import audit as audit_log
    from ..services.reports import build, render_html

    if days not in (7, 30, 90, 365):
        raise HTTPException(422, "days must be 7, 30, 90 or 365")
    if brand_id is not None:
        get_brand_for(db, p, brand_id)
    data = build(db, p.org, days, brand_id)
    audit_log.record(db, p, "data.exported", "report", None, f"Executive report ({days} days)", {"brand_id": brand_id})
    db.commit()
    return HTMLResponse(render_html(data, get_settings().frontend_origin.rstrip("/")), headers={"Cache-Control": "no-store"})
