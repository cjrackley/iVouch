# Spec logs

One log file per spec: `logs/specN_log.md` (N = 0-9).

- Tasks from spec 1 go in `spec1_log.md`, spec 4 tasks in `spec4_log.md`, and so on.
  Never mix specs in one file.
- **Only the orchestrator writes logs.** Builders return their entry as text; the
  orchestrator appends it, one entry at a time, so parallel builders never interleave.
- **Append-only.** Nobody edits or removes earlier lines.
- **Encoding:** UTF-8 without BOM, LF line endings, plain ASCII text. Each entry is written
  in one append with an encoding-controlled method (see `agents/orchestrator.md` §6.2), then
  read back to confirm the file still decodes as UTF-8.
- At phase start, the orchestrator writes a `## Phase start` section: date, model and effort
  from Muse Code's records, missing human inputs with the mock or fallback for each, deferred
  criteria carried over from earlier phases.
- Each builder entry contains: brief type, files touched/created, tests and results,
  test-integrity statement, dependencies added (version + license), resources and budget
  used, mocks, decisions, any stop signal, and ends `Status: PROVISIONAL`.
- Under each entry the orchestrator adds the model (runtime ID from Muse Code's records),
  effort, wall time, and its verdict: `ACCEPTED`, `ACCEPTED-WITH-BLOCKERS` (listing deferred
  criteria), `REJECTED` (naming the failed gates), or `NEEDS-USER-APPROVAL` (with the
  question), plus the commit hash for accepted work.
- The orchestrator appends a `# Spec completion report` section once every objective in the
  spec is ACCEPTED or ACCEPTED-WITH-BLOCKERS.
- Never write secrets, personal data, image content or thumbnails, or details from policy
  datasets in any log.

`logs/model_phase_log.md` is a closed record of the one-time setup test run on 2026-10-27
(its spec has since been removed). Don't append to it.
