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
- Commit bddcac7 recorded for 2.2 (6 files incl. requirements pins, working tree clean after).
- Roster: 2.3 upload+pipeline swarm pair dispatched 2026-10-29T18:34:29-04:00 (implementer + test-specialist, disjoint files, dictated contract).

### Task 2.3 implement, attempt 1
- Objective: synchronous upload + processing pipeline (spec-2 2.3, implement half)
- Touched: lite/app/server/api.py (edited: create_app gains optional clip_encoder kwarg stored as app.state.clip_encoder plus upload_router include; new POST /analyze route only -- no auth-route changes)
- Created: lite/app/server/pipeline.py (new: process_upload/analyze_bytes/build_response/stored_response/persist_accepted_upload/prior_report_rows/load_mock_hashes/sha256_hex/phash_hex/upload_extension/write_upload_file/record_mock_rejection)
- Tests: python -m pytest lite/tests -q -- 88 passed (79 prior + 9 new from co-worker test_upload.py); must_pass subset (ignore test_upload.py) also 79 passed. Self-probe script (throwaway, outside repo) verified happy-path exact keys, idempotent replay, 422x4 with nothing stored, 403 unverified, mock-gate body/audit/no-file, 415/413 -- ALL PASSED.
- Test integrity: no test files written or edited; no locked-path edits; one real bug found by probe + co-worker (missing `fusion` import in pipeline.py) fixed in code, not in tests
- Dependencies: none added (stdlib + PIL/imagehash/fastapi already pinned)
- Resources: ~55 min of 60 budget; CPU only, stub encoder for verification, no GPU used
- Checkpoint: lite/work/checkpoints/spec-2-2.3-impl.md
- Mocks/blocked: mock hash gate is the spec'd MockHashMatcher (benign synthetic fixtures only); live CLIP path left to 2.5 per brief. Sandbox blocks sockets (WinError 10013), so TestClient runs used require_escalated approvals (suite + probe). Co-worker test_upload.py landed mid-task; pytest-of-camer/ junk dir at repo root is test fallout for the orchestrator to remove (builders cannot delete).
- Signals: none
- Design notes: no job queue -- deliberate Lite simplification, recorded in pipeline.py module comment. Order enforced: location/consent 422 (stores nothing) -> verified gate 403 -> idempotent replay -> 413 oversize -> 415 type -> mock gate (200 generic body + demo_notice, one mock_rejection audit event) -> provenance/duplicates/CLIP/claim/fuse -> report + check_results + file at <uploads_dir>/<account_id>/<report_id>.<ext>. Response keys exactly report_id/incident_probs/severity_probs/top_severity/verdict/reasons/confidence/needs_review. Check modules called as module attributes for instrumented order tests; encoder= seam defaults to live. File field accepts photo/file/image aliases; claim accepts claim_text/claim. Finding for 2.4/2.5: every committed image fixture is mock-listed, so happy-path tests must generate novel bytes.
- Status: PROVISIONAL

### Task 2.3 tests, attempt 1
- Objective: upload and processing pipeline tests (swarm role C)
- Touched: none (test-only brief)
- Created: lite/tests/test_upload.py
- Tests: python -m pytest lite/tests/test_upload.py -q -- 5 passed, 4 failed
  (all 4 fail inside implementer code: NameError "fusion" not defined at
  lite/app/server/pipeline.py:179; locked path for this brief, fix is role A's)
- Test integrity: no locked-path edits; no code under test mocked
  (spies wrap and call through); stub CLIP encoder via create_app
  clip_encoder seam only; full suite not green due to the above bug
- Dependencies: none added
- Resources: ~55 min of 60 budget; CPU only, no GPU used
- Checkpoint: lite/work/checkpoints/spec-2-2.3-tests.md
- Mocks/blocked: FanStub encoder (live path is 2.5's); one require_escalated
  socket approval used and working for TestClient
- Signals: none (implementer bug reported, not a stop signal from this brief)
- Status: PROVISIONAL

Verdict (joint 2.3): ACCEPTED (both native, inherit; paired dispatch
18:34, entries landed ~19:29-19:35 after orchestrator-relayed fix).
Gates: (1) diff clean — pipeline.py new + api.py route-only edit +
test_upload.py new + orchestrator log; user agents/* excluded; junk
removed. (2) tests run in-session (escalated path for sockets):
88 passed. (3) integrity: test file uses novel noise bytes for happy
path (all fixtures mock-listed), call-through spies for order,
exact-keys + nothing-stored asserts; the missing-`fusion`-import bug
the pair surfaced was fixed in code. (4) honesty: stub encoder is the
brief-sanctioned fast surface, live path deferred to 2.5; mock gate
is the spec-defined mock. (5) both entries complete. Swarm note:
cross-builder bug catch worked — test side failed loudly on
implementer code, orchestrator relayed the one-line fix, no
re-dispatch needed. Mock rejection returns 200 + generic body (spec
pins the body, not the status).
Commit: (recorded after commit)

# Spec status: 3/5 ACCEPTED; open: 2.4, 2.5
- Commit 2c786ba recorded for 2.3 (4 files, working tree clean after).
- Roster: 2.4 retrieval swarm pair dispatched 2026-10-29T19:31:02-04:00 (implementer: geo.py + route extension; test-specialist: test_retrieval.py; dictated contract).

### Task 2.4 implement, attempt 1
- Objective: report retrieval endpoints (owner + shared + photos) with deterministic jitter
- Touched: lite/app/server/api.py (edited: imports, claim hook in analyze, retrieval_router with 5 routes, router include)
- Created: lite/app/server/geo.py (display_point seeded by report id, jitter bounds via loader, 111320 m/deg with cos(lat) lng scaling)
- Tests: python -m pytest lite/tests -q --ignore=lite/tests/test_retrieval.py -- 88 passed; lite/tests/test_retrieval.py (concurrent builder's file, run only, never read/edited) -- 6 passed
- Test integrity: no locked-path edits; no test written or edited; existing upload/auth file-count assertions preserved (no new files under uploads_dir)
- Dependencies: none added
- Resources: within 60-min budget; CPU only, stubbed encoder probe
- Checkpoint: lite/work/checkpoints/spec-2-2.4-impl.md
- Mocks/blocked: none; sandbox blocked sockets for TestClient tests (WinError 10013), so verification used one legitimate require_escalated approval per AGENTS.md 3
- Notes: claim_text persists in lazily created report_claims aux table (first-wins, FK cascade) since committed schema has no claim column and upload file counts are asserted exact; accepted = has check_results row; owner non-member reads 404; no email/exact-coords/paths serialized (exact key sets per brief)
- Signals: none
- Status: PROVISIONAL

### Task 2.4 tests, attempt 1
- Objective: report retrieval tests (spec-2 2.4, tests half)
- Touched: none (no production files)
- Created: lite/tests/test_retrieval.py (6 tests: owner exact keys + list isolation; other-account 403/404 + shared access; forbidden-field sweep + display stability; photo bytes + anonymous 401; mock-rejected 404s; accepted-only shared surfaces)
- Tests: python -m pytest lite/tests/test_retrieval.py -q -- 6 passed; python -m pytest lite/tests -q -- 94 passed
- Test integrity: no locked-path edits; one helper bug (wrong-recipient mail token) fixed in the new test file, not in code; implementation verified as landed by the concurrent implementer (geo.py + api.py), never written by this role
- Dependencies: none added (stdlib + PIL/fastapi already pinned)
- Resources: ~25 min of 60 budget; CPU only, stubbed CLIP encoder, no GPU used
- Checkpoint: lite/work/checkpoints/spec-2-2.4-tests.md
- Mocks/blocked: stubbed CLIP encoder via create_app clip_encoder seam (fast; live path is 2.5's); one legitimate require_escalated approval for sandbox-blocked sockets (WinError 10013)
- Signals: none
- Status: PROVISIONAL

Verdict (joint 2.4): ACCEPTED (both native, inherit; paired dispatch
19:31, entries landed ~20:32).
Gates: (1) diff clean — geo.py new + api.py route-only edit +
test_retrieval.py new + orchestrator log; user agents/* excluded.
(2) tests run in-session (escalated path for sockets): 94 passed.
(3) integrity: new test file only, exact owner/shared key sets,
forbidden-field sweep incl. exact-float coords, jitter stability,
photo round-trip, mock-rejected 404s; helper bug fixed in own file.
(4) honesty: stub encoder is the sanctioned fast surface, live path
is 2.5's; no email/coords/paths in any response per sweep test.
(5) both entries complete. Extra orchestrator gate: live
register/upload-with-claim/delete probe (throwaway, removed after)
confirmed claim row stored then fully cascaded (0 claims/reports/
accounts, 1 deletion audit) — the aux-table design holds.
Swarm note: implementer wait-registry hiccup (target_missing on
wait) did not stop its work — files/checkpoint all landed; pairing
held by disjoint paths.
Commit: (recorded after commit)

# Spec status: 4/5 ACCEPTED; open: 2.5
- Commit 53a1fd9 recorded for 2.4 (4 files, working tree clean after).

### Task 2.5 implement, attempt 1
- Objective: end-to-end smoke (stubbed in-suite test + one live-model run)
- Touched: none (no app code changes)
- Created: lite/tests/test_e2e_smoke.py
- Tests: python -m pytest lite/tests -q -- 95 passed (94 prior green + 1 new)
- Test integrity: no locked-path edits; new test only; novel noise JPEG generated in-memory (no fixture used, all fixtures mock-listed); stub via create_app clip_encoder seam; failures fixed in code (none -- new test passed after one sandbox approval, no test edits)
- Dependencies: none added
- Resources: approx 30 min of 90 budget; one legitimate require_escalated approval for TestClient sockets (sandbox blocks socketpair/listen with WinError 10013; pre-existing TestClient tests fail identically without it)
- Checkpoint: n/a (short task; entry only)
- Mocks/blocked: Part A uses FanStub encoder (deterministic stub, allowed by brief); Part B live openai/clip-vit-base-patch32 from lite/data/artifacts/ (cached, no download)
- Part B live run (throwaway script outside repo, deleted after; tmp dirs under system temp):
  - device=cpu (cpu_fallback=True; torch.cuda.is_available()=False; config requested cuda, fell back to CPU)
  - model openai/clip-vit-base-patch32 rev 3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268, load 0.5 s (cached weights)
  - app_create 5.59 s, register 0.08 s, verify 0.01 s, login 0.12 s
  - upload response 0.72 s (includes live CLIP inference on novel 64x64 noise JPEG via POST /analyze with location+consent)
  - report read-back 0.013 s via GET /reports/{id}
  - verdict label=needs-review, reasons=['claim_mismatch'], confidence=0.8373, needs_review=True
  - incident_probs top car_crash 0.8373; severity top minor 0.6328
  - No accuracy claim is made (single novel-noise run).
- Signals: none
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit).
Gates: (1) diff clean — 1 new test file only plus orchestrator log;
user agents/* excluded. (2) tests run in-session (escalated path
for sockets): 95 passed. (3) integrity: new test only, novel noise
bytes, stub seam, endpoint values cross-checked against direct
spec-1 calls. (4) honesty: Part B recorded as a single observed
live run with device/timings/verdict and explicit no-accuracy-claim;
suite coverage rests on the stubbed Part A per spec. (5) log entry
complete.
Commit: (recorded after commit)

# Spec status: 5/5 ACCEPTED; open: none

# Spec completion report — Lite spec 2 (server)
- Objectives: 2.1 schema+stores+CLI (273ad20), 2.2 accounts+auth
  (bddcac7, incl. orchestrator-pinned server deps), 2.3
  upload+pipeline (2c786ba, swarm pair), 2.4 retrieval (53a1fd9,
  swarm pair), 2.5 e2e smoke (commit below). All ACCEPTED; no mocks
  beyond the spec-defined mock safety gate and brief-sanctioned
  stubbed encoders (live path observed once in 2.5 Part B).
- Files: lite/app/server/{db,auth,mail,api,pipeline,geo}.py,
  expanded cli.py, lite/tests/test_{db,auth,upload,retrieval,
  e2e_smoke}.py.
- Tests: python -m pytest lite/tests -q -> 95 passed, run in-session
  (escalated path for TestClient sockets; default sandbox denies
  socket creation — environment note for all future TestClient
  gates).
- Retries: none (2.3 needed an orchestrator-relayed one-line import
  fix inside attempt 1; no re-dispatch).
- Wall time: 16:22 (2.1 dispatch) to ~20:40 (2.5 verdict).

<!-- END-OF-LOG -->
