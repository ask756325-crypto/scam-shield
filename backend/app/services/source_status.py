"""Source registry status: configuration validation and health derived only from real evidence.

Evidence = finished scan runs of the source (ScanSource rows) and explicit connectivity tests (SourceCheck rows).
Nothing is assumed: a source with no evidence is "not tested", whatever its configuration says.

State (what the source *is* for this organization):
    live        enabled, configuration valid, most recent evidence not a failure (or no evidence yet)
    simulated   the bundled synthetic demo adapter (demo brand only; never a live substitute)
    disabled    switched off by an owner — not queried by any scan
    unavailable enabled, but its configuration is invalid or its most recent evidence is a failure
Health (what we last observed):
    not_tested | operational | no_results | degraded | rate_limited | failing | invalid_config | simulated
"""
from __future__ import annotations

import importlib.util
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Brand, Organization, Scan, ScanSource, SourceCheck
from ..serializers import iso
from ..sources.mastodon import valid_instance
from . import registry

FAILURE_OUTCOMES = {"rate_limited", "timeout", "unavailable", "auth_required", "error", "invalid_config"}
INTEGRATION_TYPES = {
    "official public API": "Official public API",
    "unofficial": "Unofficial scraper",
    "synthetic": "Synthetic dataset",
}
PLATFORMS = {
    "bluesky": "Bluesky (AT Protocol)",
    "mastodon": "Mastodon (fediverse)",
    "apple_app_store": "Apple App Store",
    "google_play": "Google Play",
    "youtube": "YouTube",
    "ct_domains": "Web domains (Certificate Transparency)",
    "demo": "Synthetic demo",
}
# ISO 3166-1 alpha-2 (storefront country for app-store searches).
ISO_COUNTRIES = set("""
ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz ca cc cd cf cg
ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz ec ee eg eh er es et fi fj fk fm fo fr ga gb gd ge gf gg gh gi gl
gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im in io iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la
lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np
nr nu nz om pa pe pf pg ph pk pl pm pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv
sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug um us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw
""".split())


def redact(text: str | None) -> str | None:
    """Defence in depth: strip configured secrets from any message before it is stored or returned."""
    if not text:
        return text
    secrets_ = [*get_settings().mastodon_tokens().values(), get_settings().youtube_key()]
    for token in secrets_:
        if token:
            text = text.replace(token, "[redacted]")
    return text


# ------------------------------------------------------------------ configuration


def config_problems(name: str, cfg: dict) -> list[str]:
    """Static configuration problems for one source (no network)."""
    problems: list[str] = []
    if name == "mastodon":
        inst = cfg.get("mastodon_instances") or []
        if not inst:
            problems.append("No Mastodon instance configured")
        bad = [i for i in inst if not valid_instance(i)]
        if bad:
            problems.append(f"Invalid instance hostname(s): {', '.join(bad)}")
    if name in ("apple_app_store", "google_play"):
        c = str(cfg.get("store_country", "")).lower()
        if c not in ISO_COUNTRIES:
            problems.append(f"Store country “{c}” is not an ISO 3166 country code")
    if name == "youtube" and not get_settings().youtube_key():
        problems.append("No API key: set SCAMSHIELD_YOUTUBE_API_KEY on the server")
    if name == "google_play" and importlib.util.find_spec("google_play_scraper") is None:
        problems.append("The google-play-scraper package is not installed on the server")
    return problems


def auth_status(name: str, cfg: dict) -> dict:
    """Authentication/credential status. Never includes secret values."""
    if name == "demo":
        return {"status": "not_required", "label": "No network access — bundled synthetic data", "credentials": []}
    if name == "mastodon":
        tokens = get_settings().mastodon_tokens()
        instances = cfg.get("mastodon_instances") or []
        creds = [{"instance": i, "configured": i in tokens, "source": "environment (SCAMSHIELD_MASTODON_ACCESS_TOKENS)" if i in tokens else None}
                 for i in instances]
        unused = sorted(set(tokens) - set(instances))
        label = ("Access token configured for " + ", ".join(i for i in instances if i in tokens)) if any(c["configured"] for c in creds) \
            else "Public access — no credentials required (optional token per instance)"
        return {"status": "configured" if any(c["configured"] for c in creds) else "not_required", "label": label, "credentials": creds,
                "unused_tokens_for": unused}
    if name == "youtube":
        has = bool(get_settings().youtube_key())
        return {"status": "configured" if has else "missing", "label": "API key configured on the server (SCAMSHIELD_YOUTUBE_API_KEY)" if has
                else "API key required — set SCAMSHIELD_YOUTUBE_API_KEY on the server", "credentials": [{"instance": "googleapis.com", "configured": has,
                "source": "environment (SCAMSHIELD_YOUTUBE_API_KEY)" if has else None}]}
    return {"status": "not_required", "label": "Public access — no credentials required", "credentials": []}


# ------------------------------------------------------------------ evidence


def _scan_health(ss: ScanSource) -> str:
    if ss.status == "ok":
        return "operational"
    if ss.status == "empty":
        return "no_results"
    if ss.failure_kind == "rate_limited":
        return "rate_limited"
    return "degraded" if ss.status == "partial" else "failing"


def _check_health(c: SourceCheck) -> str:
    return {"ok": "operational", "empty": "no_results", "rate_limited": "rate_limited", "invalid_config": "invalid_config"}.get(c.outcome, "failing")


def _scan_succeeded(ss: ScanSource) -> bool:
    """At least one genuine request succeeded (ok/empty outcomes), even if others failed."""
    if ss.status in ("ok", "empty"):
        return True
    oc = ss.query_outcomes or {}
    return ss.status == "partial" and (oc.get("ok", 0) + oc.get("empty", 0)) > 0


def _newest(*items: tuple[datetime | None, dict] | None) -> dict | None:
    present = [i for i in items if i and i[0]]
    return max(present, key=lambda i: i[0])[1] if present else None


def _scan_rows(db: Session, brand_ids: list[int], source: str, limit: int = 50) -> list[ScanSource]:
    if not brand_ids:
        return []
    return list(db.scalars(
        select(ScanSource).join(Scan).where(Scan.brand_id.in_(brand_ids), ScanSource.source == source)
        .order_by(ScanSource.id.desc()).limit(limit)
    ))


def _checks(db: Session, org_id: int, source: str, limit: int = 50) -> list[SourceCheck]:
    return list(db.scalars(
        select(SourceCheck).where(SourceCheck.organization_id == org_id, SourceCheck.source == source).order_by(SourceCheck.id.desc()).limit(limit)
    ))


def check_out(c: SourceCheck) -> dict:
    return {"id": c.id, "outcome": c.outcome, "detail": redact(c.detail), "result_count": c.result_count, "latency_ms": c.latency_ms,
            "rate_limit": c.rate_limit, "at": iso(c.created_at)}


def source_entry(db: Session, org: Organization, info, brand_ids: list[int]) -> dict:
    cfg = registry.source_config(org)
    name = info.name
    enabled = name == "demo" or name in cfg["enabled_sources"]
    problems = [] if name == "demo" else config_problems(name, cfg)
    runs = _scan_rows(db, brand_ids, name)
    finished = [r for r in runs if r.status not in ("pending", "running") and r.finished_at]
    checks = _checks(db, org.id, name)
    last_run = finished[0] if finished else None
    last_check = checks[0] if checks else None

    observed = _newest(
        (last_run.finished_at, {"via": "scan", "health": _scan_health(last_run), "at": last_run.finished_at, "scan_id": last_run.scan_id,
                                "detail": redact(last_run.error) or f"{last_run.candidates} candidate(s) from {last_run.queries_done} queries"}) if last_run else None,
        (last_check.created_at, {"via": "test", "health": _check_health(last_check), "at": last_check.created_at, "scan_id": None,
                                 "detail": redact(last_check.detail)}) if last_check else None,
    )
    ok_run = next((r for r in finished if _scan_succeeded(r)), None)
    ok_check = next((c for c in checks if c.outcome in ("ok", "empty")), None)
    last_success = _newest(
        (ok_run.finished_at, {"at": iso(ok_run.finished_at), "via": "scan", "scan_id": ok_run.scan_id,
                              "detail": f"Scan #{ok_run.scan_id}: {ok_run.candidates} candidate(s)"}) if ok_run else None,
        (ok_check.created_at, {"at": iso(ok_check.created_at), "via": "test", "scan_id": None, "detail": redact(ok_check.detail)}) if ok_check else None,
    )
    err_run = next((r for r in finished if r.status in ("failed", "partial") and r.error), None)
    err_check = next((c for c in checks if c.outcome in FAILURE_OUTCOMES), None)
    last_error = _newest(
        (err_run.finished_at, {"at": iso(err_run.finished_at), "via": "scan", "scan_id": err_run.scan_id, "kind": err_run.failure_kind or "error",
                               "message": redact(err_run.error)}) if err_run else None,
        (err_check.created_at, {"at": iso(err_check.created_at), "via": "test", "scan_id": None, "kind": err_check.outcome,
                                "message": redact(err_check.detail)}) if err_check else None,
    )
    attempted = runs[0] if runs else None

    # Observed rate-limit headers (most recent), and when the source last told us to slow down.
    rl_obs = _newest(
        (last_run.finished_at, {"values": last_run.rate_limit, "at": iso(last_run.finished_at), "via": "scan"}) if last_run and last_run.rate_limit else None,
        (last_check.created_at, {"values": last_check.rate_limit, "at": iso(last_check.created_at), "via": "test"}) if last_check and last_check.rate_limit else None,
    )
    last_limited_at = max([d for d in [next((r.finished_at for r in finished if r.failure_kind == "rate_limited"), None),
                                       next((c.created_at for c in checks if c.outcome == "rate_limited"), None)] if d], default=None)

    if name == "demo":
        health, state = "simulated", "simulated"
    else:
        health = "invalid_config" if problems else (observed["health"] if observed else "not_tested")
        if not enabled:
            state = "disabled"
        elif problems or health in ("failing", "rate_limited"):
            state = "unavailable"
        else:
            state = "live"

    return {
        "name": name,
        "label": info.label,
        "platform": PLATFORMS.get(name, info.label),
        "category": info.category,
        "integration_type": INTEGRATION_TYPES.get(info.reliability, info.reliability),
        "integration": info.integration,
        "reliability": info.reliability,
        "source_type": info.source_type,
        "docs_url": info.docs_url,
        "notes": info.notes,
        "enabled": enabled,
        "state": state,
        "health": health,
        "health_detail": observed["detail"] if observed else ("Never queried — run a connectivity test" if name != "demo" else "Synthetic data, no network"),
        "observed_at": iso(observed["at"]) if observed else None,
        "observed_via": observed["via"] if observed else None,
        "config": {"valid": not problems, "problems": problems},
        "auth": auth_status(name, cfg),
        "last_success": last_success,
        "last_error": last_error,
        "last_attempted_scan": {"scan_id": attempted.scan_id, "status": attempted.status, "at": iso(attempted.finished_at or attempted.started_at),
                                "candidates": attempted.candidates, "query_outcomes": attempted.query_outcomes or {}} if attempted else None,
        "last_test": check_out(last_check) if last_check else None,
        "rate_limit": {"documented": info.rate_limit or None, "observed": rl_obs, "last_rate_limited_at": iso(last_limited_at)},
        # Flat fields used by the dashboard and sidebar.
        "status": health,
        "unavailable": enabled and state == "unavailable",
        "last_success_at": last_success["at"] if last_success else None,
        "last_success_scan_id": last_success["scan_id"] if last_success else None,
        "checked_at": iso(observed["at"]) if observed else None,
        "detail": observed["detail"] if observed else "",
        "failure_kind": last_error["kind"] if last_error and state == "unavailable" else None,
    }


def registry_status(db: Session, org: Organization, brand_ids: list[int] | None = None, include_demo: bool = True) -> list[dict]:
    if brand_ids is None:
        brand_ids = list(db.scalars(select(Brand.id).where(Brand.organization_id == org.id)))
    return [source_entry(db, org, info, brand_ids) for info in registry.catalog() if include_demo or info.name != "demo"]
