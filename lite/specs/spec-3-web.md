# Lite Spec 3 — Web UI (server-rendered)

**Why separate:** specs 1-2 proved checks and API. This spec is only
the human surface: signup, login, upload, result card, own-reports
list. Reviewer screens wait for spec 4.

| | |
|---|---|
| Depends on | spec-2 |
| Unblocks | spec-4 |
| Execution | Sequential only — spec 4 of 6 |
| Stack | FastAPI + Jinja2, minimal vanilla JS, no SPA framework |

## Human inputs

None. Styling is plain, readable CSS. No design system, no npm
toolchain, no JavaScript framework in Lite.

## Objectives

### 3.1 Account pages

Pages: `/signup`, `/login`, `/logout`, `/account` (shows own
email, verified state, delete-account action), `/verify` landing.

Auth bridge: login issues the spec-2 JWT; the web stores it in an
HttpOnly session cookie and sends it as a bearer token (or cookie)
on API calls. Every POST form carries a CSRF token. The builder
picks the cookie/CSRF mechanism and documents it.

**Acceptance criteria**

- [ ] Signup shows the age gate, the demo disclaimer, and the
  data-use notice: what an upload shares with other logged-in
  users (photo, claim text, approximate map location, verdict)
  and what is never shared (email, exact coordinates, file
  paths). Under-age submission shows the generic rejection
  (test via spec-2 API).
- [ ] Unverified users landing on upload see "verify your email"
  with a resend action; upload is disabled (page test).
- [ ] Delete account from `/account` confirms once, calls the
  spec-2 endpoint, and returns to login (test).
- [ ] Session cookie is HttpOnly; every POST form carries a CSRF
  token (test).

### 3.2 Upload page

`GET /upload` form (photo, optional claim text, required location
picker plus mandatory consent checkbox) posting to spec 2's
`POST /analyze`; `GET /reports/{id}` owner result page;
`GET /reports` own-reports list; `GET /shared/{id}` community
report page (spec 5; shared fields plus photo, any logged-in user).

**Acceptance criteria**

- [ ] The demo content notice appears above the file picker: what
  Lite checks, that safety screening is a mock, and "Not for
  emergencies: call your local emergency number."
- [ ] The data-use notice appears above the file picker: uploads
  (photo, claim text, approximate map location, verdict) are
  visible to other logged-in demo users; email, exact
  coordinates, and file paths are never shared. Submit stays
  disabled until a location is set and the consent box is
  checked (page test).
- [ ] Result card shows incident type and probability, severity,
  authenticity label with every reason listed, and confidence.
- [ ] A `needs_review` verdict shows "needs human review" prominently.
- [ ] A mock-gate rejection shows only the generic message plus the
  content notice. No report details leak (page test).
- [ ] Reports list shows own reports only, newest first (test).
  Community discovery happens on `GET /map` and `GET /shared/{id}`
  (spec 5), not in this list.

### 3.3 Wording and honesty pass

**Acceptance criteria**

- [ ] No page uses certainty words (template grep test): strip
  the exact label tokens (`likely-real`, `needs-review`,
  `likely-manipulated`) from each rendered template, then assert
  no case-insensitive whole-word match for `proven`, `fake`,
  `real`, or the phrase `verified real` remains. Labels are
  exactly `likely-real` / `needs-review` / `likely-manipulated`
  rendered in plain language with "signals observed" reasons.
  (The `/account` email-verified state text is exempt from the
  `verified real` phrase check: it never appears adjacent to the
  word `real`.)
- [ ] Every result page carries "Demo build — results need human
  review and are not evidence of authenticity."
- [ ] Every result page and the community page carry the short
  data-use line: "Visible to logged-in demo users. Your email
  and exact location are never shared."
- [ ] Pages render with no JavaScript enabled except the upload
  form's file picker (manual check logged; no browser automation is
  required in Lite). The map page (`GET /map`, spec 5) is exempt:
  it needs JavaScript and the CDN, with a list fallback.

## Agent notes

- Server-rendered only. If a page seems to need a JS framework, the
  page is too big for Lite; simplify the page.
- Never display uploaded image bytes on the own-reports list page.
  The owner result page shows the owner's image back to the owner;
  community surfaces (`GET /shared/{id}`, map popups in spec 5)
  show accepted-report photos to any logged-in user, never photos
  of rejected uploads or deleted accounts. No email, exact
  coordinates, or file paths appear on any of these pages.
- Keep templates free of thresholds; read display values from the
  API response, never re-compute checks in a template.

## Out of scope

Reviewer queue and actions (spec 4), safety console, removal-request
pages, map (spec 5), accessibility audit tooling, any mobile client.

## Definition of done

Every criterion recorded as passing in `lite/logs/spec3_log.md`,
full Lite suite green, page wording grep test passing.
