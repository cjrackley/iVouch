"""SQLite schema and stores for Lite spec 2, objective 2.1.

Stdlib ``sqlite3`` only. One database file, one process, no migrations
framework: Lite is a fresh-install demo, so schema changes mean
recreating the database, never a migration.

Tables: ``accounts``, ``reports``, ``check_results``,
``review_actions``, ``audit_events``, plus a ``schema_version`` row.
No column anywhere stores a date of birth -- only
``accounts.age_confirmed_at`` is kept.

``init_db`` is idempotent: running it on an existing database is a
clean no-op success.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

VALID_LOCATION_SOURCES = frozenset({"browser", "manual_pin"})

VALID_AUDIT_KINDS = frozenset(
    {"mock_rejection", "review_action", "account_deletion"}
)


class UnknownEmailError(ValueError):
    """Raised when an email address matches no account row."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    """Default database file: ``lite/data/ivouch.db``."""
    return Path(__file__).resolve().parents[2] / "data" / "ivouch.db"


def connect(path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys enforced."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0 CHECK (email_verified IN (0, 1)),
    age_confirmed_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    reviewer INTEGER NOT NULL DEFAULT 0 CHECK (reviewer IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    client_report_id TEXT NOT NULL,
    sha256 TEXT,
    phash TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    location_lat REAL NOT NULL,
    location_lng REAL NOT NULL,
    location_consented INTEGER NOT NULL CHECK (location_consented = 1),
    location_source TEXT NOT NULL
        CHECK (location_source IN ('browser', 'manual_pin')),
    UNIQUE (account_id, client_report_id)
);

CREATE TABLE IF NOT EXISTS check_results (
    report_id INTEGER PRIMARY KEY REFERENCES reports(id) ON DELETE CASCADE,
    incident_probs TEXT,
    severity_probs TEXT,
    provenance TEXT,
    verdict TEXT,
    reasons TEXT
);

CREATE TABLE IF NOT EXISTS review_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    reviewer_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    before TEXT,
    after TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL
        CHECK (kind IN ('mock_rejection', 'review_action', 'account_deletion')),
    actor_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    report_id INTEGER REFERENCES reports(id) ON DELETE SET NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


def init_db(path) -> Path:
    """Create the Lite schema at ``path``; a no-op success if it exists.

    Creates parent directories, creates every table with
    ``IF NOT EXISTS``, and keeps exactly one ``schema_version`` row.
    Returns the resolved database path.
    """
    resolved = Path(path)
    if resolved.parent != resolved and str(resolved.parent):
        resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(resolved)
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at)"
            " VALUES (?, ?)",
            (SCHEMA_VERSION, _utcnow()),
        )
        conn.commit()
    finally:
        conn.close()
    return resolved


def create_account(
    conn: sqlite3.Connection,
    *,
    email: str,
    password_hash: str,
    email_verified: int = 0,
    age_confirmed_at=None,
    status: str = "active",
) -> int:
    """Insert an account row; returns the new account id."""
    cur = conn.execute(
        "INSERT INTO accounts (email, password_hash, email_verified,"
        " age_confirmed_at, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            email,
            password_hash,
            email_verified,
            age_confirmed_at,
            status,
            _utcnow(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_account_by_email(conn: sqlite3.Connection, email: str):
    """Return the account row for ``email``, or ``None``."""
    return conn.execute(
        "SELECT * FROM accounts WHERE email = ?", (email,)
    ).fetchone()


def make_reviewer(conn: sqlite3.Connection, email: str) -> int:
    """Set ``reviewer = 1`` for the account with ``email``.

    Returns the account id. Raises :class:`UnknownEmailError` when no
    account has that email.
    """
    row = get_account_by_email(conn, email)
    if row is None:
        raise UnknownEmailError(f"unknown email: {email}")
    conn.execute("UPDATE accounts SET reviewer = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    return row["id"]


def find_report(
    conn: sqlite3.Connection, account_id: int, client_report_id: str
):
    """Return the report row for ``(account_id, client_report_id)`` or None."""
    return conn.execute(
        "SELECT * FROM reports WHERE account_id = ? AND client_report_id = ?",
        (account_id, client_report_id),
    ).fetchone()


def create_report(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    client_report_id: str,
    sha256=None,
    phash=None,
    status: str = "pending",
    location_lat: float,
    location_lng: float,
    location_consented=1,
    location_source: str,
) -> tuple[int, bool]:
    """First-wins idempotent report insert.

    When a report already exists for ``(account_id,
    client_report_id)`` the existing id is returned with ``False``
    and nothing is inserted or changed -- even when the new bytes
    (hashes) differ. Otherwise a new row is inserted and ``(id,
    True)`` is returned.
    """
    existing = find_report(conn, account_id, client_report_id)
    if existing is not None:
        return existing["id"], False
    if location_consented is not True and location_consented != 1:
        raise ValueError("location_consented must be true")
    if location_source not in VALID_LOCATION_SOURCES:
        raise ValueError(
            "location_source must be one of"
            f" {sorted(VALID_LOCATION_SOURCES)}, got {location_source!r}"
        )
    try:
        cur = conn.execute(
            "INSERT INTO reports (account_id, client_report_id, sha256,"
            " phash, status, created_at, location_lat, location_lng,"
            " location_consented, location_source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                account_id,
                client_report_id,
                sha256,
                phash,
                status,
                _utcnow(),
                location_lat,
                location_lng,
                1,
                location_source,
            ),
        )
        conn.commit()
        return cur.lastrowid, True
    except sqlite3.IntegrityError:
        # Lost a race with a concurrent first insert: first wins.
        existing = find_report(conn, account_id, client_report_id)
        if existing is None:
            raise
        conn.rollback()
        return existing["id"], False
