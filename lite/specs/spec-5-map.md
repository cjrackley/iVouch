# Lite Spec 5 — Map (plot submissions, human visual compare)

**Why separate:** specs 1-4 prove checks, API, pages, and review.
This spec adds the map: every consented submission is plotted, and a
person can visually compare the photo against its mapped location.
It is the last Lite spec.

| | |
|---|---|
| Depends on | spec-2 (location storage), spec-3 (pages) |
| Unblocks | demo (end of Lite) |
| Execution | Sequential only — spec 6 of 6 |
| Stack | FastAPI + Jinja2, MapLibre GL JS via CDN, OpenFreeMap tiles |

## What fits Lite, and what does not

In scope: plotting each consented report as a dot, and showing the
photo next to its mapped location so a human can see visible
similarities (or mismatches) between scene and place.

Out of scope, explicitly: any automated check that the photo's scene
matches its claimed location (landmark/terrain/vegetation matching,
image geo-localization). That needs a geo-localization model or a
paid vision API, which breaks Lite's local-only, $0-inference rule.
In Lite the similarity judgement is human-only, aided by the
satellite view in 5.3. No fusion rule, score, or reason in Lite may
claim a scene-location match or mismatch.

## Human inputs

None. Map tiles load in the user's browser from OpenFreeMap (free
tier). Tile fetching is browser-side runtime traffic at demo time,
not a paid API and not agent browsing; a brief that adds the CDN
or tile hosts to a page still lists them in `network_allowed` so
the orchestrator can review them. With no internet, the map page
falls back to the reports list (5.3).

## Objectives

### 5.1 Required location capture

Upload form (spec 3 page, extended here): a required location
section with two ways to set it — a "Use my location" button
(browser geolocation) or clicking a pin onto a small picker
map — plus a mandatory consent checkbox, unchecked by default.
`location_source` is `browser` or `manual_pin`. Location and
consent are mandatory: the form blocks submit until a pin is set
and the box is checked, and the server returns 422 otherwise
(spec 2). There are no location-less reports in Lite, so every
accepted report can appear on the map.

The consent text states the sharing rule in plain words: "Your
photo, claim text, approximate map location, and verdict will be
visible to other logged-in demo users. Your email and exact
location are never shared."

**Acceptance criteria**

- [ ] Submit is disabled until a pin is set and the consent box
  is checked; an upload without either is rejected with 422
  and nothing stored (form test + spec-2 storage test).
- [ ] Every accepted report has coordinates and consent true
  (storage test); every accepted report appears in the 5.2
  payload unless rejected or deleted.
- [ ] Turning consent off after setting a pin clears the pin
  before submit (page test).
- [ ] The consent text above is shown next to the checkbox
  (page test).

### 5.2 Display point and map API

Exact coordinates stay server-side. The display point is offset
deterministically per report (hash of report id seeding an
offset within `jitter_min_m`..`jitter_max_m` from
`lite/config.yaml`), so repeated requests return the same
jittered point and cannot be averaged back to the exact
location.

`GET /api/incidents` (login required): GeoJSON-style list of
`{report_id, display_lat, display_lng, incident_type, severity,
label, created_at}` for accepted, non-rejected reports from all
accounts (location is mandatory, so every accepted report is a
candidate). Exact coordinates, emails, and file paths are never
in this payload.

**Acceptance criteria**

- [ ] Same report returns the identical display point on repeated
  calls (test); offset distance is within the configured bounds
  (`jitter_min_m`/`jitter_max_m`, test).
- [ ] Mock-gate-rejected and deleted-account reports are excluded
  (tests). There is no non-consented case: uploads without
  consent are rejected at submit (5.1, spec 2).
- [ ] Payload contains no exact coordinates, emails, or file paths
  (test).

### 5.3 Map page

`GET /map` (login required). Full-page MapLibre map with one dot
per report from 5.2. Clicking a dot opens a popup/panel showing:
the report's photo, incident type, severity, authenticity label
with reasons, time, and a link to the community page
`GET /shared/{id}` (shared fields plus photo, any logged-in
user; never the owner-only `GET /reports/{id}`, which stays
403 for other accounts). A basemap toggle switches
street/satellite so the viewer can visually compare the photo's
scene with the mapped surroundings.

**Acceptance criteria**

- [ ] Dots render for seeded reports; rejected and deleted
  reports have no dot (manual check logged; no browser automation
  required in Lite).
- [ ] Dot click shows photo, type, severity, label, and reasons
  (manual check logged).
- [ ] Street/satellite toggle works and the popup states:
  "Compare the photo with this area visually. Lite does not
  automatically verify that a photo matches its location."
- [ ] Without internet/CDN access the page shows the reports list
  instead of a blank map (manual check logged).
- [ ] The popup link opens `GET /shared/{id}` for another
  account's report (manual check logged); the owner-only report
  URL stays 403 for other accounts (test in spec 2).

### 5.4 Photo visibility on the map

Lite is a demo with accounts, so logged-in users see report photos
in map popups. This is a deliberate demo simplification, recorded
here: the full plan blurs faces/plates and restricts originals,
which Lite does not implement.

**Acceptance criteria**

- [ ] Map popups never show photos of mock-gate-rejected or
  deleted reports (they have no dot; covered by 5.2 tests).
- [ ] The map page carries the demo disclaimer from spec 3 plus:
  "Demo only: photos are visible to logged-in users. Do not upload
  sensitive images."

### 5.5 Final demo update

Extend `lite/DEMO.md` (spec 4) with the map: how to upload a
report with the required location plus consent, open `/map`,
click a dot, open the community page, and compare photo vs
satellite view. State the out-of-scope automated scene-location
check in the same section, and repeat the data-use rule (shared
vs never-shared fields).

**Acceptance criteria**

- [ ] A fresh checkout following `lite/README.md` reaches a working
  map with at least one seeded report plotted (manual run logged
  by the orchestrator).
- [ ] Full Lite suite passes, including the new 5.1/5.2 tests.

## Agent notes

- CDN scripts (MapLibre GL JS) and tile hosts must be listed in
  the brief's `network_allowed` as page-runtime hosts; they are not
  agent browsing and cost $0. No npm toolchain is added for the map.
- Keep clustering, filtering, heatmaps, and real-time updates out.
  One dot per report and a click popup is the whole Lite map.
- Never add an automated scene-vs-location score, rule, or reason
  here, however simple it seems. That is a scope change needing a
  user decision (orchestrator section 5).

## Out of scope

Automated photo-to-location similarity checking, PostGIS, exact-pin
display to anyone, public (logged-out) map access, clustering,
external/storage changes beyond spec-2 location columns.

## Definition of done

Every criterion recorded as passing in `lite/logs/spec5_log.md`,
full Lite suite green, map manually verified with a seeded report.
Lite is then a finished demo — not a launch candidate.
