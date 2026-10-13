"""Request dependencies: authentication, organization scoping and brand ownership checks."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Brand, Finding, Membership, Organization, Scan, User
from .security import lookup_session


@dataclass
class Principal:
    user: User
    org: Organization
    role: str
    token: str


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    token = request.cookies.get(get_settings().session_cookie_name)
    session = lookup_session(db, token)
    if not session or not session.user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    membership = db.scalar(select(Membership).where(Membership.user_id == session.user_id).order_by(Membership.id))
    if not membership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No organization membership")
    return Principal(user=session.user, org=membership.organization, role=membership.role, token=token or "")


def require_owner(p: Principal = Depends(get_principal)) -> Principal:
    if p.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    return p


def get_brand_for(db: Session, p: Principal, brand_id: int) -> Brand:
    """Fetch a brand only if it belongs to the caller's organization. 404 (not 403) avoids leaking existence."""
    brand = db.scalar(select(Brand).where(Brand.id == brand_id, Brand.organization_id == p.org.id))
    if not brand:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand not found")
    return brand


def get_scan_for(db: Session, p: Principal, scan_id: int) -> Scan:
    scan = db.scalar(select(Scan).join(Brand).where(Scan.id == scan_id, Brand.organization_id == p.org.id))
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan


def get_finding_for(db: Session, p: Principal, finding_id: int) -> Finding:
    f = db.scalar(select(Finding).join(Brand, Finding.brand_id == Brand.id).where(Finding.id == finding_id, Brand.organization_id == p.org.id))
    if not f:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return f


def client_ip(request: Request) -> str:
    """Peer IP; X-Forwarded-For is trusted only when the direct peer is the local Next.js proxy."""
    peer = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd and peer in ("127.0.0.1", "::1", "localhost"):
        return fwd.split(",")[0].strip()[:64]
    return peer
