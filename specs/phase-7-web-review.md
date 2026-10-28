# Phase 7 — Web: Accounts, Upload, Reviewer and Safety Consoles

This phase covers the web surface. Under the sequential block schedule
it is Block 3, phase 2 of 2.

**Why separate:** a different surface (browser, server-rendered pages)
for different users — web submitters, reviewers, safety officers, and
members of the public filing removal requests. It needs the backend
and authenticity service to be real so reviewers see real signals.

| | |
|---|---|
| Depends on | Phases 4, 5 |
| Unblocks | Phase 8 |
| Execution | Sequential only — Block 3, phase 2 of 2 (starts automatically after Phase 6; manual stop after this phase) |
| Stack | FastAPI + Jinja2 templates, minimal vanilla JS, MapLibre GL JS (report detail mini-map only), Playwright for tests |

## Human inputs (gate)

| Input | If missing |
|---|---|
| Named safety officer(s) and a takedown contact address | Placeholder contact in config; launch-checklist item stays `blocked` in Phase 8 |

Staff accounts are created with a CLI command.

## Objectives

### 7.1 Account pages

Signup (email, password, date of birth, terms), verify email, login,
logout, password reset, and **account deletion** (Google Play requires
a web link for deletion requests).

**Acceptance criteria**

- [ ] Same rules as the API (age gate without storing date of birth,
  verification before upload).
- [ ] The deletion page works for a logged-in user, is linked from the
  site footer, and its URL is in config for the Play Console listing.
- [ ] Session cookies are HttpOnly + Secure + SameSite; all POST forms
  have CSRF protection (test).

### 7.2 Web upload page

Server-analyzed uploads (no on-device step): `capture_source =
web_upload`, no attestation. Requires login, verified email and current
policy accepted.

**Acceptance criteria**

- [ ] Content policy shown and must be accepted before the file picker
  is enabled.
- [ ] Optional manual location pin and claim text; posts to
  `POST /v1/analyze`.
- [ ] Result page polls until the report is `complete` or rejected and
  shows the same report card content as the Android app; rejections
  show only the generic message plus a policy link.

### 7.3 Public removal-request page (TAKE IT DOWN)

No login required. Linked from the site footer, the Android app's
Settings and every map bottom sheet.

```python
# server/ivserver/web/takedown.py
def takedown_form(request) -> HTMLResponse: ...
def takedown_submit(request, form: TakedownForm) -> HTMLResponse: ...   # calls submit_takedown (Phase 4)
def takedown_status(request, req_id: str, token: str) -> HTMLResponse: ...
```

**Acceptance criteria**

- [ ] Shows the plain-language notice from
  `docs/REMOVAL_REQUESTS.md` above the form.
- [ ] Form collects every required field (name, contact email,
  electronic signature, content location, good-faith statement) and
  explains each in plain language.
- [ ] After submission, shows the request id and a status link; the
  requester also gets an email.

### 7.4 Staff login and review queue

Shared login; screens depend on role.

```python
# server/ivserver/web/review.py
def queue_page(request, filters: QueueFilters) -> HTMLResponse: ...
def report_page(request, report_id: str) -> HTMLResponse: ...
# server/ivserver/cli.py
def create_staff(email: str, roles: list[str]) -> None: ...   # roles ⊆ {reviewer, safety_officer, admin}
```

**Acceptance criteria**

- [ ] Queue sorted by severity, then confidence ascending, then age;
  filters by type, severity, authenticity label.

### 7.5 Report detail for reviewers

Shows: blurred photo with mask overlay toggle, device vs. server
outputs (and disagreements), rationale, every authenticity signal
with its reason, escalation result, duplicates and web matches
(links), corroborating reports, mini-map with exact pin (reviewer
only). The submitter's identity is not shown to reviewers.

**Acceptance criteria**

- [ ] "View original" requires a confirmation click, opens the signed
  URL and writes an audit row (test).
- [ ] Every signal shown has a plain-language explanation.

### 7.6 Review actions and label export

Confirm / correct (incident types, severity, authenticity label, mask
accept/reject) / escalate (triggers Phase 5 escalation if budget
allows) / **flag suspected CSAM**.

```python
# server/ivserver/review/export.py
def export_review_labels(since: datetime, out: Path) -> Path: ...  # parquet compatible with Phase 1 manifest columns
```

**Acceptance criteria**

- [ ] Each action produces an audit row with before/after values.
- [ ] "Flag suspected CSAM" asks for one confirmation, then the item
  disappears from the reviewer's screen and browser cache headers
  prevent re-display (test).
- [ ] Exported labels load into `ivml.data.manifest.build_manifest`
  without errors and never include quarantined or removed items (test).

### 7.7 Safety console (`safety_officer` only)

- **Takedown queue:** open requests sorted by deadline, countdown to
  the 48-hour limit; validate → execute (shows the target and every
  duplicate that will be removed) → done. Overdue and near-deadline
  requests highlighted.
- **Quarantine:** metadata only (time, source, account, legal-hold
  expiry). Viewing content requires a typed justification and is
  audit-logged; images open blurred by default.
- **CyberTip reports:** prepare from a quarantine item, review the
  draft, submit (mock client in dev/test), see submission status.
- **Account actions:** suspend / reinstate with reason.

**Acceptance criteria**

- [ ] Every safety page returns 403 for all other roles, including
  `admin` without `safety_officer` (tests).
- [ ] Every view and action writes an audit row.
- [ ] Takedown dashboard shows time remaining for each open request;
  a request at the `takedown.alert_after_h` mark is highlighted
  (frozen-clock test).

### 7.8 Accessibility

**Acceptance criteria**

- [ ] axe-core (via Playwright) reports no serious/critical issues on
  account, upload, removal-request, queue, detail and safety pages.
- [ ] Fully keyboard-operable review and takedown actions.
  (Playwright/browser unavailability in the agent environment is
  ENV-BLOCKED with the tool error recorded, not a silent skip. The brief
  lists Playwright browser-download hosts in `network_allowed`.)

## Agent notes

- Keep it server-rendered; a SPA framework isn't needed for v1.
- Reviewers will see disturbing incident content. Default to blurred
  images and avoid autoplaying or enlarging media.
- Never seed any environment with real abuse material. Quarantine
  screens are tested with mock-matched synthetic fixtures.

## Out of scope

Admin analytics dashboards, public marketing website, any mobile work.

## Definition of done

Every acceptance criterion recorded as passing in `logs/spec7_log.md`
(the boxes above are spec source text and are never ticked; see
`logs/README.md`), including Playwright E2E: (1) web signup → verify →
upload → report complete →
reviewer corrects → label export contains the correction → user
deletes account; (2) public removal request → officer validates and
executes → target and copies gone → requester status shows done;
(3) reviewer flags a fixture → appears only in the safety console →
officer prepares a mock CyberTip report. A criterion that cannot run —
Playwright/browser unavailable, no named safety officer for the real
contact details — stays open (ENV-BLOCKED / NEEDS-USER-APPROVAL) and
keeps the phase incomplete under orchestrator §7. There is no partial
completion.
