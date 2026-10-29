"""Tests for Lite spec 2, objective 2.2: accounts and auth.

TestClient against tmp SQLite + tmp mail/uploads dirs only -- never
the real ``lite/data/`` directory. The JWT secret comes from the
``LITE_JWT_SECRET`` env var (set per-test here).
"""

import re
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from lite.app.server.api import (
    GENERIC_LOGIN_DETAIL,
    GENERIC_REGISTER_MESSAGE,
    create_app,
)
from lite.app.server.db import connect, create_report

TEST_SECRET = "test-jwt-secret-for-auth-tests-0123456789"
PASSWORD = "correct-horse-9"
ADULT_DOB = (date.today() - timedelta(days=365 * 30)).isoformat()
TEEN_DOB = (date.today() - timedelta(days=365 * 10)).isoformat()
EXACTLY_18_DOB = date(
    date.today().year - 18, date.today().month, date.today().day
).isoformat()


@pytest.fixture()
def secret(monkeypatch):
    monkeypatch.setenv("LITE_JWT_SECRET", TEST_SECRET)


@pytest.fixture()
def app_dirs(tmp_path):
    return {
        "db": tmp_path / "test.db",
        "mail": tmp_path / "mail",
        "uploads": tmp_path / "uploads",
    }


@pytest.fixture()
def client(secret, app_dirs):
    app = create_app(
        db_path=app_dirs["db"],
        mail_dir=app_dirs["mail"],
        uploads_dir=app_dirs["uploads"],
    )
    return TestClient(app), app_dirs


def _mail_tokens(mail_dir):
    tokens = []
    for path in sorted(mail_dir.glob("*.txt")):
        match = re.search(r"^token:\s*(\S+)\s*$", path.read_text(
            encoding="utf-8"), re.MULTILINE)
        assert match, f"mail file {path.name} has no token line"
        tokens.append(match.group(1))
    return tokens


def _register(client, email, password=PASSWORD, dob=ADULT_DOB):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "date_of_birth": dob,
        },
    )


def _account_count(db_path):
    conn = connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM accounts"
        ).fetchone()["n"]
    finally:
        conn.close()


def test_register_verify_login_account_flow(client):
    http, dirs = client
    resp = _register(http, "reporter@example.com")
    assert resp.status_code == 200
    assert resp.json() == {"message": GENERIC_REGISTER_MESSAGE}

    tokens = _mail_tokens(dirs["mail"])
    assert len(tokens) == 1

    verify = http.post(
        "/auth/verify-email",
        json={"email": "reporter@example.com", "token": tokens[0]},
    )
    assert verify.status_code == 200

    login = http.post(
        "/auth/login",
        json={"email": "reporter@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["email_verified"] is True
    assert body["access_token"]

    me = http.get(
        "/account",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    account = me.json()
    assert account["email"] == "reporter@example.com"
    assert account["email_verified"] is True
    # Exact response shape: no password hash, no birth date, nothing extra.
    assert set(account) == {
        "id", "email", "email_verified", "status", "created_at",
    }

    bad = http.post(
        "/auth/login",
        json={"email": "reporter@example.com", "password": "wrong-pass-1"},
    )
    assert bad.status_code == 401

    anon = http.get("/account")
    assert anon.status_code == 401
    forged = http.get(
        "/account", headers={"Authorization": "Bearer not-a-token"}
    )
    assert forged.status_code == 401


def test_exactly_18_registers(tmp_path, secret):
    app = create_app(
        db_path=tmp_path / "t.db",
        mail_dir=tmp_path / "mail",
        uploads_dir=tmp_path / "up",
    )
    http = TestClient(app)
    resp = _register(http, "adult@example.com", dob=EXACTLY_18_DOB)
    assert resp.status_code == 200
    assert _account_count(tmp_path / "t.db") == 1
    assert _mail_tokens(tmp_path / "mail")


def test_underage_signup_creates_nothing(client):
    http, dirs = client
    resp = _register(http, "teen@example.com", dob=TEEN_DOB)
    # Generic response: indistinguishable from a real signup.
    assert resp.status_code == 200
    assert resp.json() == {"message": GENERIC_REGISTER_MESSAGE}
    assert _account_count(dirs["db"]) == 0
    assert list(dirs["mail"].glob("*.txt")) == []

    # And no birth date is stored anywhere for the adult path either:
    # the accounts table has no date-of-birth-like column.
    _register(http, "grown@example.com")
    conn = connect(str(dirs["db"]))
    try:
        columns = [
            row["name"].lower()
            for row in conn.execute("PRAGMA table_info(accounts)")
        ]
        for banned in (
            "date_of_birth", "dob", "birthdate", "birth_date",
            "birthday",
        ):
            assert banned not in columns
        row = conn.execute(
            "SELECT age_confirmed_at FROM accounts WHERE email = ?",
            ("grown@example.com",),
        ).fetchone()
        assert row["age_confirmed_at"]
    finally:
        conn.close()


def test_register_and_login_are_generic_about_existence(client):
    http, dirs = client
    first = _register(http, "twice@example.com")
    second = _register(http, "Twice@Example.com")  # case variant
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json() == {
        "message": GENERIC_REGISTER_MESSAGE
    }
    assert _account_count(dirs["db"]) == 1
    # No second mail: re-registering a known email changes nothing.
    assert len(_mail_tokens(dirs["mail"])) == 1

    wrong_password = http.post(
        "/auth/login",
        json={"email": "twice@example.com", "password": "wrong-pass-1"},
    )
    unknown_email = http.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-pass-1"},
    )
    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {
        "detail": GENERIC_LOGIN_DETAIL
    }
    assert "twice" not in unknown_email.text.lower().replace(
        "invalid email or password", "")


def test_unverified_account_can_log_in_but_stays_unverified(client):
    # Per spec: unverified accounts cannot *upload* (objective 2.3
    # answers 403 there); login itself still returns a token.
    http, _ = client
    assert _register(http, "fresh@example.com").status_code == 200
    login = http.post(
        "/auth/login",
        json={"email": "fresh@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["email_verified"] is False

    me = http.get(
        "/account",
        headers={
            "Authorization": f"Bearer {login.json()['access_token']}"
        },
    )
    assert me.status_code == 200
    assert me.json()["email_verified"] is False


def test_verify_email_rejects_bad_tokens(client):
    http, dirs = client
    assert _register(http, "v@example.com").status_code == 200
    for payload in (
        {"token": "garbage"},
        {"token": "garbage", "email": "v@example.com"},
    ):
        resp = http.post("/auth/verify-email", json=payload)
        assert resp.status_code == 400
    # Token for one address cannot verify with another attached.
    before = set(_mail_tokens(dirs["mail"]))
    assert _register(http, "other@example.com").status_code == 200
    other_token = (set(_mail_tokens(dirs["mail"])) - before).pop()
    mismatch = http.post(
        "/auth/verify-email",
        json={"token": other_token, "email": "v@example.com"},
    )
    assert mismatch.status_code == 400


def test_delete_account_removes_reports_and_files(client):
    http, dirs = client
    assert _register(http, "leaver@example.com").status_code == 200
    token = _mail_tokens(dirs["mail"])[0]
    assert http.post(
        "/auth/verify-email", json={"token": token}
    ).status_code == 200
    login = http.post(
        "/auth/login",
        json={"email": "leaver@example.com", "password": PASSWORD},
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    account_id = http.get("/account", headers=headers).json()["id"]

    # Seed one report plus one uploaded file for this account.
    conn = connect(str(dirs["db"]))
    try:
        create_report(
            conn,
            account_id=account_id,
            client_report_id="client-1",
            sha256="a" * 64,
            phash="b" * 16,
            location_lat=51.5,
            location_lng=-0.12,
            location_consented=1,
            location_source="browser",
        )
    finally:
        conn.close()
    account_dir = dirs["uploads"] / str(account_id)
    account_dir.mkdir(parents=True, exist_ok=True)
    photo = account_dir / "photo.jpg"
    photo.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")

    deleted = http.delete("/account", headers=headers)
    assert deleted.status_code == 200

    assert _account_count(dirs["db"]) == 0
    conn = connect(str(dirs["db"]))
    try:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM reports"
        ).fetchone()["n"] == 0
        audit = conn.execute(
            "SELECT kind, detail FROM audit_events"
        ).fetchall()
        assert [row["kind"] for row in audit] == ["account_deletion"]
        assert "leaver@example.com" in audit[0]["detail"]
    finally:
        conn.close()
    assert not photo.exists()
    assert not account_dir.exists()

    # The old token is now orphaned: every authenticated call is 401.
    assert http.get("/account", headers=headers).status_code == 401
    assert http.delete("/account", headers=headers).status_code == 401
    relogin = http.post(
        "/auth/login",
        json={"email": "leaver@example.com", "password": PASSWORD},
    )
    assert relogin.status_code == 401
    assert relogin.json() == {"detail": GENERIC_LOGIN_DETAIL}


def test_rejects_bad_shapes(client):
    http, _ = client
    assert http.post(
        "/auth/register",
        json={
            "email": "not-an-email",
            "password": PASSWORD,
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 422
    assert http.post(
        "/auth/register",
        json={
            "email": "short@example.com",
            "password": "tiny",
            "date_of_birth": ADULT_DOB,
        },
    ).status_code == 422
