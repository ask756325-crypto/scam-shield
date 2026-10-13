"""ScamShield AI API."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import time

from .config import get_settings
from .observability import install_logging, metrics, new_request_id, request_id_var
from .db import init_db
from .demo.assets import ensure_assets
from .routers import auth, brands, dashboard, evaluation, findings, notifications, registry, scans, schedules, settings, sources, takedowns, team
from .services import scanner
from .services.backfill import backfill_detection_types, migrate_legacy_schedules, migrate_legacy_source_tests
from .services.scheduler import scheduler_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
from .logredact import install as _install_redaction  # noqa: E402

_install_redaction()
install_logging()
log = logging.getLogger("scamshield")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-scamshield-csrf"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    init_db()
    ensure_assets()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    backfill_detection_types()
    migrate_legacy_schedules()
    migrate_legacy_source_tests()
    n = scanner.mark_interrupted_scans(s.process_role)
    if n:
        log.warning("Marked %d interrupted scan(s) as failed", n)
    task = asyncio.create_task(scheduler_loop(s.scheduler_tick_seconds, s.process_role)) if s.scheduler_enabled else None
    if not s.scheduler_enabled:
        log.info("Scheduler disabled in this process; run `python -m app.worker` for scheduled scans")
    yield
    if task:
        task.cancel()
    running = list(scanner._running.values())
    for t in running:
        t.cancel()
    await asyncio.gather(*running, return_exceptions=True)


app = FastAPI(title="ScamShield AI API", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    rid = new_request_id(request.headers.get("x-request-id"))
    token = request_id_var.set(rid)
    started = time.perf_counter()
    try:
        response = await _secured(request, call_next)
    except Exception:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        response = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
    finally:
        request_id_var.reset(token)
    route = getattr(request.scope.get("route"), "path", None) or "unmatched"
    elapsed = time.perf_counter() - started
    if request.url.path.startswith("/api/"):
        metrics.observe(request.method, route, response.status_code, elapsed)
    response.headers["X-Request-ID"] = rid
    return response


async def _secured(request: Request, call_next):
    # CSRF: state-changing API calls must carry a custom header. Browsers cannot attach custom headers
    # to cross-site requests without a CORS preflight, which this API never approves.
    if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/") and request.headers.get(CSRF_HEADER) != "1":
        return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
    response = await call_next(request)
    # A 401 while a session cookie was sent means the session expired or was revoked: clear the stale cookie
    # (so the UX middleware stops treating the browser as signed in — no redirect loops) and tell the client why.
    cookie_name = get_settings().session_cookie_name
    if response.status_code == 401 and request.cookies.get(cookie_name) and request.url.path.startswith("/api/"):
        response.delete_cookie(cookie_name, path="/")
        response.headers["X-Session-State"] = "expired"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Return concise, safe validation messages (no echo of submitted secrets)."""
    errors = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
        msg = str(e.get("msg", "Invalid value")).removeprefix("Value error, ")
        errors.append({"field": loc, "message": msg})
    summary = "; ".join(f"{e['field']}: {e['message']}" if e["field"] else e["message"] for e in errors[:5])
    return JSONResponse({"detail": summary or "Invalid request", "errors": errors}, status_code=422)


@app.get("/api/health")
def health():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready():
    """Readiness: the database answers. Load balancers should route traffic only when this returns 200."""
    from sqlalchemy import text

    from .db import engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception as e:
        log.error("readiness check failed: %s", type(e).__name__)
        return JSONResponse({"status": "unavailable", "database": "unreachable"}, status_code=503)


@app.get("/api/metrics", include_in_schema=False)
def prometheus_metrics(request: Request):
    """Prometheus text metrics. Requires `Authorization: Bearer <SCAMSHIELD_METRICS_TOKEN>`; 404 when no token is set."""
    import hmac

    from fastapi.responses import PlainTextResponse
    from sqlalchemy import func, select

    from .db import SessionLocal
    from .models import Finding, NotificationLog, Scan
    from .services.scheduler import scheduler_status

    expected = get_settings().metrics_token.get_secret_value() if get_settings().metrics_token else ""
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not expected:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if not hmac.compare_digest(given, expected):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    lines = metrics.render()
    with SessionLocal() as db:
        lines += ["# HELP scamshield_scans_total Scans by status (all organizations)", "# TYPE scamshield_scans_total gauge"]
        for status_, n in db.execute(select(Scan.status, func.count()).group_by(Scan.status)).all():
            lines.append(f'scamshield_scans_total{{status="{status_}"}} {n}')
        lines += ["# HELP scamshield_findings_open Findings needing review by level", "# TYPE scamshield_findings_open gauge"]
        for lvl, n in db.execute(select(Finding.risk_level, func.count()).where(Finding.status.in_(["open", "escalated"])).group_by(Finding.risk_level)).all():
            lines.append(f'scamshield_findings_open{{level="{lvl}"}} {n}')
        failed = db.scalar(select(func.count()).select_from(NotificationLog).where(NotificationLog.status == "failed")) or 0
        lines += ["# TYPE scamshield_notifications_failed_total gauge", f"scamshield_notifications_failed_total {failed}"]
        st = scheduler_status(db)
    age = -1
    if st["last_tick_at"]:
        from datetime import datetime, timezone

        age = int((datetime.now(timezone.utc) - datetime.fromisoformat(st["last_tick_at"])).total_seconds())
    lines += ["# HELP scamshield_scheduler_last_tick_age_seconds Seconds since the scheduler last ran (-1 = never)",
              "# TYPE scamshield_scheduler_last_tick_age_seconds gauge", f"scamshield_scheduler_last_tick_age_seconds {age}"]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


for r in (auth.router, team.auth_router, team.router, brands.router, registry.router, brands.demo_router, scans.router, schedules.router, findings.router, evaluation.router, evaluation.campaigns_router, evaluation.reports_router, notifications.router, takedowns.router, dashboard.router, sources.router, settings.router):
    app.include_router(r)
