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

import json
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
    Response,
    UploadFile,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator

from lite.app.config import load_config
from lite.app.server import auth as auth_helpers
from lite.app.server import pipeline as upload_pipeline
from lite.app.server.geo import display_point
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
    from lite.app.server import pages as pages_module

    # Pages first: the HTML GET /account (browser navigation) is reached
    # before the JSON GET /account below; non-HTML clients are delegated
    # back to the spec-2 implementation inside the page handler.
    app.include_router(pages_module.pages_router)
    app.include_router(auth_router)
    app.include_router(upload_router)
    app.include_router(retrieval_router)
    app.include_router(review_router)
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
    if "report_id" in body:
        # Remember the normalised claim for retrieval. First upload
        # wins on idempotent replay (INSERT OR IGNORE), matching the
        # report row's first-wins rule. Claims live in an auxiliary
        # table owned here so the committed schema stays untouched.
        with _connection(request) as conn:
            _remember_claim(conn, body["report_id"], claim_value)
    return body


retrieval_router = APIRouter(tags=["retrieval"])

_CLAIMS_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS report_claims ("
    " report_id INTEGER PRIMARY KEY REFERENCES reports(id)"
    " ON DELETE CASCADE,"
    " claim_text TEXT)"
)


def _ensure_claims_table(conn) -> None:
    """Create the auxiliary claim-text table when missing."""
    conn.execute(_CLAIMS_TABLE_SQL)
    conn.commit()


def _remember_claim(conn, report_id: int, claim_text) -> None:
    """Store ``claim_text`` for ``report_id`` (first write wins)."""
    _ensure_claims_table(conn)
    conn.execute(
        "INSERT OR IGNORE INTO report_claims (report_id, claim_text)"
        " VALUES (?, ?)",
        (report_id, claim_text),
    )
    conn.commit()


def _claim_text(conn, report_id: int):
    """Return the stored claim for ``report_id``, or None."""
    _ensure_claims_table(conn)
    row = conn.execute(
        "SELECT claim_text FROM report_claims WHERE report_id = ?",
        (report_id,),
    ).fetchone()
    return row["claim_text"] if row is not None else None


def _check_result(conn, report_id: int):
    """Return the ``check_results`` row, or None when not accepted."""
    return conn.execute(
        "SELECT * FROM check_results WHERE report_id = ?",
        (report_id,),
    ).fetchone()


def _accepted_report(conn, report_id: int):
    """Return ``(report, check)`` for an accepted report, else None.

    Accepted means the report row exists and has a ``check_results``
    row. Mock-gate-rejected uploads create no report row, so they
    land here as None (404 everywhere).
    """
    report = conn.execute(
        "SELECT * FROM reports WHERE id = ?", (report_id,)
    ).fetchone()
    if report is None:
        return None
    check = _check_result(conn, report_id)
    if check is None:
        return None
    return report, check


def _photo_url(report_id: int) -> str:
    """Public photo route for a report (never a raw file path)."""
    return f"/api/photos/{report_id}"


def _report_payload(report, check, claim_text, owner: bool) -> dict:
    """Build the exact retrieval body for one accepted report.

    Never serializes the uploader email, exact coordinates, or raw
    file paths -- only the jittered ``display_*`` point.
    """
    incident = dict(json.loads(check["incident_probs"]))
    severity = dict(json.loads(check["severity_probs"]))
    display_lat, display_lng = display_point(
        report["location_lat"], report["location_lng"], report["id"]
    )
    shared = {
        "report_id": report["id"],
        "photo_url": _photo_url(report["id"]),
        "claim_text": claim_text,
        "display_lat": display_lat,
        "display_lng": display_lng,
        "incident_probs": incident,
        "severity_probs": severity,
        "top_severity": (
            max(severity, key=severity.get) if severity else None
        ),
        "verdict": check["verdict"],
        "reasons": list(json.loads(check["reasons"])),
        "confidence": (
            max(incident.values()) if incident else 0.0
        ),
        "created_at": report["created_at"],
    }
    if not owner:
        return shared
    return {
        "report_id": shared["report_id"],
        "status": report["status"],
        "client_report_id": report["client_report_id"],
        "photo_url": shared["photo_url"],
        "claim_text": shared["claim_text"],
        "display_lat": shared["display_lat"],
        "display_lng": shared["display_lng"],
        "incident_probs": shared["incident_probs"],
        "severity_probs": shared["severity_probs"],
        "top_severity": shared["top_severity"],
        "verdict": shared["verdict"],
        "reasons": shared["reasons"],
        "confidence": shared["confidence"],
        "needs_review": check["verdict"] != "likely-real",
        "created_at": shared["created_at"],
    }


def _photo_path(uploads_dir, account_id: int, report_id: int):
    """Resolve the stored photo file, or None when missing."""
    parent = Path(uploads_dir) / str(account_id)
    if not parent.is_dir():
        return None
    candidates = sorted(parent.glob(f"{report_id}.*"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _photo_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return "application/octet-stream"


@retrieval_router.get("/reports")
def list_reports(request: Request, account: dict = Depends(get_current_account)):
    """List the caller's own accepted reports (owner-only)."""
    with _connection(request) as conn:
        rows = conn.execute(
            "SELECT r.* FROM reports r"
            " JOIN check_results c ON c.report_id = r.id"
            " WHERE r.account_id = ? ORDER BY r.id",
            (account["id"],),
        ).fetchall()
        return [
            _report_payload(
                row,
                _check_result(conn, row["id"]),
                _claim_text(conn, row["id"]),
                owner=True,
            )
            for row in rows
        ]


@retrieval_router.get("/reports/{report_id}")
def get_report(
    report_id: int,
    request: Request,
    account: dict = Depends(get_current_account),
):
    """Return one own report; 404 unless the caller owns it."""
    with _connection(request) as conn:
        report = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        if report is None or report["account_id"] != account["id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )
        check = _check_result(conn, report_id)
        if check is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )
        return _report_payload(
            report, check, _claim_text(conn, report_id), owner=True
        )


@retrieval_router.get("/api/incidents")
def list_incidents(
    request: Request, account: dict = Depends(get_current_account)
):
    """GeoJSON-style shared list of accepted reports, all accounts."""
    with _connection(request) as conn:
        rows = conn.execute(
            "SELECT r.* FROM reports r"
            " JOIN check_results c ON c.report_id = r.id"
            " ORDER BY r.id"
        ).fetchall()
        features = []
        for report in rows:
            check = _check_result(conn, report["id"])
            payload = _report_payload(
                report, check, _claim_text(conn, report["id"]),
                owner=False,
            )
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            payload["display_lng"],
                            payload["display_lat"],
                        ],
                    },
                    "properties": payload,
                }
            )
    return {"type": "FeatureCollection", "features": features}


@retrieval_router.get("/shared/{report_id}")
def get_shared_report(
    report_id: int,
    request: Request,
    account: dict = Depends(get_current_account),
):
    """Return one accepted report's shared fields (any login)."""
    with _connection(request) as conn:
        found = _accepted_report(conn, report_id)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )
        report, check = found
        return _report_payload(
            report, check, _claim_text(conn, report_id), owner=False
        )


@retrieval_router.get("/api/photos/{report_id}")
def get_photo(
    report_id: int,
    request: Request,
    account: dict = Depends(get_current_account),
):
    """Serve stored photo bytes.

    Any logged-in user may fetch an accepted report's photo;
    otherwise only the owner (404 for everyone else, and 404 when
    no report row exists, e.g. mock-rejected uploads).
    """
    with _connection(request) as conn:
        report = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )
        accepted = _check_result(conn, report_id) is not None
        if not accepted and report["account_id"] != account["id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )
        path = _photo_path(
            request.app.state.uploads_dir,
            report["account_id"],
            report_id,
        )
        if path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )
        return Response(
            content=path.read_bytes(),
            media_type=_photo_media_type(path),
        )


review_router = APIRouter(tags=["review"])

REVIEW_ACTIONS = frozenset({"confirm", "correct", "dismiss"})


class ReviewActionRequest(BaseModel):
    """Body for ``POST /review/{id}/actions`` (unknown keys ignored)."""

    action: str
    incident: Optional[str] = None
    severity: Optional[str] = None
    note: Optional[str] = None


def _require_reviewer(account: dict) -> dict:
    """Raise 403 unless ``account`` carries the reviewer flag."""
    if not account.get("reviewer"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer access required.",
        )
    return account


def _check_tops(check) -> tuple:
    """Return ``(incident_top, severity_top)`` for a check_results row."""
    incident = dict(json.loads(check["incident_probs"]))
    severity = dict(json.loads(check["severity_probs"]))
    return (
        max(incident, key=incident.get) if incident else None,
        max(severity, key=severity.get) if severity else None,
    )


def effective_labels(conn, report_id: int) -> dict:
    """Return the effective incident/severity labels for ``report_id``.

    Reads the stored check outputs plus the latest ``correct`` review
    action (never mutates anything). Shape (shared with the spec-4
    4.1 review-detail page and the owner result banner carry-over)::

        {"incident_top": str | None,
         "severity": str | None,
         "corrected": bool,
         "correction": None |
            {"incident_top": str, "severity": str,
             "reviewer": str | None, "time": str}}
    """
    incident_top, severity_top = None, None
    check = _check_result(conn, report_id)
    if check is not None:
        incident_top, severity_top = _check_tops(check)
    row = conn.execute(
        "SELECT ra.*, a.email AS reviewer_email FROM review_actions ra"
        " LEFT JOIN accounts a ON a.id = ra.reviewer_account_id"
        " WHERE ra.report_id = ? AND ra.action = 'correct'"
        " ORDER BY ra.id DESC LIMIT 1",
        (report_id,),
    ).fetchone()
    if row is None:
        return {
            "incident_top": incident_top,
            "severity": severity_top,
            "corrected": False,
            "correction": None,
        }
    after = json.loads(row["after"]) if row["after"] else {}
    return {
        "incident_top": after.get("incident_top", incident_top),
        "severity": after.get("severity", severity_top),
        "corrected": True,
        "correction": {
            "incident_top": after.get("incident_top"),
            "severity": after.get("severity"),
            "reviewer": row["reviewer_email"],
            "time": row["created_at"],
        },
    }


def _action_history(conn, report_id: int) -> list:
    """Return every review action for ``report_id``, oldest first."""
    rows = conn.execute(
        "SELECT ra.*, a.email AS reviewer_email FROM review_actions ra"
        " LEFT JOIN accounts a ON a.id = ra.reviewer_account_id"
        " WHERE ra.report_id = ? ORDER BY ra.id",
        (report_id,),
    ).fetchall()
    return [
        {
            "reviewer": row["reviewer_email"],
            "action": row["action"],
            "before": json.loads(row["before"]) if row["before"] else None,
            "after": json.loads(row["after"]) if row["after"] else None,
            "time": row["created_at"],
        }
        for row in rows
    ]


@review_router.post("/review/{report_id}/actions")
def review_action(
    report_id: int,
    payload: ReviewActionRequest,
    request: Request,
    account: dict = Depends(get_current_account),
):
    """Record one reviewer action (confirm/correct/dismiss).

    Reviewers only (403 otherwise); 404 when no accepted report
    exists. ``correct`` requires an incident label from the config
    taxonomy and a severity (else 422); ``confirm``/``dismiss`` keep
    the current effective values and ignore extras. Writes exactly
    one ``review_actions`` row (plus one ``review_action`` audit
    event) and never touches ``check_results``.
    """
    _require_reviewer(account)
    with _connection(request) as conn:
        found = _accepted_report(conn, report_id)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )
        if payload.action not in REVIEW_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail=f"action must be one of {sorted(REVIEW_ACTIONS)}.",
            )
        cfg = load_config()
        if payload.action == "correct":
            if payload.incident not in cfg.incident_prompts:
                raise HTTPException(
                    status_code=422,
                    detail="correct requires incident from the taxonomy.",
                )
            if payload.severity not in cfg.severity_prompts:
                raise HTTPException(
                    status_code=422,
                    detail="correct requires severity minor|moderate|severe.",
                )
        before_values = effective_labels(conn, report_id)
        before = {
            "incident_top": before_values["incident_top"],
            "severity": before_values["severity"],
        }
        if payload.action == "correct":
            after = {
                "incident_top": payload.incident,
                "severity": payload.severity,
            }
        else:
            after = dict(before)
        now = auth_helpers.utcnow_iso()
        conn.execute(
            "INSERT INTO review_actions (report_id, reviewer_account_id,"
            " action, before, after, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                report_id,
                account["id"],
                payload.action,
                json.dumps(before),
                json.dumps(after),
                now,
            ),
        )
        conn.execute(
            "INSERT INTO audit_events (kind, actor_account_id, report_id,"
            " detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                "review_action",
                account["id"],
                report_id,
                json.dumps(
                    {
                        "action": payload.action,
                        "before": before,
                        "after": after,
                    }
                ),
                now,
            ),
        )
        conn.commit()
    return {"ok": True, "action": payload.action, "report_id": report_id}


@review_router.get("/review/api/{report_id}")
def review_detail(
    report_id: int,
    request: Request,
    account: dict = Depends(get_current_account),
):
    """Reviewer JSON detail: shared report fields plus review state.

    Shape: the shared (non-owner) report payload plus ``correction``
    (None when uncorrected, else ``{incident_top, severity, reviewer,
    time}``), ``corrected`` (bool), and ``history`` (list of
    ``{reviewer, action, before, after, time}``, oldest first). Never
    includes the uploader's email. Reviewers only (403); 404 when no
    accepted report exists.
    """
    _require_reviewer(account)
    with _connection(request) as conn:
        found = _accepted_report(conn, report_id)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )
        report, check = found
        payload = _report_payload(
            report, check, _claim_text(conn, report_id), owner=False
        )
        current = effective_labels(conn, report_id)
        payload["corrected"] = current["corrected"]
        payload["correction"] = current["correction"]
        payload["history"] = _action_history(conn, report_id)
        return payload


# Module-level app for serving (uvicorn lite.app.server.api:app).
# Created without touching disk: paths resolve on first request.
app = create_app()
