"""Database engine and session management (SQLAlchemy 2.0, parameterized queries only)."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str) -> Engine:
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure(url: str) -> None:
    """Re-point the engine (used by tests)."""
    global engine
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["skip_logging"] = True  # keep the application's logging configuration
    return cfg


def init_db() -> None:
    """Bring the database schema to the latest Alembic revision.

    * empty database            → `alembic upgrade head` creates every table
    * Alembic-managed database  → `alembic upgrade head` applies pending revisions
    * pre-Alembic database      → create missing tables + additive columns/repairs, then `alembic stamp head`
    """
    from alembic import command
    from sqlalchemy import inspect

    from . import models  # noqa: F401  (register models)

    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and tables & {"users", "organizations", "brands"}:
        Base.metadata.create_all(bind=engine)
        _add_missing_columns()
        _ensure_active_scan_index()
        command.stamp(_alembic_config(), "head")
    else:
        command.upgrade(_alembic_config(), "head")


def _ensure_active_scan_index() -> None:
    """Databases created before the index existed: keep only the newest queued/running scan per brand, then add it."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE scans SET status = 'failed', error = 'Superseded duplicate scan' "
            "WHERE status IN ('queued', 'running') AND id NOT IN "
            "(SELECT MAX(id) FROM scans WHERE status IN ('queued', 'running') GROUP BY brand_id)"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scans_one_active_per_brand ON scans (brand_id) "
            "WHERE status IN ('queued', 'running')"
        ))


# Additive, nullable columns introduced after the first release. create_all() does not alter existing
# tables, so add them in place. (Use Alembic for anything beyond simple additive changes.)
_ADDITIVE_COLUMNS = [
    ("users", "email_verified_at", "TIMESTAMP NULL"),
    ("brands", "website_url", "VARCHAR(500) NULL"),
    ("brands", "additional_identifiers", "JSON NULL"),
    ("brands", "exclusion_rules", "JSON NULL"),
    ("official_apps", "name", "VARCHAR(255) NULL"),
    ("scan_sources", "query_outcomes", "JSON NULL"),
    ("scan_sources", "failure_kind", "VARCHAR(20) NULL"),
    ("scan_sources", "rate_limit", "JSON NULL"),
    ("findings", "detection_type", "VARCHAR(40) NULL"),
    ("decisions", "from_status", "VARCHAR(20) NULL"),
    ("decisions", "to_status", "VARCHAR(20) NULL"),
    ("organizations", "monitoring_config", "JSON NULL"),
    ("scans", "findings_missing", "INTEGER NOT NULL DEFAULT 0"),
    ("scans", "findings_unverified", "INTEGER NOT NULL DEFAULT 0"),
    ("scans", "schedule_id", "INTEGER NULL REFERENCES monitoring_schedules(id) ON DELETE SET NULL"),
    ("scans", "runner", "VARCHAR(40) NULL"),
    ("scans", "heartbeat_at", "TIMESTAMP NULL"),
    ("findings", "missed_scans", "INTEGER NOT NULL DEFAULT 0"),
    ("organizations", "notification_config", "JSON NULL"),
    ("findings", "assignee_id", "INTEGER NULL REFERENCES users(id) ON DELETE SET NULL"),
    ("users", "totp_secret", "VARCHAR(64) NULL"),
    ("users", "totp_pending_secret", "VARCHAR(64) NULL"),
    ("users", "totp_enabled_at", "TIMESTAMP NULL"),
    ("users", "totp_last_step", "INTEGER NULL"),
    ("users", "recovery_codes", "JSON NULL"),
]


def _add_missing_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    pg = engine.dialect.name == "postgresql"
    with engine.begin() as conn:
        for table, column, ddl in _ADDITIVE_COLUMNS:
            if pg:
                # Match TZDateTime (timestamptz). A plain TIMESTAMP column would store aware datetimes as
                # session-local wall time and read back shifted by the server's UTC offset.
                ddl = ddl.replace("TIMESTAMP NULL", "TIMESTAMP WITH TIME ZONE NULL")
            if table in insp.get_table_names() and column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        if pg:
            _repair_pg_timestamp_columns(conn)


def _repair_pg_timestamp_columns(conn) -> None:
    """PostgreSQL databases migrated by earlier versions got `timestamp without time zone` for added columns.
    Convert them to timestamptz, interpreting stored values in the session time zone that wrote them."""
    from sqlalchemy import text

    for table, column, ddl in _ADDITIVE_COLUMNS:
        if not ddl.startswith("TIMESTAMP"):
            continue
        dtype = conn.execute(text(
            "SELECT data_type FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = :t AND column_name = :c"), {"t": table, "c": column}).scalar()
        if dtype == "timestamp without time zone":
            conn.execute(text(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TIMESTAMP WITH TIME ZONE "
                f"USING {column} AT TIME ZONE current_setting('TimeZone')"))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
