# Lite Spec 2 Log — Server

## Spec start

- Date: 2026-10-29 (session continuation).
- Session model/effort: unobserved.
- Dispatch: native (muse.subagent_spawn; inherit). Swarm splits allowed
  per user trial approval (1.5 trial: SUCCESS) for separable objectives
  with disjoint single-file briefs + dictated contracts.
- Baseline: `git status --short` shows only M lite/agents/{builder.md,
  models.yaml,orchestrator.md} (pre-existing user workflow edits —
  excluded from all diff gates, never committed as builder work).
  Spec-1 complete 5/5 ACCEPTED (564c1ea, 6854348, 6cc92ae, 7c445c3,
  4ff16e4). Suite at 64 passed.
- Human inputs: none (spec states none). Email is console-file only;
  no real provider in Lite.
- Scope guard: Lite work touches only files under `lite/`.
- Plan: 2.1 schema+stores+CLI first (serial foundation); then 2.2,
  2.3 (swarm-split candidate: pipeline wiring + endpoint tests),
  2.4, 2.5 in order. Server deps (fastapi, argon2-cffi, PyJWT,
  httpx, multipart) not yet installed — provisioned before 2.2.
- Roster:
  - 2.1 schema+stores+CLI implement: dispatched 2026-10-29T16:22:55-04:00.
  - 2.2 accounts+auth implement: pending.
  - 2.3 upload+pipeline implement: pending.
  - 2.4 retrieval implement: pending.
  - 2.5 e2e smoke implement: pending.

### Task 2.1 implement, attempt 1
- Objective: schema and stores (spec-2-server objective 2.1)
- Touched: lite/app/cli.py (edited: --db flag defaulting to lite/data/ivouch.db, make-reviewer subcommand; main() with no args still returns 0)
- Created: lite/app/server/db.py (stdlib sqlite3 schema: accounts, reports, check_results, review_actions, audit_events, schema_version row; init_db idempotent no-op; create_report first-wins on (account_id, client_report_id) incl. differing bytes; no DOB column anywhere), lite/tests/test_db.py (7 tests, tmp SQLite files only)
- Tests: python -m pytest lite/tests -q -- 71 passed (64 prior + 7 new)
- Test integrity: no locked-path edits; layout-test conflict (argparse reading pytest argv) fixed in code by defaulting main() argv to [] with sys.argv[1:] passed explicitly at __main__
- Dependencies: none added (stdlib only)
- Resources: within 60 min budget; CPU only
- Checkpoint: lite/work/checkpoints/spec-2-2.1.md
- Mocks/blocked: none
- Signals: none
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit).
Gates: (1) diff clean — cli.py edit (brief-allowed) + 2 new files
plus orchestrator log; user agents/* edits excluded; pytest junk
removed by orchestrator. (2) tests run in-session: 71 passed.
(3) integrity: new test file, tmp DBs only, DOB spelling sweep,
idempotency incl. differing bytes, CLI via subprocess; the
argparse/pytest-argv clash fixed in code, layout test still green.
(4) honesty: no mocks. (5) log entry complete.
Commit: (recorded after commit)

# Spec status: 1/5 ACCEPTED; open: 2.2, 2.3, 2.4, 2.5

### Task 2.2 implement, attempt 1
- Objective: accounts + auth (register / verify-email / login / account / delete)
- Touched: none (all new files)
- Created: lite/app/server/auth.py, lite/app/server/mail.py, lite/app/server/api.py, lite/tests/test_auth.py
- Tests: python -m pytest lite/tests -q -- 79 passed (71 prior + 8 new)
- Test integrity: no locked-path edits; committed tests use TestClient with tmp SQLite + tmp mail/uploads dirs only; no test edits existing files
- Dependencies: none added (used pinned fastapi==0.162.0, argon2-cffi==25.1.0, PyJWT==2.15.1, httpx==0.28.1, python-multipart==0.0.32; no AGPL/GPL in this set)
- Resources: within 60-min budget; CPU only, no GPU used
- Checkpoint: lite/work/checkpoints/spec-2-2.2.md (complete, no resume needed)
- Mocks/blocked: none (no mocks allowed/needed). Sandbox blocks sockets, so TestClient runs used one legitimate require_escalated approval per AGENTS.md 3; tmp dirs kept under scratch dir probe_0r7yhz_p/ -- orchestrator please remove that dir (builders cannot delete). lite/agents/*.md + lite/requirements.txt were dirty before this session (pre-existing, not mine).
- Signals: none
- Design notes: verify tokens are stateless signed JWTs (no change to committed db.py schema); register always answers 200 with one generic body (new / known-email / under-age indistinguishable, under-age stores nothing and sends no mail, DOB never stored -- only age_confirmed_at, min_age + jwt_access_minutes via loader); login answers 401 with one body for unknown email vs wrong password (plus dummy-verify timing); login succeeds pre-verification and the verified-only gate lives on upload (2.3 answers 403); DELETE removes account + cascaded reports + <uploads_dir>/<account_id>/ tree and keeps one account_deletion audit event; JWT secret from LITE_JWT_SECRET with a clearly marked dev-only fallback; api.py exposes create_app(db/mail/uploads) + module app, one router per area for later objectives
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit).
Gates: (1) diff clean — 4 new files only plus orchestrator log and
orchestrator-owned requirements pins; user agents/* edits excluded;
builder scratch dirs removed by orchestrator. (2) tests run
in-session: 79 passed — with one environment note: the default
sandbox denies socket creation (WinError 10013), which TestClient
needs, so the suite was gated via the sanctioned one-time
require_escalated approval path per AGENTS.md 3 (same mechanism as
all prior provisioned installs). (3) integrity: new test file, tmp
dirs only, env-var JWT secret, generic responses asserted.
(4) honesty: no mocks; DOB never stored, only age_confirmed_at.
(5) log entry complete. Orchestrator-pinned server deps
(argon2-cffi/PyJWT/httpx/multipart, all permissive licences) ride
in this commit since requirements.txt is builder-locked.
Commit: (recorded after commit)

# Spec status: 2/5 ACCEPTED; open: 2.3, 2.4, 2.5

<!-- END-OF-LOG -->
