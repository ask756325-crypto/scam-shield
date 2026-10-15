from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, client_ip, get_principal
from ..models import AuthSession, EmailVerification, LoginChallenge, Membership, Organization, PasswordReset, User
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
        "demo_enabled": s.demo_mode,
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
    if user.totp_enabled_at:
        # Password is correct but no session yet: the second factor completes the login.
        challenge = secrets.token_urlsafe(32)
        db.add(LoginChallenge(user_id=user.id, token_hash=token_hash(challenge), remember=body.remember,
                              expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
        db.commit()
        return {"two_factor_required": True, "challenge": challenge}
    token = create_session(db, user, request.headers.get("user-agent"), remember=body.remember)
    _set_cookie(response, token, remember=body.remember)
    return _session_payload(db, user)


@router.post("/demo-login")
def demo_login(request: Request, response: Response, db: Session = Depends(get_db)):
    """Create a short-lived session for the seeded demo workspace when explicitly enabled."""
    s = get_settings()
    if not s.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo access is disabled.")
    _limit(f"demo-login:{client_ip(request)}")
    email = "demo@scamshield.local"
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, name="Demo Analyst", password_hash=hash_password(secrets.token_urlsafe(32)))
        org = Organization(name="ScamShield Demo", detection_config={}, source_config={})
        db.add_all([user, org])
        db.flush()
        db.add(Membership(user_id=user.id, organization_id=org.id, role="owner"))
        db.commit()
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Demo account is disabled.")
    token = create_session(db, user, request.headers.get("user-agent"), remember=False)
    _set_cookie(response, token, remember=False)
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


# ---------------------------------------------------------------- two-factor authentication (TOTP)

from pydantic import BaseModel, Field  # noqa: E402

from .. import totp  # noqa: E402
from ..services import audit as audit_log  # noqa: E402

MAX_CHALLENGE_ATTEMPTS = 5


class SecondFactorIn(BaseModel):
    challenge: str = Field(min_length=10, max_length=200)
    code: str = Field(default="", max_length=20)
    recovery_code: str = Field(default="", max_length=40)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class DisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(default="", max_length=40)  # a TOTP code or a recovery code


def _check_second_factor(db: Session, user: User, code: str, recovery_code: str = "") -> str | None:
    """Return "totp" or "recovery" when valid (and consume it), else None."""
    if code:
        step = totp.verify(user.totp_secret or "", code, user.totp_last_step)
        if step is not None:
            user.totp_last_step = step
            return "totp"
    rc = recovery_code or (code if len(code.strip()) > 6 else "")
    if rc:
        h = totp.hash_recovery(rc)
        codes = list(user.recovery_codes or [])
        if h in codes:
            codes.remove(h)
            user.recovery_codes = codes
            return "recovery"
    return None


@router.post("/login/2fa")
def login_second_factor(body: SecondFactorIn, request: Request, response: Response, db: Session = Depends(get_db)):
    _limit(f"2fa-ip:{client_ip(request)}")
    ch = db.scalar(select(LoginChallenge).where(LoginChallenge.token_hash == token_hash(body.challenge)))
    if not ch or ch.expires_at < datetime.now(timezone.utc) or ch.attempts >= MAX_CHALLENGE_ATTEMPTS:
        raise HTTPException(401, "This sign-in attempt expired. Sign in again.")
    user = db.get(User, ch.user_id)
    ch.attempts += 1
    used = _check_second_factor(db, user, body.code, body.recovery_code) if user and user.is_active and user.totp_enabled_at else None
    if not used:
        db.commit()
        left = MAX_CHALLENGE_ATTEMPTS - ch.attempts
        raise HTTPException(401, "Incorrect code." + (f" {left} attempt{'s' if left != 1 else ''} left." if left > 0 else " Sign in again."))
    remember = ch.remember
    db.delete(ch)
    db.commit()
    token = create_session(db, user, request.headers.get("user-agent"), remember=remember)
    _set_cookie(response, token, remember=remember)
    out = _session_payload(db, user)
    if used == "recovery":
        out["recovery_codes_left"] = len(user.recovery_codes or [])
    return out


@router.get("/2fa")
def two_factor_status(p: Principal = Depends(get_principal)):
    u = p.user
    return {"enabled": u.totp_enabled_at is not None, "enabled_at": u.totp_enabled_at.isoformat() if u.totp_enabled_at else None,
            "recovery_codes_left": len(u.recovery_codes or []) if u.totp_enabled_at else 0, "setup_pending": bool(u.totp_pending_secret)}


@router.post("/2fa/setup")
def two_factor_setup(body: PasswordIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Start setup (re-authenticates with the password). The secret is shown once, until confirmed with a code."""
    _limit(f"2fa-setup:{p.user.id}")
    user = db.get(User, p.user.id)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "Password is incorrect.")
    if user.totp_enabled_at:
        raise HTTPException(409, "Two-factor authentication is already on. Turn it off first to set up a new device.")
    secret = totp.new_secret()
    user.totp_pending_secret = secret
    db.commit()
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, user.email)}


@router.post("/2fa/enable")
def two_factor_enable(body: CodeIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _limit(f"2fa-enable:{p.user.id}")
    user = db.get(User, p.user.id)
    if not user.totp_pending_secret:
        raise HTTPException(409, "Start setup first.")
    step = totp.verify(user.totp_pending_secret, body.code)
    if step is None:
        raise HTTPException(400, "That code doesn't match. Check the time on your device and try again.")
    codes = totp.new_recovery_codes()
    user.totp_secret, user.totp_pending_secret = user.totp_pending_secret, None
    user.totp_enabled_at, user.totp_last_step = datetime.now(timezone.utc), step
    user.recovery_codes = [totp.hash_recovery(c) for c in codes]
    audit_log.record(db, p, "security.2fa_enabled", "user", user.id, f"{user.email} turned on two-factor authentication")
    db.commit()
    revoke_all_sessions(db, user.id, except_token=p.token)
    return {"enabled": True, "recovery_codes": codes}


@router.post("/2fa/disable")
def two_factor_disable(body: DisableIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _limit(f"2fa-disable:{p.user.id}")
    user = db.get(User, p.user.id)
    if not user.totp_enabled_at:
        raise HTTPException(409, "Two-factor authentication is not on.")
    if not verify_password(body.password, user.password_hash) or not _check_second_factor(db, user, body.code):
        raise HTTPException(400, "Password or code is incorrect.")
    user.totp_secret = user.totp_pending_secret = None
    user.totp_enabled_at, user.totp_last_step, user.recovery_codes = None, None, None
    audit_log.record(db, p, "security.2fa_disabled", "user", user.id, f"{user.email} turned off two-factor authentication")
    db.commit()
    return {"enabled": False}


@router.post("/2fa/recovery-codes")
def regenerate_recovery_codes(body: CodeIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    _limit(f"2fa-codes:{p.user.id}")
    user = db.get(User, p.user.id)
    if not user.totp_enabled_at or not _check_second_factor(db, user, body.code):
        raise HTTPException(400, "Enter a current code from your authenticator app.")
    codes = totp.new_recovery_codes()
    user.recovery_codes = [totp.hash_recovery(c) for c in codes]
    audit_log.record(db, p, "security.recovery_codes_regenerated", "user", user.id, f"{user.email} generated new recovery codes")
    db.commit()
    return {"recovery_codes": codes}
