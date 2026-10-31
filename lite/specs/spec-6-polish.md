# Lite Spec 6 — Native App Polish and Endpoint Coverage

**Why separate:** specs 3-5 built every Lite page with plain,
readable CSS. This spec restyles those pages to look and feel like
a native Apple iOS / Android app (green/blue theme, no jagged
text), fixes every orphan route, and re-checks spec 5 (map, pins,
saving). It changes how pages look and how they are reached, not
what the checks or the API do.

| | |
|---|---|
| Depends on | spec-3 (pages), spec-4 (review and audit pages), spec-5 (map) |
| Unblocks | demo (end of Lite) |
| Execution | Sequential only — spec 7 of 7 |
| Stack | FastAPI + Jinja2 templates, `static/style.css`, minimal vanilla JS, MapLibre GL JS via CDN (spec 5) |

## Human inputs

None for the restyle and the route fixes. Objectives and items
marked **Needs user approval** add features Lite does not have
today; each waits for a user decision (orchestrator section 5)
before a brief is dispatched. Apple/Google sign-in (6.9) also
needs OAuth client credentials from the user; Lite has none.

## Route map (draft name -> Lite route)

This spec was drafted against app-style route names. Lite's real
routes are used everywhere below.

| Draft route | Lite route | Status |
|---|---|---|
| `/`, `/map` | `GET /map` (`/` redirects to `/map`, 6.2) | exists |
| `/pin/:id`, `/vouch/:id` | `GET /shared/{id}` (community), `GET /reports/{id}` (owner) | exists |
| `/create`, `/add-location` | `GET /upload` | exists |
| `/login`, `/register` | `GET /login`, `GET /signup` | exists |
| `/me`, `/settings` | `GET /account` | exists |
| `/audit` | `GET /audit` (reviewer only) | exists |
| `/saved`, `/bookmarks` | `GET /saved` | new, needs user approval (6.6) |
| `/feed`, `/explore` | `GET /feed` | new, needs user approval (6.7) |
| `/profile/:id` | `GET /profile/{id}` | new, needs user approval (6.8) |
| `/notifications`, `/search` | none | new, needs user approval (6.10) |

## Objectives

### 6.1 Global design system (every page)

One stylesheet, `lite/app/server/static/style.css`, holds the
whole design system as CSS variables. `templates/base.html`
loads it for every page.

Theme palette:

- Primary blue `#0F6BFF`; secondary green `#00C98D`.
- Primary-action gradient:
  `linear-gradient(135deg, #0F6BFF 0%, #00C98D 100%)`.
- Background `#F5F8FB`; card `#FFFFFF`; border `#E5E7EB`.
- Text primary `#111827`, secondary `#6B7280`, muted `#9CA3AF`.
- Radius: cards 16px, buttons 12px, pills 24px.
- Shadow: cards `0 2px 10px rgba(0,0,0,0.06)`, FAB
  `0 8px 24px rgba(15,107,255,0.25)`.

Typography (fixes jagged, out-of-place text):

- Font stack: `'Inter', -apple-system, BlinkMacSystemFont,
  'SF Pro Display', 'Segoe UI', sans-serif`.
- Applied globally: `-webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;`.
- Headers: weight 600-700, line-height 1.2, letter-spacing
  -0.02em. Body: weight 400-500, line-height 1.5.
- Never Times New Roman, never pure black `#000` text. Body is
  left-aligned; only hero and onboarding text is centered.
  Consistent 16px horizontal padding (SafeArea) on every page.

Buttons (every button):

- `min-height: 44px` (Apple HIG touch target), radius 12px,
  weight 600, `transition: all 0.15s ease`, `cursor: pointer`,
  `user-select: none`.
- Required states: default; hover (brightness 0.95); active
  (scale 0.98 + brightness 0.9); disabled (opacity 0.5,
  `cursor: not-allowed`); loading (spinner).
- Primary: gradient background, white text, shadow. Secondary:
  white background, `1.5px solid #E5E7EB`, text `#111827`.
  Tertiary/icon: ghost, no border.
- Every raw `<a>` text link used for navigation becomes a button
  or card component (shared Jinja2 macros or classes).

Layout shell:

- Mobile: bottom tab bar 80px tall, top bar 64px. Desktop: a
  centered max-width 430px phone shell, or a responsive grid with
  the same tab bar collapsed to a sidebar.
- Every page: 16px SafeArea padding, background `#F5F8FB`.
- Cards: white, 16px radius, card shadow, 16px internal padding.

**Acceptance criteria**

- [ ] Every colour, radius, and shadow above is a CSS variable in
  `style.css`; templates use the variables, not literals (grep
  test).
- [ ] Font smoothing applies globally; no page uses Times New
  Roman or `#000` text (grep test plus manual check logged).
- [ ] Every button is 44px+ tall and shows every state listed
  above, with press feedback (manual check logged; no browser
  automation required in Lite).
- [ ] The green/blue theme is applied consistently on every page
  (manual check logged).

### 6.2 Endpoint coverage (no orphan pages)

1. Audit the FastAPI routers (`pages.py`, `api.py`) and list every
   page route.
2. For each page route, confirm a visible button, card, tab, or
   icon reaches it. No URL-only pages.
3. Add any missing entry point on the logical parent:

| Lite route | Entry point |
|---|---|
| `GET /map` | Tab bar Map; `/` redirects here |
| `GET /shared/{id}` | Map pin bottom sheet [View Details]; feed cards |
| `GET /reports/{id}` | Own-reports list cards |
| `GET /upload` | FAB (+) on map and feed, top bar, tab bar Create |
| `GET /reports` | Account page "My Pins" tab |
| `GET /account` | Tab bar avatar/Profile; header gear; feed card avatar (own) |
| `GET /login`, `GET /signup` | Header; redirect on 401 |
| `GET /logout` | Account page |
| `GET /verify` | Console-mail link; unverified notice on `/upload` (spec 3.1) |
| `GET /review`, `GET /review/{id}`, `GET /audit` | Admin link on the account page, reviewer accounts only |

4. Remove dead links. Every list page gets an empty state with a
   button back to `/map`.

Static files, photo routes, JSON API routes, and form POST targets
are not pages and are exempt from the orphan rule.

**Acceptance criteria**

- [ ] A test lists the app's GET page routes and asserts each
  appears as a link target on at least one page a user can reach
  (page test). Zero orphan routes.
- [ ] The Admin link appears only for reviewer accounts (page
  test).
- [ ] No page links to a route that does not exist (page test).
- [ ] Each list page shows its empty state with a `/map` button
  when it has no items (page test).
- [ ] Stage 5 check: deep links work. Opening `/map`,
  `/shared/{id}`, or `/upload` directly loads the page, or
  redirects to `/login` when logged out (page test).

### 6.3 Map page

`GET /map` (and `/`).

- The map fills the viewport minus top bar and bottom tab bar.
  Nothing is cut off.
- Floating controls: [Recenter], [Zoom +/-], and the gradient
  [Create Pin +] FAB bottom-right (opens `/upload`).
- Pins: a custom marker (pill with icon, category colour, and
  count), never the default red pin. Active pin: scale 1.15 plus
  a 3px white ring.
- Pin tap slides up a bottom sheet (60% height, grab handle,
  rounded 24px top) instead of the spec-5 popup. It shows the
  photo, title, vouch count, [View Details] -> `/shared/{id}`,
  and a [Save] bookmark toggle that fills green when saved. The
  page does not navigate away until [View Details] is tapped.
- Everything spec 5.3 and 5.4 require stays: incident type,
  severity, label with reasons, time, the street/satellite toggle,
  the visual-compare text, the demo photo disclaimer, and the list
  fallback without internet.
- **Needs user approval:** the floating search bar at the top
  (white, 24px pill, shadow, filter icon), vouch count, and
  [Save] (6.6). Spec 5 keeps filtering out of Lite. Until the
  title field (6.5) is approved, the sheet shows incident type in
  its place.

**Acceptance criteria**

- [ ] Stage 5 check: pins load from `GET /api/incidents`, persist
  after a page refresh, and Recenter handles a denied location
  permission without breaking the page (manual check logged).
- [ ] Bottom sheet shows the fields above and opens
  `/shared/{id}` only from [View Details] (manual check logged).
- [ ] Spec-5 map tests still pass unchanged (suite).

### 6.4 Report detail page

`GET /shared/{id}` (community) and `GET /reports/{id}` (owner)
share one layout.

- Hero photo 240px tall, rounded 16px, with a back-button overlay
  top-left (white circle, 40px).
- An overlapping white card: title (20px, weight 700); trust
  badge (the authenticity label as a green pill); a mini-map
  preview (120px, rounded) at the jittered display point only,
  with no street address; the description (claim text).
- **Needs user approval:** the vouches/comments list as stacked
  cards; a sticky bottom action row with [Vouch] (gradient),
  [Save] (icon toggle), and [Share] (`navigator.share`); and
  [Edit]/[Delete], shown only when the current user owns the
  report.

**Acceptance criteria**

- [ ] Stage 5 check: both pages load for the right users; the
  owner page stays 403 for other accounts (spec 2 test still
  passes).
- [ ] The mini-map uses the jittered display point; the page
  contains no exact coordinates and no address (page test).
- [ ] If approved: [Edit]/[Delete] appear only for the owner
  (page test); [Share] works (manual check logged); [Save] syncs
  with `/saved` (test).

### 6.5 Upload page

`GET /upload`, styled as an iOS form sheet.

- Top nav: [Cancel] left, "New Vouch" centered, [Post] right.
  [Post] is the form's submit and stays disabled until the form is
  valid.
- Fields are iOS grouped cells: label 12px uppercase grey; input
  16px, background `#F9FAFB`, rounded 12px, focus border
  `#0F6BFF`.
- Fields: location picker (mini-map tap sets lat/lng, plus the
  spec-5 "Use my location" button; no address autocomplete or
  reverse geocoding); description (the claim text); photo upload
  (dashed rounded drop zone).
- The spec-5.1 consent checkbox and consent text stay as they are.
- **Needs user approval:** title field and category pill selector.

**Acceptance criteria**

- [ ] Stage 5 check: the upload saves lat/lng, not a text address,
  and is validated before POST. [Post] stays disabled until a pin
  is set and consent is checked (spec-5 tests still pass).
- [ ] Consent text from spec 5.1 is shown next to the checkbox
  (page test).

### 6.6 Saved places

**Needs user approval.** New page `GET /saved` (the draft's
`/bookmarks` is the same page).

- Header "Saved Places" plus count.
- Segmented toggle: List | Map.
- List: vertical cards, image left (80x80, rounded 12px), title
  right, and an [Unsave] heart (green, filled). No address.
- Empty state: illustration, "No saved vouches yet", and an
  [Explore Map] button -> `/map`.
- Unsave removes the card instantly and shows a toast.

**Acceptance criteria**

- [ ] Save on the map sheet or detail page adds the report here;
  unsave removes it (test).
- [ ] Stage 5 check: save/unsave syncs across map, detail, and
  saved pages (test).
- [ ] Empty state shows with the `/map` button (page test).

### 6.7 Feed

**Needs user approval.** New page `GET /feed` (the draft's
`/explore` is the same page).

- Segmented top: For You | Nearby | Following.
- Cards: user avatar row on top; a location card below with photo
  (160px), title, vouches, and distance.
- The whole card opens `/shared/{id}`; each card has a [Save]
  bookmark top-right.

**Acceptance criteria**

- [ ] Each card opens `/shared/{id}`; [Save] works per card
  (page test).
- [ ] Cards show shared fields only: no email, no exact
  coordinates (page test).

### 6.8 Account and profile

`GET /account` is the own profile (the draft's `/me`) and holds
settings (the draft's `/settings`).

- Avatar (80px circle), name (20px, weight 700), bio (secondary
  text), and a stats row with 3 columns: Vouches | Saved |
  Following.
- Tabs: My Pins (own reports, `/reports`) | Saved | Activity.
- Top-right: [Settings] gear for the settings section (verified
  state, delete account, spec 3.1) and an [Edit Profile]
  secondary button. Reviewers also get the Admin link (6.2).
- **Needs user approval:** name, bio, avatar, Edit Profile, the
  Saved and Following stats, the Saved and Activity tabs, and
  other users' profiles at `GET /profile/{id}`.

**Acceptance criteria**

- [ ] Delete account still confirms once and returns to login
  (spec 3 test still passes).
- [ ] No profile page shows another user's email (page test).

### 6.9 Login and signup

`GET /login`, `GET /signup` (the draft's `/register`).

- Centered onboarding: logo (32px, bold), inputs as iOS cells,
  full-width 48px gradient primary button.
- All text centered, nothing jagged or misaligned.
- The spec-3.1 age gate, demo disclaimer, and data-use notice stay
  on signup.
- **Needs user approval:** [Continue with Apple] and [Continue
  with Google] secondary buttons (external OAuth; credentials are
  a human input), and a "Forgot password" link (Lite has no
  password reset flow).

**Acceptance criteria**

- [ ] Signup still shows the age gate, disclaimer, and data-use
  notice (spec 3 test still passes).
- [ ] Login and signup render centered on mobile and desktop
  (manual check logged).

### 6.10 Navigation

- Bottom tab bar (mobile), 5 icons: [Feed] [Map] [Create +]
  [Saved] [Profile]. Active tab in blue/green; labels 10px,
  weight 600. On desktop it collapses to the sidebar (6.1).
- The Create FAB is visible on the map and feed.
- Header: Settings gear (-> `/account`). Search and a
  Notifications bell with a dot appear only once those routes
  exist.
- Feed and Saved tabs appear only once 6.7 and 6.6 are built, so
  the bar never holds a dead link.
- **Needs user approval:** search and notifications.

**Acceptance criteria**

- [ ] Every tab and header icon points at an existing route (page
  test, shared with 6.2).
- [ ] Tab bar and header render correctly on mobile and desktop
  widths (manual check logged).

## Agent notes

- Build order: (1) `style.css` variables, font, button base;
  (2) tab bar and header in `base.html`; (3) map -> report detail
  -> upload -> saved -> feed -> account -> login/signup;
  (4) final orphan audit (6.2).
- Spec 3.3 still holds: every page except `/map` renders without
  JavaScript, and the wording grep test still passes. Segmented
  toggles are links or forms; JS only adds polish (bottom sheet,
  toasts, `navigator.share`).
- No npm toolchain and no JS framework. A font or icon CDN goes
  in the brief's `network_allowed` like the spec-5 map hosts.
- Never put exact coordinates, emails, or file paths in any new
  page or payload. The mini-maps use the jittered display point.
- Approved features that need new tables (saved reports, follows,
  vouches, comments, profile fields) follow spec 2: schema
  changes mean recreating the database, never a migration.
- Category (6.5) is user input. It never replaces the CLIP
  incident type or any check output.
- Restyle only for unapproved items. Do not build a "Needs user
  approval" item until the user approves it.

## Out of scope

React, Next.js, any SPA framework or npm toolchain; street
addresses, address autocomplete, and reverse geocoding (Lite shows
only the jittered point); a native iOS or Android build (this spec
makes the web app look native); automated scene-vs-location
checks, clustering, and heatmaps (spec 5 limits still apply).

## Definition of done

Every criterion recorded as passing in `lite/logs/spec6_log.md`,
full Lite suite green, the spec-3 wording grep test still passing,
and mobile and desktop checked manually and logged. Each "Needs
user approval" item is either approved and passing, or recorded as
not started by user decision.
