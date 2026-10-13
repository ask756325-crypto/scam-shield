"""Dedicated scheduler worker — the production way to run recurring scans.

    SCAMSHIELD_PROCESS_ROLE=worker python -m app.worker

Run exactly one worker (more are safe — schedule claims are compare-and-set — but unnecessary), and set
SCAMSHIELD_SCHEDULER_ENABLED=false on every API process. The worker needs the same database URL and source
settings as the API. Scheduled scans run inside the worker; manual scans run in the API process.
Stop it with Ctrl+C / SIGTERM: scans in progress are marked failed ("Cancelled") rather than left running.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from .config import get_settings
from .db import init_db
from .demo.assets import ensure_assets
from .services import scanner
from .services.backfill import migrate_legacy_schedules
from .services.scheduler import scheduler_loop

log = logging.getLogger("scamshield.worker")


async def main() -> None:
    os.environ.setdefault("SCAMSHIELD_PROCESS_ROLE", "worker")
    get_settings.cache_clear()
    s = get_settings()
    init_db()
    ensure_assets()
    migrate_legacy_schedules()
    n = scanner.mark_interrupted_scans(s.process_role)
    if n:
        log.warning("Marked %d interrupted %s scan(s) as failed", n, s.process_role)
    log.info("Scheduler worker started (role=%s, tick=%ss, max concurrent scheduled scans=%s)",
             s.process_role, s.scheduler_tick_seconds, s.scheduler_max_concurrent_scans)
    loop_task = asyncio.create_task(scheduler_loop(s.scheduler_tick_seconds, s.process_role))
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: rely on KeyboardInterrupt
            pass
    try:
        await stop.wait()
    finally:
        loop_task.cancel()
        running = list(scanner._running.values())
        for t in running:
            t.cancel()
        await asyncio.gather(loop_task, *running, return_exceptions=True)
        log.info("Scheduler worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .logredact import install

    install()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
