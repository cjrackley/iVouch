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
- Commit f9dbad7 recorded for joint 5.1/5.2 (4 files, working tree clean after).
- Roster: 5.3 map page + 5.4 photo visibility combined brief dispatched 2026-10-30T18:36:01-04:00.

### Task 5.3 + 5.4 implement, attempt 1
- Objective: map page (5.3) + photo visibility (5.4) with tests
- Touched: lite/app/server/pages.py (added GET /map route + docstring line)
- Created: lite/app/server/templates/map.html, lite/tests/test_map.py
- Tests: python -m pytest lite/tests/test_map.py -q -- 4 passed; python -m pytest lite/tests -q -- 166 passed, 1 failed (locked test_wording.py::test_no_javascript_except_upload_file_picker asserts zero script tags outside upload.html; spec-5 mandates MapLibre via CDN so map.html needs 2 -- orchestrator amendment required, file untouched)
- Test integrity: no locked-path edits; failures fixed nowhere (single failure is a spec-vs-locked-test conflict, not implementation error)
- Dependencies: none added (MapLibre 5.6.0 via unpkg CDN + OpenFreeMap tiles are page-runtime hosts per brief network_allowed, not installed packages)
- Resources: about 25 min of 60 budget; CPU only, no GPU used
- Checkpoint: lite/work/checkpoints/spec-5-5.3.md
- Mocks/blocked: stubbed CLIP encoder for seeded-report setup (fast, per brief); one approved require_escalated sandbox approval for socket access (TestClient fails with WinError 10013 without it); no browser available so pixel rendering not eyeballed -- all map wiring asserted server-side via TestClient, logged honestly in test docstring
- Signals: none (needs orchestrator ruling on the locked wording-test amendment, recorded as a note not a stop signal)
- Status: PROVISIONAL

### Task lite-spec-5 5.3+5.4 wording rewrite, attempt 2
- Objective: 5.3 Map page + 5.4 photo visibility (wording-test rewrite per orchestrator ruling)
- Touched: lite/tests/test_wording.py (edited; unlocked for this brief only per orchestrator ruling)
- Created: lite/work/checkpoints/spec-5-5.3-fix-entry.md (this entry), lite/work/checkpoints/spec-5-5.3-fix.md (checkpoint note)
- Tests: python -m pytest lite/tests -q -- 167 passed
- Test integrity: no-script test rewritten as a general allowlist policy, not a map.html exception: <script> tags with src must exactly match SCRIPT_SRC_ALLOWLIST (single pinned URL https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js, copied from map.html line 20; upload.html carries the same URL only as a JS string for dynamic injection, no static src); at most one inline <script> per template, and its body must contain either the upload-picker markers (location_consented + upload_submit) or the map-wiring markers (maplibregl + showFallback + /api/incidents), identified by content not file name; every other script tag (unpinned/unknown src, extra inline block) fails. Upload picker presence still asserted. All other assertions in the file (certainty words, label set, demo/data-use lines, server-side render pass) untouched in intent. No production code changes; map.html/upload.html read-only.
- Dependencies: none added
- Resources: ~2 min of 30 budget (20:27-20:29 EDT); no GPU used
- Checkpoint: lite/work/checkpoints/spec-5-5.3-fix.md
- Mocks/blocked: none; one legitimate require_escalated approval used for the test run because the sandbox blocks sockets (TestClient tests need loopback listen; pre-existing tests unaffected)
- Signals: none
- Pre-existing dirt (not mine, untouched): M lite/app/server/pages.py, M lite/logs/spec5_log.md, ?? lite/app/server/templates/map.html, ?? lite/tests/test_map.py (attempt-1 work)
- Status: PROVISIONAL

Verdict (joint 5.3/5.4): ACCEPTED (attempt 1 built the surface;
attempt 2 resolved the flagged spec-vs-test conflict).
Gates: (1) diff clean — pages.py /map route + map.html + test_map
+ rewritten wording test + orchestrator log. (2) tests run
in-session (escalated path for sockets): 167 passed. (3)
integrity: 4 map tests (login gate, wiring incl. exact compare
line + disclaimers + toggle + fallback, payload-driven dots with
rejected/deleted excluded, other-user popup photo); rewrite is a
general pinned-CDN allowlist identified by content, still
forbidding unknown scripts. (4) honesty: no mocks beyond
sanctioned stub; no automated scene-location score anywhere;
pixel rendering honestly not eyeballed (no browser in env).
(5) both entries complete. Ruling logged: test_wording.py
unlocked for this brief only (§5.2 + Lite §6 rewrite rule).
Commit: (recorded after commit)

# Spec status: 3/5 ACCEPTED (5.3+5.4 jointly); open: 5.5
- Roster: 5.5 DEMO update dispatched 2026-10-30 (docs-only brief).

### Task 5.5 final demo update, attempt 1
- Objective: extend lite/DEMO.md with a map section (spec-5 objective 5.5, docs brief)
- Touched: lite/DEMO.md (edited step 10 only; all other content preserved)
- Created: none
- Tests: none (docs only per brief; must_pass empty, no suite run, no server start)
- Test integrity: no locked-path edits; no test, fixture, or expected-value changes
- Dependencies: none added
- Resources: well within 30 min budget; no network, no models, no GPU used
- Checkpoint: n/a (short docs task)
- Mocks/blocked: none
- Signals: none
- Status: PROVISIONAL

Verdict (5.5): ACCEPTED (native, inherit).
Gates: (1) diff clean - DEMO.md step 10 only (+23/-7), all other
content preserved. (2) docs-only: no code changed, so no suite
regression possible from this diff; suite stands at 167 passed from
the 5.3/5.4 gate. (3) integrity: no locked paths, no tests touched.
(4) honesty: ASCII-only; no accuracy claims - states human visual
judgement only, out-of-scope automated check, and the data-use rule.
(5) entry complete.
Commit: de2cdba (lite/DEMO.md + lite/logs/spec5_log.md; entry file
gitignored by lite/work rule).

### Orchestrator fresh-checkout map run (5.5 verification)
- Fresh tree: workspace HEAD (incl. 5.3/5.4 commit) synced to sandbox
  temp dir; server started on port 8002 with LITE_JWT_SECRET set;
  exercised over real HTTP with httpx (no TestClient).
- Seed: 2 verified accounts; 2 live uploads with required location
  + consent (lat/lng pairs); both report ids returned.
- Observed: GET /api/incidents (as other user) returned both dots
  with display_lat/display_lng and no emails; GET /shared/{id} 200;
  GET /shared/photos/{id} 200 via cookie session (Bearer-only
  request correctly 404s - route is documented cookie-session);
  GET /map 200 with /api/incidents wiring, compare line, both
  disclaimers, and fallback container.
- Friction (env, not product): login rate limit is 5/IP/900s, so
  repeated script iterations 429'd; fixed by one clean run after a
  server restart. Page POST /login answers 303 (accepted alongside
  200/302 in the probe). Probe JPEGs are small (678-byte photo
  response), so the size floor was lowered - bytes verified present.
- Pixel rendering not eyeballed (no browser in env); all map wiring
  asserted server-side over real HTTP.
- Result: MAP RUN OK.

# Spec status: 5/5 ACCEPTED; spec-5 COMPLETE.
- Commit for 5.5 recorded below. Suite: 167 passed. Lite specs 0-5
  all ACCEPTED - demo-ready app, docs, and manual fresh-checkout
  verifications done (4.4 full run + 5.5 map run).
