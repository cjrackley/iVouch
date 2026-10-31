# Lite Spec 6 Log — Native App Polish and Endpoint Coverage

## Spec start

- Date: 2026-10-31 (session continuation).
- Session model/effort: unobserved.
- Dispatch: native (muse.subagent_spawn; inherit). Swarm splits only
  per user trial approval (prior verdicts: SUCCESS where converged).
- Baseline: `git status --short` shows only `?? lite/specs/spec-6-polish.md`
  (user-authored spec file, pre-existing user work — excluded from all
  builder diff gates, never committed as builder work; specs/** is
  protected in any case). Lite specs 0-5 all ACCEPTED (commits f9dbad7,
  2ee8c58, 6f78e7b, f1e5b93). Suite at 167 passed.
- Human inputs: none for the restyle and route fixes. OAuth client
  credentials (Apple/Google, 6.9) would be a human input only if the
  user approves those buttons; Lite has none today.
- Scope guard: Lite work touches only files under `lite/`. No npm, no
  JS framework. Every page except `/map` renders without JavaScript
  (spec 3.3 still holds). No exact coordinates, emails, or file paths
  in new pages/payloads; mini-maps use jittered display points.
- Approval-gated items (NOT started until user approves each): 6.6
  saved places page, 6.7 feed page, 6.8 other-user profiles,
  6.10 search + notifications, 6.9 OAuth buttons + forgot password,
  6.5 title field + category selector, 6.4 vouches/comments list +
  Vouch/Save/Share/Edit/Delete actions, 6.3 floating search bar +
  vouch count + Save toggle on map sheet. Default: restyle only.
- Plan: (1) user decisions on approval items; (2) 6.1 design system;
  (3) page restyles in spec order (map -> detail -> upload ->
  account -> login/signup); (4) 6.2 orphan audit last.
- Order adjustment (Save dependency): 6.6 backend (saves table +
  save/unsave endpoints) ships as part of the 6.6 brief BEFORE 6.3,
  because the approved map-sheet Save toggle and detail Save sync
  with /saved. Vouch/comment tables + title/category columns are
  owned by the 6.4/6.5 briefs (first users); feed reads vouch
  counts after 6.4 lands. Schema changes recreate the database per
  spec 2 (never migrations); seed/test data follows the spec-2
  recreate path.

## User decisions (2026-10-31, request_user_input)

- New pages: ADD Saved (6.6) + Feed (6.7). NOT approved: other-user
  profiles (6.8 `/profile/{id}`), search + notifications (6.10).
  Consequence: no `/profile/{id}` route; feed avatar rows link
  nowhere (no profile pages); feed shows only the segments that work
  without follows (For You | Nearby); tab bar holds Feed + Saved
  tabs; header has no search/bell.
- Interactions: ALL approved. Vouch/Save/Share + comments list on
  detail, owner Edit/Delete, upload title field + category selector.
- Login: restyle ONLY. No Apple/Google buttons (no credentials),
  no Forgot-password link (no reset flow).
- Account (6.8) scope reading: own profile only, no Edit Profile,
  no name/bio/avatar editing, no Following stat, no Activity tab
  (those were 6.8 approval items the user did not approve).
  Saved stat + Saved tab ship as part of the approved saved
  feature. Delete account + Admin link + verified state stay.

## Taste-skill note

- `bundled:taste` read before frontend work. It is negative
  constraints only; spec 6 explicitly mandates Inter, gradients,
  and radii, so the user-authored spec wins everywhere they
  conflict. Briefs carry this precedence.

- Roster: 6.1 design system dispatched 2026-10-30T21:44:34-04:00
  (native, inherit).

### Task 6.1 implement, attempt 1
- Objective: global design system (every page)
- Touched: lite/app/server/static/style.css (rewritten as variable design system), lite/app/server/templates/base.html (layout shell)
- Created: lite/tests/test_design_system.py
- Tests: python -m pytest lite/tests -q -- 179 passed (167 prior + 12 new), confirmed by orchestrator in-session run (escalated path for sockets)
- Test integrity: no locked-path edits; log untouched by builder
- Dependencies: none added; plain CSS only
- Resources: ~25 min of 60 budget
- Checkpoint: lite/work/checkpoints/spec-6-6.1.md
- Mocks/blocked: none; one legitimate require_escalated approval for sockets (WinError 10013)
- Decisions: :root holds every spec value; tab bar Map/Create/Profile only (no Feed/Saved until 6.7/6.6); zero script tags in base.html; pure HTML+CSS shell
- Manual checks (no browser in env): press-feedback states and theme consistency by code inspection; on-device feel stays a demo manual check
- Signals: none
- Status: PROVISIONAL

Verdict (6.1): ACCEPTED (native, inherit).
Gates: (1) diff clean - style.css + base.html + new test +
orchestrator log. (2) 179 passed run in-session. (3) 12 new
grep-style tests (variables, no literals, smoothing, no Times/#000,
44px buttons + states); wording/locked suites green. (4) honesty:
manual checks logged as inspection, no browser claims. (5) entry
complete.
Commit: 6.1 recorded below.

# Spec status: 1/10 ACCEPTED (6.1); open: 6.6, 6.3, 6.4, 6.5, 6.7, 6.8, 6.9, 6.10, 6.2
- Roster: 6.6 Saved places dispatched 2026-10-30T22:58:58-04:00
  (native, inherit).

### Task lite-spec-6 6.6 implement, attempt 1
- Objective: 6.6 Saved places (backend + page), shipping before 6.3/6.4
- Touched: db.py (saves table + 4 helpers); pages.py (GET /saved, POST /saved, POST /saved/{id}/unsave + helpers); base.html (Saved tab); test_design_system.py (unlocked-only tab-set extension)
- Created: templates/saved.html; tests/test_saved.py (9 tests)
- Tests: python -m pytest lite/tests -q -- 188 passed (179 prior + 9 new), confirmed by orchestrator in-session run (escalated path for sockets)
- Test integrity: unlocked edit minimal (Saved in, Feed still asserted absent); all other assertions kept
- Dependencies: none added (stdlib sqlite3, existing FastAPI/Jinja2, style.css variables)
- Resources: within 90-min budget; FanStub CLIP seam reused; no network
- Checkpoint: lite/work/checkpoints/spec-6-6.6.md
- Mocks/blocked: none; ONE require_escalated approval for sockets (WinError 10013, confirmed environmental)
- Decisions: saves table via spec-2 recreate path (IF NOT EXISTS, no migration, SCHEMA_VERSION untouched); save needs accepted report (404 otherwise); unsave no-op success; card title = claim text w/ incident-type fallback; List|Map toggle links; server-rendered notice instead of toast (no new script tag); no api.py change needed
- Signals: none
- Status: PROVISIONAL

Verdict (6.6): ACCEPTED (native, inherit).
Gates: (1) diff clean - db.py + pages.py + base.html + unlocked
test extension + saved.html + test_saved.py + orchestrator log.
(2) 188 passed run in-session. (3) 9 new tests (save/unsave,
sync, empty state, login gate, isolation, card links,
shared-fields-only); unlocked diff verified minimal. (4) honesty:
no accuracy claims; no browser claims. (5) entry complete.
Commit: 6.6 recorded below.

# Spec status: 2/10 ACCEPTED (6.1, 6.6); open: 6.3, 6.4, 6.5, 6.7, 6.8, 6.9, 6.10, 6.2
- Roster: 6.3 map restyle dispatched 2026-10-31T02:04:57-04:00
  (native, inherit).

### Task 6.3 implement, attempt 1
- Objective: map page restyle + bottom sheet
- Touched: templates/map.html (restyled); pages.py (map_page passes csrf_token + saved_ids)
- Created: tests/test_map_restyle.py (6 page tests)
- Tests: python -m pytest lite/tests -q -- 194 passed (188 prior + 6 new), confirmed by orchestrator in-session run (escalated path for sockets)
- Test integrity: no locked-path edits; spec-5 map/wording/design suites green unchanged
- Dependencies: none added (MapLibre 5.6.0 pinned CDN + OpenFreeMap only)
- Resources: within 90-min budget; FanStub seam only
- Mocks/blocked: none; ONE require_escalated approval for sockets
- Decisions: sheet shows incident type (title is 6.5's work, approved but not yet built - 6.5 brief switches the sheet to title); vouch count omitted from sheet (stays out: approved interactions cover vouch actions/counts on detail+feed, not the map sheet); coincident pins get Prev/Next pager; Recenter falls back to default view on denied geolocation
- Correction to builder note: title field (6.5) IS user-approved, contrary to the entry's "(6.6 unapproved)"-style remark; sequencing only
- Signals: none
- Status: PROVISIONAL

Verdict (6.3): ACCEPTED (native, inherit).
Gates: (1) diff clean - map.html + pages.py + new test file +
orchestrator log. (2) 194 passed run in-session. (3) 6 new page
tests (sheet fields, View Details link, Save form targets,
spec-5 strings intact, no search bar); scan confirms exactly the
pinned script src + one inline block. (4) honesty: no browser
claims. (5) entry complete.
Commit: 6.3 recorded below.

# Spec status: 3/10 ACCEPTED (6.1, 6.6, 6.3); open: 6.4, 6.5, 6.7, 6.8, 6.9, 6.10, 6.2
- Roster: 6.4 detail dispatched 2026-10-31T03:15:22-04:00
  (native, inherit).

### Task 6.4 implement, attempt 1
- Objective: 6.4 Report detail page (backend + restyle)
- Touched: db.py (vouches + comments tables, helpers); api.py (update_claim_text helper only); pages.py (detail context, vouch/unvouch, comments post/list, owner edit-claim, owner delete, dual form/JSON); shared.html, report.html (rewritten restyle)
- Created: tests/test_detail.py (11 tests)
- Tests: python -m pytest lite/tests -q -- 205 passed (194 prior + 11 new), confirmed by orchestrator in-session run (escalated path for sockets)
- Test integrity: no locked-path edits; JSON retrieval shapes untouched; owner 403 suite green
- Dependencies: none added
- Resources: ~50 min of 90 budget; FanStub seam only
- Mocks/blocked: none; ONE require_escalated approval for sockets
- Decisions: vouch toggle idempotent (one per account); comments plain-text escaped, capped; edit = claim text only (title is 6.5); delete reuses confirm-once pattern; Share = navigator.share in the one inline script + URL-text fallback; mini-map at jittered display point
- Signals: none
- Status: PROVISIONAL

Verdict (6.4): ACCEPTED (native, inherit).
Gates: (1) diff clean - db.py + api.py + pages.py + both
templates + new test file + orchestrator log. (2) 205 passed run
in-session. (3) 11 new tests (both pages, 403, jittered
mini-map, vouch toggle/counts, comment escape/caps, Save sync,
owner-only edit/delete enforced, Share present). (4) honesty:
template scan clean (display_* are jittered points; email line
is the required data-use notice). (5) entry complete.
Commit: 6.4 recorded below.

# Spec status: 4/10 ACCEPTED (6.1, 6.6, 6.3, 6.4); open: 6.5, 6.7, 6.8, 6.9, 6.10, 6.2
- Roster: 6.5 upload dispatched 2026-10-31T03:22:36-04:00
  (native, inherit).

### Task 6.5 implement, attempt 1
- Objective: 6.5 Upload page restyle + title/category
- Touched: api.py, db.py (title+category columns), pages.py, templates/upload.html, map.html, shared.html, report.html (title propagation)
- Created: tests/test_upload_restyle.py (6 tests)
- Tests: python -m pytest lite/tests -q -- 211 passed (205 prior + 6 new), confirmed by orchestrator in-session run (escalated path for sockets)
- Test integrity: no locked-path edits; first attempt broke 4 frozen exact-keys JSON tests by adding title/category to frozen bodies and correctly rescoped to incidents-properties + DB reads instead of weakening asserts
- Dependencies: none added
- Resources: within 90-min budget; FanStub seam only
- Mocks/blocked: none; ONE require_escalated approval for sockets
- Decisions: title required in form ([Post] gating + required attr), optional server-side with claim-text fallback (locked suites POST title-less uploads); frozen JSON contracts byte-identical; category display-only, separation test proves CLIP type unaffected; centralized display_title helper with claim/incident fallback (saved cards included)
- Env note: pre-existing lite/data/ivouch.db (gitignored dev data) predates the new columns - title writes need it recreated (delete file, spec-2 recreate path); reads fall back. Fresh-checkout/demo runs use fresh DBs and are unaffected.
- Signals: none
- Status: PROVISIONAL

Verdict (6.5): ACCEPTED (native, inherit).
Gates: (1) diff clean - api.py + db.py + pages.py + 4 templates
+ new test file + orchestrator log. (2) 211 passed run
in-session. (3) 6 new tests (sheet structure, gating,
persistence, category separation, consent intact, lat/lng not
address, title propagation + fallback). (4) honesty: upload scan
clean (single inline script, consent intact). (5) entry complete.
Commit: 6.5 recorded below.

# Spec status: 5/10 ACCEPTED (6.1, 6.6, 6.3, 6.4, 6.5); open: 6.7, 6.8, 6.9, 6.10, 6.2
- Next: 6.7 feed (approved; For You | Nearby only, no follows/profiles).

<!-- END-OF-LOG -->
