from __future__ import annotations

import io
import secrets

import httpx
from pydantic import BaseModel, Field
from fastapi import APIRouter, Query, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..services import audit as audit_log
from ..demo.assets import asset_path
from ..demo.dataset import DEMO_BRAND
from ..deps import Principal, get_brand_for, get_principal
from ..detection.logo import InvalidImage, compute_hashes, load_image
from ..models import REVIEW_STATUSES, Brand, Exclusion, Finding, OfficialAccount, OfficialApp, Scan
from ..schemas import BrandIn
from ..serializers import brand_out, iso
from ..services import scanner
from ..sources.importer import ImportError_, parse_csv

router = APIRouter(prefix="/api/brands", tags=["brands"])
MAX_BRANDS_PER_ORG = 50
LOGO_MIN_PX = 32
LOGO_MAX_PX = 4096


def _stats(db: Session, brand: Brand) -> dict:
    rows = db.execute(
        select(Finding.risk_level, func.count()).where(Finding.brand_id == brand.id, Finding.status.in_(REVIEW_STATUSES)).group_by(Finding.risk_level)
    ).all()
    last = db.scalar(select(Scan).where(Scan.brand_id == brand.id).order_by(Scan.id.desc()).limit(1))
    return {
        "open_by_level": {lvl: n for lvl, n in rows},
        "open_review": sum(n for lvl, n in rows if lvl in ("critical", "high", "medium")),
        "last_scan": {"id": last.id, "status": last.status, "finished_at": iso(last.finished_at), "created_at": iso(last.created_at)} if last else None,
    }


def _apply(brand: Brand, body: BrandIn) -> None:
    brand.name = body.name
    brand.aliases = body.aliases
    brand.description = body.description.strip()
    brand.official_domains = body.official_domains
    brand.keywords = body.keywords
    brand.website_url = body.website_url
    brand.additional_identifiers = body.additional_identifiers
    brand.official_accounts = [OfficialAccount(**a.model_dump()) for a in body.official_accounts]
    brand.official_apps = [OfficialApp(**a.model_dump()) for a in body.official_apps]


@router.get("")
def list_brands(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    brands = db.scalars(select(Brand).where(Brand.organization_id == p.org.id).order_by(Brand.is_demo, Brand.name)).all()
    return [brand_out(b, _stats(db, b)) for b in brands]


@router.post("", status_code=201)
def create_brand(body: BrandIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(Brand).where(Brand.organization_id == p.org.id))
    if count >= MAX_BRANDS_PER_ORG:
        raise HTTPException(400, f"An organization can have at most {MAX_BRANDS_PER_ORG} brands")
    if db.scalar(select(Brand).where(Brand.organization_id == p.org.id, func.lower(Brand.name) == body.name.lower())):
        raise HTTPException(409, "A brand with this name already exists")
    brand = Brand(organization_id=p.org.id)
    _apply(brand, body)
    db.add(brand)
    db.flush()
    audit_log.record(db, p, "brand.created", "brand", brand.id, f"Created brand {brand.name}")
    db.commit()
    return brand_out(brand, _stats(db, brand))


class AutofillIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)


@router.post("/autofill")
async def autofill_from_website(body: AutofillIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Draft a brand profile from a public website. Nothing is saved: the analyst reviews the draft first."""
    from ..netsafe import UnsafeURL
    from ..security import rate_limiter
    from ..services.autofill import autofill

    ok, retry = rate_limiter.hit(f"autofill:{p.user.id}", 10, 300)
    if not ok:
        raise HTTPException(429, f"Too many autofill requests. Try again in {int(retry) + 1} seconds.")
    country = (p.org.source_config or {}).get("store_country", "us")
    try:
        draft = await autofill(body.url, country)
    except UnsafeURL as e:
        raise HTTPException(422, str(e))
    except (httpx.HTTPError, ValueError):
        raise HTTPException(422, "The website could not be read. Check the address and try again.")
    audit_log.record(db, p, "brand.autofill", "brand", None, f"Autofill draft from {draft['source_url'][:200]}",
                     {"found": draft["found"], "missing": draft["missing"]})
    db.commit()
    return draft


@router.get("/preview-variants")
def preview_variants(name: str, aliases: list[str] | None = Query(None), p: Principal = Depends(get_principal)):
    """Before a first scan: the search terms ScamShield will use, and illustrative look-alikes with whether the
    detection engine's name matching would flag each for review. Examples are generated, not observed."""
    from ..detection.scoring import DEFAULT_CONFIG
    from ..detection.similarity import name_similarity
    from ..detection.variants import example_lookalikes, generate_search_terms

    name = name.strip()[:120]
    if len(name) < 2:
        raise HTTPException(422, "Enter a brand name of at least 2 characters")
    names = [name, *[a.strip()[:120] for a in (aliases or []) if a.strip()]][:10]
    threshold = DEFAULT_CONFIG["relevance"]["identity_min"]
    examples = []
    for ex in example_lookalikes(name):
        text = ex["text"].lstrip("@")
        if ex["kind"] == "domain":
            text = text.rsplit(".", 1)[0].replace("-", " ").replace(".", " ")
        score = name_similarity(text, names).score
        examples.append({**ex, "similarity": round(score, 2), "flagged": score >= threshold})
    return {"search_terms": generate_search_terms(name, names[1:]), "examples": examples, "relevance_threshold": threshold,
            "note": "Illustrative examples generated from the name — not accounts that exist. Scans search the enabled sources for real ones."}


@router.get("/{brand_id}")
def get_brand(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    return brand_out(b, _stats(db, b))


@router.put("/{brand_id}")
def update_brand(brand_id: int, body: BrandIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    dup = db.scalar(select(Brand).where(Brand.organization_id == p.org.id, func.lower(Brand.name) == body.name.lower(), Brand.id != b.id))
    if dup:
        raise HTTPException(409, "A brand with this name already exists")
    _apply(b, body)
    audit_log.record(db, p, "brand.updated", "brand", b.id, f"Updated brand profile {b.name}",
                     {"official_accounts": len(body.official_accounts), "official_apps": len(body.official_apps), "official_domains": body.official_domains})
    db.commit()
    return brand_out(b, _stats(db, b))


@router.delete("/{brand_id}")
def delete_brand(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    if scanner.active_scan(db, b.id):
        raise HTTPException(409, "A scan is running for this brand. Wait for it to finish.")
    _remove_logo_file(b)
    audit_log.record(db, p, "brand.deleted", "brand", b.id, f"Deleted brand {b.name} and all its scans and findings")
    db.delete(b)
    db.commit()
    return {"ok": True}


def _remove_logo_file(b: Brand) -> None:
    if b.logo_path:
        path = get_settings().upload_dir / b.logo_path
        if path.is_file():
            path.unlink(missing_ok=True)


def _store_logo(db: Session, b: Brand, data: bytes) -> None:
    img = load_image(data)  # validates real image content, not just the extension
    w, h = img.size
    if w < LOGO_MIN_PX or h < LOGO_MIN_PX:
        raise InvalidImage(f"Logo is {w}×{h}px; use at least {LOGO_MIN_PX}×{LOGO_MIN_PX}px so logo matching is reliable")
    if w > LOGO_MAX_PX or h > LOGO_MAX_PX:
        raise InvalidImage(f"Logo is {w}×{h}px; the maximum is {LOGO_MAX_PX}×{LOGO_MAX_PX}px")
    hashes = compute_hashes(data)
    img.thumbnail((512, 512))
    buf = io.BytesIO()
    img.save(buf, format="PNG")  # re-encode: strips metadata and any trailing payloads
    upload_dir = get_settings().upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    name = f"brand-{b.id}-{secrets.token_hex(8)}.png"
    (upload_dir / name).write_bytes(buf.getvalue())
    _remove_logo_file(b)
    b.logo_path, b.logo_phash, b.logo_dhash = name, hashes["phash"], hashes["dhash"]
    db.commit()


@router.post("/{brand_id}/logo")
async def upload_logo(brand_id: int, file: UploadFile = File(...), p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    if file.content_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise HTTPException(415, "Logo must be a PNG, JPEG, WebP or GIF image")
    limit = get_settings().max_logo_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Logo must be at most {limit // (1024 * 1024)} MB")
    try:
        _store_logo(db, b, data)
    except InvalidImage as e:
        raise HTTPException(422, str(e))
    return brand_out(b, _stats(db, b))


@router.delete("/{brand_id}/logo")
def delete_logo(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    _remove_logo_file(b)
    b.logo_path = b.logo_phash = b.logo_dhash = None
    db.commit()
    return brand_out(b, _stats(db, b))


@router.get("/{brand_id}/logo")
def get_logo(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    if not b.logo_path:
        raise HTTPException(404, "No logo")
    path = (get_settings().upload_dir / b.logo_path).resolve()
    if not path.is_file() or get_settings().upload_dir.resolve() not in path.parents:
        raise HTTPException(404, "No logo")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.get("/{brand_id}/exclusions")
def exclusions(brand_id: int, limit: int = 200, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    rows = db.scalars(select(Exclusion).where(Exclusion.brand_id == b.id).order_by(Exclusion.id.desc()).limit(min(limit, 1000))).all()
    return [
        {"id": e.id, "scan_id": e.scan_id, "source": e.source, "external_id": e.external_id, "name": e.name, "url": e.url,
         "rule": e.rule, "matched_value": e.matched_value, "created_at": iso(e.created_at)}
        for e in rows
    ]


@router.post("/{brand_id}/import", status_code=202)
async def import_candidates(brand_id: int, file: UploadFile = File(...), p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    if scanner.active_scan(db, b.id):
        raise HTTPException(409, "A scan is already running for this brand")
    limit = get_settings().max_import_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "Import file too large (max 2 MB)")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(415, "Upload a .csv file")
    try:
        records = parse_csv(data)
    except ImportError_ as e:
        raise HTTPException(422, str(e))
    scan = scanner.create_import_scan(db, b, records, p.user.id)
    scanner.launch(scan.id)
    return {"scan_id": scan.id, "rows": len(records)}


# ----------------------------------------------------------------------------- demo


demo_router = APIRouter(prefix="/api/demo", tags=["demo"])


@demo_router.post("/brand", status_code=201)
def create_demo_brand(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    existing = db.scalar(select(Brand).where(Brand.organization_id == p.org.id, Brand.is_demo.is_(True)))
    if existing:
        return brand_out(existing, _stats(db, existing))
    body = BrandIn(
        name=DEMO_BRAND["name"],  # flagged is_demo and badged "Demo · synthetic" throughout the UI
        aliases=DEMO_BRAND["aliases"],
        description=DEMO_BRAND["description"],
        official_domains=DEMO_BRAND["official_domains"],
        keywords=DEMO_BRAND["keywords"],
        website_url=DEMO_BRAND["website_url"],
        additional_identifiers=DEMO_BRAND["additional_identifiers"],
        official_accounts=DEMO_BRAND["official_accounts"],
        official_apps=DEMO_BRAND["official_apps"],
    )
    brand = Brand(organization_id=p.org.id, is_demo=True)
    _apply(brand, body)
    db.add(brand)
    db.commit()
    _store_logo(db, brand, asset_path(DEMO_BRAND["logo_asset"]).read_bytes())
    return brand_out(brand, _stats(db, brand))


@demo_router.get("/assets/{name}")
def demo_asset(name: str):
    """Synthetic demo images (public: they contain no user data)."""
    path = asset_path(name)
    if not path:
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
