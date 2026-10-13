"""Scan orchestration: collect → deduplicate → exclude officials → score → persist → compare.

* Every source runs independently; one failing source never stops the others.
* Progress is computed from completed work units (queries per source + image + scoring stages).
* Synthetic data is only produced by the explicit `demo` source and is never substituted for live failures.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..candidate import CandidateRecord
from ..config import get_settings
from ..db import SessionLocal
from ..demo.assets import asset_path
from ..detection.engine import BrandContext, EvaluatedCandidate, evaluate, record_key
from ..detection.exclusion import OfficialAccountRef, OfficialAppRef
from ..detection.logo import InvalidImage, compute_hashes
from ..detection.similarity import name_similarity
from ..detection.variants import generate_search_terms
from ..models import Brand, Candidate, Decision, Exclusion, Finding, FindingChange, Observation, Organization, Scan, ScanSource
from ..netsafe import UnsafeURL, fetch_image
from ..sources.base import SourceAdapter, SourceError
from ..sources.importer import ImportAdapter
from . import registry
from .org_settings import monitoring_settings

log = logging.getLogger("scamshield.scanner")

MAX_IMAGE_FETCHES = 80
# Outcomes worth one retry (network blips, 5xx). Rate limits have their own rule; auth/4xx errors are not retried.
TRANSIENT = ("timeout", "unavailable")
IMAGE_CONCURRENCY = 6
_running: dict[int, asyncio.Task] = {}
_pending_imports: dict[int, list[CandidateRecord]] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Indirection points so tests can inject fakes without monkeypatching network libraries.
AdapterFactory = Callable[[str, dict, list[str], int], SourceAdapter]
adapter_factory: AdapterFactory = registry.build_adapter


async def default_image_loader(client: httpx.AsyncClient, url: str, extra_hosts: list[str]) -> bytes:
    if url.startswith("demo-asset://"):
        path = asset_path(url.removeprefix("demo-asset://"))
        if not path:
            raise UnsafeURL("Unknown demo asset")
        return path.read_bytes()
    return await fetch_image(client, url, extra_hosts)


image_loader: Callable[[httpx.AsyncClient, str, list[str]], Awaitable[bytes]] = default_image_loader


# --------------------------------------------------------------------------- scan creation


def brand_context(brand: Brand) -> BrandContext:
    return BrandContext(
        name=brand.name,
        aliases=list(brand.aliases or []),
        description=brand.description or "",
        keywords=list(brand.keywords or []),
        official_domains=list(brand.official_domains or []),
        logo_hashes={"phash": brand.logo_phash, "dhash": brand.logo_dhash} if brand.logo_phash else None,
        official_accounts=[OfficialAccountRef(a.platform, a.handle, a.profile_url, a.external_id) for a in brand.official_accounts],
        official_apps=[OfficialAppRef(a.store, a.app_id, a.track_id, a.publisher_id, a.publisher_name) for a in brand.official_apps],
        additional_identifiers=list(brand.additional_identifiers or []),
        exclusion_rules=brand.exclusion_rules or {},
    )


def resolve_sources(brand: Brand, org: Organization, requested: list[str] | None) -> list[str]:
    cfg = registry.source_config(org)
    allowed = set(cfg["enabled_sources"]) | ({"demo"} if brand.is_demo else set())
    if requested is None:
        return ["demo"] if brand.is_demo else cfg["enabled_sources"]
    bad = [s for s in requested if s not in allowed]
    if bad:
        raise ValueError(f"Source(s) not available for this brand: {', '.join(bad)}")
    return list(dict.fromkeys(requested))


def active_scan(db: Session, brand_id: int) -> Scan | None:
    return db.scalar(select(Scan).where(Scan.brand_id == brand_id, Scan.status.in_(["queued", "running"])))


def create_import_scan(db: Session, brand: Brand, records: list[CandidateRecord], user_id: int) -> Scan:
    scan = create_scan(db, brand, ["import"], "import", user_id)
    _pending_imports[scan.id] = records
    return scan


class ScanConflict(Exception):
    """Another scan for the brand is queued or running (enforced by a unique index across processes)."""

    def __init__(self, scan_id: int | None):
        super().__init__(f"Scan #{scan_id} is already running for this brand")
        self.scan_id = scan_id


def create_scan(db: Session, brand: Brand, sources: list[str], trigger: str, user_id: int | None,
                schedule_id: int | None = None, runner: str | None = None) -> Scan:
    if not sources:
        raise ValueError("No sources enabled. Enable at least one source on the Sources page.")
    mode = "import" if sources == ["import"] else "demo" if sources == ["demo"] else "live"
    scan = Scan(
        brand_id=brand.id,
        trigger=trigger,
        mode=mode,
        status="queued",
        created_by_id=user_id,
        schedule_id=schedule_id,
        runner=runner or get_settings().process_role,
        heartbeat_at=utcnow(),
        sources=[ScanSource(source=s) for s in sources],
    )
    db.add(scan)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        running = active_scan(db, brand.id)
        raise ScanConflict(running.id if running else None) from None
    return scan


def launch(scan_id: int) -> asyncio.Task:
    task = asyncio.create_task(run_scan(scan_id))
    _running[scan_id] = task
    task.add_done_callback(lambda _: _running.pop(scan_id, None))
    return task


def mark_interrupted_scans(runner: str | None = None) -> int:
    """On startup, scans this process role left running are marked failed (not silently resumed).

    Scans owned by another role (e.g. the worker while the API restarts) are left alone; if that process
    really died, the scheduler's stall sweep fails them after a timeout."""
    runner = runner or get_settings().process_role
    with SessionLocal() as db:
        stale = db.scalars(
            select(Scan).where(Scan.status.in_(["queued", "running"]), (Scan.runner == runner) | Scan.runner.is_(None))
        ).all()
        for s in stale:
            s.status = "failed"
            s.error = "Interrupted by server restart"
            s.finished_at = utcnow()
            for ss in s.sources:
                if ss.status in ("pending", "running"):
                    ss.status = "failed"
                    ss.error = "Interrupted by server restart"
        db.commit()
        return len(stale)


# --------------------------------------------------------------------------- execution


async def run_scan(scan_id: int) -> None:
    settings = get_settings()
    db = SessionLocal()
    cancelled = False
    try:
        scan = db.get(Scan, scan_id)
        if not scan:
            return
        brand = scan.brand
        org = db.get(Organization, brand.organization_id)
        cfg = registry.source_config(org)
        limits = monitoring_settings(org)
        scan.status, scan.started_at, scan.stage, scan.heartbeat_at = "running", utcnow(), "Generating search terms", utcnow()
        if scan.mode == "import":
            terms = ["imported file"]
        else:
            terms = generate_search_terms(brand.name, list(brand.aliases or []))[: limits["max_queries_per_source"]]
        scan.search_terms = terms
        ctx = brand_context(brand)
        demo_epoch = 0
        if any(ss.source == "demo" for ss in scan.sources):
            demo_epoch = len(
                db.scalars(
                    select(Scan.id).where(Scan.brand_id == brand.id, Scan.mode == "demo", Scan.status.in_(["completed", "partial"]), Scan.id != scan.id)
                ).all()
            )
        adapters = {
            ss.source: ImportAdapter(_pending_imports.pop(scan.id, [])) if ss.source == "import" else adapter_factory(ss.source, cfg, ctx.names, demo_epoch)
            for ss in scan.sources
        }
        for ss in scan.sources:
            ss.queries_total = len(terms)
        total_units = len(terms) * len(scan.sources) + 2
        done_units = 0

        def advance(n: int = 1) -> None:
            nonlocal done_units
            done_units += n
            scan.progress = round(min(done_units / total_units, 0.99), 3)
            scan.heartbeat_at = utcnow()
            db.commit()

        db.commit()
        timeout = httpx.Timeout(settings.http_timeout_seconds, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": settings.user_agent, "Accept": "application/json"}) as client:
            scan.stage = "Collecting from sources"
            db.commit()
            collected = await asyncio.gather(
                *(_collect(db, ss, adapters[ss.source], terms, client, advance, limits["source_time_budget_seconds"]) for ss in scan.sources),
                return_exceptions=True,
            )
            records: dict[str, CandidateRecord] = {}
            for ss, res in zip(scan.sources, collected):
                if isinstance(res, BaseException):  # defensive: _collect handles its own errors
                    ss.status, ss.error = "failed", f"Unexpected error: {type(res).__name__}"
                    continue
                for r in res:
                    key = record_key(r)
                    if key in records:
                        first = records[key].provenance.get("query")
                        q = records[key].provenance.setdefault("queries", [first] if first else [])
                        if r.provenance.get("query") and r.provenance.get("query") not in q:
                            q.append(r.provenance.get("query"))
                    else:
                        records[key] = r
            scan.candidates_collected = sum(ss.candidates for ss in scan.sources)
            scan.candidates_unique = len(records)
            db.commit()

            scan.stage = "Comparing logos"
            db.commit()
            hashes, image_errors = await _hash_images(client, list(records.values()), ctx, cfg, limits["max_image_fetches"])
            advance()

        scan.stage = "Scoring candidates"
        db.commit()
        evaluated = await asyncio.to_thread(evaluate, ctx, list(records.values()), hashes, image_errors, org.detection_config)
        _persist(db, scan, brand, evaluated)
        advance()

        statuses = [ss.status for ss in scan.sources]
        if all(s in ("ok", "empty") for s in statuses):
            scan.status = "completed"
        elif any(s in ("ok", "empty", "partial") for s in statuses):
            scan.status = "partial"
        else:
            scan.status = "failed"
            scan.error = scan.error or "All sources failed"
        scan.progress, scan.stage, scan.finished_at = 1.0, "Finished", utcnow()
        db.commit()
    except (Exception, asyncio.CancelledError) as exc:  # never leave a scan stuck in "running"
        cancelled = isinstance(exc, asyncio.CancelledError)
        if not cancelled:
            log.exception("scan %s failed", scan_id)
        db.rollback()
        scan = db.get(Scan, scan_id)
        if scan:
            scan.status, scan.stage, scan.finished_at = "failed", "Failed", utcnow()
            scan.error = "Cancelled: the process running it shut down" if cancelled else f"{type(exc).__name__}: {exc}"[:500]
            for ss in scan.sources:
                if ss.status in ("pending", "running"):
                    ss.status, ss.error = "failed", ss.error or scan.error
            db.commit()
        if cancelled:
            raise
    finally:
        db.close()
        from .scheduler import on_scan_finished  # local import: scheduler imports this module

        on_scan_finished(scan_id)
        if not cancelled:
            from .notifications import notify_scan_finished

            # Alerts (email/webhook) can block on network I/O: run them off the event loop.
            await asyncio.to_thread(notify_scan_finished, scan_id)


async def _collect(db: Session, ss: ScanSource, adapter: SourceAdapter, terms: list[str], client: httpx.AsyncClient, advance,
                   budget_seconds: float | None = None) -> list[CandidateRecord]:
    """Run every query for one source, recording a per-query outcome:
    ok | empty | rate_limited | timeout | unavailable | auth_required | error."""
    settings = get_settings()
    t0 = time.monotonic()
    ss.status, ss.started_at = "running", utcnow()
    outcomes: dict[str, int] = {}
    ss.query_outcomes = {}
    db.commit()
    out: list[CandidateRecord] = []
    errors: list[str] = []
    deadline = t0 + (budget_seconds or settings.source_timeout_seconds)

    def record(kind: str, n: int = 1) -> None:
        outcomes[kind] = outcomes.get(kind, 0) + n
        ss.query_outcomes = dict(outcomes)
        if kind not in ("ok", "empty"):
            ss.queries_failed += n
        ss.queries_done += n
        advance(n)

    for idx, term in enumerate(terms):
        if time.monotonic() > deadline:
            errors.append(f"“{term}”: source time budget exhausted")
            record("timeout")
            continue
        if idx and adapter.min_interval_seconds:
            await asyncio.sleep(adapter.min_interval_seconds)
        kind = None
        for attempt in (1, 2):
            try:
                recs = await asyncio.wait_for(adapter.search(term, client), timeout=settings.http_timeout_seconds + 5)
                out.extend(recs)
                kind = "ok" if recs else "empty"
                break
            except SourceError as e:
                if e.kind == "rate_limited" and attempt == 1 and (e.retry_after if e.retry_after is not None else 2) <= 10:
                    await asyncio.sleep(e.retry_after if e.retry_after is not None else 2)
                    continue
                if e.kind in TRANSIENT and attempt == 1 and time.monotonic() + settings.source_retry_delay_seconds < deadline:
                    await asyncio.sleep(settings.source_retry_delay_seconds)  # one retry for a transient outage
                    continue
                errors.append(f"“{term}”: {e}")
                kind = e.kind
                break
            except asyncio.TimeoutError:
                if attempt == 1 and time.monotonic() + settings.source_retry_delay_seconds < deadline:
                    await asyncio.sleep(settings.source_retry_delay_seconds)
                    continue
                errors.append(f"“{term}”: timed out")
                kind = "timeout"
                break
            except Exception as e:  # adapter bug or unexpected payload
                errors.append(f"“{term}”: {type(e).__name__}")
                kind = "error"
                break
        record(kind or "error")
        ss.candidates = len({record_key(r) for r in out})
        if kind in ("rate_limited", "auth_required"):
            # Stop hammering a source that is rejecting us; the rest are reported as not attempted for that reason.
            remaining = len(terms) - idx - 1
            if remaining:
                errors.append(f"{remaining} remaining quer{'y' if remaining == 1 else 'ies'} not attempted ({kind.replace('_', ' ')})")
                record(kind, remaining)
            return _finish(db, ss, out, errors, t0, adapter)
        db.commit()
    if out:
        try:
            out = await asyncio.wait_for(adapter.enrich(out, client), timeout=settings.source_timeout_seconds)
        except Exception as e:
            errors.append(f"enrichment failed: {type(e).__name__}")
    return _finish(db, ss, out, errors, t0, adapter)


def _finish(db, ss, out, errors, t0, adapter) -> list[CandidateRecord]:
    skipped = getattr(adapter, "skipped_without_id", 0)
    if skipped:
        errors.append(f"{skipped} result(s) skipped: package ID could not be parsed")
    warnings = list(getattr(adapter, "warnings", []) or [])
    errors.extend(warnings)
    ss.candidates = len({record_key(r) for r in out})
    outcomes = dict(ss.query_outcomes or {})
    failures = {k: v for k, v in outcomes.items() if k not in ("ok", "empty")}
    if ss.queries_failed == 0 and not warnings:
        ss.status = "ok" if ss.candidates else "empty"
    elif ss.queries_failed < ss.queries_total:
        ss.status = "partial"
    else:
        ss.status = "failed"
    # Dominant failure reason (rate limited, timed out, …) for a precise status label.
    ss.failure_kind = max(failures, key=failures.get) if failures else ("unavailable" if warnings else None)
    rl = getattr(adapter, "instance_rate_limits", None) or ({"default": adapter.rate_limit.to_dict()} if adapter.rate_limit else None)
    ss.rate_limit = rl
    ss.error = "; ".join(errors)[:2000] or None
    ss.duration_ms = int((time.monotonic() - t0) * 1000)
    ss.finished_at = utcnow()
    db.commit()
    return out


async def _hash_images(client, records: list[CandidateRecord], ctx: BrandContext, cfg: dict, max_fetches: int = MAX_IMAGE_FETCHES) -> tuple[dict, dict]:
    hashes: dict[str, dict | None] = {}
    errors: dict[str, str] = {}
    if not ctx.logo_hashes:
        return hashes, errors
    # Only fetch images for candidates that plausibly relate to the brand (bounded outbound traffic).
    ranked = sorted(
        (r for r in records if r.avatar_url and not r.image_hashes),
        key=lambda r: name_similarity(r.name, ctx.names).score if r.name else 0,
        reverse=True,
    )
    relevant = [r for r in ranked if name_similarity(r.name, ctx.names).score >= 0.5]
    eligible = relevant[:max_fetches]
    for r in records:
        if r.avatar_url and r not in eligible and not r.image_hashes:
            errors[record_key(r)] = (
                f"Image not fetched (organization limit of {max_fetches} image(s) per scan reached)" if r in relevant
                else "Image not fetched (candidate below name-relevance prefilter)"
            )
        elif not r.avatar_url:
            errors[record_key(r)] = "Candidate has no avatar/icon"
    sem = asyncio.Semaphore(IMAGE_CONCURRENCY)
    extra_hosts = list(cfg.get("mastodon_instances", []))

    async def one(r: CandidateRecord):
        async with sem:
            try:
                data = await asyncio.wait_for(image_loader(client, r.avatar_url, extra_hosts), timeout=15)
                hashes[record_key(r)] = await asyncio.to_thread(compute_hashes, data)
            except (UnsafeURL, InvalidImage) as e:
                errors[record_key(r)] = f"Image not analyzed: {e}"
            except Exception as e:
                errors[record_key(r)] = f"Image fetch failed: {type(e).__name__}"

    await asyncio.gather(*(one(r) for r in eligible))
    return hashes, errors


# --------------------------------------------------------------------------- persistence & comparison


# Candidate fields compared between observations to report *what* changed.
TRACKED_FIELDS = ("name", "handle", "url", "description", "avatar_url", "publisher_name", "publisher_id", "external_links")


def _snapshot(c: Candidate) -> dict:
    return {k: getattr(c, k) for k in TRACKED_FIELDS}


def _short(v):
    if isinstance(v, list):
        return [str(x)[:300] for x in v[:20]]
    return v[:300] if isinstance(v, str) else v


def resolve_after_misses(org: Organization | None) -> int:
    return monitoring_settings(org)["resolve_after_misses"]


def _persist(db: Session, scan: Scan, brand: Brand, evaluated: list[EvaluatedCandidate]) -> None:
    now = utcnow()
    seen_finding_ids: set[int] = set()
    existing = {
        (c.source, c.external_id): c for c in db.scalars(select(Candidate).where(Candidate.brand_id == brand.id)).all()
    }
    for ev in evaluated:
        r = ev.record
        if ev.excluded:
            db.add(
                Exclusion(
                    brand_id=brand.id, scan_id=scan.id, source=r.source, external_id=r.external_id, name=r.name[:500],
                    url=r.url, rule=ev.excluded.rule, matched_value=ev.excluded.matched_value[:500],
                )
            )
            scan.excluded_official += 1
            continue
        a = ev.assessment
        cand = existing.get((r.source, r.external_id))
        if not a.relevant and cand is None:
            continue  # unrelated public profiles are counted but not retained (data minimization)
        new_hash = r.content_hash()
        prior_hash = cand.content_hash if cand else None
        before = _snapshot(cand) if cand else None
        if cand is None:
            cand = Candidate(brand_id=brand.id, source=r.source, external_id=r.external_id, first_observed_at=now)
            db.add(cand)
        cand.source_type, cand.kind = r.source_type, r.kind
        cand.name, cand.handle, cand.url = r.name[:500], r.handle, r.url
        cand.description, cand.avatar_url = r.description[:10000], r.avatar_url
        cand.publisher_name, cand.publisher_id = r.publisher_name, r.publisher_id
        cand.external_links, cand.extra, cand.provenance = r.external_links[:50], r.metadata, r.provenance
        cand.content_hash, cand.last_observed_at, cand.source_created_at = new_hash, now, r.source_created_at
        db.flush()
        db.add(Observation(scan_id=scan.id, candidate_id=cand.id, content_hash=new_hash, risk_score=a.risk_score, observed_at=now))

        f = cand.finding
        after = _snapshot(cand)
        is_new = False
        if f is None:
            f = Finding(brand_id=brand.id, candidate_id=cand.id, first_seen_scan_id=scan.id, change_state="new", status="open", created_at=now)
            db.add(f)
            scan.findings_new += 1
            is_new = True
        else:
            content_changed = prior_hash != new_hash
            fields = [k for k in TRACKED_FIELDS if before and before.get(k) != after.get(k)]
            was_gone = f.change_state in ("missing", "resolved")
            change = "reappeared" if was_gone else "changed" if (content_changed or f.risk_level != a.risk_level) else "recurring"
            db.add(FindingChange(
                scan_id=scan.id, finding_id=f.id, change=change, changed_fields=fields,
                previous={k: _short(before[k]) for k in fields}, current={k: _short(after[k]) for k in fields},
                risk_before=f.risk_level, risk_after=a.risk_level, missed_scans=f.missed_scans or 0, created_at=now,
            ))
            f.missed_scans = 0
            if content_changed or f.risk_level != a.risk_level:
                f.change_state = "changed"
                scan.findings_changed += 1
                risk_increased = _rank(a.risk_level) < _rank(f.risk_level)
                if f.status == "safe" and (content_changed or risk_increased):
                    f.status = "open"
                    f.decisions.append(Decision(action="reopen", note="Automatically reopened: listing changed after it was marked safe.",
                                                from_status="safe", to_status="open"))
            else:
                f.change_state = "recurring"
                scan.findings_recurring += 1
            if f.status == "resolved":
                f.status = "open"
        f.risk_score, f.risk_level = a.risk_score, a.risk_level
        f.classification, f.explanation = a.classification, a.explanation
        f.detection_type = a.detection_type
        f.signals = {"signals": a.signals, "groups": a.group_scores, "not_evaluated": a.not_evaluated}
        f.reasons, f.corroborating_groups = a.reasons, a.corroborating_groups
        f.last_seen_scan_id, f.updated_at = scan.id, now
        db.flush()
        if is_new:
            db.add(FindingChange(scan_id=scan.id, finding_id=f.id, change="new", risk_after=a.risk_level, created_at=now))
        seen_finding_ids.add(f.id)

    _apply_absence_rules(db, scan, brand, seen_finding_ids, now)
    from .takedowns import verify_after_scan

    verify_after_scan(db, scan)
    db.commit()


def _apply_absence_rules(db: Session, scan: Scan, brand: Brand, seen: set[int], now: datetime) -> None:
    """Explicit resolution rules for findings this scan did not observe.

    1. Only a source that completed *cleanly* (every query succeeded: `ok`, or `empty` = searched, nothing
       found) can say a finding is absent. Each such scan increments the finding's `missed_scans`.
    2. Below the organization's threshold (`resolve_after_misses`, default 2) the finding is **missing**;
       at the threshold it is **resolved** ("no longer observed") and an open finding leaves the queue.
       Search results are ranked and capped, so one clean miss alone is weak evidence.
    3. A failed, partial or skipped source proves nothing: its findings are **unverified** for this scan and
       their miss count is unchanged.
    4. Imports are partial snapshots and never count as absence. Findings of sources not in this scan are untouched.
    5. Observing a finding again resets the count; a resolved one reopens (recorded as *reappeared*).
    """
    threshold = resolve_after_misses(db.get(Organization, brand.organization_id))
    by_source = {ss.source: ss.status for ss in scan.sources if ss.source != "import"}
    if not by_source:
        return
    rows = db.execute(
        select(Finding, Candidate.source).join(Candidate).where(
            Finding.brand_id == brand.id, Finding.change_state != "resolved", Candidate.source.in_(list(by_source))
        )
    ).all()
    for f, source in rows:
        if f.id in seen:
            continue
        if by_source[source] in ("ok", "empty"):
            f.missed_scans = (f.missed_scans or 0) + 1
            if f.missed_scans >= threshold:
                f.change_state = "resolved"
                if f.status == "open":
                    f.status = "resolved"
                scan.findings_resolved += 1
                change = "resolved"
            else:
                f.change_state = "missing"
                scan.findings_missing += 1
                change = "missing"
            f.updated_at = now
        else:
            scan.findings_unverified += 1
            change = "unverified"
        db.add(FindingChange(scan_id=scan.id, finding_id=f.id, change=change, risk_before=f.risk_level, risk_after=f.risk_level,
                             missed_scans=f.missed_scans or 0, created_at=now))


def _rank(level: str) -> int:
    return ["critical", "high", "medium", "low", "info"].index(level) if level in ("critical", "high", "medium", "low", "info") else 9
