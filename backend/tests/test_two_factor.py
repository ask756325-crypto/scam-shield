"""Two-factor authentication: RFC vectors, setup, two-step login, replay protection, recovery codes, audit."""
import base64
import time

from app import totp
from conftest import CSRF, signup

PW = "correct-horse-42"


def test_rfc6238_vectors():
    sec = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_at(sec, 59 // 30) == "287082" and totp.code_at(sec, 1111111109 // 30) == "081804"
    step = totp.verify(sec, "287082", None, now=59)
    assert step == 1 and totp.verify(sec, "287082", step, now=59) is None  # same code can't be reused


def enable(client):
    setup = client.post("/api/auth/2fa/setup", json={"password": PW}, headers=CSRF).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/ScamShield%20AI:") and "secret=" in setup["otpauth_uri"]
    r = client.post("/api/auth/2fa/enable", json={"code": totp.code_at(setup["secret"], int(time.time() // 30))}, headers=CSRF).json()
    return setup["secret"], r["recovery_codes"]


def test_setup_login_recovery_and_disable(client):
    email = signup(client)
    assert client.post("/api/auth/2fa/setup", json={"password": "wrong-password-1"}, headers=CSRF).status_code == 400
    s = client.post("/api/auth/2fa/setup", json={"password": PW}, headers=CSRF).json()
    assert client.post("/api/auth/2fa/enable", json={"code": "000000"}, headers=CSRF).status_code == 400
    r = client.post("/api/auth/2fa/enable", json={"code": totp.code_at(s["secret"], int(time.time() // 30))}, headers=CSRF).json()
    codes = r["recovery_codes"]
    assert len(codes) == 10 and client.get("/api/auth/me").json()["user"]["two_factor_enabled"]
    assert "secret" not in client.get("/api/auth/2fa").text  # never shown again
    client.cookies.clear()

    first = client.post("/api/auth/login", json={"email": email, "password": PW}, headers=CSRF)
    assert first.json()["two_factor_required"] and "ss_session" not in first.cookies  # no session after the password alone
    assert client.get("/api/auth/me").status_code == 401
    ch = first.json()["challenge"]
    assert client.post("/api/auth/login/2fa", json={"challenge": ch, "code": "123456"}, headers=CSRF).status_code == 401
    # The current code was consumed by "enable" (replay protection), so use the next one, as a real user would.
    reused = client.post("/api/auth/login/2fa", json={"challenge": ch, "code": totp.code_at(s["secret"], int(time.time() // 30))}, headers=CSRF)
    assert reused.status_code == 401
    ok = client.post("/api/auth/login/2fa", json={"challenge": ch, "code": totp.code_at(s["secret"], int(time.time() // 30) + 1)}, headers=CSRF)
    assert ok.status_code == 200 and client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/login/2fa", json={"challenge": ch, "code": "123456"}, headers=CSRF).status_code == 401  # single use
    client.cookies.clear()

    ch2 = client.post("/api/auth/login", json={"email": email, "password": PW}, headers=CSRF).json()["challenge"]
    rec = client.post("/api/auth/login/2fa", json={"challenge": ch2, "recovery_code": codes[0].lower()}, headers=CSRF).json()
    assert rec["recovery_codes_left"] == 9
    client.cookies.clear()
    ch3 = client.post("/api/auth/login", json={"email": email, "password": PW}, headers=CSRF).json()["challenge"]
    assert client.post("/api/auth/login/2fa", json={"challenge": ch3, "recovery_code": codes[0]}, headers=CSRF).status_code == 401  # used up

    ok = client.post("/api/auth/login/2fa", json={"challenge": ch3, "recovery_code": codes[1]}, headers=CSRF)
    assert ok.status_code == 200
    assert client.post("/api/auth/2fa/disable", json={"password": PW, "code": "000000"}, headers=CSRF).status_code == 400
    assert client.post("/api/auth/2fa/disable", json={"password": PW, "code": codes[2]}, headers=CSRF).json() == {"enabled": False}
    actions = [e["action"] for e in client.get("/api/settings/audit").json()["items"]]
    assert "security.2fa_enabled" in actions and "security.2fa_disabled" in actions
    client.cookies.clear()
    assert "user" in client.post("/api/auth/login", json={"email": email, "password": PW}, headers=CSRF).json()  # back to one step


def test_challenge_attempts_are_limited(client):
    email = signup(client)
    enable(client)
    client.cookies.clear()
    ch = client.post("/api/auth/login", json={"email": email, "password": PW}, headers=CSRF).json()["challenge"]
    for _ in range(5):
        client.post("/api/auth/login/2fa", json={"challenge": ch, "code": "000000"}, headers=CSRF)
    r = client.post("/api/auth/login/2fa", json={"challenge": ch, "code": "111111"}, headers=CSRF)
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_wrong_password_never_reveals_2fa(client):
    email = signup(client)
    enable(client)
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": email, "password": "not-the-password-1"}, headers=CSRF)
    assert r.status_code == 401 and "challenge" not in r.text
