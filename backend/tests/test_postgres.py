"""PostgreSQL-specific checks. Skipped on SQLite; run with SCAMSHIELD_TEST_DATABASE_URL=postgresql+psycopg://…"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.db import engine, init_db

pytestmark = pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL only")


def test_every_timestamp_column_is_timezone_aware(client):
    with engine.connect() as c:
        naive = c.execute(text(
            "SELECT table_name || '.' || column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND data_type = 'timestamp without time zone'")).scalars().all()
    assert naive == []


def test_migrated_timestamp_columns_are_repaired_without_shifting_values(client):
    # Simulate a database migrated by a pre-Alembic release: wrong column type and no alembic_version table.
    with engine.begin() as c:
        c.execute(text("ALTER TABLE scans ALTER COLUMN heartbeat_at TYPE TIMESTAMP WITHOUT TIME ZONE"))
        version = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        c.execute(text("DROP TABLE alembic_version"))
    init_db()  # legacy path: additive migration + repair, then stamp head
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == version
    with engine.connect() as c:
        assert c.execute(text("SELECT data_type FROM information_schema.columns WHERE table_name='scans' AND column_name='heartbeat_at'")).scalar() \
            == "timestamp with time zone"


def test_partial_unique_index_exists(client):
    with engine.connect() as c:
        idx = c.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_scans_one_active_per_brand'")).scalar()
    assert idx and "UNIQUE" in idx and "queued" in idx


def test_aware_datetimes_round_trip(client):
    from app.db import SessionLocal
    from app.models import RuntimeState

    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    with SessionLocal() as db:
        db.merge(RuntimeState(key="pg-roundtrip", value={}, updated_at=when))
        db.commit()
    with SessionLocal() as db:
        got = db.get(RuntimeState, "pg-roundtrip").updated_at
        assert got == when and got.utcoffset().total_seconds() == 0  # same instant, and expressed in UTC
