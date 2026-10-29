"""Console mail sender for iVouch Lite (spec 2).

Dev/test only: every message is written as a UTF-8 text file under
``console_mail_dir``. No real email provider is ever wired here --
this module is the ONLY place in Lite that sends mail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def resolve_mail_dir(explicit=None) -> Path:
    """Return the console mail directory.

    ``explicit`` (a test tmp dir, or ``app.state.mail_dir``) wins;
    otherwise the value comes from ``lite/config.yaml`` via the loader
    in ``lite/app/config.py``. Relative config values resolve against
    the ``lite/`` directory.
    """
    if explicit is not None:
        return Path(explicit)
    from lite.app.config import load_config

    raw = load_config().console_mail_dir
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parents[2] / raw


def _safe_stem(email: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in email.lower())[:64]


def write_verification_email(
    mail_dir, recipient_email: str, token: str
) -> Path:
    """Write one verification message file; return its path.

    The file holds ``To:``, a subject line, and a ``token: <token>``
    line that tests read back to complete verification.
    """
    directory = Path(mail_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = directory / f"verify_{_safe_stem(recipient_email)}_{stamp}.txt"
    path.write_text(
        f"To: {recipient_email}\n"
        "Subject: Verify your iVouch Lite account\n"
        "\n"
        "Welcome to iVouch Lite. To finish creating your account,\n"
        "submit the token below to POST /auth/verify-email.\n"
        "\n"
        f"token: {token}\n",
        encoding="utf-8",
    )
    return path
