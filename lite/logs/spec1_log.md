# Lite Spec 1 Log — Image Checks

## Spec start

- Date: 2026-10-28 (evening, America/New_York).
- Session model/effort: unobserved.
- Dispatch: native for all spec-1 briefs (muse.subagent_spawn; inherit).
- Baseline: `git status --short` clean; spec-0 complete 4/4 ACCEPTED
  (commits 097988c, b05de87, 8a8c88c, 4594f55, plus log-hash note
  97a1993). Suite at 20 passed. Pre-existing dirty files: none.
- Human inputs: none (spec states none). Thresholds in lite/config.yaml
  are uncalibrated demo values — recorded here; no accuracy target in
  this spec may be presented as met. Observed numbers only.
- Scope guard: Lite work touches only files under `lite/`.
- Plan: one builder at a time; single implementation brief with tests
  included per objective. Objectives 1.1, 1.2, 1.3, 1.4, 1.5 in order.
  imagehash (pinned imagehash==4.3.2) is not yet installed in the
  session interpreter — the 1.3 brief allows a pip install, or the
  orchestrator provisions it as env setup.
- Roster:
  - 1.1 files+mock-gate implement: dispatched 2026-10-28T21:31:49-04:00.
  - 1.2 provenance implement: pending.
  - 1.3 duplicates implement: pending.
  - 1.4 CLIP checks implement: pending.
  - 1.5 fusion implement: pending.

### Task spec-1 1.1 implement, attempt 1
- Objective: 1.1 File sanity and mock safety gate
- Touched: none (no existing files edited)
- Created: lite/app/checks/files.py (FileResult, check_file, mock_hash_match); lite/tests/test_files.py (7 tests, spec-0 fixtures only)
- Tests: python -m pytest lite/tests -q -- 27 passed (20 prior + 7 new); targeted lite/tests/test_files.py -- 7 passed
- Test integrity: no locked-path edits; failures fixed in code (none occurred); git status shows only the 2 new files plus pre-existing untracked residue (lite/logs/spec1_log.md, pytest-of-camer/, tmp*) which was left untouched
- Dependencies: none added (Pillow/pytest/pyyaml already pinned in lite/requirements.txt); thresholds read via load_config, never re-typed
- Resources: ~20 min of 60 budget; CPU only, no GPU used
- Checkpoint: lite/work/checkpoints/spec-1-1.1.md
- Mocks/blocked: mock_hash_match is SHA-256 against benign fixture list only, not real screening; pipeline stores no bytes on match (spec 2 wiring)
- Signals: none required; tool-use note for review: collected the finished full-suite output with muse.powershell_input on my own session instead of a fresh wait call
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit; wall time ~12 min:
dispatched 21:31:49, entry landed 21:43).
Gates: (1) diff clean — 2 new files only plus orchestrator log; no
locked-path edits, no secrets, small files; pytest junk removed by
orchestrator. (2) tests run in-session: 27 passed. (3) integrity: new
test file, real asserts on fixtures (valid pass, non-image/oversize/
truncated rejected, mock-list match flagged, no-bytes record shape).
(4) honesty: the only mock is the spec-defined mock gate, documented
as not real screening. (5) log entry complete. Tool-use note: builder
self-reports collecting finished output via muse.powershell_input on
its own session rather than a fresh wait — reminded that input calls
are for sending input/terminating only; deliverable independently
verified, so no gate impact.
Commit: (recorded after commit)

# Spec status: 1/5 ACCEPTED; open: 1.2, 1.3, 1.4, 1.5
- Commit 564c1ea recorded for 1.1 (3 files, working tree clean after).

### Task 1.2 implement, attempt 1
- Objective: provenance-lite flags (spec-1 objective 1.2)
- Touched: n/a (no existing files edited)
- Created: lite/app/checks/provenance.py, lite/tests/test_provenance.py
- Tests: python -m pytest lite/tests -q -- 37 passed (27 prior green, 10 new)
- Test integrity: no locked-path edits; no existing tests touched; EXIF synthesized in-test with piexif/Pillow, no new fixtures committed; fixtures read-only
- Dependencies: none added (Pillow/piexif already pinned in lite/requirements.txt); licences n/a
- Resources: ~5 min of 60 budget; CPU only, no GPU used
- Checkpoint: n/a (short task)
- Mocks/blocked: none
- Signals: implausibly-old cutoff defined as module constant EARLIEST_PLAUSIBLE_CAPTURE_TIME = 2000-01-01 UTC (no config key names it; no config key invented). Missing EXIF yields neutral flags (time_plausible True) and the module emits no verdict. Note: git status shows pre-existing M lite/logs/spec1_log.md (not touched by this brief) and untracked pytest-of-camer/ (not created by this brief's edits; left alone).
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit; wall time ~5 min).
Gates: (1) diff clean — 2 new files only plus orchestrator log; no
locked-path edits, small files; pytest junk removed by orchestrator.
(2) tests run in-session: 37 passed. (3) integrity: new test file,
real asserts (all EXIF variants incl. PNG/q50, synthesized
future-time case, no new fixtures committed). (4) honesty: no mocks;
flags only, module emits no verdict and missing EXIF stays neutral
per spec. (5) log entry complete. Implausibly-old cutoff as module
constant (no config key invented) is the brief-sanctioned choice.
Commit: (recorded after commit)

# Spec status: 2/5 ACCEPTED; open: 1.3, 1.4, 1.5
- Commit 6854348 recorded for 1.2 (3 files, working tree clean after).

### Task 1.3 Duplicates, attempt 1
- Objective: exact + phash near-duplicate checks over the sequence store protocol (lite-spec-1 objective 1.3)
- Touched: none (new files only; no locked-path edits)
- Created: lite/app/checks/duplicates.py, lite/tests/test_duplicates.py
- Tests: python -m pytest lite/tests -q -- 44 passed (37 prior + 7 new), all green
- Test integrity: no fixture/config/existing-test edits; one self-authored assertion corrected in-test (an unrelated query self-matches its own store row at distance 0, so the test now asserts r-original is absent and pins ["r-other"]) -- criterion strengthened, not weakened
- Dependencies: imagehash==4.3.2 (BSD-2-Clause; already pinned in lite/requirements.txt, no requirements change); transitive scipy==1.17.1 and PyWavelets==1.9.0 installed from PyPI; numpy resolved 1.24.2 -> 2.4.6 by pip as allowed (latest compatible); pillow==13.0.0 pre-existing. No AGPL/GPL/paid components.
- Resources: about 136 min of 60 budget (overrun from sandbox proxy stalls on the scipy/PyWavelets wheels; two stalled pip sessions terminated and retried per brief; PyPI index reachable throughout; retries eventually landed imagehash 4.3.2)
- Checkpoint: lite/work/checkpoints/spec-1-1.3.md
- Mocks/blocked: none
- Observed (demo numbers only, no accuracy claim): phash_max_distance=8 unchanged, config.yaml untouched (locked); shapes_editor vs committed shapes_q50 = 2, vs fresh in-test q50 re-encode = 2, vs 90% resize = 2; unrelated pairs (shapes vs solid/text fixtures) = 31-34. No distance raise needed.
- Not mine, left in place: lite/logs/spec1_log.md carries a 1-line modification I did not make; pip-unpack-*/ and pytest-of-camer/ scratch dirs observed in the repo root (no-delete rule, not removed).
- Signals: none (no NEEDS-SCOPE-CHANGE: all pairs fit the configured distance)
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit; wall time over
budget at ~136 min due to sandbox proxy stalls on wheel downloads,
not code iteration — gates judge the deliverable, which is green).
Gates: (1) diff clean — 2 new files only plus orchestrator log; pip
junk removed by orchestrator. (2) tests run in-session: 44 passed.
(3) integrity: new test file, distances read from loader, unrelated
pair excluded with margin (31-34 vs 8); the self-corrected assertion
pins exact behavior, not a weakening. (4) honesty: observed
distances reported as demo numbers, no accuracy claim; no config
change needed. (5) log entry complete. Env note: orchestrator also
installed pinned imagehash==4.3.2 (system interpreter) when builder
retries stalled; transitive numpy 1.24.2 -> 2.4.6 noted.
Commit: (recorded after commit)

# Spec status: 3/5 ACCEPTED; open: 1.4, 1.5
- Commit 6cc92ae recorded for 1.3 (3 files, working tree clean after).

### Task 1.4 implement, attempt 1
- Objective: incident/severity CLIP zero-shot plus claim similarity (spec-1 1.4)
- Touched: none (new files only)
- Created: lite/app/checks/clip_checks.py, lite/tests/test_clip_checks.py
- Tests: python -m pytest lite/tests -q -- 52 passed (44 prior green, 8 new: 6 stubbed plus 2 slow real-model, run unskipped)
- Test integrity: no locked-path edits; no existing-test edits; real-path failures fixed in code (transformers 5.21.0 get_image_features/get_text_features return BaseModelOutputWithPooling, so the live encoder reads pooler_output)
- Dependencies: none added (torch 2.15.0+cpu, transformers 5.21.0, Pillow pre-existing; CLIP snapshot openai/clip-vit-base-patch32, MIT licence, cached under lite/data/artifacts/)
- Resources: about 25 min of 60 budget; CPU fallback (cuda unavailable), no GPU used
- Checkpoint: n/a (short task)
- Mocks/blocked: FanStub/ClaimStub encoders for unit tests (spec allows); PytestUnknownMarkWarning for the slow mark (no marker registration in repo; tests still run unskipped). Note: lite/logs/spec1_log.md shows modified but was not touched by this brief; pytest-of-camer/ is a pytest tmp artifact from this run, left in place per the no-delete rule.
- Observed top-labels per fixture, real model, demo observations only, no accuracy claim (thresholds are uncalibrated demo values):
  - solid_no_exif.jpg: incident=flood 0.294, severity=severe 0.371, claim_sim=0.192
  - text_no_exif.jpg: incident=flood 0.470, severity=severe 0.627, claim_sim=0.188
  - shapes_gps.jpg: incident=none 0.677, severity=minor 0.605, claim_sim=0.244
  - shapes_editor.jpg: incident=none 0.677, severity=minor 0.605, claim_sim=0.244
  - shapes_q50.jpg: incident=none 0.527, severity=minor 0.610, claim_sim=0.249
  - shapes_basic.png: incident=none 0.577, severity=minor 0.602, claim_sim=0.253
  - Cross-check: incident top-label agrees with clip_model.classify_image on all six fixtures. Synthetic-fixture outputs say nothing about real-incident accuracy.
- Signals: none
- Status: PROVISIONAL

Verdict: ACCEPTED (dispatch native, model inherit; wall time ~25 min).
Gates: (1) diff clean — 2 new files only plus orchestrator log;
agents/* modifications are pre-existing user workflow edits, excluded;
pytest junk removed by orchestrator. (2) tests run in-session:
52 passed in 24 s (slow real-model tests ran unskipped). (3)
integrity: new test file, stubbed shapes + real-path cross-check,
labels from loader, no skips. (4) honesty: observed fixture
top-labels logged as demo observations, cross-checked, no accuracy
claim; stub encoders are the spec-allowed unit surface. (5) log entry
complete. CLIP licence recorded as MIT (model card; corrects 0.4's
honest-unknown).
Commit: (recorded after commit)

# Spec status: 4/5 ACCEPTED; open: 1.5

### Task 1.5 implement (swarm role A), attempt 1
- Objective: Fusion-lite (lite-spec-1 objective 1.5, implement half of swarm trial)
- Touched: none (new file only)
- Created: lite/app/checks/fusion.py
- Tests: python -m pytest lite/tests -q -- 52 passed (lite/tests/test_fusion.py not yet landed from concurrent builder, so this run is the full suite minus the fusion tests; contract probe inline: likely-real default, mock_match early-return, previously_submitted, low_confidence, likely-manipulated, and multi-reason accumulation all match spec)
- Test integrity: no locked-path edits; no test files written or edited
- Dependencies: none added
- Resources: well within 60 min budget; CPU only, no GPU used
- Checkpoint: n/a (single-file task; brief checkpoint path not written -- outside allowed_paths)
- Mocks/blocked: none; waiting on concurrent test builder for lite/tests/test_fusion.py final gate
- Signals: none
- Status: PROVISIONAL

### Task lite-spec-1 1.5 tests, attempt 1
- Objective: Fusion-lite tests (swarm role C, test-specialist)
- Touched: none (no edits to existing files)
- Created: lite/tests/test_fusion.py (12 tests)
- Tests: python -m pytest lite/tests/test_fusion.py -q -- 12 passed; python -m pytest lite/tests -q -- 64 passed, 2 warnings (pre-existing unknown `slow` mark in locked test_clip_checks.py; not touched)
- Test integrity: no locked-path edits; thresholds read via load_config() only, never re-typed; AllChecks built in-test from plain dicts/datetimes/real Provenance; no fixtures added; implementation (lite/app/checks/fusion.py) written concurrently by the paired builder and imported only, never stubbed or inlined
- Dependencies: none added
- Resources: ~5 min of 60 budget; fusion.py absent at start, present after one bounded 240 s wait chunk
- Checkpoint: lite/work/checkpoints/spec-1-1.5-tests.md (complete, no resume needed)
- Mocks/blocked: none
- Signals: none
- Status: PROVISIONAL

Verdict (joint 1.5): ACCEPTED (both native, inherit; dispatched
together ~16:16, both entries landed ~16:17-16:22).
Gates: (1) diff clean — exactly one new file per builder
(fusion.py implementer, test_fusion.py test-specialist), so
attribution holds by path despite concurrency; user agents/* edits
excluded; pytest junk removed by orchestrator. (2) tests run
in-session: 64 passed. (3) integrity: both sides converged on the
dictated contract first try (imports resolve, 12/12 rule tests
green); thresholds via loader; no-certainty regex test present.
(4) honesty: no mocks; reasons use "signals observed" wording only.
(5) both entries complete.
Swarm trial verdict: SUCCESS — first-try convergence in ~5 min per
side with zero reconciliation. Disjoint single-file briefs + a
dictated shared contract preserve gateability. Approved pattern for
similarly separable objectives; serial remains the fallback.
Commit: (recorded after commit)

# Spec status: 5/5 ACCEPTED; open: none

# Spec completion report — Lite spec 1 (image checks)
- Objectives: 1.1 files+mock-gate (564c1ea), 1.2 provenance (6854348),
  1.3 duplicates (6cc92ae), 1.4 CLIP checks (7c445c3), 1.5 fusion-lite
  (joint, commit below). All ACCEPTED; the only mock is the
  spec-defined mock safety gate (not real screening). Thresholds
  remain uncalibrated demo values; fixture top-labels and distances
  logged as observed numbers only, no accuracy claim.
- Files: lite/app/checks/{files,provenance,duplicates,clip_checks,
  fusion}.py (+clip_model.py from spec-0); lite/tests/test_{files,
  provenance,duplicates,clip_checks,fusion}.py.
- Tests: python -m pytest lite/tests -q -> 64 passed, run in-session.
- Retries: none needed in spec-1 (1.3 overran budget on proxy stalls
  but passed gates on attempt 1). Swarm trial on 1.5: success.
- Wall time: 21:31 (1.1 dispatch) to ~16:25 next day (1.5 verdict).

<!-- END-OF-LOG -->
