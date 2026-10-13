"""Notification preferences (per user), the organization webhook (owners), test sends and the delivery log."""
from __future__ import annotations

from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_principal, require_owner
from ..models import NotificationLog, NotificationPreference, Organization
from ..serializers import iso
from ..services import mailer
from ..services.notifications import WEBHOOK_EVENTS, _record, _send_email, mask_url, post_webhook, prefs_for, validate_webhook_url

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class PrefsIn(BaseModel):
    email_new_critical: bool
    email_new_high: bool
    email_source_failure: bool
    digest: str = Field(pattern="^(off|daily)$")
    digest_hour: int = Field(ge=0, le=23)
    timezone: str = Field(max_length=64)


class WebhookIn(BaseModel):
    url: str | None = Field(default=None, max_length=1000)  # None = keep the stored URL
    enabled: bool
    events: list[str] = Field(default_factory=lambda: list(WEBHOOK_EVENTS))
    clear: bool = False


def _prefs_out(p: NotificationPreference) -> dict:
    return {"email_new_critical": p.email_new_critical, "email_new_high": p.email_new_high, "email_source_failure": p.email_source_failure,
            "digest": p.digest, "digest_hour": p.digest_hour, "timezone": p.timezone, "last_digest_at": iso(p.last_digest_at)}


def _webhook_out(org: Organization) -> dict:
    cfg = org.notification_config or {}
    return {"configured": bool(cfg.get("url")), "url_masked": mask_url(cfg.get("url")), "enabled": bool(cfg.get("enabled")),
            "events": cfg.get("events") or list(WEBHOOK_EVENTS), "available_events": list(WEBHOOK_EVENTS)}


@router.get("/preferences")
def get_prefs(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return {**_prefs_out(prefs_for(db, p.user.id, p.org.id)), "email_delivery": mailer.delivery_mode(), "email": p.user.email}


@router.put("/preferences")
def put_prefs(body: PrefsIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if body.timezone not in available_timezones():
        raise HTTPException(422, {"field": "timezone", "message": f"Unknown time zone “{body.timezone}”"})
    row = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == p.user.id, NotificationPreference.organization_id == p.org.id))
    if row is None:
        row = NotificationPreference(user_id=p.user.id, organization_id=p.org.id)
        db.add(row)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    db.commit()
    return {**_prefs_out(row), "email_delivery": mailer.delivery_mode(), "email": p.user.email}


@router.get("/webhook")
def get_webhook(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _webhook_out(db.get(Organization, p.org.id))


@router.put("/webhook")
def put_webhook(body: WebhookIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    org = db.get(Organization, p.org.id)
    cfg = dict(org.notification_config or {})
    bad = [e for e in body.events if e not in WEBHOOK_EVENTS]
    if bad:
        raise HTTPException(422, {"field": "events", "message": f"Unknown event(s): {', '.join(bad)}"})
    if body.clear:
        cfg = {}
    else:
        if body.url:
            try:
                cfg["url"] = validate_webhook_url(body.url)
            except ValueError as e:
                raise HTTPException(422, {"field": "url", "message": str(e)})
        if body.enabled and not cfg.get("url"):
            raise HTTPException(422, {"field": "url", "message": "Add a webhook URL before enabling it"})
        cfg["enabled"], cfg["events"] = body.enabled, body.events
    org.notification_config = cfg
    from ..services.audit import record as audit

    audit(db, p, "webhook.updated" if not body.clear else "webhook.removed", "organization", org.id,
          f"Alert webhook {'removed' if body.clear else ('enabled' if cfg.get('enabled') else 'disabled')}",
          {"host": mask_url(cfg.get("url")), "events": cfg.get("events")})
    db.commit()
    return _webhook_out(org)


@router.post("/test")
def send_test(channel: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Send a real test message to yourself (email) or to the organization webhook, and report the true outcome."""
    subject = "ScamShield AI test notification"
    body = "This is a test notification. If you received it, alerts for this channel are working."
    if channel == "email":
        row = _send_email(db, p.org.id, p.user, "test", subject, body)
    elif channel == "webhook":
        cfg = (db.get(Organization, p.org.id).notification_config or {})
        if not cfg.get("url"):
            raise HTTPException(400, "No webhook URL is configured")
        status, detail = post_webhook(cfg["url"], {"text": f"*{subject}*\n{body}", "event": "test"})
        row = _record(db, p.org.id, "webhook", "test", mask_url(cfg["url"]) or "", subject, status, detail, p.user.id)
    else:
        raise HTTPException(422, "channel must be email or webhook")
    db.commit()
    return {"channel": row.channel, "status": row.status, "detail": row.detail}


@router.get("/log")
def delivery_log(limit: int = 50, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(NotificationLog).where(NotificationLog.organization_id == p.org.id)
                      .order_by(NotificationLog.id.desc()).limit(min(max(limit, 1), 200))).all()
    return [{"id": r.id, "channel": r.channel, "event": r.event, "recipient": r.recipient, "subject": r.subject, "status": r.status,
             "detail": r.detail, "scan_id": r.scan_id, "created_at": iso(r.created_at)} for r in rows]
