"""Lite HTTP server (spec 2). FastAPI app plus account/auth routes.

This brief (objective 2.2) creates the app and the accounts router:
``POST /auth/register``, ``POST /auth/verify-email``,
``POST /auth/login``, ``GET /account``, ``DELETE /account``.
Later objectives add more routers here with ``app.include_router`` --
keep that structure, one router per area.

Storage layout (shared with objective 2.3): SQLite file at
``app.state.db_path`` (default ``lite/data/ivouch.db``), console mail
under ``app.state.mail_dir``, uploads under
``app.state.uploads_dir`` with one sub-directory per account id.
``create_app`` takes explicit paths so tests can point at tmp dirs;
importing this module touches no disk.
"""

from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator

from lite.app.config import load_config
from lite.app.server import auth as auth_helpers
from lite.app.server import pipeline as upload_pipeline
from lite.app.server.db import (
    connect,
    create_account,
    get_account_by_email,
    init_db,
)
from lite.app.server.mail import resolve_mail_dir, write_verification_email

# One generic body for every register outcome (new account, known
# email, under-age): callers can never tell which case applied.
GENERIC_REGISTER_MESSAGE = (
    "If your details are valid, check your email for next steps."
)
GENERIC_LOGIN_DETAIL = "Invalid email or password."


def _lite_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_email(email: str) -> str:
    """Lowercase and strip an email address before any lookup."""
    return email.strip().lower()


def _valid_email_shape(email: str) -> bool:
    local, sep, domain = email.partition("@")
    return bool(sep) and bool(local) and "." in domain


class RegisterRequest(BaseModel):
    email: str
    password: str
    date_of_birth: date

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        if not _valid_email_shape(value.strip()):
            raise ValueError("email must look like name@example.com")
        return value

    @field_validator("password")
    @classmethod
    def _password_shape(cls, value: str) -> str:
        if not 8 <= len(value) <= 512:
            raise ValueError("password must be 8-512 characters")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def _not_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("date_of_birth cannot be in the future")
        return value


class VerifyEmailRequest(BaseModel):
    token: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


def create_app(
    db_path=None, mail_dir=None, uploads_dir=None, clip_encoder=None
) -> FastAPI:
    """Build the Lite FastAPI app.

    Explicit paths are for tests; defaults are the real Lite
    locations. Nothing is created on disk until a request arrives
    (each connection ensures the idempotent schema first).
    ``clip_encoder`` is the optional CLIP test hook for the upload
    pipeline (default live); tests pass a stub for speed.
    """
    app = FastAPI(title="iVouch Lite")
    app.state.db_path = str(db_path) if db_path is not None else str(
        _lite_dir() / "data" / "ivouch.db"
    )
    app.state.mail_dir = (
        str(mail_dir)
        if mail_dir is not None
        else str(resolve_mail_dir())
    )
    app.state.uploads_dir = (
        str(uploads_dir)
        if uploads_dir is not None
        else str(_lite_dir() / "data" / "uploads")
    )
    app.state.clip_encoder = clip_encoder
    app.include_router(auth_router)
    app.include_router(upload_router)
    return app


@contextmanager
def _connection(request: Request):
    """Open a SQLite connection for one request (schema ensured)."""
    init_db(request.app.state.db_path)
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _row_to_dict(row) -> dict:
    return dict(row) if row is not None else {}


def get_current_account(request: Request):
    """Dependency: account row for a valid Bearer access token.

    Missing, expired, mis-signed, or orphaned (deleted account)
    credentials all answer 401 with the same body.
    """
    http_auth = _credentials_from(request)
    token = http_auth.credentials if http_auth else None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    try:
        email = auth_helpers.decode_access_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        ) from None
    with _connection(request) as conn:
        row = get_account_by_email(conn, email)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
            )
        return _row_to_dict(row)


def _credentials_from(
    request: Request,
) -> HTTPAuthorizationCredentials | None:
    scheme, _, token = request.headers.get("authorization", "").partition(
        " "
    )
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return HTTPAuthorizationCredentials(
        scheme=scheme, credentials=token.strip()
    )


auth_router = APIRouter(tags=["auth"])


@auth_router.post("/auth/register")
def register(payload: RegisterRequest, request: Request):
    """Create an account and send a console verification mail.

    Always 200 with the same generic body: new accounts, already-known
    emails, and under-age signups are indistinguishable. Under-age
    signups create no row and send no mail; the birth date itself is
    never stored, logged, or mailed -- only ``age_confirmed_at``.
    """
    email = normalize_email(payload.email)
    with _connection(request) as conn:
        if not auth_helpers.is_adult(
            payload.date_of_birth, load_config().min_age
        ):
            return {"message": GENERIC_REGISTER_MESSAGE}
        if get_account_by_email(conn, email) is not None:
            return {"message": GENERIC_REGISTER_MESSAGE}
        try:
            create_account(
                conn,
                email=email,
                password_hash=auth_helpers.hash_password(
                    payload.password
                ),
                email_verified=0,
                age_confirmed_at=auth_helpers.utcnow_iso(),
            )
        except sqlite3.IntegrityError:
            # Lost a race with a concurrent register: stay generic.
            return {"message": GENERIC_REGISTER_MESSAGE}
        write_verification_email(
            request.app.state.mail_dir,
            email,
            auth_helpers.create_verify_token(email),
        )
    return {"message": GENERIC_REGISTER_MESSAGE}


@auth_router.post("/auth/verify-email")
def verify_email(payload: VerifyEmailRequest, request: Request):
    """Mark an account verified for a valid console-mail token."""
    try:
        token_email = auth_helpers.decode_verify_token(payload.token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token.",
        ) from None
    if payload.email is not None and normalize_email(
        payload.email
    ) != normalize_email(token_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token.",
        ) from None
    with _connection(request) as conn:
        row = get_account_by_email(conn, normalize_email(token_email))
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token.",
            ) from None
        if not row["email_verified"]:
            conn.execute(
                "UPDATE accounts SET email_verified = 1 WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
    return {"message": "Email verified."}


@auth_router.post("/auth/login")
def login(payload: LoginRequest, request: Request):
    """Check credentials and return a short-lived access JWT.

    Unknown emails and wrong passwords answer identically (401 with
    one body), so neither reveals whether an address is registered.
    Unverified accounts do get a token here -- the verified-only gate
    lives on upload (objective 2.3), which answers 403.
    """
    email = normalize_email(payload.email)
    with _connection(request) as conn:
        row = get_account_by_email(conn, email)
        if row is None:
            # Same timing shape as a real check, same body as below.
            auth_helpers.verify_password("argon2id$dummy$timing", "x")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=GENERIC_LOGIN_DETAIL,
            )
        if not auth_helpers.verify_password(
            row["password_hash"], payload.password
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=GENERIC_LOGIN_DETAIL,
            )
        if auth_helpers.password_needs_rehash(row["password_hash"]):
            conn.execute(
                "UPDATE accounts SET password_hash = ? WHERE id = ?",
                (
                    auth_helpers.hash_password(payload.password),
                    row["id"],
                ),
            )
            conn.commit()
        verified = bool(row["email_verified"])
    return {
        "access_token": auth_helpers.create_access_token(email),
        "token_type": "bearer",
        "email_verified": verified,
    }


@auth_router.get("/account")
def read_account(account: dict = Depends(get_current_account)):
    """Return the caller's own account (never the password hash)."""
    return {
        "id": account["id"],
        "email": account["email"],
        "email_verified": bool(account["email_verified"]),
        "status": account["status"],
        "created_at": account["created_at"],
    }


@auth_router.delete("/account")
def delete_account(request: Request, account: dict = Depends(get_current_account)):
    """Delete the caller's account, reports, and uploaded files.

    No legal hold in Lite. A single ``account_deletion`` audit event
    (email + time only) is kept.
    """
    with _connection(request) as conn:
        deleted = auth_helpers.delete_account_everywhere(
            conn, account["id"], request.app.state.uploads_dir
        )
    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    return {"message": "Account deleted."}


upload_router = APIRouter(tags=["upload"])


@upload_router.post("/analyze")
def analyze(
    request: Request,
    account: dict = Depends(get_current_account),
    photo: UploadFile | None = File(None),
    file: UploadFile | None = File(None),
    image: UploadFile | None = File(None),
    claim_text: str | None = Form(None),
    claim: str | None = Form(None),
    client_report_id: str | None = Form(None),
    location_lat: float | None = Form(None),
    location_lng: float | None = Form(None),
    location_consented: bool | None = Form(None),
    location_source: str | None = Form(None),
):
    """Accept one photo upload and run the synchronous check pipeline.

    Order: (1) location/consent validation first -- missing
    coordinates, a missing consent flag, or a false flag answers 422
    and stores nothing (no files, rows, or audit events); (2) the
    verified-email gate answers 403; the rest (413/415 file sanity,
    the mock hash gate, provenance -> duplicates -> CLIP -> claim ->
    fusion) is delegated to the pipeline module. A completed upload
    returns 200 with the finished report.
    """
    upload = photo if photo is not None else (
        file if file is not None else image
    )
    # (1) Location and consent first: 422 stores nothing.
    if (
        location_lat is None
        or location_lng is None
        or not math.isfinite(location_lat)
        or not math.isfinite(location_lng)
    ):
        raise HTTPException(
            status_code=422,
            detail="location_lat and location_lng are required.",
        )
    if location_consented is not True:
        raise HTTPException(
            status_code=422,
            detail="location_consented must be true.",
        )
    if location_source not in ("browser", "manual_pin"):
        raise HTTPException(
            status_code=422,
            detail="location_source must be 'browser' or 'manual_pin'.",
        )
    if client_report_id is None or not client_report_id.strip():
        raise HTTPException(
            status_code=422,
            detail="client_report_id is required.",
        )
    # (2) Verified-email gate.
    if not account.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required before upload.",
        )
    if upload is None:
        raise HTTPException(
            status_code=422,
            detail="photo is required.",
        )
    raw = upload.file.read()
    text = claim_text if claim_text is not None else claim
    claim_value = text.strip() if text and text.strip() else None
    encoder = getattr(request.app.state, "clip_encoder", None)
    with _connection(request) as conn:
        status_code, body = upload_pipeline.process_upload(
            conn=conn,
            account_id=account["id"],
            raw=raw,
            claim_text=claim_value,
            client_report_id=client_report_id.strip(),
            location_lat=location_lat,
            location_lng=location_lng,
            location_source=location_source,
            uploads_dir=request.app.state.uploads_dir,
            encoder=encoder,
        )
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=body["detail"])
    return body


# Module-level app for serving (uvicorn lite.app.server.api:app).
# Created without touching disk: paths resolve on first request.
app = create_app()
