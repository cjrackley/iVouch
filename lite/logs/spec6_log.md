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
- Next: 6.6 Saved places (backend + page) - Save dependency first.

<!-- END-OF-LOG -->
