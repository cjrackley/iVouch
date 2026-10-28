# Lite spec logs

One log per Lite spec: `lite/logs/specN_log.md` (N = 0-5, matching
`lite/specs/spec-N-*.md`).

- Only the orchestrator writes logs. Builders return their entry as
  text plus a copy at the brief's `entry_file`; the orchestrator
  appends it. Builders run one at a time, so entries never interleave.
- If a log file is missing when a spec starts, the orchestrator
  creates it with `muse.write_file` (title line plus final
  `<!-- END-OF-LOG -->` sentinel) before dispatching any builder.
- Append-only. Every file ends with the sentinel line
  `<!-- END-OF-LOG -->`. Append by using `muse.edit_file` to replace
  the sentinel with `<entry>\n\n<verdict>\n\n<!-- END-OF-LOG -->`,
  then read the file back to confirm. Never use PowerShell
  `Add-Content`, `Out-File`, `>>`, or here-strings on logs.
- Encoding: UTF-8 without BOM, LF line endings, plain ASCII. Entries
  never contain the sentinel line itself.
- At spec start the orchestrator writes a `## Spec start` section:
  date, session model/effort as `unobserved`, dispatch per brief,
  baseline `git status --short`, missing inputs with fallbacks, and
  the builder roster (spawn ids, objectives, `started_at`).
- Each builder entry holds: brief type, files touched/created, tests
  and results, test-integrity statement, dependencies (version and
  licence), resources and budget used, checkpoint state, mocks, any
  stop signal (including `ENV-BLOCKED` with the exact error), and ends
  `Status: PROVISIONAL`.
- Under each entry the orchestrator adds its verdict: `ACCEPTED`,
  `REJECTED` (failed gates named), `NEEDS-USER-APPROVAL`, or
  `ENV-BLOCKED`, plus wall time and, for accepted work, the commit
  hash. A criterion that passed only on a mock has not passed unless
  the spec defines it against that mock.
- After each verdict, append a one-line
  `# Spec status: <done>/<total> ACCEPTED; open: <ids + statuses>`
  note so the next session rebuilds state from that line alone.
- Append `# Spec completion report` only once every objective in the
  spec is ACCEPTED. Otherwise append `# Spec status` naming the open
  objectives and stop.
- Acceptance state lives here, never in the specs. The `- [ ]` boxes
  in a spec are source text and stay unticked forever.
- Never write secrets, personal data, image content, or thumbnails
  in any log.
