"""ScamShield AI API."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import init_db
from .demo.assets import ensure_assets
from .routers import auth, brands, dashboard, findings, registry, scans, schedules, settings, sources, team
from .services import scanner
from .services.backfill import backfill_detection_types, migrate_legacy_schedules, migrate_legacy_source_tests
from .services.scheduler import scheduler_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    return {"status": "ok"}


for r in (auth.router, team.auth_router, team.router, brands.router, registry.router, brands.demo_router, scans.router, schedules.router, findings.router, dashboard.router, sources.router, settings.router):
    app.include_router(r)
