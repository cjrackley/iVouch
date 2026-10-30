"""Server-rendered account pages for iVouch Lite (spec 3, objective 3.1).

Routes (``pages_router``, included FIRST in ``create_app`` so the HTML
``GET /account`` below is reached before the JSON ``GET /account`` in
the spec-2 auth router; every other path is clash-free):
``GET/POST /signup``, ``GET/POST /login``, ``GET /logout``,
``GET /account`` (HTML for browsers), ``POST /account/delete``,
``GET /verify``, ``POST /verify-resend``, ``GET /upload`` (verified
gate only; the upload form itself is objective 3.2),
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

``GET /upload`` gate helper (shared for objective 3.2): anonymous users
are redirected to ``/login``; unverified users get a page saying
"verify your email" with a resend action and uploads disabled;
verified users get a placeholder until 3.2 adds the form.
"""

from __future__ import annotations

import secrets
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import jinja2
from fastapi import APIRouter, Request
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
    """Shared upload gate (objective 3.2 builds the form on top).

    Anonymous users go to login; unverified users see the "verify your
    email" prompt with a resend action and uploads disabled; verified
    users get a placeholder until 3.2.
    """
    account = _account_for_session(request)
    if account is None:
        return _redirect("/login")
    token, is_new = _csrf_issue(request)
    return _render(
        "upload.html",
        {
            "title": "Upload",
            "csrf_token": token,
            "verified": bool(account["email_verified"]),
        },
        csrf_new=token if is_new else None,
    )
