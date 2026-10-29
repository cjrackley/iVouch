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

<!-- END-OF-LOG -->
