"""Tests for Lite spec 2, objective 2.1: schema and stores.

Uses ONLY tmp SQLite files (``tmp_path``) -- never the real
``lite/data/`` directory.
"""

import sqlite3
import subprocess
import sys

from lite.app.server.db import (
    SCHEMA_VERSION,
    connect,
    create_account,
    create_report,
    find_report,
    init_db,
)

EXPECTED_TABLES = {
    "accounts",
    "reports",
    "check_results",
    "review_actions",
    "audit_events",
    "schema_version",
}

# Column names that would store a date of birth in any spelling.
DOB_LIKE = ("date_of_birth", "dob", "birthdate", "birth_date", "birthday")


def _table_names(path) -> set:
    conn = connect(str(path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        return {row["name"] for row in rows}
    finally:
        conn.close()


def _columns(conn, table) -> list:
    return [
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    ]


def _seed_account(conn, email="reporter@example.com"):
    return create_account(
        conn,
        email=email,
        password_hash="argon2id$mock",
        email_verified=1,
        age_confirmed_at="2026-10-29T00:00:00+00:00",
    )


def _report_kwargs(**overrides):
    kwargs = {
        "client_report_id": "client-1",
        "sha256": "a" * 64,
        "phash": "b" * 16,
        "location_lat": 51.5,
        "location_lng": -0.12,
        "location_consented": 1,
        "location_source": "browser",
    }
    kwargs.update(overrides)
    return kwargs


def test_schema_creates_cleanly_and_second_init_is_noop(tmp_path):
    db_path = tmp_path / "ivouch.db"
    init_db(str(db_path))
    assert db_path.is_file()
    assert EXPECTED_TABLES <= _table_names(str(db_path))

    conn = connect(str(db_path))
    try:
        versions = conn.execute(
            "SELECT version FROM schema_version"
        ).fetchall()
        assert [row["version"] for row in versions] == [SCHEMA_VERSION]
    finally:
        conn.close()

    # Second init on the existing database is a clean no-op success.
    init_db(str(db_path))
    assert EXPECTED_TABLES <= _table_names(str(db_path))
    conn = connect(str(db_path))
    try:
        versions = conn.execute(
            "SELECT version FROM schema_version"
        ).fetchall()
        assert [row["version"] for row in versions] == [SCHEMA_VERSION]
    finally:
        conn.close()


def test_no_date_of_birth_column_anywhere(tmp_path):
    db_path = tmp_path / "ivouch.db"
    init_db(str(db_path))
    conn = connect(str(db_path))
    try:
        for table in EXPECTED_TABLES - {"schema_version"}:
            names = [name.lower() for name in _columns(conn, table)]
            for banned in DOB_LIKE:
                assert banned not in names, (
                    f"table {table} has date-of-birth-like column {banned!r}"
                )
    finally:
        conn.close()


def test_report_idempotency_first_wins_same_bytes(tmp_path):
    db_path = tmp_path / "ivouch.db"
    init_db(str(db_path))
    conn = connect(str(db_path))
    try:
        account_id = _seed_account(conn)
        first_id, created = create_report(
            conn, account_id=account_id, **_report_kwargs()
        )
        assert created is True
        second_id, created_again = create_report(
            conn, account_id=account_id, **_report_kwargs()
        )
        assert created_again is False
        assert second_id == first_id
        count = conn.execute("SELECT COUNT(*) AS n FROM reports").fetchone()[
            "n"
        ]
        assert count == 1
    finally:
        conn.close()


def test_report_idempotency_first_wins_differing_bytes(tmp_path):
    db_path = tmp_path / "ivouch.db"
    init_db(str(db_path))
    conn = connect(str(db_path))
    try:
        account_id = _seed_account(conn)
        first_id, _ = create_report(conn, account_id=account_id,
                                    **_report_kwargs())
        # Same (account_id, client_report_id) but different file bytes.
        retry_id, created = create_report(
            conn,
            account_id=account_id,
            **_report_kwargs(sha256="f" * 64, phash="0" * 16),
        )
        assert created is False
        assert retry_id == first_id
        row = find_report(conn, account_id, "client-1")
        assert row["id"] == first_id
        assert row["sha256"] == "a" * 64  # first bytes win
        assert row["phash"] == "b" * 16
        count = conn.execute("SELECT COUNT(*) AS n FROM reports").fetchone()[
            "n"
        ]
        assert count == 1
    finally:
        conn.close()


def test_location_columns_required_and_consent_true(tmp_path):
    db_path = tmp_path / "ivouch.db"
    init_db(str(db_path))
    conn = connect(str(db_path))
    try:
        account_id = _seed_account(conn)
        info = {
            row["name"]: dict(row)
            for row in conn.execute("PRAGMA table_info(reports)").fetchall()
        }
        assert info["location_lat"]["notnull"] == 1
        assert info["location_lng"]["notnull"] == 1
        # Consent false is refused at the helper level ...
        try:
            create_report(
                conn,
                account_id=account_id,
                **_report_kwargs(
                    client_report_id="no-consent", location_consented=0
                ),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("location_consented=0 was accepted")
        # ... and at the SQL level.
        with conn:
            try:
                conn.execute(
                    "INSERT INTO reports (account_id, client_report_id,"
                    " created_at, location_lat, location_lng,"
                    " location_consented, location_source)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        account_id,
                        "raw-no-consent",
                        "2026-10-29T00:00:00+00:00",
                        51.5,
                        -0.12,
                        0,
                        "browser",
                    ),
                )
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError(
                    "SQL CHECK allowed location_consented = 0"
                )
        # Bad location_source is refused as well.
        try:
            create_report(
                conn,
                account_id=account_id,
                **_report_kwargs(
                    client_report_id="bad-source", location_source="gps"
                ),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("location_source='gps' was accepted")
    finally:
        conn.close()


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "lite.app.cli", *args],
        capture_output=True,
        text=True,
    )


def test_make_reviewer_known_email_via_cli(tmp_path):
    db_path = tmp_path / "ivouch.db"
    init_db(str(db_path))
    conn = connect(str(db_path))
    try:
        _seed_account(conn, email="reviewer@example.com")
    finally:
        conn.close()

    proc = _run_cli(
        "--db", str(db_path), "make-reviewer", "reviewer@example.com"
    )
    assert proc.returncode == 0, proc.stderr
    conn = connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT reviewer FROM accounts WHERE email = ?",
            ("reviewer@example.com",),
        ).fetchone()
        assert row["reviewer"] == 1
    finally:
        conn.close()


def test_make_reviewer_unknown_email_errors_via_cli(tmp_path):
    db_path = tmp_path / "ivouch.db"
    init_db(str(db_path))
    proc = _run_cli(
        "--db", str(db_path), "make-reviewer", "nobody@example.com"
    )
    assert proc.returncode != 0
    assert "unknown email" in proc.stderr.lower()
