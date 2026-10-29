"""Lite local CLI (Lite spec 2, objective 2.1).

Commands:
    python -m lite.app.cli make-reviewer <email> [--db PATH]

``--db`` defaults to ``lite/data/ivouch.db`` -- the same path the
server resolves. ``make-reviewer`` sets ``reviewer = 1`` on the
matching account and errors clearly on an unknown email.
"""

from __future__ import annotations

import argparse
import sys

from lite.app.server.db import (
    UnknownEmailError,
    connect,
    default_db_path,
    init_db,
    make_reviewer,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lite.app.cli")
    parser.add_argument(
        "--db",
        default=str(default_db_path()),
        help="SQLite database file (default: lite/data/ivouch.db)",
    )
    sub = parser.add_subparsers(dest="command")
    reviewer = sub.add_parser(
        "make-reviewer", help="Grant the reviewer flag to an account"
    )
    reviewer.add_argument("email", help="Account email to promote")
    return parser


def _cmd_make_reviewer(db_path: str, email: str) -> int:
    init_db(db_path)
    conn = connect(db_path)
    try:
        account_id = make_reviewer(conn, email)
    except UnknownEmailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"reviewer granted for {email} (account id {account_id})")
    return 0


def main(argv=None) -> int:
    """Entry point; returns the process exit code.

    ``argv`` defaults to an empty argument list (success no-op) so the
    function is import-safe; the ``__main__`` entry passes
    ``sys.argv[1:]`` explicitly.
    """
    if argv is None:
        argv = []
    args = _build_parser().parse_args(argv)
    if args.command is None:
        return 0
    if args.command == "make-reviewer":
        return _cmd_make_reviewer(args.db, args.email)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
