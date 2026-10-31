"""Server-rendered account and upload pages for iVouch Lite (spec 3).

Routes (``pages_router``, included FIRST in ``create_app`` so each
HTML page below is reached before the same-path JSON route in the
spec-2 routers; non-browser clients are delegated to the spec-2
implementation unchanged):
objective 3.1: ``GET/POST /signup``, ``GET/POST /login``,
``GET /logout``, ``GET /account`` (HTML for browsers),
``POST /account/delete``, ``GET /verify``, ``POST /verify-resend``,
``GET /upload`` (verified gate);
objective 3.2: ``POST /upload`` (browser upload flow),
``GET /reports`` (own list, HTML for browsers),
``GET /reports/{id}`` (owner result, HTML for browsers),
``GET /shared/{id}`` (community page, HTML for browsers);
``GET /shared/photos/{id}`` (photo bytes for cookie sessions);
``GET /map`` (community map, HTML for browsers);
objective 6.6: ``GET /saved`` (saved places, HTML for browsers),
``POST /saved`` (save toggle-add), ``POST /saved/{id}/unsave``;
objective 6.7: ``GET /feed`` (community feed, HTML for browsers);
objective 6.4: ``POST /vouches`` (vouch toggle-add),
``POST /vouches/{id}/unvouch`` (remove),
``POST /comments`` (post one plain-text comment),
``GET /api/reports/{id}/comments`` (list, oldest first),
``POST /reports/{id}/edit`` (owner-only claim-text edit),
``POST /reports/{id}/delete`` (owner-only delete, confirm-once);
``GET /api/photos/{id}`` (cookie-aware bridge, delegates without one);
``GET /static/style.css``.

Auth bridge: a successful page login calls the spec-2 ``POST
/auth/login`` handler and stores the returned JWT in the ``lite_session``
cookie (HttpOnly, SameSite=Lax, Path=/). Page handlers read that cookie
and authenticate exactly as the Bearer path does (same JWT decode plus
the same account lookup); the cookie value IS the Bearer credential,
translated from cookie transport to header semantics. ``GET /logout``
clears it. No other api.py change was needed besides including this
router (see the ``create_app`` edit); page POST handlers that must go
through spec-2 (signup, login, verify) import the api module lazily
inside the handler and call the same functions the JSON routes call, so
there is exactly one implementation of each rule (generic register
replies, generic login failures, token checks).

CSRF: double-submit cookie. Every GET page that renders a POST form
issues a fresh random ``lite_csrf`` cookie (when absent) and embeds the
same value in a hidden ``csrf_token`` field. Every POST handler rejects
with 403 unless the field equals the cookie (constant-time compare).
Stateless: no server-side session store. The ``/verify`` token-entry
form uses GET (query params), so it needs no CSRF field.

Content negotiation on ``GET /account``: browsers send
``Accept: text/html`` and get the HTML page (anonymous browsers are
303-redirected to ``/login``); every other client is delegated to the
spec-2 ``GET /account`` implementation unchanged, so the JSON contract
(and its 401s) is byte-for-byte what it was.

``GET /upload`` gate: anonymous users are redirected to ``/login``;
unverified users get a page saying "verify your email" with a resend
action and uploads disabled; verified users get the upload form
(photo, optional claim text, location picker plus mandatory consent
checkbox) with the demo content notice and the data-use notice above
the picker. The submit button starts disabled and is enabled by a tiny
vanilla script only when a location is set and consent is checked;
the server enforces the same rule through the 422 path of the spec-2
``POST /analyze`` implementation.

``POST /upload`` browser flow: the form posts here (cookie session +
CSRF), and this handler delegates to the spec-2 ``POST /analyze``
implementation (``api.analyze``, same function the JSON route calls,
so there is exactly one upload rule set) with the session account.
The JSON route itself stays Bearer-only, which browsers cannot send
(the session cookie is HttpOnly). A finished upload redirects to the
owner result page; the mock-gate rejection body shape (no report row
exists) renders a page with only the generic message plus the content
notice. ``GET /reports`` lists only the caller's own reports, newest
first, as links (never image bytes). ``GET /reports/{id}`` renders
the owner result card from API JSON display values (never recomputed
checks). ``GET /shared/{id}`` renders the shared fields plus the
photo for any logged-in user (404 when no accepted report exists).

``GET /shared/photos/{id}`` serves the stored photo bytes to a
cookie-session browser (``<img>`` tags send cookies, never an
``Authorization`` header). It authenticates via the ``lite_session``
cookie exactly like the other page routes and then delegates to the
spec-2 ``GET /api/photos/{id}`` implementation with the
cookie-derived account, so the visibility rule has exactly one
implementation (any logged-in user when accepted, owner-only
otherwise, 404 for rejected/missing). Anonymous callers get the 404
page (an ``<img>`` cannot follow a login redirect).

The owner result card (``report.html``, which renders ``<img
src="{{ report.photo_url }}">`` with the API URL) is fixed without
touching that template: this router is included before the spec-2
routers, so ``GET /api/photos/{id}`` here is reached first. With a
valid session cookie it serves through the same spec-2
implementation; without one it delegates to the spec-2 handler
unchanged, so Bearer-token JSON clients (and their 401s) behave
byte-for-byte as before.
"""

from __future__ import annotations

import json
import math
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import jinja2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from lite.app.config import load_config
from lite.app.server import auth as auth_helpers
from lite.app.server.db import connect, get_account_by_email, init_db
from lite.app.server.mail import write_verification_email

SESSION_COOKIE = "lite_session"
CSRF_COOKIE = "lite_csrf"
CSRF_FIELD = "csrf_token"

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)

pages_router = APIRouter(tags=["pages"])


@contextmanager
def _page_connection(request: Request):
    """Open a SQLite connection for one page request (schema ensured)."""
    init_db(request.app.state.db_path)
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _min_age() -> int:
    return load_config().min_age


def _session_email(request: Request) -> str | None:
    """Email from the session cookie, or None when absent/invalid."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return auth_helpers.decode_access_token(token)
    except ValueError:
        return None


def _account_for_session(request: Request) -> dict | None:
    """Account row for the session cookie, or None (anon/invalid)."""
    email = _session_email(request)
    if email is None:
        return None
    with _page_connection(request) as conn:
        row = get_account_by_email(conn, email.strip().lower())
        return dict(row) if row is not None else None


def _csrf_issue(request: Request) -> tuple[str, bool]:
    """Return ``(token, is_new)`` for this request's CSRF cookie."""
    token = request.cookies.get(CSRF_COOKIE)
    if token and len(token) >= 16:
        return token, False
    return secrets.token_urlsafe(32), True


def _csrf_valid(request: Request, field_value) -> bool:
    """True when the posted field matches the CSRF cookie."""
    cookie = request.cookies.get(CSRF_COOKIE)
    if not cookie or not field_value or len(cookie) < 16:
        return False
    return secrets.compare_digest(cookie, str(field_value))


def _render(
    name: str,
    context: dict,
    status: int = 200,
    csrf_new: str | None = None,
):
    """Render a template to an HTML response (sets CSRF cookie if new)."""
    body = _env.get_template(name).render(context)
    response = HTMLResponse(body, status_code=status)
    if csrf_new is not None:
        response.set_cookie(
            CSRF_COOKIE, csrf_new, path="/", samesite="lax"
        )
    return response


def _redirect(location: str) -> RedirectResponse:
    return RedirectResponse(location, status_code=303)


def _wants_html(request: Request) -> bool:
    """True for browser navigation (HTML accept, no API credential)."""
    accept = request.headers.get("accept", "")
    return "text/html" in accept and not request.headers.get(
        "authorization", ""
    )


def _csrf_denied() -> Response:
    return _render(
        "message.html",
        {
            "title": "Not allowed",
            "heading": "Not allowed",
            "message": "Missing or invalid form token."
            " Go back and try again.",
            "back": "/",
            "back_label": "Home",
        },
        status=403,
    )


@pages_router.get("/static/style.css")
def style_css():
    """Serve the tiny page stylesheet (no StaticFiles dependency)."""
    path = STATIC_DIR / "style.css"
    if not path.is_file():
        return Response(status_code=404)
    return Response(
        path.read_bytes(encoding="utf-8"), media_type="text/css"
    )


@pages_router.get("/signup")
def signup_form(request: Request):
    """Show signup: age gate, demo disclaimer, data-use notice."""
    if _account_for_session(request) is not None:
        return _redirect("/account")
    token, is_new = _csrf_issue(request)
    return _render(
        "signup.html",
        {
            "title": "Create account",
            "csrf_token": token,
            "min_age": _min_age(),
            "error": None,
            "info": None,
        },
        csrf_new=token if is_new else None,
    )


@pages_router.post("/signup")
async def signup_submit(request: Request):
    """Submit signup through the spec-2 register handler (generic reply)."""
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    email = str(form.get("email", "") or "")
    password = str(form.get("password", "") or "")
    dob_raw = str(form.get("date_of_birth", "") or "").strip()

    def _fail(message: str):
        token, is_new = _csrf_issue(request)
        return _render(
            "signup.html",
            {
                "title": "Create account",
                "csrf_token": token,
                "min_age": _min_age(),
                "error": message,
                "info": None,
            },
            status=400,
            csrf_new=token if is_new else None,
        )

    try:
        dob = date.fromisoformat(dob_raw)
    except ValueError:
        return _fail("Enter your date of birth as YYYY-MM-DD.")
    from lite.app.server import api as api_module

    try:
        payload = api_module.RegisterRequest(
            email=email, password=password, date_of_birth=dob
        )
    except ValidationError:
        return _fail("Check the highlighted fields and try again.")
    result = api_module.register(payload, request)
    token, is_new = _csrf_issue(request)
    return _render(
        "signup.html",
        {
            "title": "Create account",
            "csrf_token": token,
            "min_age": _min_age(),
            "error": None,
            "info": result["message"],
        },
        csrf_new=token if is_new else None,
    )


@pages_router.get("/login")
def login_form(request: Request):
    """Show the login form."""
    if _account_for_session(request) is not None:
        return _redirect("/account")
    token, is_new = _csrf_issue(request)
    return _render(
        "login.html",
        {
            "title": "Log in",
            "csrf_token": token,
            "error": None,
        },
        csrf_new=token if is_new else None,
    )


@pages_router.post("/login")
async def login_submit(request: Request):
    """Log in via spec-2 and set the HttpOnly session cookie."""
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()

    def _fail(message: str, status: int):
        token, is_new = _csrf_issue(request)
        return _render(
            "login.html",
            {
                "title": "Log in",
                "csrf_token": token,
                "error": message,
            },
            status=status,
            csrf_new=token if is_new else None,
        )

    from lite.app.server import api as api_module

    try:
        payload = api_module.LoginRequest(
            email=str(form.get("email", "") or ""),
            password=str(form.get("password", "") or ""),
        )
    except ValidationError:
        return _fail("Enter an email address and password.", 400)
    try:
        result = api_module.login(payload, request)
    except Exception as exc:
        from fastapi import HTTPException as _HTTPException

        if isinstance(exc, _HTTPException):
            return _fail(exc.detail, exc.status_code)
        raise
    response = _redirect("/account")
    response.set_cookie(
        SESSION_COOKIE,
        result["access_token"],
        httponly=True,
        samesite="lax",
        path="/",
        max_age=load_config().jwt_access_minutes * 60,
    )
    return response


@pages_router.get("/logout")
def logout(request: Request):
    """Clear the session (and CSRF) cookies, then go to login."""
    response = _redirect("/login")
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@pages_router.get("/account")
def account_page(request: Request):
    """Show the caller's own account (HTML for browsers).

    Non-browser clients are delegated to the spec-2 JSON ``GET
    /account`` implementation unchanged.
    """
    if not _wants_html(request):
        from lite.app.server import api as api_module

        account = api_module.get_current_account(request)
        return api_module.read_account(account)
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    token, is_new = _csrf_issue(request)
    return _render(
        "account.html",
        {
            "title": "Your account",
            "csrf_token": token,
            "email": account["email"],
            "verified": bool(account["email_verified"]),
        },
        csrf_new=token if is_new else None,
    )


@pages_router.post("/account/delete")
async def account_delete(request: Request):
    """Delete the caller's account after a single confirm, then login."""
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")

    def _fail(message: str):
        token, is_new = _csrf_issue(request)
        return _render(
            "account.html",
            {
                "title": "Your account",
                "csrf_token": token,
                "email": account["email"],
                "verified": bool(account["email_verified"]),
                "error": message,
            },
            status=400,
            csrf_new=token if is_new else None,
        )

    if form.get("confirm") != "yes":
        return _fail("Tick the confirmation box to delete your account.")
    with _page_connection(request) as conn:
        deleted = auth_helpers.delete_account_everywhere(
            conn, account["id"], request.app.state.uploads_dir
        )
    if deleted is None:
        return _redirect("/login")
    response = _redirect("/login")
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@pages_router.get("/verify")
def verify_landing(request: Request):
    """Verify landing: reads token/email query, posts to verify API."""
    params = request.query_params
    token_param = (params.get("token") or "").strip()
    email_param = (params.get("email") or "").strip() or None
    message = None
    error = None
    if token_param:
        from lite.app.server import api as api_module

        try:
            result = api_module.verify_email(
                api_module.VerifyEmailRequest(
                    token=token_param, email=email_param
                ),
                request,
            )
            message = result["message"] + " You can now log in."
        except Exception as exc:
            from fastapi import HTTPException as _HTTPException

            if isinstance(exc, _HTTPException):
                error = exc.detail
            else:
                raise
    csrf, is_new = _csrf_issue(request)
    return _render(
        "verify.html",
        {
            "title": "Verify email",
            "csrf_token": csrf,
            "message": message,
            "error": error,
            "email": email_param or "",
        },
        csrf_new=csrf if is_new else None,
    )


@pages_router.post("/verify-resend")
async def verify_resend(request: Request):
    """Send a fresh verification mail to the logged-in account."""
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    if account["email_verified"]:
        message = "Your email address is already verified."
    else:
        email = account["email"]
        write_verification_email(
            request.app.state.mail_dir,
            email,
            auth_helpers.create_verify_token(email),
        )
        message = "Verification email sent. Check your email for next steps."
    return _render(
        "message.html",
        {
            "title": "Verification email",
            "heading": "Verification email",
            "message": message,
            "back": "/account",
            "back_label": "Back to your account",
        },
    )


@pages_router.get("/upload")
def upload_landing(request: Request):
    """Upload gate: login redirect, verify prompt, or the upload form."""
    return _upload_page(request, account=_account_for_session(request))


def _upload_page(request: Request, account, error=None, status: int = 200):
    """Render ``GET /upload`` for ``account`` (None means anonymous)."""
    if account is None:
        return _redirect("/login")
    from lite.app.server import api as api_module

    token, is_new = _csrf_issue(request)
    return _render(
        "upload.html",
        {
            "title": "Upload",
            "csrf_token": token,
            "verified": bool(account["email_verified"]),
            "client_report_id": uuid.uuid4().hex,
            "error": error,
            "categories": api_module.category_choices(),
        },
        status=status,
        csrf_new=token if is_new else None,
    )


def _parse_float(value):
    """Parse a form value to float, or None when missing/not numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _not_found(back: str = "/", back_label: str = "Home"):
    """Render the generic 404 page."""
    return _render(
        "message.html",
        {
            "title": "Not found",
            "heading": "Not found",
            "message": "Not found.",
            "back": back,
            "back_label": back_label,
        },
        status=404,
    )


def _top_incident(body: dict):
    """Top ``(name, probability)`` from an API report payload.

    Pure display derivation from the API JSON values the page was
    given; no check is recomputed here.
    """
    incident = dict(body["incident_probs"])
    name = max(incident, key=incident.get)
    return name, incident[name]


@pages_router.post("/upload")
async def upload_submit(request: Request):
    """Browser upload flow through the spec-2 ``POST /analyze`` rules.

    Cookie session plus CSRF (browsers cannot send the JSON route's
    Bearer header). Delegates to ``api.analyze`` with the session
    account, so file, location/consent, verification, and mock-gate
    rules have exactly one implementation. Missing location or
    consent answers 422 with the form re-rendered; a finished upload
    redirects to the owner result page; the mock-gate rejection body
    (no report row exists) renders only the generic message plus the
    content notice.
    """
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    if not account["email_verified"]:
        return _upload_page(request, account, status=403)

    raw_photo = form.get("photo")
    photo = (
        raw_photo
        if hasattr(raw_photo, "filename") and raw_photo.filename
        else None
    )
    claim_raw = form.get("claim_text")
    if claim_raw is None:
        claim_raw = form.get("claim")
    claim = claim_raw if isinstance(claim_raw, str) else None
    title_raw = form.get("title")
    title = title_raw if isinstance(title_raw, str) else None
    category_raw = form.get("category")
    category = category_raw if isinstance(category_raw, str) else None
    source_raw = form.get("location_source")
    source = source_raw if isinstance(source_raw, str) else None
    client_raw = form.get("client_report_id")
    client_id = (
        client_raw.strip()
        if isinstance(client_raw, str) and client_raw.strip()
        else None
    )

    from lite.app.server import api as api_module
    from lite.app.server.pipeline import MOCK_REJECTION_DETAIL

    try:
        body = api_module.analyze(
            request,
            account,
            photo=photo,
            claim_text=claim,
            client_report_id=client_id,
            location_lat=_parse_float(form.get("location_lat")),
            location_lng=_parse_float(form.get("location_lng")),
            location_consented=form.get("location_consented")
            in ("true", "on", "yes", "1"),
            location_source=source,
            title=title,
            category=category,
        )
    except HTTPException as exc:
        if exc.status_code in (413, 415, 422):
            return _upload_page(
                request, account, error=str(exc.detail),
                status=exc.status_code,
            )
        if exc.status_code == 403:
            return _upload_page(request, account, status=403)
        return _render(
            "message.html",
            {
                "title": "Upload failed",
                "heading": "Upload failed",
                "message": str(exc.detail),
                "back": "/upload",
                "back_label": "Back to upload",
            },
            status=exc.status_code,
        )
    if "report_id" in body:
        return _redirect(f"/reports/{body['report_id']}")
    return _render(
        "rejection.html",
        {
            "title": "Upload not accepted",
            "message": body.get("detail") or MOCK_REJECTION_DETAIL,
            "demo_notice": body.get("demo_notice"),
        },
    )


@pages_router.get("/reports")
def reports_list(request: Request):
    """Own-reports list: HTML for browsers, JSON delegation otherwise.

    The page shows only the caller's own reports, newest first, as
    links. No image bytes appear on this page.
    """
    if not _wants_html(request):
        from lite.app.server import api as api_module

        account = api_module.get_current_account(request)
        return api_module.list_reports(request, account)
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    from lite.app.server import api as api_module

    items = api_module.list_reports(request, account)
    return _render(
        "reports.html",
        {
            "title": "Your reports",
            "reports": list(reversed(items)),
        },
    )


@pages_router.get("/reports/{report_id}")
def report_detail(request: Request, report_id: int):
    """Owner result page: HTML for browsers, JSON delegation otherwise.

    Reads every display value from the API JSON payload. A
    ``needs_review`` verdict shows the human-review banner
    prominently. The HTML layout (hero, card, vouches, comments,
    sticky actions, owner controls) is shared with ``shared.html``.
    """
    if not _wants_html(request):
        from lite.app.server import api as api_module

        account = api_module.get_current_account(request)
        return api_module.get_report(report_id, request, account)
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    from lite.app.server import api as api_module

    try:
        body = api_module.get_report(report_id, request, account)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found(
                back="/reports", back_label="Back to your reports"
            )
        raise
    context, csrf_new = _detail_context(
        request, account, body, report_id, owner_view=True
    )
    return _render("report.html", context, csrf_new=csrf_new)


@pages_router.get("/shared/{report_id}")
def shared_detail(request: Request, report_id: int):
    """Community page: shared fields plus photo, any logged-in user.

    HTML for browsers, JSON delegation otherwise. Rejected uploads
    create no report row and deleted accounts take their rows with
    them, so both answer with the 404 page here.
    """
    if not _wants_html(request):
        from lite.app.server import api as api_module

        account = api_module.get_current_account(request)
        return api_module.get_shared_report(report_id, request, account)
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    from lite.app.server import api as api_module

    try:
        body = api_module.get_shared_report(report_id, request, account)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found()
        raise
    context, csrf_new = _detail_context(
        request, account, body, report_id, owner_view=False
    )
    return _render("shared.html", context, csrf_new=csrf_new)


COMMENT_BODY_MAX = 500
CLAIM_EDIT_MAX = 2000


def _accepted_or_404(request: Request, account: dict, report_id) -> dict:
    """Shared payload for an accepted report, else 404.

    Only accepted reports are vouchable, commentable, and savable:
    rejected uploads create no report row and rows without a check
    row answer 404 here, for every caller.
    """
    from lite.app.server import api as api_module

    if isinstance(report_id, bool) or not isinstance(report_id, int):
        raise HTTPException(status_code=404, detail="Not found.")
    try:
        return api_module.get_shared_report(report_id, request, account)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Not found."
            ) from None
        raise


def _owned_report_or_raise(
    request: Request, account: dict, report_id
) -> dict:
    """Owner payload for the owner's accepted report.

    Raises 404 when the report is missing or not accepted, 403 when a
    different account owns it. Non-owner form POSTs to the edit and
    delete endpoints answer 403 through this helper.
    """
    from lite.app.server import api as api_module

    if isinstance(report_id, bool) or not isinstance(report_id, int):
        raise HTTPException(status_code=404, detail="Not found.")
    with _page_connection(request) as conn:
        row = conn.execute(
            "SELECT account_id FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Not found.")
        if row["account_id"] != account["id"]:
            raise HTTPException(status_code=403, detail="Not allowed.")
        check = conn.execute(
            "SELECT report_id FROM check_results WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if check is None:
            raise HTTPException(status_code=404, detail="Not found.")
        return api_module.get_report(report_id, request, account)


def _owner_denied() -> Response:
    """Render the owner-only 403 page (never a login redirect)."""
    return _render(
        "message.html",
        {
            "title": "Not allowed",
            "heading": "Not allowed",
            "message": "Only the owner can change this report.",
            "back": "/",
            "back_label": "Home",
        },
        status=403,
    )


def _detail_context(
    request: Request,
    account: dict,
    body: dict,
    report_id: int,
    *,
    owner_view: bool,
    error: str | None = None,
):
    """Template context for the restyled detail layout (both pages).

    The title is the user-supplied title with the claim text (then the
    incident type) as fallback, so reports stored before titles existed
    still render. The category is display-only user input: it is shown
    as its own field and never replaces the incident type or any check
    output. Vouch counts are derived, never stored. Returns
    ``(context, csrf_new)`` for :func:`_render`.
    """
    from lite.app.server import api as api_module
    from lite.app.server import db as db_module

    name, prob = _top_incident(body)
    claim = body.get("claim_text")
    token, is_new = _csrf_issue(request)
    with _page_connection(request) as conn:
        owner_row = conn.execute(
            "SELECT account_id FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        try:
            meta = conn.execute(
                "SELECT title, category FROM reports WHERE id = ?",
                (report_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            # Database created before the 6.5 columns existed.
            meta = None
        stored_title = meta["title"] if meta is not None else None
        stored_category = (
            meta["category"] if meta is not None else None
        )
        title = api_module.display_title(
            stored_title, claim, name, report_id
        )
        category_label = (
            stored_category.replace("_", " ")
            if stored_category
            else None
        )
        is_owner = (
            owner_row is not None
            and owner_row["account_id"] == account["id"]
        )
        vouched = db_module.is_vouched(conn, account["id"], report_id)
        vouch_count = db_module.count_vouches(conn, report_id)
        vouches = db_module.list_vouches(conn, report_id)
        comments = db_module.list_comments(conn, report_id)
        saved = db_module.is_saved(conn, account["id"], report_id)
        correction = None
        if owner_view:
            correction = api_module.effective_labels(conn, report_id)[
                "correction"
            ]
    context = {
        "title": title,
        "report": body,
        "top_incident": name,
        "top_incident_prob": prob,
        "category": stored_category,
        "category_label": category_label,
        "correction": correction,
        "csrf_token": token,
        "is_owner": is_owner,
        "is_saved": saved,
        "vouched": vouched,
        "vouch_count": vouch_count,
        "vouches": vouches,
        "comments": comments,
        "error": error,
    }
    return context, (token if is_new else None)


def _render_detail_error(
    request: Request,
    account: dict,
    report_id: int,
    message: str,
    status: int = 422,
):
    """Re-render the shared detail page with an action error."""
    body = _accepted_or_404(request, account, report_id)
    context, csrf_new = _detail_context(
        request, account, body, report_id, owner_view=False, error=message
    )
    return _render("shared.html", context, status=status,
                   csrf_new=csrf_new)


def _render_owner_error(
    request: Request,
    account: dict,
    body: dict,
    report_id: int,
    message: str,
    status: int = 422,
):
    """Re-render the owner detail page with an action error."""
    context, csrf_new = _detail_context(
        request, account, body, report_id, owner_view=True, error=message
    )
    return _render("report.html", context, status=status,
                   csrf_new=csrf_new)


def _delete_report_everywhere(
    conn, account_id: int, report_id: int, uploads_dir
) -> None:
    """Delete one owned report row plus its photo files.

    Row deletion cascades to ``check_results``/claims/saves/vouches/
    comments via the schema's ``ON DELETE CASCADE``. Ownership is
    enforced by the caller (403/404 before this runs).
    """
    account_dir = (
        Path(uploads_dir) / str(account_id) if uploads_dir else None
    )
    if account_dir is not None and account_dir.is_dir():
        for candidate in sorted(account_dir.glob(f"{report_id}.*")):
            if candidate.is_file():
                candidate.unlink()
    conn.execute(
        "DELETE FROM reports WHERE id = ? AND account_id = ?",
        (report_id, account_id),
    )
    conn.commit()


@pages_router.post("/vouches")
async def vouch_add(request: Request):
    """Vouch one accepted report (idempotent add; form or JSON).

    Browser forms (cookie session plus CSRF) redirect to the shared
    page; JSON clients (Bearer [REDACTED]) get ``{"ok": true, "vouched": true,
    "vouch_count": n}``. Vouching a missing or not-accepted report
    answers 404 in both modes. One vouch per account per report: a
    repeat vouch keeps a single row, so counts never double-count.
    """
    from lite.app.server import api as api_module
    from lite.app.server import db as db_module

    if "application/json" in request.headers.get("content-type", ""):
        account = api_module.get_current_account(request)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid vouch body."
            ) from None
        report_id = (
            payload.get("report_id")
            if isinstance(payload, dict)
            else None
        )
        _accepted_or_404(request, account, report_id)
        with _page_connection(request) as conn:
            db_module.vouch_report(
                conn, account_id=account["id"], report_id=report_id
            )
            count = db_module.count_vouches(conn, report_id)
        return {
            "ok": True,
            "vouched": True,
            "report_id": report_id,
            "vouch_count": count,
        }
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    report_id = _saved_report_id(form.get("report_id"))
    if report_id is None:
        return _not_found(back="/map", back_label="Back to map")
    try:
        _accepted_or_404(request, account, report_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found(back="/map", back_label="Back to map")
        raise
    with _page_connection(request) as conn:
        db_module.vouch_report(
            conn, account_id=account["id"], report_id=report_id
        )
    return _redirect(f"/shared/{report_id}")


@pages_router.post("/vouches/{report_id}/unvouch")
async def vouch_remove(request: Request, report_id: int):
    """Remove one vouch; a missing vouch is a no-op success.

    Browser forms (cookie session plus CSRF) redirect to the shared
    page; JSON clients (Bearer [REDACTED]) get ``{"ok": true, "vouched": false,
    "vouch_count": n}``. Unvouching a missing or not-accepted report
    answers 404 in both modes.
    """
    from lite.app.server import api as api_module
    from lite.app.server import db as db_module

    if "application/json" in request.headers.get("content-type", ""):
        account = api_module.get_current_account(request)
        _accepted_or_404(request, account, report_id)
        with _page_connection(request) as conn:
            db_module.unvouch_report(
                conn, account_id=account["id"], report_id=report_id
            )
            count = db_module.count_vouches(conn, report_id)
        return {
            "ok": True,
            "vouched": False,
            "report_id": report_id,
            "vouch_count": count,
        }
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    try:
        _accepted_or_404(request, account, report_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found(back="/map", back_label="Back to map")
        raise
    with _page_connection(request) as conn:
        db_module.unvouch_report(
            conn, account_id=account["id"], report_id=report_id
        )
    return _redirect(f"/shared/{report_id}")


@pages_router.post("/comments")
async def comment_add(request: Request):
    """Post one plain-text comment on an accepted report.

    Browser forms (cookie session plus CSRF) redirect to the shared
    page; JSON clients (Bearer [REDACTED]) get the stored comment back. Empty
    bodies and bodies over 500 characters answer 422 in both modes;
    commenting on a missing or not-accepted report answers 404.
    Comments render as plain text (the templates escape HTML).
    """
    from lite.app.server import api as api_module
    from lite.app.server import db as db_module

    def _check(body_text) -> str | None:
        """Return an error message, or None when ``body_text`` posts."""
        if not isinstance(body_text, str) or not body_text.strip():
            return "Write a comment before posting."
        if len(body_text.strip()) > COMMENT_BODY_MAX:
            return (
                "Comments are limited to"
                f" {COMMENT_BODY_MAX} characters."
            )
        return None

    if "application/json" in request.headers.get("content-type", ""):
        account = api_module.get_current_account(request)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid comment body."
            ) from None
        fields = payload if isinstance(payload, dict) else {}
        report_id = fields.get("report_id")
        _accepted_or_404(request, account, report_id)
        error = _check(fields.get("body"))
        if error is not None:
            raise HTTPException(status_code=422, detail=error)
        text = str(fields.get("body")).strip()
        with _page_connection(request) as conn:
            comment_id = db_module.add_comment(
                conn,
                report_id=report_id,
                account_id=account["id"],
                body=text,
            )
            stored = [
                entry
                for entry in db_module.list_comments(conn, report_id)
                if entry["id"] == comment_id
            ][0]
        return {"ok": True, "report_id": report_id, "comment": stored}
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    report_id = _saved_report_id(form.get("report_id"))
    if report_id is None:
        return _not_found(back="/map", back_label="Back to map")
    try:
        _accepted_or_404(request, account, report_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found(back="/map", back_label="Back to map")
        raise
    error = _check(
        form.get("body") if isinstance(form.get("body"), str) else None
    )
    if error is not None:
        return _render_detail_error(request, account, report_id, error)
    text = str(form.get("body")).strip()
    with _page_connection(request) as conn:
        db_module.add_comment(
            conn,
            report_id=report_id,
            account_id=account["id"],
            body=text,
        )
    return _redirect(f"/shared/{report_id}")


@pages_router.get("/api/reports/{report_id}/comments")
def comment_list(request: Request, report_id: int):
    """List one accepted report's comments, newest last (login only).

    Bodies are plain text; no author emails appear. 404 when no
    accepted report exists.
    """
    from lite.app.server import api as api_module
    from lite.app.server import db as db_module

    account = api_module.get_current_account(request)
    _accepted_or_404(request, account, report_id)
    with _page_connection(request) as conn:
        return {
            "report_id": report_id,
            "comments": db_module.list_comments(conn, report_id),
        }


@pages_router.post("/reports/{report_id}/edit")
async def report_edit_submit(request: Request, report_id: int):
    """Edit the claim-text description of one owned accepted report.

    Owner only: other accounts answer 403 in both modes (anonymous
    browsers go to ``/login``, anonymous JSON callers get 401).
    Only the description changes; the incident type and every check
    output stay as stored. Browser forms redirect to the owner page;
    JSON clients get the stored text back.
    """
    from lite.app.server import api as api_module

    def _check(text) -> str | None:
        if not isinstance(text, str):
            return "Write a description before saving."
        if len(text.strip()) > CLAIM_EDIT_MAX:
            return (
                "Descriptions are limited to"
                f" {CLAIM_EDIT_MAX} characters."
            )
        return None

    if "application/json" in request.headers.get("content-type", ""):
        account = api_module.get_current_account(request)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid edit body."
            ) from None
        fields = payload if isinstance(payload, dict) else {}
        # Ownership + accepted proven by the fetch; body unused here.
        _owned_report_or_raise(request, account, report_id)
        error = _check(fields.get("claim_text"))
        if error is not None:
            raise HTTPException(status_code=422, detail=error)
        text = str(fields.get("claim_text")).strip()
        stored = text or None
        with _page_connection(request) as conn:
            api_module.update_claim_text(conn, report_id, stored)
        return {
            "ok": True,
            "report_id": report_id,
            "claim_text": stored,
        }
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    try:
        body = _owned_report_or_raise(request, account, report_id)
    except HTTPException as exc:
        if exc.status_code == 403:
            return _owner_denied()
        if exc.status_code == 404:
            return _not_found(
                back="/reports", back_label="Back to your reports"
            )
        raise
    raw = form.get("claim_text")
    error = _check(raw if isinstance(raw, str) else None)
    if error is not None:
        return _render_owner_error(
            request, account, body, report_id, error
        )
    stored = str(raw).strip() or None
    with _page_connection(request) as conn:
        api_module.update_claim_text(conn, report_id, stored)
    return _redirect(f"/reports/{report_id}")


@pages_router.post("/reports/{report_id}/delete")
async def report_delete_submit(request: Request, report_id: int):
    """Delete one owned report after a single confirm, then the list.

    Owner only: other accounts answer 403 in both modes (anonymous
    browsers go to ``/login``, anonymous JSON callers get 401). The
    row, its photo files, and its vouches/comments/saves go with it
    (schema cascades); shared pages for it answer 404 afterwards.
    """
    from lite.app.server import api as api_module

    if "application/json" in request.headers.get("content-type", ""):
        account = api_module.get_current_account(request)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid delete body."
            ) from None
        fields = payload if isinstance(payload, dict) else {}
        _owned_report_or_raise(request, account, report_id)
        if fields.get("confirm") != "yes":
            raise HTTPException(
                status_code=422,
                detail="Confirm the deletion before continuing.",
            )
        with _page_connection(request) as conn:
            _delete_report_everywhere(
                conn,
                account["id"],
                report_id,
                request.app.state.uploads_dir,
            )
        return {"ok": True, "report_id": report_id}
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    try:
        body = _owned_report_or_raise(request, account, report_id)
    except HTTPException as exc:
        if exc.status_code == 403:
            return _owner_denied()
        if exc.status_code == 404:
            return _not_found(
                back="/reports", back_label="Back to your reports"
            )
        raise
    if form.get("confirm") != "yes":
        return _render_owner_error(
            request,
            account,
            body,
            report_id,
            "Tick the confirmation box to delete this report.",
            status=400,
        )
    with _page_connection(request) as conn:
        _delete_report_everywhere(
            conn,
            account["id"],
            report_id,
            request.app.state.uploads_dir,
        )
    return _redirect("/reports")


@pages_router.get("/shared/photos/{report_id}")
def shared_photo(request: Request, report_id: int):
    """Serve a report's photo bytes to a cookie-session browser.

    Cookie session via ``_account_for_session`` (the ``lite_session``
    cookie holds the same JWT the Bearer header carries), then
    straight to the spec-2 ``GET /api/photos/{id}`` implementation,
    so the visibility rule is identical: any logged-in user when
    accepted, owner-only otherwise, 404 for rejected/missing.
    Anonymous callers get the 404 page (an ``<img>`` cannot follow a
    login redirect, and the existence of the photo stays hidden).
    """
    account = _account_for_session(request)
    if account is None:
        return _not_found()
    from lite.app.server import api as api_module

    try:
        return api_module.get_photo(report_id, request, account)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found()
        raise


@pages_router.get("/api/photos/{report_id}")
def photo_cookie_bridge(request: Request, report_id: int):
    """Cookie-aware bridge in front of the spec-2 photo bytes route.

    This router is included before the spec-2 routers, so this
    handler is reached first for the ``<img src>`` URL the result
    pages render. With a valid session cookie it serves through the
    spec-2 ``get_photo`` implementation (same bytes, same visibility
    rule); without one it delegates to the spec-2 handler unchanged,
    so Bearer-token clients and anonymous 401s are untouched.
    """
    account = _account_for_session(request)
    from lite.app.server import api as api_module

    if account is None:
        account = api_module.get_current_account(request)
    return api_module.get_photo(report_id, request, account)


@pages_router.get("/map")
def map_page(request: Request):
    """Community map: one dot per accepted report (HTML for browsers).

    Login required: anonymous callers are redirected to ``/login``
    (an ``<img>``-style anonymous fetch cannot use this page). Dots
    themselves are rendered in-page by fetching the existing spec-5.2
    ``GET /api/incidents`` endpoint (unchanged); the photo in the
    bottom sheet uses the cookie-session ``/shared/photos/{id}``
    route, and the sheet links to ``GET /shared/{id}``. The server also renders
    the same report links into the ``map_fallback`` container, so a
    browser whose map library or tiles fail to load still shows the
    reports list instead of a blank map. No scene-vs-location
    judgement is computed here: the popup only asks the viewer to
    compare visually.
    """
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    from lite.app.server import api as api_module

    try:
        collection = api_module.list_incidents(request, account)
    except HTTPException:
        collection = {"features": []}
    features = (
        collection.get("features", [])
        if isinstance(collection, dict)
        else []
    )
    items = []
    for feature in features:
        props = (
            feature.get("properties", {})
            if isinstance(feature, dict)
            else {}
        )
        report_id = props.get("report_id") if isinstance(props, dict) else None
        if report_id is None:
            continue
        incident = (
            dict(props.get("incident_probs") or {})
            if isinstance(props, dict)
            else {}
        )
        top = max(incident, key=incident.get) if incident else None
        items.append(
            {
                "report_id": report_id,
                "display_title": api_module.display_title(
                    props.get("title") if isinstance(props, dict) else None,
                    props.get("claim_text")
                    if isinstance(props, dict)
                    else None,
                    top,
                    report_id,
                ),
            }
        )
    from lite.app.server import db as db_module

    with _page_connection(request) as conn:
        saved_ids = db_module.list_saved_report_ids(
            conn, account_id=account["id"]
        )
    token, is_new = _csrf_issue(request)
    return _render(
        "map.html",
        {
            "title": "Map",
            "reports": items,
            "csrf_token": token,
            "saved_ids": saved_ids,
        },
        csrf_new=token if is_new else None,
    )


def _saved_items(request: Request, account: dict) -> list:
    """Accepted saved reports for the session account, newest first.

    Every display value comes from the shared retrieval payload
    (photo, claim text, incident outline), so no email, address, or
    exact coordinates can appear. Saves whose report is gone or was
    never accepted are skipped.
    """
    from lite.app.server import api as api_module
    from lite.app.server import db as db_module

    with _page_connection(request) as conn:
        ids = db_module.list_saved_report_ids(conn, account["id"])
        stored_titles = {}
        for row in conn.execute("SELECT * FROM reports").fetchall():
            keys = set(row.keys())
            stored_titles[row["id"]] = (
                row["title"] if "title" in keys else None
            )
    items = []
    for report_id in reversed(ids):
        try:
            body = api_module.get_shared_report(
                report_id, request, account
            )
        except HTTPException:
            continue
        incident = dict(body.get("incident_probs") or {})
        top = max(incident, key=incident.get) if incident else None
        title = api_module.display_title(
            stored_titles.get(report_id),
            body.get("claim_text"),
            top,
            report_id,
        )
        items.append(
            {
                "report_id": body["report_id"],
                "photo_url": f"/shared/photos/{body['report_id']}",
                "title": title,
                "created_at": body.get("created_at"),
            }
        )
    return items


def _do_save(request: Request, account: dict, report_id) -> int:
    """Save one accepted report for ``account`` (idempotent add).

    Raises 404 unless the report exists and is accepted, so rejected,
    deleted, or missing reports can never be saved.
    """
    from lite.app.server import api as api_module
    from lite.app.server import db as db_module

    if isinstance(report_id, bool) or not isinstance(report_id, int):
        raise HTTPException(
            status_code=404, detail="Not found."
        )
    try:
        api_module.get_shared_report(report_id, request, account)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Not found."
            ) from None
        raise
    with _page_connection(request) as conn:
        db_module.save_report(
            conn, account_id=account["id"], report_id=report_id
        )
    return report_id


def _do_unsave(request: Request, account: dict, report_id) -> int:
    """Remove one save; a missing save is a no-op success."""
    from lite.app.server import db as db_module

    if isinstance(report_id, bool) or not isinstance(report_id, int):
        return report_id if isinstance(report_id, int) else 0
    with _page_connection(request) as conn:
        db_module.unsave_report(
            conn, account_id=account["id"], report_id=report_id
        )
    return report_id


def _saved_report_id(value) -> int | None:
    """Parse a posted report id, or None when missing/not numeric."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@pages_router.get("/saved")
def saved_list(request: Request):
    """Saved places: the caller's saved accepted reports (login only).

    Anonymous callers are redirected to ``/login``. The segmented
    List | Map toggle is two plain links (no script): List stays
    here, Map goes to the community map.
    """
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    token, is_new = _csrf_issue(request)
    notice = request.query_params.get("notice")
    return _render(
        "saved.html",
        {
            "title": "Saved Places",
            "csrf_token": token,
            "items": _saved_items(request, account),
            "removed": notice == "removed",
        },
        csrf_new=token if is_new else None,
    )


@pages_router.post("/saved")
async def saved_add(request: Request):
    """Save one accepted report (idempotent; form or JSON).

    Browser forms (cookie session plus CSRF) redirect to ``/saved``;
    JSON clients (Bearer [REDACTED]) get ``{"ok": true}``. Saving a
    missing or rejected report answers 404 in both modes.
    """
    from lite.app.server import api as api_module

    if "application/json" in request.headers.get("content-type", ""):
        account = api_module.get_current_account(request)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid save body."
            ) from None
        report_id = (
            payload.get("report_id")
            if isinstance(payload, dict)
            else None
        )
        saved_id = _do_save(request, account, report_id)
        return {"ok": True, "saved": True, "report_id": saved_id}
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    report_id = _saved_report_id(form.get("report_id"))
    if report_id is None:
        return _not_found(
            back="/saved", back_label="Back to saved places"
        )
    try:
        _do_save(request, account, report_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found(
                back="/saved", back_label="Back to saved places"
            )
        raise
    return _redirect("/saved")


@pages_router.post("/saved/{report_id}/unsave")
async def saved_remove(request: Request, report_id: int):
    """Remove one save; a missing save is a no-op success.

    Browser forms (cookie session plus CSRF) redirect to ``/saved``;
    JSON clients (Bearer [REDACTED]) get ``{"ok": true}``. Never 404s
    for a missing save.
    """
    from lite.app.server import api as api_module

    if "application/json" in request.headers.get("content-type", ""):
        account = api_module.get_current_account(request)
        saved_id = _do_unsave(request, account, report_id)
        return {"ok": True, "saved": False, "report_id": saved_id}
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    _do_unsave(request, account, report_id)
    return _redirect("/saved?notice=removed")


def _haversine_m(lat1: float, lng1: float, lat2: float,
                 lng2: float) -> float:
    """Great-circle distance in meters between two points."""
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    inner = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2)
        * math.sin(delta_lng / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(math.sqrt(inner))


def _format_distance(meters: float) -> str:
    """Short viewer-facing distance label for one feed card."""
    if meters < 1000:
        return f"{int(round(meters))} m away"
    return f"{meters / 1000.0:.1f} km away"


def _feed_items(
    request: Request,
    account: dict,
    viewer_lat=None,
    viewer_lng=None,
    nearby: bool = False,
) -> list:
    """Accepted reports for the feed, newest first (or nearest first).

    Every display value comes from the shared retrieval payload
    (photo, claim text, incident outline), so no email, address, or
    exact coordinates can appear. The owner label is a plain member
    number (never an email, never a profile link: ``/profile/{id}``
    does not exist). Distances are computed from the jittered
    display points when the viewer passed ``lat``/``lng``; otherwise
    they are omitted. ``nearby`` with a viewer location sorts
    nearest first; without one it keeps newest-first order.
    """
    from lite.app.server import api as api_module
    from lite.app.server import db as db_module

    with _page_connection(request) as conn:
        rows = conn.execute(
            "SELECT r.* FROM reports r"
            " JOIN check_results c ON c.report_id = r.id"
            " ORDER BY r.id DESC"
        ).fetchall()
        saved_ids = set(
            db_module.list_saved_report_ids(conn, account["id"])
        )
        stored = {}
        for row in rows:
            keys = set(row.keys())
            stored[row["id"]] = {
                "title": row["title"] if "title" in keys else None,
                "owner_id": row["account_id"],
            }
    items = []
    for row in rows:
        report_id = row["id"]
        try:
            body = api_module.get_shared_report(
                report_id, request, account
            )
        except HTTPException:
            continue
        incident = dict(body.get("incident_probs") or {})
        top = max(incident, key=incident.get) if incident else None
        title = api_module.display_title(
            stored[report_id]["title"],
            body.get("claim_text"),
            top,
            report_id,
        )
        with _page_connection(request) as conn:
            vouch_count = db_module.count_vouches(conn, report_id)
        distance_m = None
        distance = None
        if viewer_lat is not None and viewer_lng is not None:
            distance_m = _haversine_m(
                viewer_lat,
                viewer_lng,
                body["display_lat"],
                body["display_lng"],
            )
            distance = _format_distance(distance_m)
        items.append(
            {
                "report_id": report_id,
                "photo_url": f"/shared/photos/{report_id}",
                "title": title,
                "vouch_count": vouch_count,
                "owner_label": (
                    f"Member {stored[report_id]['owner_id']}"
                ),
                "is_saved": report_id in saved_ids,
                "distance": distance,
                "distance_m": distance_m,
            }
        )
    if nearby and viewer_lat is not None and viewer_lng is not None:
        items.sort(key=lambda entry: entry["distance_m"])
    for entry in items:
        del entry["distance_m"]
    return items


@pages_router.get("/feed")
def feed_list(request: Request):
    """Community feed: accepted reports as cards (login only).

    Anonymous callers are redirected to ``/login``. The segmented
    For You | Nearby toggle is two plain links (no script, no
    Following segment: follows were not approved). ``view=nearby``
    with ``lat``/``lng`` query values sorts nearest first and shows
    per-card distances; without them distances are omitted.
    """
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    params = request.query_params
    nearby = (params.get("view") or "").strip().lower() == "nearby"
    viewer_lat = _parse_float(params.get("lat"))
    viewer_lng = _parse_float(params.get("lng"))
    if viewer_lat is None or viewer_lng is None:
        viewer_lat = viewer_lng = None
    token, is_new = _csrf_issue(request)
    return _render(
        "feed.html",
        {
            "title": "Feed",
            "csrf_token": token,
            "nearby": nearby,
            "items": _feed_items(
                request,
                account,
                viewer_lat=viewer_lat,
                viewer_lng=viewer_lng,
                nearby=nearby,
            ),
        },
        csrf_new=token if is_new else None,
    )


def _review_denied() -> Response:
    """Render the reviewer-only 403 page (never a login redirect)."""
    return _render(
        "message.html",
        {
            "title": "Not allowed",
            "heading": "Not allowed",
            "message": "Reviewer access required.",
            "back": "/",
            "back_label": "Home",
        },
        status=403,
    )


def _reviewer_session(request: Request) -> dict | None:
    """Session account when it carries the reviewer flag, else None."""
    account = _account_for_session(request)
    if account is None or not account.get("reviewer"):
        return None
    return account


def _review_queue_items(request: Request) -> list:
    """Accepted reports: needs-review first, then newest.

    Reads only the report id, stored verdict, and stored incident
    probabilities (never the uploader email or exact coordinates).
    """
    with _page_connection(request) as conn:
        rows = conn.execute(
            "SELECT r.id, c.verdict, c.incident_probs"
            " FROM reports r"
            " JOIN check_results c ON c.report_id = r.id"
            " ORDER BY (c.verdict != 'likely-real') DESC, r.id DESC"
        ).fetchall()
        items = []
        for row in rows:
            incident = json.loads(row["incident_probs"] or "{}")
            items.append(
                {
                    "report_id": row["id"],
                    "verdict": row["verdict"],
                    "confidence": (
                        max(incident.values()) if incident else 0.0
                    ),
                    "needs_review": row["verdict"] != "likely-real",
                }
            )
    return items


def _render_review_detail(
    request: Request,
    report_id: int,
    account: dict,
    error: str | None = None,
    status: int = 200,
):
    """Render the reviewer detail page (or the queue-backed 404 page).

    Every display value comes from the stored check outputs via the
    spec-4.2 reviewer detail implementation (incident/severity
    probabilities, claim text, fusion reasons, original demo verdict,
    correction, history) plus direct reads of the stored provenance
    flags and exact-duplicate links. Nothing is recomputed here, and
    the uploader's email is never selected. History entries carry
    action, before/after values, and time only (no reviewer emails).
    """
    from lite.app.server import api as api_module

    try:
        body = api_module.review_detail(report_id, request, account)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found(
                back="/review", back_label="Back to the review queue"
            )
        raise
    with _page_connection(request) as conn:
        check = conn.execute(
            "SELECT provenance FROM check_results WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        provenance = (
            json.loads(check["provenance"] or "{}")
            if check is not None and check["provenance"]
            else {}
        )
        owner = conn.execute(
            "SELECT sha256 FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        duplicates: list = []
        if owner is not None and owner["sha256"]:
            duplicates = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM reports WHERE sha256 = ?"
                    " AND id != ? ORDER BY id",
                    (owner["sha256"], report_id),
                ).fetchall()
            ]
    cfg = load_config()
    history = [
        {
            "action": entry["action"],
            "before": entry["before"],
            "after": entry["after"],
            "time": entry["time"],
        }
        for entry in body.get("history", [])
    ]
    token, is_new = _csrf_issue(request)
    return _render(
        "review_detail.html",
        {
            "title": f"Review report {body['report_id']}",
            "report": body,
            "needs_review": body["verdict"] != "likely-real",
            "provenance": provenance,
            "duplicates": duplicates,
            "history": history,
            "incident_labels": sorted(cfg.incident_prompts),
            "severity_labels": sorted(cfg.severity_prompts),
            "csrf_token": token,
            "error": error,
        },
        status=status,
        csrf_new=token if is_new else None,
    )


@pages_router.get("/review")
def review_queue(request: Request):
    """Reviewer queue: needs-review first, then newest (403 otherwise)."""
    if _reviewer_session(request) is None:
        return _review_denied()
    return _render(
        "review.html",
        {
            "title": "Review queue",
            "reports": _review_queue_items(request),
        },
    )


@pages_router.get("/review/{report_id}")
def review_detail_page(request: Request, report_id: int):
    """Reviewer detail: stored check outputs plus action forms."""
    account = _reviewer_session(request)
    if account is None:
        return _review_denied()
    return _render_review_detail(request, report_id, account)


@pages_router.post("/review/{report_id}/actions")
async def review_action_submit(request: Request, report_id: int):
    """Record one reviewer action from a form or a JSON client.

    This router is included before the spec-4.2 review router, so
    this handler is reached first for ``POST /review/{id}/actions``.
    Bearer JSON clients are delegated to the spec-4.2
    ``review_action`` implementation unchanged (same 401/403/404/422
    contract); browser forms (cookie session plus CSRF) are
    translated into the same implementation, so the one-row audit
    rule has exactly one implementation. A finished form action
    redirects to the detail page; a rejected one re-renders it with
    an error.
    """
    from lite.app.server import api as api_module

    if "application/json" in request.headers.get("content-type", ""):
        account = api_module.get_current_account(request)
        try:
            payload = api_module.ReviewActionRequest(
                **(await request.json())
            )
        except (ValidationError, ValueError):
            raise HTTPException(
                status_code=422, detail="Invalid action body."
            ) from None
        return api_module.review_action(
            report_id, payload, request, account
        )
    form = await request.form()
    if not _csrf_valid(request, form.get(CSRF_FIELD)):
        return _csrf_denied()
    account = _reviewer_session(request)
    if account is None:
        return _review_denied()

    def _text(name: str):
        value = form.get(name)
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    def _fail(message: str):
        return _render_review_detail(
            request, report_id, account, error=message, status=422
        )

    try:
        payload = api_module.ReviewActionRequest(
            action=_text("action") or "",
            incident=_text("incident"),
            severity=_text("severity"),
            note=_text("note"),
        )
    except ValidationError:
        return _fail("Choose an action and try again.")
    try:
        api_module.review_action(report_id, payload, request, account)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _not_found(
                back="/review", back_label="Back to the review queue"
            )
        if exc.status_code == 422:
            return _fail(str(exc.detail))
        raise
    return _redirect(f"/review/{report_id}")


def _audit_events(request: Request) -> list:
    """Every audit event, oldest first, for the reviewer listing.

    Reads only the ``audit_events`` columns. Rejection details carry
    hash, time, and account only (never image bytes or claim text,
    by construction in the pipeline); review-action and
    account-deletion details likewise carry labels and email/time
    only. Nothing is recomputed here.
    """
    with _page_connection(request) as conn:
        rows = conn.execute(
            "SELECT id, kind, actor_account_id, report_id, detail,"
            " created_at FROM audit_events ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]


@pages_router.get("/audit")
def audit_list(request: Request):
    """Reviewer-only audit listing (403 otherwise, never a redirect)."""
    if _reviewer_session(request) is None:
        return _review_denied()
    return _render(
        "audit.html",
        {"title": "Audit events", "events": _audit_events(request)},
    )
