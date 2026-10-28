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

<!-- END-OF-LOG -->
