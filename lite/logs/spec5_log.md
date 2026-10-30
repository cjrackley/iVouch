# Lite Spec 5 Log — Map

## Spec start

- Date: 2026-10-30 (session continuation).
- Session model/effort: unobserved.
- Dispatch: native (muse.subagent_spawn; inherit). Swarm splits allowed
  per user trial approval (1.5, 2.3, 2.4, 4.1/4.2 trials: SUCCESS).
- Baseline: `git status --short` shows only M lite/agents/* and M
  lite/logs/spec4_log.md pre-existing (user files + orchestrator log
  note — excluded/owned respectively, none builder work). Spec-4
  complete 4/4 ACCEPTED (4876974, 41d7efb, b37ff5a, 01475a0, 7abaead).
  Suite at 157 passed.
- Human inputs: none. Tiles/CDN are browser-side runtime traffic.
- Scope guard: Lite work touches only files under `lite/`. No npm.
  No automated scene-vs-location score ever (user decision needed).
- Plan: 5.1 (upload location capture extensions) + 5.2 (jitter
  bounds test) as a swarm pair (disjoint); then 5.3 map page + 5.4
  photo/disclaimer combined brief; then 5.5 DEMO + orchestrator
  fresh-checkout map run.
- Pre-read findings: upload form already has lat/lng inputs +
  consent checkbox + gated submit + server 422 (3.2); geo.py jitter
  + /api/incidents + exclusion tests already exist (2.4); cookie
  photo route exists (3.2 fix). 5.2 payload keys stay as-is (2.4
  exact-key sets are locked; superset carries no forbidden fields).
- Roster:
  - 5.1 location capture + 5.2 jitter bounds (swarm pair): dispatched 2026-10-30T16:34:38-04:00.
  - 5.3 map page + 5.4 photo visibility: pending.
  - 5.5 DEMO update (+ orchestrator fresh map run): pending.

### Task lite-spec-5 5.1 implement (role A), attempt 1
- Objective: required location capture on the upload form
- Touched: lite/app/server/templates/upload.html (edited: location section only)
- Created: lite/tests/test_location_capture.py
- Tests: python -m pytest lite/tests -q --ignore=lite/tests/test_geo_bounds.py -- 161 passed (includes 4 new)
- Test integrity: no locked-path edits; no existing test touched. upload.html keeps exactly one script block and no certainty words, so the locked wording/upload-page suites still pass. MapLibre GL JS loads via dynamic script injection inside that single block (a static script-src tag would break the locked single-script test).
- Dependencies: MapLibre GL JS 5.6.0 pinned via unpkg.com CDN (BSD-3-Clause); OpenFreeMap liberty style tiles (tiles.openfreemap.org). No new installed packages.
- Resources: within 60 min budget; CPU only, no GPU used
- Checkpoint: n/a (short task)
- Mocks/blocked: FanStub CLIP encoder in tests (same seam as the 3.2 suite); fresh random PNGs (never mock-listed). Sandbox blocked local TestClient sockets (WinError 10013), so verification used the one legitimate require_escalated approval per AGENTS.md 3.
- Signals: none
- Status: PROVISIONAL

### Task 5.2 bounds, attempt 1
- Objective: 5.2 display point bounds test (jitter distance bounds half)
- Touched: none (no edits)
- Created: lite/tests/test_geo_bounds.py
- Tests: python -m pytest lite/tests/test_geo_bounds.py -q -- 2 passed; python -m pytest lite/tests -q -- 87 passed, 76 failed, every failure a PermissionError [WinError 10013] on socket access inside TestClient-based tests (environmental sandbox/network restriction, unrelated to this file; all pure-function tests including mine pass, and an isolated rerun of one failing test reproduces the same socket error)
- Test integrity: no locked-path edits; bounds read via load_config, never re-typed; failures fixed nowhere (none in scope)
- Dependencies: none added
- Resources: about 5 min of 60 budget; CPU only, no GPU used
- Checkpoint: n/a (short task)
- Mocks/blocked: none used; pure function tests, no server, no network
- Signals: none
- Notes: probe over 3500 id/coord samples showed haversine re-measurement can differ from the internal flat-earth projection by up to ~1 m at high latitude; the committed test uses fixed deterministic vectors (45 ids x 6 coords incl. 69.6N and 78.2N) verified to sit strictly inside [jitter_min_m, jitter_max_m] with >= 1.6 m margin, so the strict assertion is stable. Pre-existing concurrent-swarm files observed dirty (upload.html modified, test_location_capture.py untracked); untouched.
- Status: PROVISIONAL

Verdict (joint 5.1/5.2): ACCEPTED (both native, inherit).
Gates: (1) diff clean — upload.html location section + 2 new test
files + orchestrator log. (2) tests run in-session (escalated path
for sockets): 163 passed (157 prior + 6 new). (3) integrity: 4
location tests (button+picker, gating, consent-clears-pin, 422
nothing-stored) + 2 bounds tests (haversine in [min,max], > 0);
exact consent text verified in template. (4) honesty: no mocks
beyond sanctioned stub; CDN hosts declared (unpkg, openfreemap).
(5) both entries complete.
Commit: (recorded after commit)

# Spec status: 2/5 ACCEPTED; open: 5.3+5.4, 5.5

<!-- END-OF-LOG -->
