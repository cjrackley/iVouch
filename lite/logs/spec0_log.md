# Lite Spec 0 Log — Foundations

## Spec start

- Date: 2026-10-28 (session start, America/New_York).
- Session model/effort: unobserved (no Muse tool reports them; user sets at launch).
- Dispatch: native for all spec-0 briefs (muse.subagent_spawn; builders inherit session model/effort).
- Baseline: `git status --short` clean (empty output); `git log` head 9fe4c73 (lite commit). No pre-existing dirty files.
- Python: 3.11.1 (spec prefers 3.12; 3.11 permitted with this note, not a stop).
- Human inputs: none required for spec-0. GPU presence checked, not assumed; missing GPU means CPU inference with an ENV-BLOCKED note, work continues. Docker not required.
- Scope guard: Lite work touches only files under `lite/` (plus orchestrator commits). Nothing outside `lite/` is edited.
- Plan: one builder at a time; single implementation brief with tests included per objective (tiny-scaffolding allowance, lite orchestrator sec 2). Objectives 0.1, 0.2, 0.3, 0.4 in order.
- Roster:
  - 0.1 layout+tooling implement: to be dispatched.
  - 0.2 config loader implement: pending.
  - 0.3 synthetic fixtures implement: pending.
  - 0.4 CLIP smoke implement: pending.

### Spec 0.1 implement, attempt 1
- Objective: 0.1 Layout and tooling (lite/specs/spec-0-foundations.md)
- Touched: none (no existing files edited)
- Created: lite/app/__init__.py, lite/app/server/__init__.py,
  lite/app/checks/__init__.py, lite/app/cli.py (placeholder main()->0;
  spec 2 builds it out), lite/tests/__init__.py,
  lite/tests/test_layout.py, lite/requirements.txt, .gitkeep in
  lite/data/artifacts/, lite/data/uploads/, lite/data/mail/,
  lite/work/checkpoints/
- Tests: python -m pytest lite/tests -q -- 5 passed (dirs/files exist,
  requirements == pins, CLI imports cleanly, Python >=3.11 gate)
- Test integrity: test file is new per the brief (no locked-path edits,
  no edits to existing tests, no skips; version gate uses print-note,
  not skip)
- Dependencies (pinned, verified on PyPI 2026-10-28, all allow 3.11):
  fastapi==0.162.0 (MIT), pillow==13.0.0 (MIT-CMU), piexif==1.1.3
  (MIT), pyyaml==6.0.3 (MIT), imagehash==4.3.2 (BSD-2-Clause),
  transformers==5.21.0 (Apache-2.0), torch==2.15.0 (permissive
  Apache-2.0/BSD/MIT composite), pytest==9.2.0 (MIT). No AGPL/GPL.
- Resources: ~33 min of 60 budget; Python 3.11.1 (spec prefers 3.12,
  3.11 permitted with this note); CPU only, no GPU used
- Checkpoint: lite/work/checkpoints/spec-0-0.1.md
- Mocks/blocked: none (mocks_allowed was empty; none used)
- Notes: git check-ignore confirms lite/data/{artifacts,uploads,mail}
  and lite/work/checkpoints are ignored (root data/ line 20, work/
  line 75); .gitignore untouched. lite/config.yaml NOT created (0.2
  owns it). First pip install appeared stuck under default sandbox;
  terminated and retried via require_escalated approval -> pytest 9.2.0
  installed. Stray repo-root pip temp dirs (pip-unpack-*/, tmp*) are
  from this session's installs; left in place per no-delete rule for
  the orchestrator to clear. write_file returned os error 183 on first
  write into each new dir; immediate retry succeeded, tree verified.
- Signals: none
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit; wall time ~33 min:
dispatched 2026-10-28T15:29:03-04:00, entry landed 16:02).
Gates: (1) diff clean — new files only under lite/app/, lite/tests/,
lite/requirements.txt plus orchestrator log; no deletions, no
locked-path edits, no secrets, no weights, nothing over 5 MB;
data/work .gitkeep files correctly git-ignored; stray pip temp dirs
at repo root (wheel leftovers, confirmed junk) removed by
orchestrator. (2) tests run in-session: python -m pytest lite/tests
-q -> 5 passed. (3) test-integrity: new test file, real asserts, no
skips or hardcoded answers. (4) honesty: no mocks used; criteria
genuinely pass. (5) log entry complete. Python 3.11.1 recorded as
permitted (spec floor 3.11).
Commit: (recorded after commit)

# Spec status: 1/4 ACCEPTED; open: 0.2, 0.3, 0.4
- Commit 097988c recorded for 0.1 (8 files, working tree clean after).

### Spec 0.2 implement, attempt 1
- Objective: 0.2 Configuration (lite/specs/spec-0-foundations.md)
- Touched: none (no existing files edited; locked lite/tests/test_layout.py
  and lite/requirements.txt untouched, confirmed by empty git diff)
- Created: lite/config.yaml, lite/app/config.py, lite/tests/test_config.py
- Tests: python -m pytest lite/tests -q -- 8 passed (5 prior layout tests
  plus 3 new config tests, all green)
- Test integrity: test file is new per the brief (no locked-path edits,
  no edits to existing tests, no skips, no hardcoded answers, no mocks;
  negative cases derive from a copy of the shipped config)
- Dependencies: pyyaml==6.0.3 (MIT, already pinned in
  lite/requirements.txt; no new packages, no pin changes). Note: pyyaml
  was missing from the default Python 3.11.1 environment at session
  start; direct pip install failed on proxy timeouts, and a retry via
  the alternate Python 3.12 interpreter's pip surfaced yaml 6.0.3 in
  the default interpreter (exact mechanism unverified). Suite now runs
  green against yaml 6.0.3. No AGPL/GPL.
- Resources: ~40 min of 60 budget; Python 3.11.1 (spec prefers 3.12,
  3.11 permitted with this note); CPU only, no GPU used
- Checkpoint: n/a (short task; checkpoint dir not in allowed_paths)
- Mocks/blocked: none (mocks_allowed was empty; none used). Transient
  PyPI proxy timeouts during setup; resolved, suite green.
- Notes: (1) lite/config.yaml holds every brief-named key:
  max_upload_bytes 10485760, allowed_types [jpeg, png],
  clip_model_id openai/clip-vit-base-patch32, clip_device cuda (CPU
  fallback is later-spec code, not config), incident_prompts (6 labels)
  and severity_prompts (3 labels), low_confidence_below 0.5,
  claim_mismatch_below 0.2, phash_max_distance 8, duplicate_window 30,
  policy_mock_hashes_path lite/tests/fixtures/mock_hashes.txt (fixtures
  land in 0.3), min_age 18, jwt_access_minutes 30,
  upload_cap_per_account 50, login_ratelimit_max_attempts 5,
  login_ratelimit_window_seconds 900, jitter_min_m 200,
  jitter_max_m 500, console_mail_dir lite/data/mail/,
  location_required true. Uncalibrated demo values per spec 1.
  (2) Brief asked for the "exact prompt lists from spec-1", but
  spec-1 names only the six incident labels and three severity labels,
  no literal prompt strings; prompts are label-derived demo text and
  remain editable as config changes. (3) No threshold re-typed as a
  literal outside the loader: lite/app/config.py carries only key
  names and shape checks with zero numeric literals; grep confirms
  only key names (never values) appear in code, and the test asserts
  type/label membership read via the loader. (4) Pre-existing worktree
  state: lite/logs/spec0_log.md shows modified but was not touched in
  this brief (orchestrator-owned); the three new files are the only
  diff from this task.
- Signals: none
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit; wall time ~39 min:
dispatched 2026-10-28T16:06:52-04:00, entry landed 16:45).
Gates: (1) diff clean — 3 new files only plus orchestrator log; no
locked-path edits, no secrets, small files; pip/test junk dirs removed
by orchestrator. (2) tests run in-session: 8 passed. (3) integrity:
new test file, real asserts, no skips. (4) honesty: no mocks; criteria
genuinely pass. (5) log entry complete. Orchestrator note: pyyaml was
absent from the env, so the orchestrator installed the pinned
pyyaml==6.0.3 into system python (same interpreter the suite runs on)
before gating; env setup only, no tree change.
Commit: (recorded after commit)

# Spec status: 2/4 ACCEPTED; open: 0.3, 0.4
- Commit b05de87 recorded for 0.2 (4 files, working tree clean after).

### Task 0.3 implement, attempt 1 (cont)
- Objective: synthetic fixtures (spec 0.3)
- Touched: none (reused prior-run generate.py and test_fixtures.py unchanged; nothing was broken)
- Created: lite/tests/fixtures/solid_no_exif.jpg, text_no_exif.jpg, shapes_gps.jpg, shapes_editor.jpg, shapes_q50.jpg, shapes_basic.png, mock_hashes.txt (via running the generator; ~32 KB total)
- Tests: python -m pytest lite/tests -q -- 19 passed
- Test integrity: no locked-path edits; no existing-test edits; failures: none
- Dependencies: none added (pillow==13.0.0 BSD, piexif==1.1.3 MIT, pytest==9.2.0 MIT, pyyaml==6.0.3 MIT -- pins and licences already in lite/requirements.txt per 0.1 entry)
- Resources: well within 60 min budget; Python 3.11.1 (spec prefers 3.12; 3.11 permitted with this note); Pillow default font only, fixed SEED 20261028, no timestamps embedded
- Checkpoint: lite/work/checkpoints/spec-0-0.3.md
- Mocks/blocked: none (mock_hashes.txt is the spec-1 mock safety gate input: sha256 list over benign synthetic fixtures only)
- Signals: none; note: pytest-of-camer/ artifact appeared in repo root during test run, left in place per no-delete rule
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit; first run dispatched
2026-10-28T16:47:55-04:00 went quiet with no checkpoint after 16:53 and
was stopped at ~19:04 (over budget, >2h quiet); continuation dispatched
19:04:38, entry landed same evening, 19 tests green).
Gates: (1) diff clean — lite/tests/fixtures/ (6 images ~32 KB +
mock_hashes.txt + generate.py) and lite/tests/test_fixtures.py new,
plus orchestrator log; no locked-path edits, nothing over 5 MB;
__pycache__ correctly ignored; pytest/tmp junk removed by
orchestrator. (2) tests run in-session: 19 passed. (3) integrity: new
test file with real asserts (byte-identical determinism, committed
files match generator, EXIF variants parse as claimed, hash coverage).
(4) honesty: no mocks; criteria genuinely pass. (5) log entry
complete. Orchestrator notes: (a) prior run produced generate.py +
test_fixtures.py but never generated images — likely stuck on
missing piexif/pillow installs; orchestrator installed pinned
pillow==13.0.0 + piexif==1.1.3 into the session interpreter (env
setup, no tree change) before re-dispatching. (b) Per
bundled:python-env, fresh checkouts should use a project-local .venv
(uv venv + install lite/requirements.txt); this running build stays
on the session interpreter for continuity, recorded here; spec-4
README/DEMO will document the .venv setup.
Commit: (recorded after commit)

# Spec status: 3/4 ACCEPTED; open: 0.4

<!-- END-OF-LOG -->
