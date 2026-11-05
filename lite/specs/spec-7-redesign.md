# Lite Spec 7 — Interface Fixes and Visual Refinement

**Why separate:** spec 6 restyled every page to a native-app look, but demo
feedback reports the app still feels unstyled in places, plus page-level
bugs the restyle exposed (dead map controls, raw probability decimals,
verify-flow dead ends, a header that ignores login state). This spec fixes
those bugs and refines the visual system. No check, API, verdict, or
fusion logic changes: display only, with raw values and API payloads
untouched.

| | |
|---|---|
| Depends on | spec-6 (pages, review/audit pages, map, saved, feed) |
| Unblocks | demo (end of Lite) |
| Execution | Sequential only — spec 8 of 8 |
| Stack | FastAPI + Jinja2 templates, `static/style.css`, minimal vanilla JS, MapLibre GL JS via CDN (spec 5) |

## Human inputs

None. All design direction comes from the user-authored demo-feedback
list: smaller buttons, restrained gradient use, small-screen-first
optimization, and an alignment audit. No new credentials, providers, or
paid services. Tile/CDN hosts stay the spec-5 set plus one keyless
raster-imagery endpoint only if the implementer verifies it reachable
(7.3); otherwise the toggle is relabeled, no new host.

## Findings (grounding)

Each issue below was confirmed against code read before drafting:

1. No styling at all until a post-6 fix: `GET /static/style.css`
   raised `TypeError` (`Path.read_bytes()` takes no `encoding`
   argument), so every page 500'd its stylesheet. Fixed in `fbbfbb2`.
   Lesson carried into Agent notes: every 7.x objective gets a serving
   check, not only grep tests.
2. Raw probability decimals on detail pages: `report.html:102/112`
   and `shared.html:96/106` render `top_incident_prob` and
   `report.confidence` raw; the probability lists render raw floats
   (values like `9.566271774757038e-06`); `pages.py:964` passes the raw
   float into page context. -> 7.1
3. Detail photo cut off: the map bottom sheet (`map.html` `sheet_photo`)
   has no height constraint inside a 60%-height scrolling sheet, so a
   tall photo fills the sheet and covers the details. -> 7.2
4. Location preview blank: `#mini_map` starts hidden with a dot-plus-text
   fallback; the live mini-map needs the CDN, the tile host, and the
   incidents fetch to ALL succeed. -> 7.2
5. Dead map controls: street/satellite/recenter/zoom listeners are
   registered only AFTER the `maplibregl` guard (`map.html:320-335`),
   so with no CDN nothing is wired. The "satellite" style is the
   `bright` vector style (`map.html:156`), not satellite imagery, so
   the toggle appears to do nothing. -> 7.3
6. Create FAB overlaps the demo-only notices on the map. -> 7.3
7. No active-tab state: `is-active` is used only for map pills, never
   for nav tabs, so Create (the gradient tab) looks permanently
   selected. -> 7.4
8. Session-blind header: `base.html:13-15` always renders Log in, Sign
   up, AND Log out together. -> 7.4
9. Unneeded email field: `api.py:315` decodes the account email from
   the token itself; the email input only adds a mismatch failure
   mode. -> 7.5
10. Verify dead end: `verify_landing` renders `verify.html` with a bare
    success message and no onward link. -> 7.5
11. Verify entry persists: `account.html:138` ("Enter your verification
    code") sits OUTSIDE the verified conditional, so it shows after
    verification. (The upload notice is correctly conditional.) -> 7.5
12. Taste items (user direction): 44px-everywhere buttons feel big;
    full-gradient surfaces are unappealing; small screens and some
    box/line alignments need a pass. The share control renders a raw
    `/shared/N` URL as its label (`report.html:196`). -> 7.6 (7.2 for
    the share label)

## Objectives

### 7.1 Probability and confidence display

Page-render context formats every displayed probability as a
percentage; templates render strings and do no arithmetic.

- `pages.py` adds display keys alongside the raw values (e.g.
  `top_incident_pct`, `confidence_pct`, per-label percent strings
  like `91.0%`). Raw values and JSON API payloads are byte-identical.
- `report.html` / `shared.html` render the percent strings for
  incident probability, confidence, and both probability lists.
  Review surfaces rendering confidence use the same strings.

**Acceptance criteria**

- [ ] No raw decimal or exponent-notation probability on report,
  shared, or review pages (page test over rendered HTML).
- [ ] API JSON payloads unchanged (existing retrieval suites green).
- [ ] One-decimal percent format throughout (page test).
- [ ] Screenshots (360px + desktop) of the touched pages captured and
  logged with the observed look (screenshot protocol).

### 7.2 Detail media and bottom-sheet layout

- Hero photo: fully visible without covering the overlapping card
  (constrained height + `object-fit`, card overlap kept).
- Map bottom sheet: photo capped so the title, verdict, reasons, and
  [View Details] are reachable without scrolling past a full-height
  photo; sheet keeps its 60% height, grab handle, and rounded top.
- Location preview: the fallback (jittered dot + approximate text,
  no coordinates, no address) always renders when the live mini-map
  cannot init; the live mini-map path is otherwise unchanged.
- Share control labeled `Share`, not a raw URL.

**Acceptance criteria**

- [ ] Hero photo fully visible on report and shared pages (manual
  check logged, mobile width).
- [ ] Bottom sheet shows photo plus details without the photo
  occupying the whole sheet (manual check logged).
- [ ] Mini-map fallback renders with CDN blocked (page/markup test).
- [ ] Share control label is `Share` (page test).
- [ ] Screenshots (360px + desktop) of the touched pages captured and
  logged with the observed look (screenshot protocol).

### 7.3 Map reliability and honesty

- Controls degrade gracefully: with MapLibre unavailable, the
  street/satellite/recenter/zoom controls show a disabled state (or
  hide) instead of silently doing nothing; the report fallback list
  always renders.
- Satellite is real imagery or honestly labeled: the satellite toggle
  switches to a keyless public raster-imagery tile endpoint the
  implementer verifies reachable from a fresh checkout; if none is
  reachable, the toggle is relabeled to the second vector style it
  actually shows (no fake "satellite").
- Create FAB no longer overlaps the demo-only notices.
- Recenter handles denied location without breaking the page (keep
  the spec-5 behavior, extend to the no-CDN case).

**Acceptance criteria**

- [ ] Fallback report list renders with the map library absent
  (page/markup test).
- [ ] Satellite toggle shows imagery, or is relabeled to what it
  shows (manual check logged + test asserting the label matches the
  configured style).
- [ ] FAB and demo notices do not overlap at 360px width (manual
  check logged).
- [ ] Spec-5 map tests still pass unchanged (suite).
- [ ] Screenshots (360px + desktop) of the touched pages captured and
  logged with the observed look (screenshot protocol).

### 7.4 Navigation state and session-aware header

- Active tab: the current page's tab carries `is-active` in both the
  mobile tab bar and the desktop sidebar; exactly one tab is active.
- Header is session-aware: anonymous visitors see Log in + Sign up;
  logged-in users see the account gear + Log out; the states never
  mix, and no signup prompt shows once logged in.

**Acceptance criteria**

- [ ] Exactly one active tab per shell page, matching the page
  (page test across shell pages).
- [ ] Header links correct per session state, including reviewer
  Admin visibility (page test, anon + owner + reviewer).
- [ ] Screenshots (360px + desktop) of the touched pages captured and
  logged with the observed look (screenshot protocol).

### 7.5 Verify flow

- Token-only form: drop the email input. The token identifies the
  account (`api.py:315`); keep accepting an optional `email` query
  parameter for mailed-link compatibility, but never ask for it.
- Success screen: verification success renders an onward `Log in`
  button (to `/login`), not a dead-end message.
- No stale verify entries: the account Settings verify link moves
  inside the unverified branch (with the resend form); verified
  accounts see only "Email status: verified." The upload notice,
  already conditional, is confirmed unchanged.

**Acceptance criteria**

- [ ] Token-only verification succeeds end to end (page test, no
  email submitted).
- [ ] Success page links to `/login` (page test).
- [ ] No verify entry point renders for verified accounts (page
  test, account + upload).
- [ ] Screenshots (360px + desktop) of the touched pages captured and
  logged with the observed look (screenshot protocol).

### 7.6 Visual refinement pass

User-directed restraint pass over the spec-6 system (variables stay
the mechanism; no new palette):

- Compact button scale: base `min-height` 40px; primary CTA, FAB,
  and Create tab keep 44px+; every interactive target stays >= 24px.
- Gradient reserved for the primary CTA and the Create FAB only;
  secondary/tertiary surfaces go flat (card color + border).
  The Create tab rendering defect (broken gradient edge on the
  right) is fixed as part of this: no overflow, no clipped shadow,
  aligned with sibling tabs at mobile and desktop widths.
- Small-screen-first: 360px width is the primary manual surface; no
  horizontal overflow on any page; tab labels fit without wrapping.
- Alignment audit: form/card gutters, the detail action row, vouch
  and comment cards, empty states, and the review queue rows share
  consistent spacing; the raw-URL share label is gone (7.2).

**Acceptance criteria**

- [ ] Every color, radius, and shadow remains a CSS variable;
  templates use variables, no literals (grep test, extended).
- [ ] No 44px-min-height rule outside primary CTA/FAB/Create-tab
  selectors (grep test); no target below 24px (manual check logged).
- [ ] Gradient appears only on primary CTA/FAB/Create tab (grep +
  manual check logged).
- [ ] 360px mobile and desktop renderings checked manually and
  logged, including the Create tab edge fix.
- [ ] Screenshots (360px + desktop) of the touched pages captured and
  logged with the observed look (screenshot protocol).

## Agent notes

- Build order: 7.1 -> 7.5 -> 7.4 -> 7.2 -> 7.3 -> 7.6 (value
  formatting and dead-end flows first, map and polish last).
- Serving check per objective (lesson of Finding 1): after the final
  edit, `GET` each touched page and `/static/style.css` and assert
  200 plus the stylesheet link — in addition to the suite. Builders:
  run these as throwaway probes outside the repo, never as committed
  tests hitting the network.
- Screenshot evidence per objective: headless-Chromium captures (360px
  mobile + desktop viewports) of every touched page against the local
  dev server with seeded demo data, saved as PNGs under
  `lite/work/screenshots/spec-7/<objective>/` (git-ignored working
  state, never committed). The log entry lists each screenshot path
  plus a short observed-look description and the verdict against the
  criteria. Logs stay ASCII-only: paths and prose, never image bytes.
  Browser binaries come only from the brief's `network_allowed`
  (Playwright browser downloads are sanctioned tooling).
- No npm toolchain and no JS framework. CDN hosts stay the spec-5
  set (unpkg MapLibre + OpenFreeMap) plus at most one keyless
  imagery endpoint verified reachable, listed in the brief's
  `network_allowed`.
- Spec 3.3 still holds: every page except `/map` renders without
  JavaScript; the wording grep test still passes.
- Never put exact coordinates, emails, or file paths in any new
  markup. The mini-maps keep using the jittered display point.
- No schema changes: formatting is display strings in page context;
  verify changes need no new tables (recreate path not triggered).
- Restyle only; do not rebuild unlisted items. Anything in "Needs
  user approval" from spec 6 stays unapproved unless the user says
  otherwise in this session.

## Out of scope

Verdict, fusion, check, and API value changes (display strings only,
raw values intact); street addresses, address autocomplete, and
reverse geocoding; native iOS/Android builds; new paid providers or
API keys; automated photo-vs-location matching; clustering and
heatmaps (spec-5 limits stand).

## Definition of done

Every criterion recorded as passing in `lite/logs/spec7_log.md`,
full Lite suite green, the spec-3 wording grep test still passing,
mobile-360 plus desktop checked manually and logged, screenshots
captured and logged per objective, and each criterion above either
passing or recorded as not started by user decision.
