import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="scamshield-test-"))
os.environ["SCAMSHIELD_ENV"] = "test"
os.environ["SCAMSHIELD_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SCAMSHIELD_UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["SCAMSHIELD_SCHEDULER_ENABLED"] = "false"
os.environ["SCAMSHIELD_AUTH_RATE_LIMIT_ATTEMPTS"] = "8"
os.environ["SCAMSHIELD_SOURCE_RETRY_DELAY_SECONDS"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.main import app  # noqa: E402
from app.security import rate_limiter  # noqa: E402
from app.services import scanner  # noqa: E402

CSRF = {"X-ScamShield-CSRF": "1"}


@pytest.fixture(autouse=True)
def _reset_state():
    rate_limiter.reset()
    original_factory, original_loader = scanner.adapter_factory, scanner.image_loader
    yield
    scanner.adapter_factory, scanner.image_loader = original_factory, original_loader


@pytest.fixture(scope="session")
def _app_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(_app_client):
    _app_client.cookies.clear()
    return _app_client


_counter = {"n": 0}


def signup(client, email=None, password="correct-horse-42", org="Acme Security"):
    _counter["n"] += 1
    email = email or f"user{_counter['n']}-{time.time_ns()}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "name": "Test User", "organization": org}, headers=CSRF)
    assert r.status_code == 201, r.text
    return email


@pytest.fixture
def authed(client):
    signup(client)
    return client


def wait_for_scan(client, scan_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get(f"/api/scans/{scan_id}").json()
        if s["status"] not in ("queued", "running"):
            return s
        time.sleep(0.1)
    raise AssertionError(f"scan {scan_id} did not finish: {s}")
