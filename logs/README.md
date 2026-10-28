# Spec logs

One log file per spec: `logs/specN_log.md` (N = 0-8; phase 7 is web,
phase 8 is hardening after the Android-only renumbering).

- **Only the orchestrator writes logs.** Builders return their entry as
  text; the orchestrator appends it, one entry at a time. Builders run
  one at a time, so entries never interleave.
- **Creating a log file.** If `logs/specN_log.md` does not exist when a
  phase starts, the orchestrator creates it with `muse.write_file`
  (a title line plus a final `<!-- END-OF-LOG -->` sentinel) before
  dispatching any builder. This is orchestrator work, not a brief:
  Phase 0's file-creation objective comes after the first entries.
- **Append-only.** Nobody edits or removes earlier lines.
- **Append method:** every log file ends with a sentinel line
  `<!-- END-OF-LOG -->`. To append, the orchestrator uses
  `muse.edit_file` to replace the sentinel with the new entry, its
  verdict, and the sentinel again, then reads the file back with
  `muse.read_file` to confirm the entry is intact and the sentinel is
  still last. Never use PowerShell `Add-Content`, `Out-File`, `>>` or
  here-strings on logs. Entries must never contain the sentinel line
  itself (a builder quoting it breaks the unique match); if one does,
  the orchestrator paraphrases the quote before appending. For long
  logs, page with `offset`/`limit` to confirm the sentinel is last.
- **Encoding:** UTF-8 without BOM, LF line endings, plain ASCII text.
- At phase start, the orchestrator writes a `## Phase start` section:
  date, session model and effort recorded as `unobserved` (no Muse
  tool reports them; per-brief workflow tiers, where used, are recorded
  per brief instead), dispatch mechanism per brief (native/workflow),
  missing human inputs with the mock or fallback for each, objectives
  left open by earlier phases, and the builder roster (spawn IDs or
  workflow run ids, objectives, `started_at`).
- Each builder entry contains: brief type, dispatch, files
  touched/created, tests and results, test-integrity statement,
  dependencies (version + license), resources and budget used,
  checkpoint state, mocks, decisions, any stop signal (including
  `ENV-BLOCKED` with the exact environment error), and ends
  `Status: PROVISIONAL`.
- Under each entry the orchestrator adds its verdict: `ACCEPTED`,
  `REJECTED` (failed gates named), `NEEDS-USER-APPROVAL` (question or
  missing input stated), or `ENV-BLOCKED`, plus wall time from the
  roster timestamps and the commit hash for accepted work. There is no
  partial or deferred acceptance verdict: a criterion that could not be
  run, or that passed only on a mock or provisional substitute, keeps
  its objective open under one of the statuses above.
- The orchestrator appends a `# Spec completion report` only once every
  objective in the spec is ACCEPTED. The first phase of a block then
  transitions automatically to the second phase (no manual stop); the
  second phase's log also gets a `# Block N handoff` paragraph before
  the orchestrator stops and waits for the next block command
  (orchestrator §1, §11). If any objective is open, the orchestrator
  appends a `# Phase status` note listing it and its blocker instead,
  and the block stops. Only one spec is ever active at a time.
- Acceptance state lives here, not in the specs: agents never edit
  `specs/**`, so a criterion counts as met only when this log records
  it passing. The `- [ ]` boxes in a spec stay unticked forever.
- Never write secrets, personal data, image content or thumbnails, or
  details from policy datasets in any log. Builders must not state a
  model or effort in their entries (they cannot observe them reliably);
  the orchestrator records those from the brief (tier for workflow
  dispatch, `inherit` for native).
