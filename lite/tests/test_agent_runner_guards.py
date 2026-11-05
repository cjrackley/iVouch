"""Runner guardrails: lazy credentials + builder-safe tool allowlist.

Covers the `agent_runner.py` crash (Missing credentials at import) and the
requirement that any builder tool added stays within the builder contract
(`agents/builder.md` + `AGENTS.md` section 3): no log writes, no commits,
no deletes, no secret reads, no orchestrator-only tools.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
assert (ROOT / "agent_runner.py").exists()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN_TOOLS = {
    # Orchestrator-only / vital tools builders must never get via a brief.
    "subagent_spawn",
    "subagent",
    "workflow",
    "host.agent",
    "request_user_input",
    "write_todos",
    "monitor",
    "web_fetch",
    "web_search",
    "image_generation",
    "memory",
    "cron",
    "skill",
    "mcp",
    "commit",
    "push",
    "git_commit",
}


def _load_runner(monkeypatch):
    for var in ("OPENAI_API_KEY", "BASETEN_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://inference.baseten.co/v1")
    sys.modules.pop("agent_runner", None)
    return importlib.import_module("agent_runner")


def test_import_needs_no_credentials(monkeypatch):
    """Importing the runner must not crash when no API key is set."""
    _load_runner(monkeypatch)  # used to raise openai.OpenAIError at import


def test_missing_key_error_is_actionable(monkeypatch):
    runner = _load_runner(monkeypatch)
    assert hasattr(runner, "get_client"), "runner must expose get_client()"
    with pytest.raises(RuntimeError, match=r"(?i)api.?key|credential|OPENAI_API_KEY"):
        runner.get_client()


def test_tool_allowlist_has_search_and_no_vital_tools(monkeypatch):
    runner = _load_runner(monkeypatch)
    names = set()
    for tool in runner.TOOLS_SPEC:
        fn = tool.get("function", {}).get("name", "")
        names.add(fn)
        lowered = fn.lower()
        for forbidden in FORBIDDEN_TOOLS:
            assert forbidden not in lowered, f"vital tool leaked: {fn}"
    # Builder needs file search (spec-7 grep checks); exec probes alone are not enough.
    assert "search_files" in names, f"expected search_files in {sorted(names)}"
    assert "read_file" in names
    assert "write_file" in names


def test_write_blocks_logs_and_outside_root(monkeypatch, tmp_path):
    runner = _load_runner(monkeypatch)
    monkeypatch.setattr(runner, "WORK_ROOT", tmp_path)
    monkeypatch.setattr(runner, "ALLOWED_ROOT", tmp_path / "lite")
    (tmp_path / "lite").mkdir()
    assert "ERROR" in runner.write_file("lite/logs/spec7_log.md", "x")
    assert "ERROR" in runner.write_file("../outside.txt", "x")


def test_apply_patch_enforces_scope(monkeypatch, tmp_path):
    runner = _load_runner(monkeypatch)
    monkeypatch.setattr(runner, "WORK_ROOT", tmp_path)
    monkeypatch.setattr(runner, "ALLOWED_ROOT", tmp_path / "lite")
    (tmp_path / "lite").mkdir()
    with pytest.raises(Exception, match=r"(?i)scope|lite/|denied|ERROR"):
        runner.apply_patch("../outside.txt", "a", "b")
    with pytest.raises(Exception, match=r"(?i)log|orchestrator|denied|ERROR"):
        runner.apply_patch("lite/logs/spec7_log.md", "a", "b")


def test_exec_cmd_blocks_destructive_ops(monkeypatch):
    runner = _load_runner(monkeypatch)
    for cmd in (
        "rm -rf lite/data",
        "Remove-Item lite/data -Recurse",
        "git commit -m hi",
        "git push",
        "echo hi >> lite/logs/spec7_log.md",
        "cat .env",
    ):
        out = runner.exec_cmd(cmd)
        assert "ERROR" in out or "BLOCKED" in out, f"exec_cmd allowed: {cmd!r}"


def test_touched_pages_missing_or_placeholder_is_not_ok(monkeypatch):
    """A builder that lists no real routes must be flagged, never silently accepted.

    Regression for the 7.1 run: the builder emitted no usable touched_pages,
    evidence fell back to home only, and the failure was debatable instead
    of explicit.
    """
    runner = _load_runner(monkeypatch)
    pages, ok = runner.parse_touched_pages("done, no routes mentioned")
    assert pages == ["/"] and ok is False
    pages, ok = runner.parse_touched_pages("touched_pages=[...]")
    assert pages == ["/"] and ok is False
    pages, ok = runner.parse_touched_pages("touched_pages=[]")
    assert pages == ["/"] and ok is False


def test_touched_pages_valid_list_is_ok(monkeypatch):
    runner = _load_runner(monkeypatch)
    pages, ok = runner.parse_touched_pages(
        "fixed templates touched_pages=['/report/1', '/shared/demo'] done"
    )
    assert ok is True
    assert pages == ["/report/1", "/shared/demo"]


def test_builder_prompt_demands_real_routes_and_self_checks(monkeypatch):
    runner = _load_runner(monkeypatch)
    prompt = runner.BUILDER_SYS
    assert "touched_pages" in prompt
    assert "search_files" in prompt
    assert "pytest" in prompt


def test_reviewer_template_blocks_home_only_override(monkeypatch):
    """The reviewer must never let GET / evidence satisfy page-specific criteria."""
    runner = _load_runner(monkeypatch)
    tmpl = runner.REVIEWER_TMPL
    assert "'/'" in tmpl
    assert "360px" in tmpl and "desktop" in tmpl


def test_specs_are_read_only_for_builder(monkeypatch, tmp_path):
    """Builders implement the spec; they must never rewrite it to fit.

    Regression: nothing in the runner stopped write_file/apply_patch/exec_cmd
    from editing lite/specs/, i.e. passing by weakening the criteria.
    """
    runner = _load_runner(monkeypatch)
    monkeypatch.setattr(runner, "WORK_ROOT", tmp_path)
    monkeypatch.setattr(runner, "ALLOWED_ROOT", tmp_path / "lite")
    (tmp_path / "lite" / "specs").mkdir(parents=True)
    assert "ERROR" in runner.write_file("lite/specs/spec-7-redesign.md", "x")
    with pytest.raises(Exception, match=r"(?i)spec|read-only|denied|ERROR"):
        runner.apply_patch("lite/specs/spec-7-redesign.md", "a", "b")
    out = runner.exec_cmd("echo x > lite/specs/spec-7-redesign.md")
    assert "ERROR" in out or "BLOCKED" in out, "exec_cmd allowed a spec edit"


def test_builder_prompt_keeps_specs_read_only(monkeypatch):
    runner = _load_runner(monkeypatch)
    assert "lite/specs/" in runner.BUILDER_SYS


def test_reviewer_template_requires_human_evidence_for_manual_checks(monkeypatch):
    """Manual-check criteria (7.2/7.3/7.6) need cited human observation.

    Auto-captured screenshot lines alone must never satisfy them.
    """
    runner = _load_runner(monkeypatch)
    assert "manual" in runner.REVIEWER_TMPL.lower()


def test_screenshots_are_removed_not_deferred(monkeypatch):
    """Screenshot capture is gone: no helper, no CLI flag, no checklist."""
    runner = _load_runner(monkeypatch)
    assert not hasattr(runner, "_shot_log_line")
    assert not hasattr(runner, "capture_screenshots")
    source = (runner.__file__ and open(runner.__file__, encoding="utf-8").read()) or ""
    assert "--skip-screenshots" not in source
    assert "screenshot-checklist" not in source


def test_empty_reviewer_scores_are_invalid(monkeypatch):
    """A review with no per-criterion scores decides nothing.

    Regression: the verifier returned overall_pass:false with scores:[] and
    the run stopped on an unscored verdict instead of re-asking once.
    """
    runner = _load_runner(monkeypatch)
    ok, normalized = runner._valid_review(
        {"overall_pass": False, "scores": [], "issues": ["x"]}, ["criterion one"]
    )
    assert ok is False
    assert normalized["overall_pass"] is False
    assert any("score" in i.lower() for i in normalized["issues"])


def test_scored_review_passes_validation(monkeypatch):
    runner = _load_runner(monkeypatch)
    review = {
        "overall_pass": True,
        "scores": [{"criterion": "criterion one", "pass": True, "evidence": "log line"}],
        "issues": [],
    }
    ok, normalized = runner._valid_review(review, ["criterion one"])
    assert ok is True
    assert normalized is review


def test_reviewer_template_defines_leakage_precisely(monkeypatch):
    """Template source is not leakage; same-origin API paths are not secrets.

    Regression: the verifier quoted template-source {{ }} lines and
    INCIDENTS_URL="/api/incidents" as findings. Leakage means unrendered
    markers in SERVED page bodies; secrets are emails, exact coordinates,
    file paths, keys - never a same-origin API path.
    """
    runner = _load_runner(monkeypatch)
    tmpl = runner.REVIEWER_TMPL
    assert "Template source" in tmpl
    assert "served" in tmpl.lower()
    assert "same-origin" in tmpl.lower()


def test_builder_prompt_spells_out_probe_commands(monkeypatch):
    """Bare CLIs (pytest, playwright) may not be on PATH; python -m is.

    Regression: builder logs showed 'The system cannot find the file
    specified.' from exec_cmd probes using bare command names.
    """
    runner = _load_runner(monkeypatch)
    assert "python -m pytest" in runner.BUILDER_SYS


def test_changed_files_ignores_preexisting_dirty(monkeypatch):
    """Only the delta counts as one builder run's work.

    Regression: the 7.1 builder changed zero files and the verdict rested
    on the reviewer's reading alone instead of a measured empty delta.
    """
    runner = _load_runner(monkeypatch)
    before = "?? lite/specs/spec-7-redesign.md\n M lite/app/server/pages.py"
    after = before + "\n M lite/app/server/templates/report.html"
    assert runner._changed_files(before, after) == [" M lite/app/server/templates/report.html"]
    assert runner._changed_files(before, before) == []


def test_builder_prompt_starts_with_file_discovery(monkeypatch):
    runner = _load_runner(monkeypatch)
    assert "relevant files" in runner.BUILDER_SYS


def test_empty_builder_run_gets_continuation(monkeypatch):
    """A builder that changed nothing and listed no routes never started.

    Regression: the 7.1 builder made two directory listings and stopped;
    the run went straight to review instead of sending it back once.
    """
    runner = _load_runner(monkeypatch)
    assert runner._needs_builder_continuation([], False) is True
    assert runner._needs_builder_continuation([" M lite/x.py"], False) is False
    assert runner._needs_builder_continuation([], True) is False


def test_touched_pages_uses_last_occurrence(monkeypatch):
    """After a continuation, the final routes list wins."""
    runner = _load_runner(monkeypatch)
    pages, ok = runner.parse_touched_pages(
        "touched_pages=[...] earlier attempt touched_pages=['/report/1']"
    )
    assert ok is True
    assert pages == ["/report/1"]


def test_screenshot_criteria_split(monkeypatch):
    """Screenshot criteria defer to manual verification when skipped.

    Regression: --skip-screenshots avoided capture but the reviewer still
    failed the run on missing screenshot evidence, so the spec could never
    finish without screenshots.
    """
    runner = _load_runner(monkeypatch)
    criteria = [
        "No raw decimal or exponent-notation probability on report",
        "Screenshots (360px + desktop) of the touched pages captured and logged",
        "API JSON payloads unchanged (existing retrieval suites green).",
    ]
    code, deferred = runner._split_criteria(criteria)
    assert len(code) == 2
    assert len(deferred) == 1
    assert "creenshots" in deferred[0]


def test_builder_system_skip_variant_drops_screenshot_demands(monkeypatch):
    runner = _load_runner(monkeypatch)
    full = runner.builder_system(False)
    assert "observed-look" in full
    assert "touched_pages" in full
    skip = runner.builder_system(True)
    assert "touched_pages" in skip
    assert "do not capture" in skip.lower()
    assert "write your own observed-look notes" not in skip


def _http_error(code, location=""):
    import urllib.error
    from email.message import Message

    headers = Message()
    if location:
        headers["Location"] = location
    return urllib.error.HTTPError(
        f"http://localhost:8000/x", code, "msg", headers, None
    )


def test_page_request_asks_for_html(monkeypatch):
    """Serving checks must exercise the browser branch, not the JSON API.

    Regression: anonymous urllib GETs (no Accept header) hit the JSON
    delegation and 401'd on login-required pages.
    """
    runner = _load_runner(monkeypatch)
    req = runner._page_request("http://localhost:8000/reports/1")
    assert "text/html" in req.get_header("Accept")


def test_serving_error_lines_are_honest(monkeypatch):
    runner = _load_runner(monkeypatch)
    redirect = runner._format_serving_error("/reports/1", _http_error(302, "/login"))
    assert "-> /login" in redirect
    assert "login redirect" in redirect.lower()
    denied = runner._format_serving_error("/review/1", _http_error(401))
    assert "401" in denied
    assert "logged-in" in denied
    missing = runner._format_serving_error("/nope", _http_error(404))
    assert "404" in missing


def test_prompt_evidence_truncates_builder_dump(monkeypatch):
    """The reviewer chokes on full builder output; send the tail only.

    Regression: the reviewer returned unscored output twice on a run whose
    builder section was tens of KB of pytest dots.
    """
    runner = _load_runner(monkeypatch)
    big = "x" * 30000
    evidence, _ = runner._prompt_evidence(big, "serving")
    assert len(evidence) <= 8100
    assert "truncated" in evidence.lower()
    short, serving = runner._prompt_evidence("small", "serving")
    assert short == "small"
    assert serving == "serving"


def test_reviewer_template_marks_redirects_as_non_evidence(monkeypatch):
    runner = _load_runner(monkeypatch)
    assert "login redirect" in runner.REVIEWER_TMPL.lower()


def test_skip_note_removes_screenshots_honestly(monkeypatch):
    """Removed screenshot criteria are never scored or passed."""
    runner = _load_runner(monkeypatch)
    note = runner.REVIEWER_SKIP_NOTE
    assert "removed" in note.lower()
    assert "do not" in note.lower() and "screenshot" in note.lower()
    assert "user decision" in note.lower()


def test_change_note_names_preexisting_dirty_files(monkeypatch):
    """An empty delta next to pre-existing dirty files must say so.

    Regression: the 7.1 tree already contained the implementation, so the
    builder delta was empty while git status was not - the log line looked
    contradictory instead of explaining the attribution.
    """
    runner = _load_runner(monkeypatch)
    note = runner._change_note_for([], "?? lite/tests/test_x.py\n M lite/app/y.py\n")
    assert "none new" in note
    assert "2 pre-existing" in note
    note = runner._change_note_for([], "")
    assert note.startswith("BUILDER-FILE-CHANGES: none -")
    note = runner._change_note_for([" M lite/app/y.py"], " M lite/app/y.py")
    assert "lite/app/y.py" in note


def test_run_tool_loop_404_names_model_and_url(monkeypatch):
    """A 404 from the endpoint must name the likely misconfiguration.

    Regression: a provider/model mismatch crashed with a bare
    openai.NotFoundError traceback instead of saying which of
    MODEL_NAME / OPENAI_BASE_URL / key provider to check.
    """
    import httpx
    import openai as openai_pkg

    runner = _load_runner(monkeypatch)
    monkeypatch.setenv("MODEL_NAME", "bad-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")

    def boom(*args, **kwargs):
        raise openai_pkg.NotFoundError(
            "model not found",
            response=httpx.Response(
                404,
                content=b"{}",
                request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"),
            ),
            body={},
        )

    class FakeCompletions:
        create = staticmethod(boom)

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(runner, "get_client", lambda: FakeClient())
    with pytest.raises(RuntimeError, match=r"(?i)404"):
        runner.run_tool_loop("sys", "hi", max_turns=1)
