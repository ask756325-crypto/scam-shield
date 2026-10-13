"""Alerts: email (per user) and an organization webhook, plus a daily digest. Every attempt is logged with its
real outcome — an email without SMTP is "logged"/"skipped", never reported as sent.

Events
    new_threat       a finding first appears at, or rises to, critical/high in a scan
    source_failure   a source failed in two consecutive scans of a brand (alerted at most once per 24 h per source)
    schedule_paused  a schedule paused itself after repeated failures
    digest           daily summary (opt-in per user, at a local hour)
"""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    Brand, Candidate, Finding, FindingChange, Membership, MonitoringSchedule, NotificationLog, NotificationPreference,
    Organization, Scan, ScanSource, User,
)
from . import mailer

log = logging.getLogger("scamshield.notifications")
SEVERE = ("critical", "high")
WEBHOOK_EVENTS = ("new_threat", "source_failure", "schedule_paused")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ helpers


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def mask_url(url: str | None) -> str | None:
    if not url:
        return None
    p = urlsplit(url)
    tail = p.path[-4:] if len(p.path) > 4 else ""
    return f"{p.scheme}://{p.hostname}/…{tail}"


def prefs_for(db: Session, user_id: int, org_id: int) -> NotificationPreference:
    p = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id, NotificationPreference.organization_id == org_id))
    return p or NotificationPreference(user_id=user_id, organization_id=org_id, email_new_critical=True, email_new_high=False,
                                       email_source_failure=True, digest="off", digest_hour=8, timezone="UTC")


def _record(db: Session, org_id: int, channel: str, event: str, recipient: str, subject: str, status: str, detail: str = "",
            user_id: int | None = None, scan_id: int | None = None) -> NotificationLog:
    row = NotificationLog(organization_id=org_id, user_id=user_id, channel=channel, event=event, recipient=recipient[:255],
                          subject=subject[:300], status=status, detail=detail[:2000], scan_id=scan_id)
    db.add(row)
    return row


def validate_webhook_url(url: str) -> str:
    """https only, no credentials in the URL, and the host must resolve to public addresses (SSRF guard)."""
    p = urlsplit(url.strip())
    if p.scheme != "https" or not p.hostname:
        raise ValueError("Webhook URL must start with https://")
    if p.username or p.password:
        raise ValueError("Webhook URL must not contain credentials")
    host = p.hostname
    try:
        ipaddress.ip_address(host)
        raise ValueError("Use a hostname, not an IP address")
    except ValueError as e:
        if "hostname" in str(e):
            raise
    try:
        infos = socket.getaddrinfo(host, p.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError(f"{host} does not resolve") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError(f"{host} resolves to a non-public address")
    return url.strip()


def post_webhook(url: str, payload: dict) -> tuple[str, str]:
    try:
        validate_webhook_url(url)
        with httpx.Client(timeout=httpx.Timeout(5.0, connect=4.0), follow_redirects=False,
                          headers={"User-Agent": get_settings().user_agent, "Content-Type": "application/json"}) as c:
            r = c.post(url, content=json.dumps(payload))
        if 200 <= r.status_code < 300:
            return "sent", f"HTTP {r.status_code}"
        return "failed", f"HTTP {r.status_code}"
    except ValueError as e:
        return "failed", str(e)
    except httpx.HTTPError as e:
        return "failed", type(e).__name__


def _send_email(db: Session, org_id: int, user: User, event: str, subject: str, body: str, scan_id: int | None = None) -> NotificationLog:
    try:
        status = mailer.send_notification(user.email, subject, body)
        detail = {"sent": "Delivered to the SMTP server", "logged": "Development mode: written to the server log (no SMTP)",
                  "skipped": "Not delivered: no SMTP server is configured"}[status]
    except Exception as e:  # SMTP errors are reported, not hidden
        status, detail = "failed", f"{type(e).__name__}: {e}"[:300]
    return _record(db, org_id, "email", event, mask_email(user.email), subject, status, detail, user.id, scan_id)


def _deliver(db: Session, org: Organization, event: str, subject: str, body: str, *, pref_attr: str | None,
             payload: dict, scan_id: int | None = None) -> None:
    members = db.execute(select(User).join(Membership, Membership.user_id == User.id).where(Membership.organization_id == org.id, User.is_active.is_(True))).scalars().all()
    for user in members:
        if pref_attr and getattr(prefs_for(db, user.id, org.id), pref_attr):
            _send_email(db, org.id, user, event, subject, body, scan_id)
    cfg = org.notification_config or {}
    if cfg.get("enabled") and cfg.get("url") and event in (cfg.get("events") or WEBHOOK_EVENTS):
        status, detail = post_webhook(cfg["url"], {"text": f"*{subject}*\n{body}", "event": event, **payload})
        _record(db, org.id, "webhook", event, mask_url(cfg["url"]) or "", subject, status, detail, None, scan_id)


# ------------------------------------------------------------------ events


def notify_scan_finished(scan_id: int) -> None:
    try:
        with SessionLocal() as db:
            scan = db.get(Scan, scan_id)
            if not scan:
                return
            brand = db.get(Brand, scan.brand_id)
            org = db.get(Organization, brand.organization_id)
            _new_threats(db, org, brand, scan)
            _source_failures(db, org, brand, scan)
            db.commit()
    except Exception:
        log.exception("notifications for scan %s failed", scan_id)


def _new_threats(db: Session, org: Organization, brand: Brand, scan: Scan) -> None:
    rows = db.execute(
        select(FindingChange, Finding, Candidate).join(Finding, FindingChange.finding_id == Finding.id)
        .join(Candidate, Finding.candidate_id == Candidate.id)
        .where(FindingChange.scan_id == scan.id, FindingChange.risk_after.in_(SEVERE),
               (FindingChange.change == "new") | (FindingChange.risk_before.is_(None)) | (FindingChange.risk_before.not_in(SEVERE)))
    ).all()
    if not rows:
        return
    synthetic = scan.mode == "demo"
    base = get_settings().frontend_origin.rstrip("/")
    lines = [f"• [{f.risk_level.upper()}] {c.name} ({c.source}) — {f.classification}. {base}/app/investigations/{f.id}" for _, f, c in rows[:20]]
    crit = sum(1 for _, f, _ in rows if f.risk_level == "critical")
    subject = f"{'[Synthetic demo] ' if synthetic else ''}{brand.name}: {len(rows)} new high-risk finding{'s' if len(rows) != 1 else ''}" + (f" ({crit} critical)" if crit else "")
    body = ("Potential impersonation — review required. Scores are heuristic triage evidence, not proof.\n\n" + "\n".join(lines)
            + (f"\n… and {len(rows) - 20} more" if len(rows) > 20 else "") + f"\n\nScan #{scan.id}: {base}/app/scans/{scan.id}")
    payload = {"brand": brand.name, "scan_id": scan.id, "synthetic": synthetic,
               "findings": [{"id": f.id, "name": c.name, "source": c.source, "risk_level": f.risk_level, "risk_score": f.risk_score} for _, f, c in rows[:50]]}
    # Critical findings go to users who opted into critical; high-only batches only to users who opted into high.
    attr = "email_new_critical" if crit else "email_new_high"
    _deliver(db, org, "new_threat", subject, body, pref_attr=attr, payload=payload, scan_id=scan.id)
    if crit and len(rows) > crit:  # also tell high-only subscribers who did not opt into critical
        members = db.execute(select(User).join(Membership, Membership.user_id == User.id).where(Membership.organization_id == org.id)).scalars().all()
        for u in members:
            p = prefs_for(db, u.id, org.id)
            if p.email_new_high and not p.email_new_critical:
                _send_email(db, org.id, u, "new_threat", subject, body, scan.id)


def _source_failures(db: Session, org: Organization, brand: Brand, scan: Scan) -> None:
    failed_now = [ss.source for ss in scan.sources if ss.status == "failed" and ss.source not in ("demo", "import")]
    for source in failed_now:
        prev = db.scalar(
            select(ScanSource).join(Scan).where(Scan.brand_id == brand.id, ScanSource.source == source, Scan.id < scan.id,
                                                ScanSource.status.not_in(["pending", "running"])).order_by(ScanSource.id.desc()).limit(1))
        if not prev or prev.status != "failed":
            continue
        recent = db.scalar(select(func.count()).select_from(NotificationLog).where(
            NotificationLog.organization_id == org.id, NotificationLog.event == "source_failure",
            NotificationLog.subject.contains(f"{source} "), NotificationLog.created_at >= utcnow() - timedelta(hours=24)))
        if recent:
            continue
        err = next((ss.error for ss in scan.sources if ss.source == source), "") or ""
        subject = f"{source} failing: 2 consecutive scans of {brand.name}"
        body = (f"The {source} source failed in scan #{prev.scan_id} and scan #{scan.id}. Other sources kept running; no findings were "
                f"resolved because of the failure.\n\nLast error: {err[:500]}\n\nSource status: {get_settings().frontend_origin.rstrip('/')}/app/sources")
        _deliver(db, org, "source_failure", subject, body, pref_attr="email_source_failure",
                 payload={"brand": brand.name, "source": source, "scan_ids": [prev.scan_id, scan.id]}, scan_id=scan.id)


def notify_schedule_paused(schedule_id: int) -> None:
    try:
        with SessionLocal() as db:
            s = db.get(MonitoringSchedule, schedule_id)
            if not s:
                return
            brand = db.get(Brand, s.brand_id)
            org = db.get(Organization, brand.organization_id)
            subject = f"Schedule paused for {brand.name}"
            body = f"{s.paused_reason or 'The schedule was paused.'}\n\nLast error: {s.last_error or '—'}\n\nResume it on the brand's Monitoring tab."
            _deliver(db, org, "schedule_paused", subject, body, pref_attr="email_source_failure", payload={"brand": brand.name, "schedule_id": s.id})
            db.commit()
    except Exception:
        log.exception("schedule-paused notification failed")


# ------------------------------------------------------------------ digest


def digest_text(db: Session, org: Organization, since: datetime) -> tuple[str, str]:
    brand_ids = list(db.scalars(select(Brand.id).where(Brand.organization_id == org.id)))
    if not brand_ids:
        return "", ""
    new = dict(db.execute(select(Finding.risk_level, func.count()).where(Finding.brand_id.in_(brand_ids), Finding.created_at >= since)
                          .group_by(Finding.risk_level)).all())
    scans = dict(db.execute(select(Scan.status, func.count()).where(Scan.brand_id.in_(brand_ids), Scan.created_at >= since).group_by(Scan.status)).all())
    open_review = db.scalar(select(func.count()).select_from(Finding).where(Finding.brand_id.in_(brand_ids), Finding.status.in_(["open", "escalated"]),
                                                                            Finding.risk_level.in_(["critical", "high", "medium"]))) or 0
    subject = f"ScamShield daily digest — {org.name}"
    body = (f"Last 24 hours\n"
            f"New findings: {new.get('critical', 0)} critical, {new.get('high', 0)} high, {new.get('medium', 0)} medium, {new.get('low', 0)} low\n"
            f"Scans: {sum(scans.values())} ({scans.get('completed', 0)} completed, {scans.get('partial', 0)} partial, {scans.get('failed', 0)} failed)\n"
            f"Waiting for review (medium and above): {open_review}\n\n{get_settings().frontend_origin.rstrip('/')}/app/review")
    return subject, body


def send_due_digests(now: datetime | None = None) -> int:
    now = now or utcnow()
    sent = 0
    with SessionLocal() as db:
        prefs = db.scalars(select(NotificationPreference).where(NotificationPreference.digest == "daily")).all()
        for p in prefs:
            try:
                local = now.astimezone(ZoneInfo(p.timezone))
            except Exception:
                continue
            last_local = p.last_digest_at.astimezone(ZoneInfo(p.timezone)).date() if p.last_digest_at else None
            if local.hour < p.digest_hour or last_local == local.date():
                continue
            user, org = db.get(User, p.user_id), db.get(Organization, p.organization_id)
            if not user or not org or not user.is_active:
                continue
            subject, body = digest_text(db, org, now - timedelta(hours=24))
            if subject:
                _send_email(db, org.id, user, "digest", subject, body)
                sent += 1
            p.last_digest_at = now
        db.commit()
    return sent
