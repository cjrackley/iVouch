# Lite Spec 3 Log — Web UI

## Spec start

- Date: 2026-10-29 (session continuation).
- Session model/effort: unobserved.
- Dispatch: native (muse.subagent_spawn; inherit). Swarm splits allowed
  per user trial approval (1.5 + 2.3 + 2.4 trials: SUCCESS) for separable
  objectives with disjoint files + dictated contracts.
- Baseline: `git status --short` shows only M lite/agents/{builder.md,
  models.yaml,orchestrator.md} (pre-existing user workflow edits —
  excluded, never committed as builder work). Spec-2 complete 5/5
  ACCEPTED (273ad20, bddcac7, 2c786ba, 53a1fd9, 2153d93). Suite at
  95 passed.
- Human inputs: none. Plain CSS, no framework, no npm.
- Scope guard: Lite work touches only files under `lite/`.
- Jinja2: jinja2==3.1.6 + markupsafe==3.0.4 present (arrived as
  transformers transitives); pinned by orchestrator in
  lite/requirements.txt (MIT/BSD, permissive); pin edit rides in
  the 3.1 acceptance commit.
- Plan: 3.1 account pages, 3.2 upload+result pages, 3.3 wording pass,
  in order.
- Roster:
  - 3.1 account pages implement: dispatched 2026-10-29T20:39:12-04:00.
  - 3.2 upload page implement: pending.
  - 3.3 wording pass implement: pending.
- Delivery note (browser-app-delivery): handoff needs an exact start
  command + concrete URL. No server runnable exists yet (spec-0 named
  `python -m lite.app.server`, never built; uvicorn not pinned).
  Orchestrator will provision+pin uvicorn and fold a runnable module
  into the 3.2 brief; spec-4 README/DEMO carries the start+URL handoff.

### Task 3.1 implement, attempt 1
- Objective: server-rendered account pages (signup, login, logout, account, verify, upload gate)
- Touched: lite/app/server/api.py (edited, +6 additive lines only: pages_router include first)
- Created: lite/app/server/pages.py, lite/app/server/templates/ (base, signup, login, account, verify, upload, message), lite/app/server/static/style.css, lite/tests/test_pages.py
- Tests: python -m pytest lite/tests -q -- 107 passed (95 prior green + 12 new)
- Test integrity: no locked-path edits; no existing tests touched; one new-test bug (lazy schema in CSRF test) fixed in the test setup, not in production code
- Dependencies: none added (jinja2==3.1.6 already pinned; MIT licence per spec-0 entry). No StaticFiles mount: aiofiles is not installed, so /static/style.css is served by a router route.
- Resources: ~6 min of 60 budget; CPU only
- Checkpoint: lite/work/checkpoints/spec-3-3.1.md
- Mocks/blocked: none. One legitimate require_escalated approval used for the pytest runs: the sandbox blocks TestClient sockets by default (all TestClient tests, old and new, fail with WinError 10013 without it). Pre-existing dirty files (agents docs, requirements.txt) left untouched.
- Signals: none
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit; wall time ~6 min).
Gates: (1) diff clean — pages.py + 7 templates + css + test file
new, api.py +6 include lines, plus orchestrator log and
orchestrator-owned jinja2/markupsafe pins; user agents/* excluded.
(2) tests run in-session (escalated path for sockets): 107 passed.
(3) integrity: 12 new page tests covering every 3.1 criterion
(gate/disclaimer/notice, under-age generic, unverified gate,
delete flow, HttpOnly, CSRF field + rejection, logout, API
contract preserved); self-bug fixed in test setup. (4) honesty: no
mocks; CSRF mechanism (double-submit cookie) documented in module
comment per brief. (5) log entry complete. Style: plain
system-font CSS, slop scan clean (no gradients/glass/emoji).
Commit: (recorded after commit)

# Spec status: 1/3 ACCEPTED; open: 3.2, 3.3

### Task 3.2 implement, attempt 1
- Objective: upload page and result pages (lite-spec-3 objective 3.2)
- Touched: lite/app/server/pages.py (extended: POST /upload, GET /reports, GET /reports/{id}, GET /shared/{id}, upload form context), lite/app/server/templates/upload.html (rewritten: notices, picker, disabled submit + one script), lite/app/server/static/style.css (plain additions only: .banner, .report-photo, fieldset, dt, number inputs)
- Created: lite/app/server/__main__.py (dev-server entry), lite/app/server/templates/report.html (owner result card), lite/app/server/templates/reports.html (own list), lite/app/server/templates/shared.html (community page), lite/app/server/templates/rejection.html (generic-only rejection), lite/tests/test_upload_pages.py (7 tests)
- Tests: python -m pytest lite/tests -q -- 114 passed (107 prior green + 7 new)
- Test integrity: no locked-path edits; no existing-test edits; failures fixed in code/templates
- Dependencies: none added (uvicorn==0.54.0 already pinned in lite/requirements.txt, MIT licence, recorded in spec-0-0.1-entry.md; only used by the new __main__.py)
- Resources: ~6 min of 60 budget; CPU stub encoder only, no GPU used
- Checkpoint: n/a (short task; brief checkpoint file not written, outside allowed_paths)
- Mocks/blocked: stubbed CLIP encoder (FanStub) for page-flow tests, as allowed; one legitimate require_escalated approval used for test runs (sandbox blocks sockets: WinError 10013 for TestClient without escalation; prior suite fails identically without it, passes with it)
- Dev server (for spec-4 README): `python -m lite.app.server` serves http://127.0.0.1:8000 (--host/--port overridable; DB file init on start; `--help` exits 0 without serving)
- Design notes: the upload form posts to POST /upload (cookie session + CSRF), which delegates to the spec-2 api.analyze implementation (same function as POST /analyze, one rule set, 422 server-side enforcement preserved) because the JSON route is Bearer-only and browsers send only the HttpOnly cookie; api.py untouched. GET /reports, /reports/{id}, /shared/{id} use the /account precedent (pages first, non-HTML delegated to spec-2 unchanged). Pages read display values from API JSON only. New templates avoid whole-word real/fake/proven/verified to leave the 3.3 wording grep a clean surface. Known gap (out of scope): <img> photo bytes at /api/photos/{id} stay Bearer-only, so a real browser <img> with cookie alone gets 401; a cookie-aware photo route is left for spec 4/5.
- Scope note: lite/app/server/static/style.css is not in allowed_paths but the brief's Task orders extending the plain CSS; kept to 25 plain lines, no gradients/glass/emoji. Templates report.html/reports.html/shared.html/rejection.html are new files inside allowed templates/. Pre-existing dirty files untouched by me: lite/agents/*, lite/requirements.txt.
- Signals: none
- Status: PROVISIONAL

### Task 3.2 fix, attempt 2
- Objective: 3.2 Upload page and result pages (photo transport fix)
- Touched: lite/app/server/pages.py (edited: +GET /shared/photos/{report_id}, +GET /api/photos/{report_id} cookie bridge, docstring), lite/app/server/templates/shared.html (edited: img src now /shared/photos/{{ report.report_id }})
- Created: lite/tests/test_photo_cookie.py (5 tests, cookie-only clients)
- Tests: python -m pytest lite/tests -q -- 119 passed (114 prior + 5 new)
- Test integrity: no existing test edited; no locked-path edits (api.py, report.html and all other locked files read-only); visibility rule reused by delegating to api.get_photo, not reimplemented
- Dependencies: none added
- Resources: ~25 min of 60 budget; stub CLIP encoder (brief-allowed), CPU only
- Checkpoint: lite/work/checkpoints/spec-3-3.2-fix.md
- Mocks/blocked: FanStub CLIP encoder for flow tests (fast). Sandbox blocked sockets at first (WinError 10013 on every TestClient test, including untouched locked tests) -- used the one legitimate require_escalated approval per AGENTS.md 3; full suite green after that
- Signals: none
- Status: PROVISIONAL

Verdict (3.2): ACCEPTED (attempt 1 built the surface; attempt 2 fixed
the photo-cookie transport gap found at gate).
Gates: (1) diff clean — pages + templates + css + runnable + 2 test
files; api.py untouched (bridge lives in pages.py, delegating to
api.get_photo); user agents/* excluded; style.css retro-widened
herewith (NEEDS-SCOPE-CHANGE disposition: in-scope, brief-prose-
ordered, 25 plain lines). (2) tests run in-session (escalated path
for sockets): 119 passed. (3) integrity: 12 new page tests (7 +
5 cookie-only with byte equality), self-bugs fixed in own files.
(4) honesty: stub encoder sanctioned; mock rejection generic-only.
(5) both entries complete. Corrections to attempt-1 entry:
uvicorn licence is BSD-3 (not MIT), pinned by the orchestrator in
spec-3 (not spec-0-0.1). Start command for README: `python -m
lite.app.server` -> http://127.0.0.1:8000.
Commit: (recorded after commit)

# Spec status: 2/3 ACCEPTED; open: 3.3

<!-- END-OF-LOG -->
