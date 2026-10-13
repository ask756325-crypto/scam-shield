"""Team management (invites, roles, removal) and invite acceptance / email change."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, client_ip, get_principal, require_owner
from ..models import Invite, Membership, Organization, User
from ..schemas import AcceptInviteIn, ChangeEmailIn, InviteIn, MemberRoleIn
from ..security import create_session, hash_password, password_problems, revoke_all_sessions, token_hash, verify_password
from ..serializers import iso
from ..services import mailer
from .auth import _limit, _session_payload, _set_cookie, issue_verification

INVITE_TTL_DAYS = 7
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
router = APIRouter(prefix="/api/settings", tags=["team"])


def _invite_out(i: Invite) -> dict:
    return {"id": i.id, "email": i.email, "role": i.role, "created_at": iso(i.created_at), "expires_at": iso(i.expires_at)}


def _live_invite(db: Session, token: str) -> Invite | None:
    inv = db.scalar(select(Invite).where(Invite.token_hash == token_hash(token)))
    if not inv or inv.accepted_at or inv.revoked_at or inv.expires_at < datetime.now(timezone.utc):
        return None
    return inv


# ------------------------------------------------------------------ public: accept an invite


@auth_router.get("/invite/{token}")
def invite_info(token: str, request: Request, db: Session = Depends(get_db)):
    _limit(f"invite-info:{client_ip(request)}")
    inv = _live_invite(db, token)
    if not inv:
        raise HTTPException(404, "This invitation is invalid, expired or already used.")
    return {"email": inv.email, "organization": db.get(Organization, inv.organization_id).name, "role": inv.role}


@auth_router.post("/accept-invite", status_code=201)
def accept_invite(body: AcceptInviteIn, request: Request, response: Response, background: BackgroundTasks, db: Session = Depends(get_db)):
    _limit(f"accept-invite:{client_ip(request)}")
    inv = _live_invite(db, body.token)
    if not inv:
        raise HTTPException(400, "This invitation is invalid, expired or already used.")
    email = inv.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "An account with this email already exists. Sign in with it instead.")
    problems = password_problems(body.password, email)
    if problems:
        raise HTTPException(422, " ".join(problems))
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=inv.organization_id, role=inv.role))
    inv.accepted_at = datetime.now(timezone.utc)
    db.commit()
    issue_verification(db, user, background)  # the invite link may have been shared by hand, so verify the address
    _set_cookie(response, create_session(db, user, request.headers.get("user-agent")))
    return _session_payload(db, user)


@auth_router.post("/change-email")
def change_email(body: ChangeEmailIn, background: BackgroundTasks, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Re-authenticates with the current password; the new address must then be verified."""
    _limit(f"chem:{p.user.id}")
    user = db.get(User, p.user.id)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "Password is incorrect.")
    new = body.new_email.lower()
    if new == user.email.lower():
        raise HTTPException(422, "That is already your email address.")
    if db.scalar(select(User).where(func.lower(User.email) == new)) or db.scalar(
        select(Invite).where(func.lower(Invite.email) == new, Invite.accepted_at.is_(None), Invite.revoked_at.is_(None), Invite.expires_at > datetime.now(timezone.utc))
    ):
        raise HTTPException(409, "That email address is already in use.")
    user.email = new
    user.email_verified_at = None
    db.commit()
    revoke_all_sessions(db, user.id, except_token=p.token)
    issue_verification(db, user, background)
    return _session_payload(db, user)


# ------------------------------------------------------------------ owner: manage the team


@router.get("/invites")
def list_invites(p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(Invite)
        .where(Invite.organization_id == p.org.id, Invite.accepted_at.is_(None), Invite.revoked_at.is_(None), Invite.expires_at > now)
        .order_by(Invite.id.desc())
    ).all()
    return [_invite_out(i) for i in rows]


@router.post("/invites", status_code=201)
def create_invite(body: InviteIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "That email already has an account. Accounts belong to a single organization.")
    now = datetime.now(timezone.utc)
    for old in db.scalars(select(Invite).where(Invite.organization_id == p.org.id, Invite.email == email, Invite.accepted_at.is_(None), Invite.revoked_at.is_(None))):
        old.revoked_at = now  # a re-invite supersedes earlier links
    token = secrets.token_urlsafe(32)
    inv = Invite(organization_id=p.org.id, email=email, role=body.role, token_hash=token_hash(token), created_by_id=p.user.id, expires_at=now + timedelta(days=INVITE_TTL_DAYS))
    db.add(inv)
    db.commit()
    link = f"{get_settings().frontend_origin}/accept-invite?token={token}"
    emailed = False
    if mailer.delivery_mode() == "email":
        try:
            mailer.send_invite(email, p.org.name, link)
            emailed = True
        except Exception:
            emailed = False
    # The link is returned once so the owner can share it; only its hash is stored.
    return {**_invite_out(inv), "link": link, "emailed": emailed}


@router.delete("/invites/{invite_id}")
def revoke_invite(invite_id: int, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    inv = db.scalar(select(Invite).where(Invite.id == invite_id, Invite.organization_id == p.org.id))
    if not inv:
        raise HTTPException(404, "Invite not found")
    inv.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


def _member(db: Session, p: Principal, user_id: int) -> Membership:
    m = db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.organization_id == p.org.id))
    if not m:
        raise HTTPException(404, "Member not found")
    return m


def _owner_count(db: Session, org_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Membership).where(Membership.organization_id == org_id, Membership.role == "owner")) or 0


@router.patch("/members/{user_id}")
def set_member_role(user_id: int, body: MemberRoleIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    m = _member(db, p, user_id)
    if m.role == "owner" and body.role != "owner" and _owner_count(db, p.org.id) <= 1:
        raise HTTPException(409, "An organization needs at least one owner.")
    m.role = body.role
    db.commit()
    return {"ok": True}


@router.delete("/members/{user_id}")
def remove_member(user_id: int, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    m = _member(db, p, user_id)
    if user_id == p.user.id:
        raise HTTPException(409, "You cannot remove yourself.")
    user = db.get(User, user_id)
    revoke_all_sessions(db, user_id)
    db.delete(m)
    db.delete(user)  # accounts belong to exactly one organization
    db.commit()
    return {"ok": True}
