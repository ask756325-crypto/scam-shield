"""Explicit response shaping (never return ORM objects or secrets directly)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .detection.exclusion import DEFAULT_RULES, effective_rules
from .models import Brand, Candidate, Decision, Finding, MonitoringSchedule, Scan, ScanSource, User


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name, "created_at": iso(u.created_at), "last_login_at": iso(u.last_login_at),
        "email_verified": u.email_verified_at is not None,
    }


def brand_out(b: Brand, stats: dict | None = None) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "aliases": b.aliases or [],
        "description": b.description,
        "official_domains": b.official_domains or [],
        "keywords": b.keywords or [],
        "website_url": b.website_url,
        "additional_identifiers": b.additional_identifiers or [],
        "exclusion_rules": effective_rules(b.exclusion_rules),
        "exclusion_rules_customised": sorted(k for k, v in (b.exclusion_rules or {}).items() if k in DEFAULT_RULES and v != DEFAULT_RULES[k]),
        "has_logo": bool(b.logo_path),
        "logo_phash": b.logo_phash,
        "logo_dhash": b.logo_dhash,
        "is_demo": b.is_demo,
        # Summary of the monitoring schedule (full details: GET /api/brands/{id}/schedule).
        "schedule": schedule_summary(b.schedule),
        "schedule_enabled": bool(b.schedule and b.schedule.state == "active"),
        "next_scheduled_at": iso(b.schedule.next_run_at) if b.schedule and b.schedule.state == "active" else None,
        "official_accounts": [
            {"id": a.id, "platform": a.platform, "handle": a.handle, "profile_url": a.profile_url, "external_id": a.external_id}
            for a in b.official_accounts
        ],
        "official_apps": [
            {"id": a.id, "store": a.store, "name": a.name, "app_id": a.app_id, "track_id": a.track_id, "publisher_id": a.publisher_id,
             "publisher_name": a.publisher_name, "url": a.url}
            for a in b.official_apps
        ],
        "created_at": iso(b.created_at),
        "updated_at": iso(b.updated_at),
        "stats": stats or {},
    }


def scan_source_out(s: ScanSource) -> dict:
    return {
        "source": s.source, "status": s.status, "queries_total": s.queries_total, "queries_done": s.queries_done,
        "queries_failed": s.queries_failed, "candidates": s.candidates, "error": s.error, "duration_ms": s.duration_ms,
        "query_outcomes": s.query_outcomes or {}, "failure_kind": s.failure_kind, "rate_limit": s.rate_limit,
        "started_at": iso(s.started_at), "finished_at": iso(s.finished_at),
    }


WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def describe_schedule(s: MonitoringSchedule) -> str:
    if s.frequency == "interval":
        return f"Every {s.interval_hours} hour{'s' if s.interval_hours != 1 else ''}"
    if s.frequency == "daily":
        return f"Daily at {s.time_of_day} ({s.timezone})"
    days = ", ".join(WEEKDAY_NAMES[d] for d in sorted(s.weekdays or []))
    return f"Weekly on {days} at {s.time_of_day} ({s.timezone})"


def _local(dt: datetime | None, tz: str) -> str | None:
    return dt.astimezone(ZoneInfo(tz)).isoformat() if dt else None


def schedule_summary(s: MonitoringSchedule | None) -> dict | None:
    if s is None:
        return None
    return {"state": s.state, "description": describe_schedule(s), "next_run_at": iso(s.next_run_at) if s.state == "active" else None,
            "last_outcome": s.last_outcome, "consecutive_failures": s.consecutive_failures}


def schedule_out(s: MonitoringSchedule, upcoming: list[datetime] | None = None) -> dict:
    return {
        "id": s.id, "brand_id": s.brand_id, "state": s.state, "frequency": s.frequency, "interval_hours": s.interval_hours,
        "time_of_day": s.time_of_day, "weekdays": s.weekdays or [], "timezone": s.timezone, "sources": s.sources,
        "description": describe_schedule(s),
        "next_run_at": iso(s.next_run_at) if s.state == "active" else None,
        "next_run_local": _local(s.next_run_at, s.timezone) if s.state == "active" else None,
        "upcoming": [{"utc": iso(d), "local": _local(d, s.timezone)} for d in (upcoming or [])],
        "last_run_at": iso(s.last_run_at), "last_scan_id": s.last_scan_id, "last_outcome": s.last_outcome, "last_error": s.last_error,
        "consecutive_failures": s.consecutive_failures, "paused_reason": s.paused_reason,
        "created_at": iso(s.created_at), "updated_at": iso(s.updated_at),
    }


def scan_out(s: Scan, brand_name: str | None = None) -> dict:
    duration = int((s.finished_at - s.started_at).total_seconds() * 1000) if s.started_at and s.finished_at else None
    failed_sources = [x.source for x in s.sources if x.status in ("failed", "partial")]
    return {
        "schedule_id": s.schedule_id, "runner": s.runner, "duration_ms": duration,
        "sources_attempted": [x.source for x in s.sources],
        "source_failures": failed_sources,
        "findings_updated": s.findings_changed + s.findings_recurring,
        "findings_missing": s.findings_missing or 0, "findings_unverified": s.findings_unverified or 0,
        "id": s.id, "brand_id": s.brand_id, "brand_name": brand_name, "trigger": s.trigger, "mode": s.mode,
        "status": s.status, "progress": s.progress, "stage": s.stage, "search_terms": s.search_terms or [],
        "candidates_collected": s.candidates_collected, "candidates_unique": s.candidates_unique,
        "excluded_official": s.excluded_official, "findings_new": s.findings_new, "findings_changed": s.findings_changed,
        "findings_recurring": s.findings_recurring, "findings_resolved": s.findings_resolved, "error": s.error,
        "created_at": iso(s.created_at), "started_at": iso(s.started_at), "finished_at": iso(s.finished_at),
        "sources": [scan_source_out(x) for x in s.sources],
    }


def candidate_out(c: Candidate) -> dict:
    return {
        "id": c.id, "source": c.source, "source_type": c.source_type, "kind": c.kind, "external_id": c.external_id,
        "name": c.name, "handle": c.handle, "url": c.url, "description": c.description, "avatar_url": c.avatar_url,
        "publisher_name": c.publisher_name, "publisher_id": c.publisher_id, "external_links": c.external_links or [],
        "metadata": c.extra or {}, "provenance": c.provenance or {}, "first_observed_at": iso(c.first_observed_at),
        "last_observed_at": iso(c.last_observed_at), "source_created_at": c.source_created_at,
        "platform": (c.extra or {}).get("platform") or c.source,
    }


def decision_out(d: Decision) -> dict:
    return {"id": d.id, "action": d.action, "note": d.note, "created_at": iso(d.created_at),
            "user": d.user.name if d.user else "System", "from_status": d.from_status, "to_status": d.to_status}


def finding_out(f: Finding, brand_name: str | None = None, detail: bool = False) -> dict:
    out = {
        "id": f.id, "brand_id": f.brand_id, "brand_name": brand_name, "risk_score": f.risk_score, "risk_level": f.risk_level,
        "classification": f.classification, "detection_type": f.detection_type, "explanation": f.explanation, "status": f.status, "change_state": f.change_state,
        "corroborating_groups": f.corroborating_groups or [], "first_seen_scan_id": f.first_seen_scan_id,
        "last_seen_scan_id": f.last_seen_scan_id, "created_at": iso(f.created_at), "updated_at": iso(f.updated_at),
        "candidate": candidate_out(f.candidate),
    }
    if detail:
        out["signals"] = f.signals or {}
        out["reasons"] = f.reasons or []
        out["decisions"] = [decision_out(d) for d in f.decisions]
    return out
