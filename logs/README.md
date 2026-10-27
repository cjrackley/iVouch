# Spec logs

One log file per spec: `logs/specN_log.md` (N = 0-9).

- Tasks from spec 1 go in `spec1_log.md`, spec 4 tasks in `spec4_log.md`, and so on.
  Never mix specs in one file.
- **Append-only.** Nobody edits or removes earlier lines. The orchestrator rejects any log
  diff that changes existing lines.
- At phase start, the orchestrator writes a `## Phase start` section: date, missing human
  inputs with the mock or fallback for each, deferred criteria carried over from earlier phases.
- The builder appends one entry per attempt (tests briefs and implementation briefs alike)
  with: exact model ID, tier, effort, brief type, files touched/created, tests and results,
  test-integrity statement, dependencies added (version + license), resources and budget
  used, mocks, decisions, any stop signal. Builder entries always end `Status: PROVISIONAL`.
- The orchestrator appends a verdict under each attempt: `ACCEPTED`, `ACCEPTED-WITH-BLOCKERS`
  (listing deferred criteria), `REJECTED` (naming the failed gates), or `NEEDS-USER-APPROVAL`
  (with the question), plus the commit hash for accepted work.
- The orchestrator appends a `# Spec completion report` section once every objective in the
  spec is ACCEPTED or ACCEPTED-WITH-BLOCKERS.
- Never write secrets, personal data, image content or thumbnails, or details from policy
  datasets in any log.
