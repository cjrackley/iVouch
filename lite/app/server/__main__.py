"""Dev-server entry for iVouch Lite (spec 3, objective 3.2).

Run with ``python -m lite.app.server`` (default
``http://127.0.0.1:8000``; host and port overridable via
``--host``/``--port``). The database file is initialised on start.
``--help`` prints usage and exits without serving.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    """Command-line parser for the Lite dev server."""
    parser = argparse.ArgumentParser(
        prog="lite.app.server",
        description="Run the iVouch Lite demo server.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind (default 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default 8000).",
    )
    return parser


def main(argv=None) -> int:
    """Parse ``argv``, init the DB file, and serve with uvicorn."""
    args = build_parser().parse_args(argv)
    import uvicorn

    from lite.app.server.api import app as application
    from lite.app.server.db import init_db

    init_db(application.state.db_path)
    uvicorn.run(
        "lite.app.server.api:app", host=args.host, port=args.port
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
