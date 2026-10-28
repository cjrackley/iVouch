# Lite Spec 4 — Review Queue and Demo Hardening

**Why separate:** Lite is usable after spec 3. This spec adds the
human-in-the-loop proof (a reviewer can correct the demo) and the
small hardening pass that makes the demo safe to show. The map
(spec-5) follows it as the final Lite spec.

| | |
|---|---|
| Depends on | spec-3 |
| Unblocks | spec-5 |
| Execution | Sequential only — spec 5 of 6 |
| Stack | FastAPI + Jinja2 (spec 3), pytest |

## Human inputs

None required. A named reviewer account is created with a local CLI
command; no real safety officer, no real takedown contact, and no
external organisation is involved in Lite.

## Objectives

### 4.1 Reviewer role and queue

Accounts carry the `reviewer` flag created in spec 2, set only by
the local CLI (`python -m lite.app.cli make-reviewer <email>`).
Pages: `GET /review` (queue: `needs_review` first, then newest),
`GET /review/{id}` (report detail with all check outputs).

**Acceptance criteria**

- [ ] Queue and detail return 403 for non-reviewer accounts (tests).
- [ ] Detail shows incident/severity probabilities, provenance
  flags, duplicate links, claim similarity, and fusion reasons.
- [ ] The uploader's email is not shown on reviewer pages (test).

### 4.2 Review actions

Actions on `/review/{id}`: `confirm`, `correct` (pick incident type
and severity from the fixed taxonomy), `dismiss`. Each writes a
`review_actions` row (reviewer, action, before, after, time).

**Acceptance criteria**

- [ ] Every action writes exactly one audit row with before/after
  values (test).
- [ ] A corrected report shows "corrected by reviewer" with the new
  values on the owner's result page (test).
- [ ] Review actions never change the stored check outputs; the
  original demo verdict stays visible on the detail page (test).

### 4.3 Abuse and safety basics

**Acceptance criteria**

- [ ] Per-account upload cap from `lite/config.yaml` returns 429
  when exceeded (test).
- [ ] Login attempts are rate-limited per IP by a simple counter in
  config (test with a lowered test value).
- [ ] A repo grep test finds no secret patterns (`AKIA`, `sk-`,
  `ghp_`, `BEGIN ... PRIVATE KEY`, `HF_TOKEN=`) outside an exact-path
  allowlist for docs.
- [ ] Mock-gate rejections, review actions, and account deletions
  all appear in an audit listing readable by reviewers (page
  test). The listing reads the `audit_events` table from spec 2:
  rejection entries show hash, time, and account id only, never
  image bytes or claim text.

### 4.4 Demo pack and final checks

Deliverables: `lite/README.md` run section (install, seed a reviewer,
start server, demo script), plus `lite/DEMO.md` describing exactly
what the demo does and does not prove.

**Acceptance criteria**

- [ ] A fresh checkout following `lite/README.md` reaches a working
  upload and result page (manual run logged by the orchestrator).
- [ ] `DEMO.md` states plainly: zero-shot demo accuracy, mock safety
  gate (not real screening), no forensic detector, no launch or
  pilot claim.
- [ ] Full Lite suite passes; fixture observations from spec 1 and
  the real-model run from spec 2 are summarised in the completion
  report without new accuracy claims.

## Agent notes

- No red-team suite, no load testing, no bias evaluation in Lite.
  Those belong to the full plan's hardening phase, not this demo.
- Do not "improve" CLIP prompts to chase nicer demo numbers during
  this spec. Prompt changes reopen spec 1.
- If a hardening item seems to need new infrastructure (real email,
  real hosting, TLS), it is out of Lite. Log it as a future item in
  the completion report instead.

## Out of scope

Safety-officer console, takedown workflow, NCMEC anything, public
launch checklist, store submission, the full plan's phase 8.

## Definition of done

Every criterion recorded as passing in `lite/logs/spec4_log.md`,
full Lite suite green, `DEMO.md` written, and the completion report
committed. Spec-5 (map) then runs as the final Lite spec.
