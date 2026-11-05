# agent_runner.py - Generic Lite Orchestrator -> Builder -> Verifier
# Works with any Lite Spec (7, 8, etc). No hardcoded spec number.
# muse-spark-open via OpenAI API
import re, json, pathlib, difflib, subprocess, urllib.request, argparse
from openai import NotFoundError, OpenAI

import os

# Baseten's OpenAI-compatible endpoint at https://inference.baseten.co/v1
# expects Authorization: Api-Key <key>, not Bearer. The OpenAI SDK sends
# Bearer by default, so we subclass to override auth_headers for Baseten.
DEFAULT_BASE_URL = "https://inference.baseten.co/v1"
DEFAULT_MODEL = "meta-models/muse-spark-open-1026"

class BasetenOpenAI(OpenAI):
    @property
    def auth_headers(self):
        # Baseten uses Api-Key, OpenAI uses Bearer - switch based on URL
        if "baseten.co" in str(self.base_url):
            return {"Authorization": f"Api-Key {self.api_key}"}
        return {"Authorization": f"Bearer {self.api_key}"}

def _resolve_api_key() -> str:
    return os.getenv("OPENAI_API_KEY") or os.getenv("BASETEN_API_KEY") or ""


def _resolve_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL)


def _resolve_model() -> str:
    return os.getenv("MODEL_NAME", DEFAULT_MODEL)


def get_client() -> BasetenOpenAI:
    """Create the model client lazily so --help and imports work without keys."""
    api_key = _resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Missing API key: set OPENAI_API_KEY (or BASETEN_API_KEY) before running "
            "agent_runner.py. The runner creates no client at import time so this "
            "is the only credential checkpoint."
        )
    return BasetenOpenAI(base_url=_resolve_base_url(), api_key=api_key)
WORK_ROOT = pathlib.Path(".").resolve()
ALLOWED_ROOT = WORK_ROOT / "lite"

TOOLS_SPEC = [
  {"type":"function","function":{"name":"read_file","description":"Read file inside lite/","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
  {"type":"function","function":{"name":"write_file","description":"Write file inside lite/ and return diff","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
  {"type":"function","function":{"name":"apply_patch","description":"Replace exact old_text with new_text inside lite/ (never lite/logs/)","parameters":{"type":"object","properties":{"path":{"type":"string"},"old_text":{"type":"string"},"new_text":{"type":"string"}},"required":["path","old_text","new_text"]}}},
  {"type":"function","function":{"name":"search_files","description":"Regex search inside lite/ only; returns path:line matches (read-only)","parameters":{"type":"object","properties":{"pattern":{"type":"string"},"glob":{"type":"string"}},"required":["pattern"]}}},
  {"type":"function","function":{"name":"exec_cmd","description":"Throwaway read-only shell probe (pytest/python/dir); no delete, no git writes, no log writes, no secret reads","parameters":{"type":"object","properties":{"cmd":{"type":"string"}},"required":["cmd"]}}},
]

def read_file(path: str) -> str:
    p = (WORK_ROOT / path).resolve()
    if ALLOWED_ROOT not in p.parents and p != ALLOWED_ROOT:
        return "ERROR: NEEDS-SCOPE-CHANGE - outside allowed_paths"
    return p.read_text(encoding="utf-8", errors="ignore")

def write_file(path: str, content: str) -> str:
    p = (WORK_ROOT / path).resolve()
    if ALLOWED_ROOT not in p.parents:
        return "ERROR: NEEDS-SCOPE-CHANGE - outside lite/"
    if path.startswith("lite/logs/"):
        return "ERROR: Builder cannot write to lite/logs/ - orchestrator does those"
    if path == "lite/specs" or path.startswith("lite/specs/"):
        return "ERROR: Builder cannot edit specs - specs are read-only input"
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text() if p.exists() else ""
    p.write_text(content, encoding="utf-8")
    diff = "".join(difflib.unified_diff(old.splitlines(True), content.splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"))
    return f"WROTE {path} (PROVISIONAL diff):\n{diff[:5000]}"

def _scope_error(path: str) -> str | None:
    p = (WORK_ROOT / path).resolve()
    if ALLOWED_ROOT not in p.parents and p != ALLOWED_ROOT:
        return "ERROR: NEEDS-SCOPE-CHANGE - outside lite/"
    if path == "lite/logs" or path.startswith("lite/logs/"):
        return "ERROR: Builder cannot write to lite/logs/ - orchestrator does those"
    if path == "lite/specs" or path.startswith("lite/specs/"):
        return "ERROR: Builder cannot edit specs - specs are read-only input"
    return None


def apply_patch(path: str, old_text: str, new_text: str) -> str:
    denied = _scope_error(path)
    if denied:
        raise ValueError(denied)
    p = (WORK_ROOT / path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"ERROR: no such file inside lite/: {path}")
    text = p.read_text(encoding="utf-8", errors="ignore")
    assert old_text in text, "old_text not found"
    return write_file(path, text.replace(old_text, new_text, 1))


def search_files(pattern: str, glob: str = "**/*.py") -> str:
    """Read-only regex search confined to lite/. Mirrors the builder search tool."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"ERROR: bad regex: {e}"
    hits: list[str] = []
    roots = sorted((ALLOWED_ROOT).rglob("*"))
    import fnmatch

    for f in roots:
        if not f.is_file():
            continue
        rel = f.relative_to(WORK_ROOT).as_posix()
        if not fnmatch.fnmatch(rel, glob) and not fnmatch.fnmatch(f.name, glob):
            continue
        if f.stat().st_size > 512 * 1024:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{rel}:{i}:{line.strip()[:200]}")
                if len(hits) >= 100:
                    return "\n".join(hits) + "\nTRUNCATED at 100 hits"
    return "\n".join(hits) if hits else "NO MATCHES"


_BLOCKED_CMD = re.compile(
    r"(?i)\b(rm\b|rmdir|del\b|erase\b|remove-item|ri\b|clear-content|set-content|"
    r"out-file|move-item|shutil|os\.remove|os\.unlink|pathlib.*unlink|git\s+(add|commit|push|amend|rebase|branch|checkout|restore|reset|stash|clean)|"
    r"docker\s+(volume|compose\s+down)|drop\b|truncate\b)",
)
_BLOCKED_PATH = re.compile(r"(?i)(\.env\b|lite/logs/|lite/specs/|logs/spec|\.pem\b|\.key\b|\.p12\b|service-account|credentials)")


def exec_cmd(cmd: str) -> str:
    lowered = cmd.strip().lower()
    if _BLOCKED_CMD.search(cmd) or _BLOCKED_PATH.search(cmd):
        return (
            "ERROR: BLOCKED - exec_cmd is a throwaway read-only probe only "
            "(pytest/python/dir). Deletes, git writes, log writes, database "
            "drops and secret reads are never allowed."
        )
    if re.search(r"(?i)(>>|>\s*\S*log)", cmd) and "log" in lowered:
        return "ERROR: BLOCKED - probes never write logs."
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return f"EXIT:{r.returncode}\nSTDOUT:\n{r.stdout[-4000:]}\nSTDERR:\n{r.stderr[-4000:]}"

TOOL_IMPL = {"read_file": read_file, "write_file": write_file, "apply_patch": apply_patch, "search_files": search_files, "exec_cmd": exec_cmd}

def _chat_create(client, model, messages, **kwargs):
    """One chat-completions call with an actionable error on 404.

    A 404 almost always means the key, base URL and model come from
    different providers (or a stale model ID), so name the resolved
    values instead of dumping a traceback.
    """
    try:
        return client.chat.completions.create(model=model, messages=messages, **kwargs)
    except NotFoundError as e:
        raise RuntimeError(
            "Model endpoint returned 404: no such model at this URL. "
            f"MODEL_NAME={_resolve_model()!r} OPENAI_BASE_URL={_resolve_base_url()!r}. "
            "Use a key, base URL and model name from the SAME provider "
            "(e.g. an OpenAI key with https://api.openai.com/v1 and an OpenAI model, "
            "or a Baseten key with the Baseten URL and a Baseten model ID)."
        ) from e

def _needs_builder_continuation(changed: list[str], touched_ok: bool) -> bool:
    """One automatic retry when the builder never started.

    A builder that edited no files and listed no routes produced no
    implementation to verify; sending it straight to review wastes the
    verdict. Retry once with explicit instructions instead.
    """
    return not changed and not touched_ok


def _split_criteria(criteria: list[str]) -> tuple[list[str], list[str]]:
    """Split code criteria from screenshot criteria.

    When screenshots are skipped, only the code criteria go to the
    reviewer; screenshot criteria are recorded as deferred manual work,
    never scored. A criterion counts as a screenshot criterion when it
    names screenshots or captures.
    """
    deferred = [
        c for c in criteria
        if "screenshot" in c.lower() or "capture" in c.lower()
    ]
    code = [c for c in criteria if c not in deferred]
    return code, deferred


def _change_note_for(changed: list[str], pre_status: str) -> str:
    """File-change evidence line for one builder run.

    An empty delta next to pre-existing dirty files names that fact, so
    the log never reads as contradictory: pre-existing work is excluded
    from attribution by design (it is not the builder's).
    """
    if changed:
        return "BUILDER-FILE-CHANGES:\n" + "\n".join(changed)
    pre = [line for line in pre_status.splitlines() if line.strip()]
    if pre:
        return (
            "BUILDER-FILE-CHANGES: none new - the builder run modified/added no files under lite/ "
            f"({len(pre)} pre-existing dirty line(s) excluded from attribution)."
        )
    return "BUILDER-FILE-CHANGES: none - the builder modified/added no files under lite/."


def _worktree_snapshot() -> str:
    """`git status --short -- lite/` (best effort; "" when git is unavailable)."""
    try:
        r = subprocess.run(
            "git status --short -- lite/", shell=True,
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _changed_files(before: str, after: str) -> list[str]:
    """Worktree delta for one builder run.

    Compares status snapshots so pre-existing dirty files are not blamed
    on the builder; an empty delta means the builder changed nothing.
    """
    old = set(before.splitlines())
    return sorted(line for line in after.splitlines() if line not in old)


def run_tool_loop(system: str, user: str, max_turns=12):
    client = get_client()
    model = _resolve_model()
    msgs = [{"role":"system","content": system}, {"role":"user","content": user}]
    for _ in range(max_turns):
        resp = _chat_create(client, model, msgs, tools=TOOLS_SPEC, tool_choice="auto")
        m = resp.choices[0].message
        if not m.tool_calls:
            return m.content or ""
        msgs.append({
            "role": "assistant",
            "content": m.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in m.tool_calls
            ]
        })
        for tc in m.tool_calls:
            args = json.loads(tc.function.arguments)
            if tc.function.name not in TOOL_IMPL:
                result = (
                    f"ERROR: BLOCKED - tool {tc.function.name!r} is not a builder tool. "
                    "Builders use read_file, write_file, apply_patch, search_files "
                    "and read-only exec_cmd probes only."
                )
            else:
                try:
                    result = TOOL_IMPL[tc.function.name](**args)
                except Exception as e:
                    result = f"ERROR: {e}"
            msgs.append({"role":"tool","tool_call_id": tc.id, "content": result})
    # out of turns - return last message content or last tool output
    last = msgs[-1]
    if isinstance(last, dict):
        return last.get("content") or "max turns reached"
    return getattr(last, "content", None) or "max turns reached"

def parse_spec(md_path: str):
    text = pathlib.Path(md_path).read_text()
    m_spec = re.search(r"#\s+Lite Spec\s+(\d+)", text)
    spec_num = m_spec.group(1) if m_spec else (re.search(r"spec-?(\d+)", md_path).group(1) if re.search(r"spec-?(\d+)", md_path) else "0")
    m_exec = re.search(r"\|\s*Execution\s*\|\s*([^\n|]+)", text)
    execution = m_exec.group(1).strip() if m_exec else "Sequential"
    raw = re.findall(r"###\s+(\d+\.\d+)[^\n]*\n(.*?)(?=\n###\s+\d+\.\d+|\n##\s+|\Z)", text, re.S)
    if not raw:
        raw = re.findall(r"##\s+(?:Objective\s+)?(\d+\.\d+)[^\n]*\n(.*?)(?=\n##\s+(?:Objective\s+)?\d+\.\d+|\Z)", text, re.S)
    objectives=[]
    for obj_id, body in raw:
        criteria = re.findall(r"- \[ \] (.+)", body)
        objectives.append({"id": obj_id, "body": body.strip(), "criteria": criteria})
    return {"spec_num": spec_num, "execution": execution, "objectives": objectives}

def parse_touched_pages(builder_out: str) -> tuple[list[str], bool]:
    """Parse touched_pages=[...]. Returns (pages, ok).

    ok is False when the builder listed no real routes (missing, placeholder,
    or unparsable): evidence then covers only '/' and can never satisfy
    page-specific criteria. Callers must surface ok=False to the reviewer
    instead of silently accepting the fallback. When several lists are
    present (e.g. after a continuation), the last one wins.
    """
    matches = re.findall(r"touched_pages\s*=\s*(\[.*?\])", builder_out, re.S)
    if not matches:
        print("WARNING: no touched_pages found in builder_out, defaulting to ['/'] - Builder must end with touched_pages=[...]")
        return ["/"], False
    raw = matches[-1].strip()
    # handle literal placeholder like [...] or [... ] which is not valid JSON
    if "..." in raw or raw == "[]":
        print(f"WARNING: builder returned placeholder {raw!r}, defaulting to ['/'] - Builder must list real routes like ['/report/1']")
        return ["/"], False
    # try JSON with single-quote tolerance, then fallback to quoted strings
    try:
        pages = json.loads(raw.replace("'", '"'))
        return (pages, True) if pages else (["/"], False)
    except Exception as e:
        # fallback: extract quoted strings
        fallback = re.findall(r"""['\"]([^'\"]+)['\"]""", raw)
        if fallback:
            print(f"WARNING: json.loads failed ({e}), fallback parsed {fallback} from {raw!r}")
            return fallback, True
        print(f"WARNING: could not parse touched_pages {raw!r}: {e}, defaulting to ['/']")
    return ["/"], False

def _valid_review(review: object, criteria: list[str]) -> tuple[bool, dict]:
    """Reviewer JSON must score the criteria; empty scores decide nothing.

    Returns (True, review) when scores exist, else (False, normalized) with
    overall_pass forced False and the protocol breach recorded in issues.
    """
    if not isinstance(review, dict):
        return False, {
            "overall_pass": False,
            "scores": [],
            "issues": ["reviewer returned non-JSON output"],
        }
    scores = review.get("scores") or []
    if not scores:
        issues = list(review.get("issues", []))
        issues.append("reviewer returned no per-criterion scores; verdict is unscored")
        return False, {**review, "overall_pass": False, "scores": [], "issues": issues}
    return True, review


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects to the caller instead of following them."""

    def _raise(self, req, fp, code, msg, headers):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

    http_error_301 = _raise
    http_error_302 = _raise
    http_error_303 = _raise
    http_error_307 = _raise
    http_error_308 = _raise


def _page_request(url: str) -> urllib.request.Request:
    """A browser-navigation request: HTML accept, no API credentials."""
    return urllib.request.Request(
        url, headers={"Accept": "text/html", "User-Agent": "iVouch-agent-runner/1.0"}
    )


def _format_serving_error(page: str, err: Exception) -> str:
    """Honest one-line serving evidence for non-200 responses."""
    code = getattr(err, "code", None)
    location = ""
    try:
        location = (err.headers.get("Location", "") or "") if hasattr(err, "headers") else ""
    except Exception:
        location = ""
    if code in (301, 302, 303, 307, 308) and location:
        return f"GET {page} {code} -> {location} (login redirect; anonymous check cannot evidence page content)"
    if code == 401:
        return f"GET {page} 401 Unauthorized (anonymous request reached the JSON branch - page needs a logged-in browser session)"
    if code in (403, 404):
        return f"GET {page} {code} (route refused or missing for anonymous request)"
    return f"GET {page} FAILED: {err}"


def _prompt_evidence(builder_out: str, serving_log: str) -> tuple[str, str]:
    """Reviewer-sized evidence: builder tail only, serving log capped."""
    if len(builder_out) > 8000:
        builder_out = "[builder output truncated to last 8000 chars]\n" + builder_out[-8000:]
    return builder_out, serving_log[:4000]


def serving_check(base_url: str, touched_pages: list[str]) -> str:
    logs=[]
    opener = urllib.request.build_opener(_NoRedirect)
    for page in touched_pages + ["/static/style.css"] :
        url = base_url.rstrip("/") + page
        try:
            with opener.open(_page_request(url), timeout=10) as r:
                assert r.status == 200, f"{page} {r.status}"
                body = r.read().decode(errors="ignore") if page != "/static/style.css" else ""
                if page != "/static/style.css":
                    assert "/static/style.css" in body or "stylesheet" in body, f"stylesheet link missing in {page}"
                logs.append(f"GET {page} 200 + stylesheet link OK")
        except Exception as e:
            logs.append(_format_serving_error(page, e))
    return "\n".join(logs)

_BUILDER_BASE = "You are Builder. You implement one brief inside lite/. You cannot judge your own work, write to lite/logs/, edit lite/specs/, commit, spawn agents, or mark work done. Specs are read-only input; logs are the orchestrator's. Stay inside allowed_paths or return NEEDS-SCOPE-CHANGE. Tools: read_file, write_file, apply_patch, search_files, exec_cmd (read-only probes; never delete, never git writes, never log writes, never spec edits, never secret reads). Start by locating the relevant files with search_files using the template, context-key and route names from the criteria - do not guess file contents. Spell probes as 'python -m ...' (e.g. python -m pytest lite/tests/test_pages.py -q): bare CLIs like pytest or playwright may not be on PATH and fail with file-not-found. Use search_files for grep-style checks, not exec_cmd. No subagent/workflow/monitor/web/request/memory/cron/skill tools exist for you. Before finishing: re-read every criterion, use search_files to prove no forbidden pattern remains, run the relevant pytest suite via exec_cmd"
_BUILDER_SHOTS = ", and write your own observed-look notes per screenshot (what you changed, what you verified)."
_BUILDER_TAIL = " End with touched_pages=[...] listing EVERY route you changed, e.g. touched_pages=['/report/1','/shared/demo']. ['/'] is allowed only when home was truly the only page changed. Never use placeholder [...]."
_BUILDER_SKIP_SHOTS = " Screenshots are skipped for this run: do not capture any screenshots and write no observed-look notes; implement the code and verify with search_files plus the pytest suite instead."


def builder_system(skip_screenshots: bool) -> str:
    """Builder prompt, with screenshot demands removed when skipped."""
    shots = _BUILDER_SKIP_SHOTS if skip_screenshots else _BUILDER_SHOTS
    return _BUILDER_BASE + shots + _BUILDER_TAIL


BUILDER_SYS = builder_system(True)
REVIEWER_TMPL = "You are Verifier. Spec {spec_num} Objective {id} Execution:{execution} Body:{body} Criteria JSON:{criteria_json} Builder PROVISIONAL:{builder_out} Serving evidence (GET each touched page + /static/style.css 200 + stylesheet link):{serving_log} Screenshot evidence (PNGs under lite/work/screenshots/spec-{spec_num}/{id}/, 360px mobile + desktop, log = path + observed-look + verdict, ASCII-only):{screenshot_log} Rules: a serving log covering only '/' (or only /static/style.css) never satisfies page-specific criteria - fail those criteria regardless of home-page lines. A screenshot criterion passes only with 360px AND desktop captures of every touched page. A criterion requiring a manual check passes only on cited human observation in the builder output or logs - auto-captured screenshot lines alone never satisfy it. Template source files under templates/ naturally contain {{{{ }}}} and {{% %}} markers - that is not leakage. Leakage means those markers appearing in SERVED page bodies. Same-origin API paths (e.g. /api/incidents) are not secret exposure; secrets are emails, exact coordinates, file paths, keys. A 302-to-/login line is a login redirect, not page content - it never satisfies a content criterion. Score EVERY criterion in Criteria JSON, one entry each - an empty scores list is invalid. Return JSON ONLY: {{\"scores\":[{{\"criterion\":\"...\",\"pass\":bool,\"evidence\":\"cite log line\"}}],\"overall_pass\":bool,\"issues\":[]}}"
REVIEWER_SKIP_NOTE = " Screenshot criteria were removed from this spec run per user decision (2026-11-04): the criteria above are the code criteria only. Do not score, pass, or fail any screenshot/capture requirement - those were removed, not waived. Judge overall_pass on the listed criteria alone."
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generic Lite agent runner")
    ap.add_argument("--spec", default="specs/spec-7-redesign.md", help="path to spec markdown")
    ap.add_argument("--base-url", default="http://localhost:8000", help="base URL of running app (local or remote)")
    args = ap.parse_args()
    # Screenshot verification was removed per user decision (2026-11-04):
    # the runner never captures screenshots and screenshot criteria are
    # recorded as removed, never scored.
    try:
        get_client()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        raise SystemExit(2)
    spec = parse_spec(args.spec)
    print(f"Spec {spec['spec_num']} Execution: {spec['execution']} Objectives: {[o['id'] for o in spec['objectives']]}")
    print(f"Base URL: {args.base_url}")
    SYSTEM_ORCH = f"You are Orchestrator with final say for Spec {spec['spec_num']}. Execution: {spec['execution']}. Only PASS if Verifier overall_pass=true."
    for obj in spec["objectives"]:
        print(f"\n=== Objective {obj['id']} ===")
        print(f"Criteria: {obj['criteria']}")
        code_criteria, deferred_criteria = _split_criteria(obj["criteria"])
        if deferred_criteria:
            print(f"Screenshots removed: {len(deferred_criteria)} screenshot criterion/criteria taken out per user decision, not scored.")
        pre_status = _worktree_snapshot()
        builder_out = run_tool_loop(builder_system(True), f"Objective {obj['id']}:\n{obj['body']}\nRepo root: ./\nScreenshot verification is removed: do not capture any; implement and verify code plus tests only.")
        print(f"--- Builder raw output ---\n{builder_out[-6000:]}\n--- end Builder output ---")
        # Only warn on real exec_cmd failure markers, not on source-code mentions of EXIT:255
        if re.search(r"EXIT:\s*255\b", builder_out) and "STDERR:" in builder_out:
            print("WARNING: Builder reported EXIT:255 - check STDOUT/STDERR above for build/test failure details")
        touched, touched_ok = parse_touched_pages(builder_out)
        print(f"Parsed touched_pages: {touched} (routes_listed={touched_ok})")
        changed = _changed_files(pre_status, _worktree_snapshot())
        if _needs_builder_continuation(changed, touched_ok):
            print("Builder changed no files and listed no routes - sending it back once with explicit instructions.")
            builder_out += "\n\n--- CONTINUATION (first attempt changed nothing) ---\n" + run_tool_loop(
                builder_system(True),
                f"Objective {obj['id']} (continued):\n{obj['body']}\nRepo root: ./\n"
                "Your previous attempt only listed directories: it edited no files and ended with no touched_pages. "
                "Now: use read_file/search_files to open the relevant spec and code files, make the edits the criteria require "
                "(or, if the tree already satisfies them, verify with search_files and the pytest suite), and end with "
                "touched_pages=[...] listing EVERY route you changed or verified.",
            )
            print(f"--- Builder raw output (continued) ---\n{builder_out[-6000:]}\n--- end Builder output ---")
            touched, touched_ok = parse_touched_pages(builder_out)
            print(f"Parsed touched_pages: {touched} (routes_listed={touched_ok})")
        changed = _changed_files(pre_status, _worktree_snapshot())
        change_note = _change_note_for(changed, pre_status)
        if not changed:
            print("WARNING: builder changed no files under lite/.")
        shot_dir = WORK_ROOT / "lite" / "work" / "runner"
        shot_dir.mkdir(parents=True, exist_ok=True)
        (shot_dir / f"spec-{spec['spec_num']}-{obj['id']}-builder.md").write_text(
            builder_out[-20000:] + "\n\n--- REVIEW ---\n", encoding="utf-8")
        if not touched_ok:
            print("BLOCKED: builder listed no real routes - evidence covers only '/' and cannot satisfy page-specific criteria.")
        screenshot_log = "Screenshots removed per user decision (2026-11-04): no capture step, no screenshot evidence."
        try:
            serving_log = serving_check(args.base_url, touched)
        except Exception as e:
            serving_log = f"Serving check FAILED: {e}"
        serving_log = change_note + "\n" + serving_log
        if not touched_ok:
            serving_log = "TOUCHED-PAGES PROTOCOL FAILURE: builder listed no real routes; evidence below covers only '/' and cannot satisfy page-specific criteria.\n" + serving_log
        print(f"Serving log:\n{serving_log}")
        print(f"Screenshot log:\n{screenshot_log}")
        if not code_criteria:
            print(f"Objective {obj['id']} has only removed screenshot criteria - nothing for the reviewer to judge.")
            review = {"overall_pass": True, "scores": [], "issues": ["all criteria removed (screenshot verification removed per user decision)"]}
            ok_review = True
            reviewer_raw = "(reviewer skipped: no code criteria)"
        else:
            prompt_builder, prompt_serving = _prompt_evidence(builder_out, serving_log)
            reviewer_prompt = REVIEWER_TMPL.format(spec_num=spec['spec_num'], id=obj['id'], execution=spec["execution"], body=obj["body"], criteria_json=json.dumps(code_criteria), builder_out=prompt_builder, serving_log=prompt_serving, screenshot_log=screenshot_log)
            reviewer_prompt += REVIEWER_SKIP_NOTE
            reviewer_raw = run_tool_loop("You are Reviewer. Return JSON only.", reviewer_prompt)
            try:
                review = json.loads(re.search(r"\{.*\}", reviewer_raw, re.S).group(0))
            except Exception:
                review = {"overall_pass": False, "scores": [], "issues": [reviewer_raw]}
            ok_review, review = _valid_review(review, code_criteria)
        if not ok_review:
            print("Reviewer JSON invalid (no per-criterion scores) - re-asking reviewer once.")
            retry_raw = run_tool_loop(
                "You are Reviewer. Return JSON only.",
                reviewer_prompt + " Your previous reply had no per-criterion scores. "
                "Score EVERY criterion in Criteria JSON, one entry each. Return JSON ONLY.",
            )
            try:
                retry = json.loads(re.search(r"\{.*\}", retry_raw, re.S).group(0))
            except Exception:
                retry = {"overall_pass": False, "scores": [], "issues": [retry_raw]}
            ok_review, review = _valid_review(retry, code_criteria)
            if not ok_review:
                print("Reviewer JSON still invalid - failing the objective on reviewer protocol.")
        with open(shot_dir / f"spec-{spec['spec_num']}-{obj['id']}-builder.md", "a", encoding="utf-8") as fh:
            fh.write(change_note + "\nServing:\n" + serving_log[:4000] + "\nScreenshots:\n" + screenshot_log[:4000] + "\nReview JSON:\n" + json.dumps(review)[:8000] + "\n")
        for s in review.get("scores", []):
            print(f"[{'PASS' if s['pass'] else 'FAIL'}] {s['criterion']} -> {s['evidence']}")
        verdict_client = get_client()
        prompt_builder, prompt_serving = _prompt_evidence(builder_out, serving_log)
        verdict = _chat_create(verdict_client, _resolve_model(), messages=[{"role":"system","content": SYSTEM_ORCH},{"role":"user","content": f"Objective {obj['id']} Reviewer JSON:\n{json.dumps(review)}\nBuilder:\n{prompt_builder}\nServing:\n{prompt_serving}\nApprove? Return PASS/FAIL."}]).choices[0].message.content or ""
        print(verdict)
        if "FAIL" in verdict.upper() or not review.get("overall_pass"):
            print(f"Stopped at {obj['id']} for fixes before next objective.")
            break
        log_path = pathlib.Path(f"lite/logs/spec{spec['spec_num']}_log.md")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log_path, "a")
        if deferred_criteria:
            fh.write(f"\n### Objective {obj['id']} CODE-PASS (screenshot verification removed per user decision 2026-11-04)\n")
            for s in review.get("scores", []): fh.write(f"- [x] {s['criterion']}\n")
            for d in deferred_criteria: fh.write(f"- [ ] REMOVED: {d}\n")
        else:
            fh.write(f"\n### Objective {obj['id']} ACCEPTED\n")
            for s in review.get("scores", []): fh.write(f"- [x] {s['criterion']}\n")
        fh.close()
        if deferred_criteria:
            print(f"{obj['id']} CODE-PASS - logged (screenshots removed per user decision, not committed as ACCEPTED)")
        else:
            subprocess.run(f"git add lite/ && git commit -m 'spec {spec['spec_num']} {obj['id']} ACCEPTED' --allow-empty", shell=True)
            print(f"{obj['id']} ACCEPTED - committed")
