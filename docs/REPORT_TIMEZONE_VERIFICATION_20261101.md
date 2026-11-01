# Report timestamp regression — 2026-11-01

## Defect and narrow remedy

`immutionctl report` accepted both timezone-aware and timezone-less ISO dates,
then called `min`/`max` on the combined list. A synthetic CSV mixing
`2026-07-22T11:30:00+02:00`, `2026-07-22T10:00:00Z`, and
`2026-07-22T09:00:00` reproduced a TypeError instead of a completed report.

The gate emits explicit offsets. Keep the shared parser unchanged, but require
an explicit timezone for report time bounds. Skip ambiguous dates with the
existing invalid-timestamp warning, expanded to explain the exclusion. Do not
assume server timezone or UTC for missing offsets. Counts still include all
rows; aware dates compare by instant and retain their original offset in output.

## Regression and verification

The new CLI regression contains two subcases: mixed aware/naive/malformed
rows, and naive-only input. Before the change: one error (mixed comparisons)
and one assertion failure (ambiguous date treated as valid). After: both pass.
Tests check chronological ordering across different offsets, event/action/IP
counts, warnings, omission of ambiguous bounds, IP/query suppression and
byte-for-byte unchanged input. All fixtures use documentation-only addresses.

Local checks:

- Core/CLI: 15 tests passed.
- Dashboard: 42 tests passed; offline DOM harness passed.
- `./scripts/check-release.sh`: passed (Python compilation, shell syntax,
  PHP syntax/gate smoke, config fixture and systemd verification).
- `git diff --check`: passed; manual diff review completed.

Hosted Python/PHP compatibility and Apache integration results are recorded in
the PR checks, not inferred from these local checks.

## Boundaries and backlog

Only the read-only report, tests and docs change. No scoring, gate, policy,
config, installer, dependency or schema change. No live logs or SSH used.
Legacy/custom timezone-less rows now generate a warning rather than misleading
time bounds or a crash. This does not validate event authenticity or extend
report coverage to rotated files. PRs #5, #6 and #7 remain independent; their
privacy/source-safety/explanation work is neither duplicated nor included.
Merge, deployment and operational monitor evidence require separate authority.
