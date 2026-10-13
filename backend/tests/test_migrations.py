"""Alembic: models and migrations never drift; empty and pre-Alembic databases both end at head."""
import tempfile
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app import db as dbmod
from app.db import Base, _alembic_config, init_db


def _with_db(url, fn):
    original = str(dbmod.engine.url)
    dbmod.configure(url)
    try:
        return fn()
    finally:
        dbmod.configure(original)


def head():
    return ScriptDirectory.from_config(_alembic_config()).get_current_head()


def test_empty_database_upgrades_to_head_with_no_drift():
    url = f"sqlite:///{Path(tempfile.mkdtemp()) / 'fresh.db'}"

    def run():
        init_db()
        with dbmod.engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == head()
            diffs = compare_metadata(MigrationContext.configure(c), Base.metadata)
        assert diffs == [], diffs  # a model change without a migration fails here
    _with_db(url, run)


def test_pre_alembic_database_is_upgraded_in_place_and_stamped():
    path = Path(tempfile.mkdtemp()) / "legacy.db"
    url = f"sqlite:///{path}"
    # Simulate an older release: a subset of tables, with columns added later missing.
    legacy = create_engine(url)
    with legacy.begin() as c:
        c.execute(text("CREATE TABLE organizations (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, detection_config JSON, "
                       "source_config JSON, created_at DATETIME)"))
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(254) NOT NULL UNIQUE, name VARCHAR(120) NOT NULL, "
                       "password_hash VARCHAR(255) NOT NULL, is_active BOOLEAN, created_at DATETIME, last_login_at DATETIME)"))
        c.execute(text("INSERT INTO organizations (id, name) VALUES (1, 'Old Org')"))
    legacy.dispose()

    def run():
        init_db()
        insp = inspect(dbmod.engine)
        cols = {c["name"] for c in insp.get_columns("users")}
        assert {"email_verified_at", "totp_secret", "recovery_codes"} <= cols
        assert {"monitoring_config", "notification_config"} <= {c["name"] for c in insp.get_columns("organizations")}
        assert "takedown_cases" in insp.get_table_names() and "audit_events" in insp.get_table_names()
        with dbmod.engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == head()
            assert c.execute(text("SELECT name FROM organizations")).scalar() == "Old Org"  # data kept
        init_db()  # idempotent on the next start
    _with_db(url, run)
