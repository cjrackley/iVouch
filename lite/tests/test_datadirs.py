"""Tests for the spec-4 4.4 data-dir resolution fix.

Default data directories must anchor at the repository root no matter
what the process CWD is; explicit absolute dirs pass through
unchanged. Every assert here is a pure path comparison, except the
read-only mock-hash load -- nothing creates files outside pytest tmp
dirs, and no request is ever served (a register/upload against
default dirs would write into the real repo tree).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from lite.app.server import db as db_module
from lite.app.server import pipeline as pipeline_module
from lite.app.server.api import create_app
from lite.app.server.mail import resolve_mail_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MAIL = REPO_ROOT / "lite" / "data" / "mail"
EXPECTED_UPLOADS = REPO_ROOT / "lite" / "data" / "uploads"
EXPECTED_DB = REPO_ROOT / "lite" / "data" / "ivouch.db"


def test_repo_root_has_expected_markers():
    assert (REPO_ROOT / "AGENTS.md").is_file()
    assert (REPO_ROOT / "lite").is_dir()
    assert db_module.repo_root() == REPO_ROOT


def test_default_db_path_is_repo_anchored():
    assert db_module.default_db_path() == EXPECTED_DB


def test_default_mail_dir_is_repo_anchored():
    assert resolve_mail_dir() == EXPECTED_MAIL


def test_default_app_dirs_are_repo_anchored():
    app = create_app()
    assert Path(app.state.db_path) == EXPECTED_DB
    assert Path(app.state.mail_dir) == EXPECTED_MAIL
    assert Path(app.state.uploads_dir) == EXPECTED_UPLOADS


def test_defaults_ignore_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert db_module.repo_root() == REPO_ROOT
    assert db_module.default_db_path() == EXPECTED_DB
    assert resolve_mail_dir() == EXPECTED_MAIL
    app = create_app()
    assert Path(app.state.db_path) == EXPECTED_DB
    assert Path(app.state.mail_dir) == EXPECTED_MAIL
    assert Path(app.state.uploads_dir) == EXPECTED_UPLOADS


def test_mock_hashes_resolve_independent_of_cwd(monkeypatch, tmp_path):
    expected = pipeline_module.load_mock_hashes()
    assert expected, "mock hashes fixture should be non-empty"
    monkeypatch.chdir(tmp_path)
    assert pipeline_module.load_mock_hashes() == expected


def test_explicit_absolute_dirs_pass_through(tmp_path):
    mail = tmp_path / "mail"
    uploads = tmp_path / "uploads"
    db_path = tmp_path / "test.db"
    assert resolve_mail_dir(mail) == mail
    assert resolve_mail_dir(str(mail)) == mail
    assert db_module.resolve_repo_relative(str(mail)) == mail
    app = create_app(db_path=db_path, mail_dir=mail, uploads_dir=uploads)
    assert Path(app.state.db_path) == db_path
    assert Path(app.state.mail_dir) == mail
    assert Path(app.state.uploads_dir) == uploads


def test_default_dirs_visible_on_test_client_app():
    # TestClient-level coverage of the default (non-explicit) dirs:
    # app state resolves repo-anchored. No request is made here --
    # serving a register/upload against defaults would write into the
    # real repo tree. Pointing defaults at tmp would need a new config
    # surface (e.g. env vars), out of scope for this fix; explicit tmp
    # dirs are covered by every other TestClient test in the suite.
    client = TestClient(create_app())
    assert Path(client.app.state.db_path) == EXPECTED_DB
    assert Path(client.app.state.mail_dir) == EXPECTED_MAIL
    assert Path(client.app.state.uploads_dir) == EXPECTED_UPLOADS
