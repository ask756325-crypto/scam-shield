from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, client_ip, get_principal
from ..models import AuthSession, EmailVerification, Membership, Organization, PasswordReset, User
from ..schemas import ChangePasswordIn, LoginIn, ProfileIn, ResetConfirmIn, ResetRequestIn, SignupIn, VerifyEmailIn
from ..security import (
    create_session,
    lookup_session,
    hash_password,
    password_problems,
    rate_limiter,
    revoke_all_sessions,
    revoke_session,
    session_ttl_hours,
    token_hash,
    verify_password,
)
from ..serializers import user_out
from ..services import mailer

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _limit(key: str) -> None:
    s = get_settings()
    ok, retry = rate_limiter.hit(key, s.auth_rate_limit_attempts, s.auth_rate_limit_window_seconds)
    if not ok:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please wait and try again.", headers={"Retry-After": str(int(retry) + 1)}
        )


def _set_cookie(response: Response, token: str, remember: bool = False) -> None:
    """remember → persistent cookie matching the long server-side TTL; otherwise a browser-session cookie
    (no Max-Age) whose server-side session also expires after SCAMSHIELD_SHORT_SESSION_TTL_HOURS."""
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=session_ttl_hours(True) * 3600 if remember else None,
        httponly=True,
        secure=s.secure_cookies,
        samesite="lax",
        path="/",
    )


def issue_verification(db: Session, user: User, background: BackgroundTasks) -> None:
    """Create a single-use verification token for the user's current email and deliver it."""
    token = secrets.token_urlsafe(32)
    db.add(
        EmailVerification(
            user_id=user.id,
            email=user.email,
            token_hash=token_hash(token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=get_settings().email_verification_ttl_hours),
        )
    )
    db.commit()
    background.add_task(mailer.send_verification_link, user.email, f"{get_settings().frontend_origin}/verify-email?token={token}")


def _session_payload(db: Session, user: User) -> dict:
    m = db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id))
    return {
        "user": user_out(user),
        "organization": {"id": m.organization.id, "name": m.organization.name} if m else None,
        "role": m.role if m else None,
    }


@router.get("/config")
def auth_config():
    s = get_settings()
    return {
        "password_reset_delivery": mailer.delivery_mode(),
        "email_delivery": mailer.delivery_mode(),
        "min_password_length": 10,
        "remember_me_days": s.session_ttl_hours // 24,
        "session_hours": s.short_session_ttl_hours,
    }


@router.post("/signup", status_code=201)
def signup(body: SignupIn, request: Request, response: Response, background: BackgroundTasks, db: Session = Depends(get_db)):
    _limit(f"signup:{client_ip(request)}")
    email = body.email.lower()
    problems = password_problems(body.password, email)
    if problems:
        raise HTTPException(422, " ".join(problems))
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    org = Organization(name=body.organization.strip(), detection_config={}, source_config={})
    db.add_all([user, org])
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role="owner"))
    db.commit()
    issue_verification(db, user, background)
    token = create_session(db, user, request.headers.get("user-agent"), remember=False)
    _set_cookie(response, token, remember=False)
    return _session_payload(db, user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    ip = client_ip(request)
    _limit(f"login-ip:{ip}")
    _limit(f"login:{ip}:{email}")
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    valid = verify_password(body.password, user.password_hash if user else None)
    if not user or not valid or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    token = create_session(db, user, request.headers.get("user-agent"), remember=body.remember)
    _set_cookie(response, token, remember=body.remember)
    return _session_payload(db, user)


@router.post("/verify-email")
def verify_email(body: VerifyEmailIn, request: Request, db: Session = Depends(get_db)):
    _limit(f"verify:{client_ip(request)}")
    ev = db.scalar(select(EmailVerification).where(EmailVerification.token_hash == token_hash(body.token)))
    now = datetime.now(timezone.utc)
    if not ev or ev.used_at or ev.expires_at < now:
        raise HTTPException(400, "This verification link is invalid or has expired. Request a new one from Settings.")
    user = db.get(User, ev.user_id)
    if not user or user.email.lower() != ev.email.lower():
        raise HTTPException(400, "This link was issued for a different email address. Request a new one.")
    user.email_verified_at = now
    ev.used_at = now
    db.commit()
    return {"ok": True, "email": user.email}


@router.post("/resend-verification")
def resend_verification(background: BackgroundTasks, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ok, retry = rate_limiter.hit(f"resend-verify:{p.user.id}", 3, 600)
    if not ok:
        raise HTTPException(429, "Too many verification emails. Try again later.", headers={"Retry-After": str(int(retry) + 1)})
    user = db.get(User, p.user.id)
    if user.email_verified_at:
        return {"ok": True, "already_verified": True}
    issue_verification(db, user, background)
    return {"ok": True, "delivery": mailer.delivery_mode()}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    revoke_session(db, request.cookies.get(s.session_cookie_name))
    response.delete_cookie(s.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/session")
def session_status(request: Request, db: Session = Depends(get_db)):
    """Public, non-erroring session probe for marketing pages: 200 with a boolean, no user details."""
    s = lookup_session(db, request.cookies.get(get_settings().session_cookie_name))
    return {"authenticated": bool(s and s.user.is_active)}


@router.get("/me")
def me(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _session_payload(db, p.user)


@router.patch("/me")
def update_me(body: ProfileIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    user = db.get(User, p.user.id)
    user.name = body.name.strip()
    db.commit()
    return _session_payload(db, user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _limit(f"chpw:{p.user.id}")
    user = db.get(User, p.user.id)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    problems = password_problems(body.new_password, user.email)
    if problems:
        raise HTTPException(422, " ".join(problems))
    user.password_hash = hash_password(body.new_password)
    db.commit()
    revoke_all_sessions(db, user.id, except_token=p.token)  # sign out other devices
    return {"ok": True}


@router.post("/password-reset/request")
def request_reset(body: ResetRequestIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    email = body.email.lower()
    _limit(f"reset:{client_ip(request)}")
    _limit(f"reset-email:{email}")
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        db.add(PasswordReset(user_id=user.id, token_hash=token_hash(token), expires_at=datetime.now(timezone.utc) + timedelta(minutes=30)))
        db.commit()
        link = f"{get_settings().frontend_origin}/reset-password?token={token}"
        background.add_task(mailer.send_reset_link, user.email, link)
    # Identical response whether or not the account exists (no user enumeration).
    return {"ok": True, "delivery": mailer.delivery_mode()}


@router.post("/password-reset/confirm")
def confirm_reset(body: ResetConfirmIn, request: Request, db: Session = Depends(get_db)):
    _limit(f"reset-confirm:{client_ip(request)}")
    pr = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_hash(body.token)))
    now = datetime.now(timezone.utc)
    if not pr or pr.used_at or pr.expires_at < now:
        raise HTTPException(400, "This reset link is invalid or has expired. Request a new one.")
    user = db.get(User, pr.user_id)
    problems = password_problems(body.password, user.email)
    if problems:
        raise HTTPException(422, " ".join(problems))
    user.password_hash = hash_password(body.password)
    pr.used_at = now
    db.commit()
    revoke_all_sessions(db, user.id)
    return {"ok": True}


@router.get("/sessions")
def list_sessions(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """The caller's own active sessions (never another user's). Tokens are never returned."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == p.user.id, AuthSession.expires_at > now).order_by(AuthSession.created_at.desc())).all()
    current = token_hash(p.token) if p.token else None
    return [{"id": s.id, "created_at": s.created_at.isoformat(), "expires_at": s.expires_at.isoformat(),
             "user_agent": (s.user_agent or "")[:160] or None, "current": s.token_hash == current} for s in rows]


@router.delete("/sessions/{session_id}")
def revoke_one(session_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    s = db.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == p.user.id))
    if not s:
        raise HTTPException(404, "Session not found")
    if p.token and s.token_hash == token_hash(p.token):
        raise HTTPException(400, "Use Sign out to end the current session")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/logout-others")
def logout_others(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    before = db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == p.user.id)) or 0
    revoke_all_sessions(db, p.user.id, except_token=p.token)
    return {"ok": True, "revoked": max(before - 1, 0)}
