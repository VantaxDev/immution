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

## Follow-up completion — 2026-10-31

PR #4 has since merged as main `858aa998ac460daa75bdea98f0944439cb0165cf`.
The original PR #5 commits are preserved. A separate development worktree
integrates current main without rewriting either published history, then
completes the same Host-privacy slice; PR #5 is updated rather than duplicated.
The earlier verification above describes the original 2026-10-30 baseline.

Review found another fallback bypass: hexadecimal/mixed numeric claims such as
`0xc0000201`, `0XC0000201:443`, `0xc0.0.2.1`, `0xc0.0x0.0x2.0x1:80` and
`0300.0x0.2.01`. Two new regression methods produced **six failures** before
the patch (five normalization subcases plus the CLI snapshot/export assertion).
The actual CLI output displayed those claims as top Host labels.

The filter now rejects claims whose dot-separated components are entirely
decimal digits or `0x`-prefixed hexadecimal digits, in addition to the original
numeric/dot-only suppression. It is deliberately conservative, not an IPv4
validator: invalid numeric claims also become `unknown`. No DNS lookup or new
library is needed; existing `re`/`ipaddress` remain sufficient. Normal domains
`0xc0000201.example.invalid` and `0xcafe.invalid` remain visible.

The new subprocess regression executes the current CLI with a fixed custom
date range. Both `--once` and `--export` suppress address labels/IP/query data,
preserve blocked=3 and would_block=1, and aggregate the three blocked claims
as `unknown`. Explicit `--site` numeric/hex claims are refused without repeating
the supplied value in stderr. Existing top-N, date/DST, no-clobber and viewport
tests continue to run on the integrated feature set.

Verified locally after the change:

- **47 dashboard tests PASS**, including PTY, the original three privacy tests
  and two new regressions.
- **14 core tests PASS** via the release check; DOM harness, compilation,
  shell/PHP/config/systemd checks and whitespace PASS.
- Protected paths `src config packaging scripts VERSION` have no difference
  from current main. Diff review: only Host-label normalization, synthetic
  regressions and documentation; no engine/gate/scoring changes.

Hosted CI must be checked on the published head, separately from these local
results. This round has **no server access, merge into main, or deployment**.

## Remaining backlog

- PR #5 review/merge and any deployment need separate authorization; this
  fix is not installed by this development round.
- Release checklist human gates (representative monitor workload, review of
  legitimate paths/exclusions, proxy identity and private reporting decisions)
  remain open; no stable-release claim or invented operational evidence.
- Claimed domains can contain private identifiers: this is not general-purpose
  anonymization, verified vhost attribution or proof of detector coverage.
