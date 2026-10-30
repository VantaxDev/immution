# Dashboard verification — 2026-10-30

## Baseline checked live

PR #1 is open and draft, head `a53a40bfa01406612dd9d3dd4d43069368b16117`,
base `main` at `003c89ff0bfd542baf49e194465c5be209aba5c2`.
GitHub reports MERGEABLE, not approval to merge.

- [tests run](https://github.com/VantaxDev/immution/actions/runs/41102166018): success.
- [Ubuntu integration run](https://github.com/VantaxDev/immution/actions/runs/41102165792): success.
- Both runs identify the exact PR head above. No workflow was rerun on production.

Read-only deployment inspection compared SHA256 hashes: deployed `live.py`,
core `immution.py` and `gate.php` match the PR versions. The deployed LIVE.md
differs only in the older wording about what may be committed in deployment
notes. Service state, process IDs/start times, dashboard launcher and website
file digest were unchanged between the two inspection passes. This does not
prove complete gate coverage or validate event counts. No production logs,
private deployment details or production metrics are included here.

## Reproduced defect and correction

A gzip rotation with a valid gzip header but invalid DEFLATE block type raises
`zlib.error`, which the reader did not catch. This terminates the dashboard
instead of showing an incomplete-read warning. A synthetic regression failed
on the PR baseline with `invalid block type`.

The reader now catches `zlib.error` alongside existing I/O and EOF errors,
reports `READ ERROR`, and continues healthy sources. The regression checks the
initial count, subsequent append, absence of double counting and persistent
warning across refreshes. It never reads production data.

The existing offline JavaScript DOM harness was absent from GitHub CI. The
source job now runs it with an explicit Node 22 setup, without npm packages.
This is not browser rendering or visual verification.

## Local verification

Environment: Python 3.12.3, PHP 8.3.6, Node 18.19.1.

```sh
python3 -m unittest discover -s experimental/dashboard -v
node experimental/dashboard/test_ui.cjs
./scripts/check-release.sh
git diff --check
```

Before the correction: 24 dashboard tests, DOM harness and release checks pass;
the added regression fails. After the correction: 25 dashboard tests pass,
including synthetic PTY navigation/resize/terminal restoration; DOM harness
passes; release checks pass (14 core tests, compilation, shell and PHP syntax,
PHP gate behavior, fixture/config validation and systemd unit verification).

Changes do not alter scoring, permissions, source logs or deployment settings.
No merge, deployment, service restart or production traffic probe was performed.
The production copy still lacks this fix; applying it is a separate decision.

## Remaining verification

Baseline CI success does not certify the correction commit: inspect both
workflows on its exact SHA after publication. Actual light/dark terminal and
desktop/mobile browser visual checks remain outstanding. No new independent
fixed-cutoff production event aggregation was performed. Bandwidth saved
remains unknown without explicit byte evidence.
