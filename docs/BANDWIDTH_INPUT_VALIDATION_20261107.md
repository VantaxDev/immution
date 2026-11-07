# Bandwidth estimate input validation — 2026-11-07

The standalone `tools/immution_bandwidth.py` CLI previously accepted negative
`--block-bytes` and `--fallback-bytes` values. A negative block response size
inflates avoided traffic; a negative fallback size creates impossible response
totals. Both options now require non-negative integers through argparse, before
opening any input file. Zero remains valid (empty responses or explicit zero
overhead), defaults are unchanged, and a negative *net estimate* remains possible
when valid block response sizes exceed estimated original response sizes.

The standard-library argparse validator needs no dependency. Regression tests
verify both negative options produce exit status 2 and a clear option-specific
error before file access; a real synthetic CSV checks that both zero values
remain accepted. Both negative-option subcases failed before the fix.

Verification: all 56 core/CLI tests pass; Python compilation and
`git diff --check` pass. Existing explicit-action tests are unchanged. No
dashboard, scoring, installer, schema, service or production behavior is changed.
Hosted compatibility CI has not been run for this local-only branch.
