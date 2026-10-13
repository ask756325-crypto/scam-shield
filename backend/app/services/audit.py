"""Organization audit log. Call `record(...)` in the same transaction as the change it describes."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditEvent

# Keys that must never be written to the audit log, even if a caller passes them.
_SECRET_KEYS = {"password", "token", "secret", "url", "webhook_url", "totp_secret", "code", "recovery_codes"}


def record(db: Session, principal, action: str, target_type: str = "", target_id=None, summary: str = "",
           details: dict | None = None, ip: str = "") -> AuditEvent:
    clean = {k: v for k, v in (details or {}).items() if k.lower() not in _SECRET_KEYS}
    ev = AuditEvent(
        organization_id=principal.org.id, actor_user_id=principal.user.id, actor_email=principal.user.email,
        action=action, target_type=target_type, target_id="" if target_id is None else str(target_id)[:64],
        summary=summary[:500], details=clean, ip=(ip or getattr(principal, "ip", "") or "")[:64],
    )
    db.add(ev)
    return ev
