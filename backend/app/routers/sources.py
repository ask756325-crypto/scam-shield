"""Sources & Integrations: registry status, validated configuration, genuine connectivity tests."""
from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..services import audit as audit_log
from ..deps import Principal, get_principal, require_owner
from ..models import Organization, SourceCheck
from ..netsafe import UnsafeURL, resolve_public
from ..schemas import SourceConfigIn
from ..security import rate_limiter
from ..services import registry
from ..services.source_status import ISO_COUNTRIES, check_out, config_problems, redact, registry_status
from ..sources.base import SourceError
from ..sources.mastodon import valid_instance

router = APIRouter(prefix="/api/sources", tags=["sources"])

TEST_QUERY = "news"  # neutral, high-recall term: proves connectivity without searching for any brand
_verified_instances: dict[str, float] = {}  # host -> verified at (monotonic)


@router.get("")
def list_sources(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    entries = registry_status(db, p.org)
    for e in entries:
        e["health_status"] = e["health"]
    return {
        "sources": entries,
        "unavailable": registry.UNAVAILABLE_SOURCES,  # platforms that are not integrated at all
        "config": registry.source_config(p.org),
    }


async def verify_mastodon_instance(host: str) -> None:
    """Check that `host` is a public Mastodon-compatible server before it can be saved."""
    s = get_settings()
    cached = _verified_instances.get(host)
    if cached and time.monotonic() - cached < s.instance_validation_cache_seconds:
        return
    try:
        await resolve_public(host)
    except UnsafeURL as e:
        raise HTTPException(422, {"field": "mastodon_instances", "message": f"{host}: {e}"})
    except OSError:
        raise HTTPException(422, {"field": "mastodon_instances", "message": f"{host}: hostname does not resolve"})
    url = f"https://{host}/api/v2/instance"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=5.0), headers={"User-Agent": s.user_agent}, follow_redirects=False) as c:
            r = await c.get(url)
    except httpx.TimeoutException:
        raise HTTPException(422, {"field": "mastodon_instances", "message": f"{host}: timed out while verifying the instance"})
    except httpx.HTTPError as e:
        raise HTTPException(422, {"field": "mastodon_instances", "message": f"{host}: could not connect ({type(e).__name__})"})
    try:
        body = r.json() if r.status_code == 200 else None
    except ValueError:
        body = None
    if not isinstance(body, dict) or not (body.get("domain") or body.get("uri")):
        raise HTTPException(422, {"field": "mastodon_instances", "message": f"{host}: not a Mastodon-compatible server (GET /api/v2/instance returned HTTP {r.status_code})"})
    _verified_instances[host] = time.monotonic()


@router.put("/config")
async def update_config(body: SourceConfigIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """Validate everything before saving: unknown sources, hostnames, storefront country, and that each newly
    added Mastodon instance really is a reachable public Mastodon server."""
    unknown = [s for s in body.enabled_sources if s not in registry.LIVE_ADAPTERS]
    if unknown:
        raise HTTPException(422, {"field": "enabled_sources", "message": f"Unknown source(s): {', '.join(unknown)}"})
    instances: list[str] = []
    for i in body.mastodon_instances:
        i = i.strip().lower().removeprefix("https://").strip("/")
        if not valid_instance(i):
            raise HTTPException(422, {"field": "mastodon_instances", "message": f"Invalid Mastodon instance hostname: {i}"})
        if i not in instances:
            instances.append(i)
    country = body.store_country.lower().strip()
    if country not in ISO_COUNTRIES:
        raise HTTPException(422, {"field": "store_country", "message": f"“{body.store_country}” is not an ISO 3166 two-letter country code"})
    org = db.get(Organization, p.org.id)
    current = registry.source_config(org)
    new_cfg = {"enabled_sources": list(dict.fromkeys(body.enabled_sources)), "mastodon_instances": instances, "store_country": country}
    for name in new_cfg["enabled_sources"]:
        problems = config_problems(name, new_cfg)
        if problems:
            raise HTTPException(422, {"field": name, "message": f"Cannot enable {name}: {'; '.join(problems)}"})
    added = [i for i in instances if i not in current["mastodon_instances"]]
    if added and "mastodon" in new_cfg["enabled_sources"]:
        for host in added:
            await verify_mastodon_instance(host)
    cfg = dict(org.source_config or {})
    before = {k: current[k] for k in ("enabled_sources", "mastodon_instances", "store_country")}
    cfg.update(new_cfg)
    org.source_config = cfg
    audit_log.record(db, p, "sources.config_updated", "organization", org.id, "Source settings changed", {"before": before, "after": new_cfg})
    db.commit()
    return registry.source_config(org)


@router.post("/{name}/test")
async def test_source(name: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Run one real query against the source and record the genuine outcome (no synthetic fallback).

    Works for disabled sources too, so a configuration can be checked before it is enabled."""
    if name == "demo":
        raise HTTPException(400, "The synthetic demo adapter makes no network requests, so there is no connectivity to test.")
    if name not in registry.LIVE_ADAPTERS:
        raise HTTPException(404, "Unknown source")
    ok, _ = rate_limiter.hit(f"srctest:{p.org.id}:{name}", 6, 60)
    if not ok:
        raise HTTPException(429, "Too many connection tests; wait a minute.")
    org = db.get(Organization, p.org.id)
    cfg = registry.source_config(org)
    s = get_settings()
    check = SourceCheck(organization_id=org.id, source=name, created_by_id=p.user.id)
    problems = config_problems(name, cfg)
    t0 = time.monotonic()
    if problems:
        check.outcome, check.detail = "invalid_config", "; ".join(problems)
    else:
        adapter = registry.build_adapter(name, cfg, ["test"])
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(s.http_timeout_seconds, connect=8.0), headers={"User-Agent": s.user_agent}) as client:
                recs = await asyncio.wait_for(adapter.search(TEST_QUERY, client), timeout=s.http_timeout_seconds + 5)
            check.result_count = len(recs)
            warnings = list(getattr(adapter, "warnings", []) or [])
            if recs:
                check.outcome, check.detail = "ok", f"Live query “{TEST_QUERY}” returned {len(recs)} result(s)"
            else:
                check.outcome, check.detail = "empty", f"The source responded, but the query “{TEST_QUERY}” returned no results"
            if warnings:
                check.detail += " — some instances failed: " + "; ".join(warnings)
        except SourceError as e:
            check.outcome, check.detail = e.kind, str(e)
        except asyncio.TimeoutError:
            check.outcome, check.detail = "timeout", f"{name} did not answer within {int(s.http_timeout_seconds + 5)} s"
        except Exception as e:  # adapter bug or unexpected payload — reported, never hidden
            check.outcome, check.detail = "error", f"Unexpected {type(e).__name__}"
        rl = getattr(adapter, "instance_rate_limits", None) or ({"default": adapter.rate_limit.to_dict()} if adapter.rate_limit else None)
        check.rate_limit = rl
    check.latency_ms = int((time.monotonic() - t0) * 1000)
    check.detail = redact(check.detail)[:2000]
    db.add(check)
    db.commit()
    db.refresh(check)
    return {**check_out(check), "status": {"ok": "ok", "empty": "empty", "rate_limited": "rate_limited"}.get(check.outcome, "failed"),
            "source": name, "enabled": name in cfg["enabled_sources"]}


@router.get("/{name}/checks")
def list_checks(name: str, limit: int = 20, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if name not in registry.LIVE_ADAPTERS:
        raise HTTPException(404, "Unknown source")
    rows = db.scalars(
        select(SourceCheck).where(SourceCheck.organization_id == p.org.id, SourceCheck.source == name)
        .order_by(SourceCheck.id.desc()).limit(min(max(limit, 1), 100))
    ).all()
    return [check_out(c) for c in rows]
