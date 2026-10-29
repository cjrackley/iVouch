"""Account helpers for iVouch Lite (spec 2, objective 2.2).

Framework-free helpers: argon2id password hashing (argon2-cffi),
short-lived JWT access tokens plus self-contained email-verification
tokens (PyJWT), the signup age gate, and full account deletion.

No date of birth is ever stored anywhere -- callers check it with
:func:`is_adult` and keep only ``accounts.age_confirmed_at``.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

# DEV-ONLY fallback. Never commit a real secret: production sets the
# LITE_JWT_SECRET environment variable. Tests set it too.
DEV_ONLY_FALLBACK_SECRET = "lite-dev-insecure-secret-DO-NOT-USE-IN-PROD"

_VERIFY_PURPOSE = "email_verify"
_VERIFY_LIFETIME = timedelta(hours=24)

_ph = PasswordHasher()  # argon2id defaults from argon2-cffi


def get_jwt_secret() -> str:
    """Return the JWT signing secret.

    Always read from the ``LITE_JWT_SECRET`` environment variable;
    fall back to an insecure dev-only constant (clearly marked above)
    with a warning when the variable is unset.
    """
    secret = os.environ.get("LITE_JWT_SECRET")
    if secret:
        return secret
    warnings.warn(
        "LITE_JWT_SECRET is not set; using an insecure dev-only "
        "fallback secret. Never use this outside local development.",
        UserWarning,
        stacklevel=2,
    )
    return DEV_ONLY_FALLBACK_SECRET


def hash_password(password: str) -> str:
    """Hash ``password`` with argon2id; return the encoded hash."""
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Return True when ``password`` matches ``stored_hash``.

    Unknown emails and wrong passwords both end up here as False, so
    callers can answer every login failure identically.
    """
    try:
        return bool(_ph.verify(stored_hash, password))
    except (VerifyMismatchError, InvalidHash, AttributeError, TypeError):
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    """Return True when ``stored_hash`` should be re-hashed on login."""
    try:
        return bool(_ph.check_needs_rehash(stored_hash))
    except (InvalidHash, AttributeError, TypeError):
        return False


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string for timestamp columns."""
    return datetime.now(timezone.utc).isoformat()


def age_on(dob: date, on: date | None = None) -> int:
    """Whole years lived on date ``on`` (default: today)."""
    on = on or date.today()
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def is_adult(dob: date, min_age: int) -> bool:
    """Return True when ``dob`` meets the ``min_age`` gate."""
    return age_on(dob) >= min_age


def _encode(payload: dict) -> str:
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def create_access_token(email: str, minutes: int | None = None) -> str:
    """Mint a short-lived access JWT for ``email``.

    ``minutes`` defaults to ``jwt_access_minutes`` from
    ``lite/config.yaml`` via the loader.
    """
    if minutes is None:
        from lite.app.config import load_config

        minutes = load_config().jwt_access_minutes
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": email,
            "purpose": "access",
            "iat": now,
            "exp": now + timedelta(minutes=minutes),
        }
    )


def decode_access_token(token: str) -> str:
    """Return the account email for a valid access JWT.

    Raises :class:`ValueError` for expired, mis-signed, wrong-purpose,
    or otherwise invalid tokens -- callers answer all of these with
    the same 401.
    """
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValueError(f"invalid access token: {exc}") from exc
    if payload.get("purpose") != "access" or not payload.get("sub"):
        raise ValueError("invalid access token")
    return payload["sub"]


def create_verify_token(email: str) -> str:
    """Mint a self-contained email-verification token for ``email``.

    Stateless (a signed JWT), so no token column is needed on the
    committed ``accounts`` schema.
    """
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": email,
            "purpose": _VERIFY_PURPOSE,
            "iat": now,
            "exp": now + _VERIFY_LIFETIME,
        }
    )


def decode_verify_token(token: str) -> str:
    """Return the account email for a valid verification token.

    Raises :class:`ValueError` for any invalid or expired token.
    """
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValueError(f"invalid verification token: {exc}") from exc
    if payload.get("purpose") != _VERIFY_PURPOSE or not payload.get("sub"):
        raise ValueError("invalid verification token")
    return payload["sub"]


def delete_account_everywhere(
    conn: sqlite3.Connection, account_id: int, uploads_dir
) -> str | None:
    """Delete an account, its reports, and its uploaded files.

    Report rows cascade to ``check_results``/``review_actions`` via the
    schema's ``ON DELETE CASCADE``. Uploaded files live under
    ``<uploads_dir>/<account_id>/`` (convention shared with objective
    2.3). One ``account_deletion`` audit event (email + time, no image
    bytes) is kept. Returns the deleted email, or None when unknown.
    """
    row = conn.execute(
        "SELECT email FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row is None:
        return None
    email = row["email"]
    account_dir = Path(uploads_dir) / str(account_id) if uploads_dir else None
    if account_dir is not None and account_dir.is_dir():
        shutil.rmtree(account_dir, ignore_errors=False)
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.execute(
        "INSERT INTO audit_events (kind, actor_account_id, report_id,"
        " detail, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            "account_deletion",
            None,
            None,
            f"account {email} deleted at {utcnow_iso()}",
            utcnow_iso(),
        ),
    )
    conn.commit()
    return email
