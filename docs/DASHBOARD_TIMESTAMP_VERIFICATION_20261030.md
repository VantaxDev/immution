# Dashboard timestamp robustness — 2026-10-30

## Selection and current baseline

GitHub PR #1 remains open/draft at `a53a40bfa01406612dd9d3dd4d43069368b16117`.
PR #2 remains open/draft at `4c3ce549c2e5da997390f587a4bc7b2ac9ed0b80`;
all its push/PR checks were green when inspected. There are no open GitHub issues.
Local verification checkout was clean. The existing release checklist still
requires human monitor-mode and deployment-specific evidence; no such evidence
is claimed by this change.

This focused follow-up branches from PR #2, preserving its gzip fix and DOM CI
coverage without repeating or modifying either PR. Branch:
`fix/dashboard-timestamp-overflow-20261030`.

## Reproduction and fix

An ISO timestamp can parse successfully but overflow when converted to Rome:
`0001-01-01T00:00:00+23:59` and `9999-12-31T23:59:59-23:59`.
The dashboard previously terminated with `OverflowError: date value out of range`
instead of continuing to subsequent CSV records.

The new regression failed against the unchanged PR #2 source. The reader now
classifies this error as malformed input, using its existing visible issue
counter. The test checks both date boundaries, healthy blocked/monitor records
in the same file, and subsequent appends without duplicate counts or issues.
No dependencies, scoring, permissions, daemon or gate behavior change.

## Verification performed

- `python3 -m unittest test_live.LiveTests.test_timestamp_conversion_overflow_does_not_stop_ingestion -v`
  from `experimental/dashboard`: ERROR before the fix (OverflowError).
- `python3 -m unittest discover -s experimental/dashboard -v`: 26 passed after
  the fix, including the new regression and existing PTY checks.
- `node experimental/dashboard/test_ui.cjs`: PASS.
- `./scripts/check-release.sh`: PASS, including 14 core tests, compilation,
  shell/PHP checks, gate smoke test, fixture/config and systemd verification.
- `git diff --check`: PASS.

Tests used only temporary synthetic files. No production access, merge, deploy,
service restart or manual automation execution was performed. Hosted CI for
this follow-up must be checked on its published head, not inferred from PR #2.
Visual terminal/browser checks and human release gates remain open separately.
