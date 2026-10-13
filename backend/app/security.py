"""Password hashing (Argon2id), opaque session tokens and an in-memory rate limiter."""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuthSession, User

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters
# Constant-time-ish defence against user enumeration: verify against a dummy hash for unknown emails.
_DUMMY_HASH = _hasher.hash("not-a-real-password-" + secrets.token_hex(8))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problems(password: str, email: str = "") -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("Password must be at least 10 characters.")
    if len(password) > 256:
        problems.append("Password must be at most 256 characters.")
    if password.lower() == email.lower() or (email and email.split("@")[0].lower() in password.lower() and len(email.split("@")[0]) >= 4):
        problems.append("Password must not contain your email name.")
    if password.isalpha() or password.isdigit():
        problems.append("Use a mix of letters and numbers or symbols.")
    return problems


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_ttl_hours(remember: bool) -> int:
    s = get_settings()
    return s.session_ttl_hours if remember else s.short_session_ttl_hours


def create_session(db: Session, user: User, user_agent: str | None, remember: bool = False) -> str:
    """remember=False → short server-side lifetime and a browser-session cookie (see routers/auth._set_cookie)."""
    token = secrets.token_urlsafe(32)
    ttl = timedelta(hours=session_ttl_hours(remember))
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=datetime.now(timezone.utc) + ttl,
            user_agent=(user_agent or "")[:255],
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    # Housekeeping: drop this user's expired sessions.
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at < datetime.now(timezone.utc)))
    db.commit()
    return token


def lookup_session(db: Session, token: str | None) -> AuthSession | None:
    if not token or len(token) > 200:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if not s or s.expires_at < datetime.now(timezone.utc):
        return None
    return s


def revoke_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        db.commit()


def revoke_all_sessions(db: Session, user_id: int, except_token: str | None = None) -> None:
    q = delete(AuthSession).where(AuthSession.user_id == user_id)
    if except_token:
        q = q.where(AuthSession.token_hash != token_hash(except_token))
    db.execute(q)
    db.commit()


class RateLimiter:
    """Sliding-window limiter keyed by arbitrary strings. In-process; use a shared store when scaling out."""

    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False, max(0.0, q[0] + window - now)
            q.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class DatabaseRateLimiter:
    """Sliding window stored in the database, so every API replica shares the same counts.

    Best effort under heavy concurrency (two simultaneous requests can both pass at the boundary), which is
    acceptable for brute-force protection. Keys are SHA-256 hashed so emails and IPs are never stored."""

    def hit(self, key: str, limit: int, window: float) -> tuple[bool, float]:
        from sqlalchemy import delete as sa_delete, func as sa_func, select as sa_select

        from .db import SessionLocal
        from .models import RateLimitEvent

        now = time.time()
        kh = hashlib.sha256(key.encode()).hexdigest()
        with SessionLocal() as db:
            db.execute(sa_delete(RateLimitEvent).where(RateLimitEvent.key_hash == kh, RateLimitEvent.at <= now - window))
            count, oldest = db.execute(sa_select(sa_func.count(), sa_func.min(RateLimitEvent.at)).where(RateLimitEvent.key_hash == kh)).one()
            if count >= limit:
                db.commit()
                return False, max(0.0, (oldest or now) + window - now)
            db.add(RateLimitEvent(key_hash=kh, at=now))
            db.commit()
            return True, 0.0

    def reset(self) -> None:
        from sqlalchemy import delete as sa_delete

        from .db import SessionLocal
        from .models import RateLimitEvent

        with SessionLocal() as db:
            db.execute(sa_delete(RateLimitEvent))
            db.commit()

    @staticmethod
    def purge_older_than(seconds: float) -> int:
        from sqlalchemy import delete as sa_delete

        from .db import SessionLocal
        from .models import RateLimitEvent

        with SessionLocal() as db:
            n = db.execute(sa_delete(RateLimitEvent).where(RateLimitEvent.at < time.time() - seconds)).rowcount
            db.commit()
            return n or 0


class _RateLimiterProxy:
    """Chooses the backend from settings at call time (database by default)."""

    def __init__(self):
        self._memory = RateLimiter()
        self._database = DatabaseRateLimiter()

    @property
    def backend(self):
        from .config import get_settings

        return self._memory if get_settings().rate_limit_backend == "memory" else self._database

    def hit(self, key: str, limit: int, window: float) -> tuple[bool, float]:
        return self.backend.hit(key, limit, window)

    def reset(self) -> None:
        self._memory.reset()
        try:
            self._database.reset()
        except Exception:  # tables may not exist yet in pure unit tests
            pass


rate_limiter = _RateLimiterProxy()
