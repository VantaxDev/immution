# Numeric claimed-Host redaction — 2026-10-30

Base: main `51f12688a4fe28b68687b00fca21bd63a3e1b94f`.

## Backlog and selected task

GitHub had no open issues. PR #4 (compact overview, calendar timeframes and
exports) remained open at `c57726cd4742e43c69091eac3036030dc37b2d34`, with all
reported checks successful. This independent fix starts at main, does not
repeat that feature work and does not alter its branch.

## Reproduction and fix

The live dashboard promises not to display IPs, but strict `ipaddress` parsing
rejects ambiguous numeric address spellings. The hostname fallback then accepted
`192.000.002.001`, `192.000.002.001:80`, `3221225985` and `192.513` as displayable
claims. All samples are synthetic, based on the documentation-only 192.0.2.0/24
range. Three regression tests run before the implementation change produced
five failures: four normalization subcases and the aggregate-output assertion.
Ordinary IPs, trailing-dot addresses and bracketed IPv6 were already hidden.

After removing the optional port, numeric/dot-only claims now become `unknown`
before hostname fallback. Uses existing Python `re`; adds no dependency, DNS
lookup, network request or per-refresh scan. Domain labels with numeric prefixes
(including `192.0.2.1.example.invalid`) remain visible: this is not a general
hostname anonymizer or validation/authentication of claimed Host.

Counts are preserved rather than dropping events: the synthetic reader fixture
retains blocked=3 and would_block=1, with the three numeric claims aggregated in
`unknown` and the ordinary monitor-mode domain still visible. Only the Host
label changes; scoring, gate, permissions and event parsing do not change.

## Verification

- `python3 -m unittest discover -s experimental/dashboard -v`: 29 PASS,
  including three new regressions and the existing terminal/PTY tests.
- `node experimental/dashboard/test_ui.cjs`: PASS.
- `./scripts/check-release.sh`: PASS, including 14 core tests, Python
  compilation, shell/PHP syntax, PHP smoke test and systemd unit validation.
- `git diff --check`: PASS.
- Compatibility with PR #4 checked in a disposable archive of a computed tree
  (`git merge-tree --write-tree`, no branch/merge commit created): no conflicts;
  all 45 combined dashboard tests PASS, including PTY, timeframe and export
  regressions. The first compatibility check found a test-only assumption that
  monitor-only hostnames always appear in the dump; PR #4 intentionally groups
  them in Other. The new regression now verifies the filtered summary instead,
  retaining the numeric-label output checks. No implementation change needed.

CI evidence for the published head is recorded in the workspace automation
report, not inferred from local tests. No live server integration, merge,
deployment, site update or production access is part of this task.

## Remaining backlog

- PR #4 still needs owner review/authorization before merge or deployment.
- This independent PR needs review; combine through ordinary GitHub flow, not
  by rewriting PR #4. Both change different areas of `live.py`.
- Existing visual/human release gates remain separate; this fix is not a
  declaration of a stable release.
