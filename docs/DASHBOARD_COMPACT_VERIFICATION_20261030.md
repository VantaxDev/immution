# Compact timeframe dashboard — 2026-10-30

## Scope and baseline

Branch `feat/dashboard-timeframes-compact`, from main
`51f12688a4fe28b68687b00fca21bd63a3e1b94f`. Previously merged PRs #1/#2/#3,
including gzip and timestamp-overflow regressions, are preserved. No duplicate
fix, engine/gate/scoring, installer, service, scheduler or website change.
This expansion is for review only: **no merge or deployment authorized here**.

The existing reader and standard-library curses/zoneinfo are reused. Runtime
presentation and date-window logic are separated into two small local modules;
all three runtime files must travel together in any future approved deployment.

## Observable change

- Single-viewport overview, target 80x24 with 79 printable columns; no scroll
  offset or off-screen report. Compact fallback, resize and bounded help.
- Top blocked claimed Hosts (default 5, configurable 1..20), deterministic
  hostname tie-breaker. Monitor-only/hidden hosts aggregate into Other; complete
  selected-scope totals remain independent of the displayed list length.
- Preset keys 1/2/3/4 and t: today, yesterday, last7 including today, previous
  Monday-Sunday calendar week. Custom CLI date range has exclusive --end.
- Europe/Rome midnight boundaries converted to UTC for comparison; 23/25-hour
  days and 167/169-hour weeks are not treated as fixed UTC durations. As-of
  generation is an additional exclusive cutoff, never counting future records.
- Changing real bounds rebuilds a cache once under the existing bounded read
  budget. Ordinary refresh reads appended bytes; summaries/top ranks are
  cached. Only global/current-Host summaries are retained between refreshes.
- Ordered sanitized --once text and --export FILE: generated time, exact range,
  timezone/offsets, totals/top/Other, exclusions, source counts, warnings and
  UNKNOWN history. Exclusive create refuses existing files and symlinks;
  exports are private (0600), with no automatic archive schedule.
- Default terminal colors and prominent MB N/D or explicit STIMA preserved.
  ASCII digits need both height and width; negative estimates stay negative.

## Reproduction and synthetic demo

Unchanged main, synthetic CSV with 20 blocked claimed Hosts, 79 columns:
`panel_rows` produces **43 content rows**, before its additional screen chrome.
It cannot fit a 24-row viewport without scrolling. This baseline was run, not
inferred from source. The new layout is bounded by both dimensions for many
viewports; j/k/PageDown do not move the overview.

[COMPACT_DEMO.txt](../experimental/dashboard/COMPACT_DEMO.txt) contains actual
renderer output from temporary synthetic CSV/gzip, fixed generation time
2026-10-30T17:00:00Z. The 80x24 example uses **22 rows**: blocked 35, monitor 26;
top five blocked counts 12+8+6+4+3, Other B=2/M=22; one selftest excluded.
These are illustrative fixtures, **not production measurements**.

The historical dump demonstrates previous-week
`[2026-10-19T00:00:00+02:00, 2026-10-26T00:00:00+01:00)` and explicitly
reports evidence on only 2/7 dates (idle OR gaps, never a fabricated history).

## Checks executed locally

```sh
python3 -m unittest discover -s experimental/dashboard -v
node experimental/dashboard/test_ui.cjs
./scripts/check-release.sh
python3 -m py_compile experimental/dashboard/live.py experimental/dashboard/presentation.py experimental/dashboard/timeframes.py
git diff --check
git diff --exit-code origin/main -- src config packaging scripts VERSION
```

- **42 dashboard tests PASS** (26 existing plus 16 additions).
- DOM harness PASS.
- Release check PASS, including **14 core tests**, compilation, shell/PHP
  syntax, PHP gate smoke, config/fixture and systemd-unit validation.
- Explicit compilation, whitespace and protected-source diff checks PASS.

Regressions cover exact inclusive/exclusive edges and generation cutoff;
Rome midnight; spring/fall DST, repeated-hour offsets and year/week crossover;
custom date validation; plain/gzip rotations and compression deduplication;
read budget and append-only reads; preset switching and midnight cache reset;
missing/idle history; top blocked ranking/ties and Other conservation;
sanitized/deterministic dumps, exclusive exports and symlink refusal;
STIMA height/width limits; layout bounded from tiny viewports to 80x24 and
larger; ignored scrolling keys. Local POSIX PTY exercises default-color modes,
80x24 startup, Host/help/preset controls, resize to tiny dimensions, quit and
exact terminal-attribute restoration. No OSC palette commands emitted.

GitHub CI must be verified on the published branch SHA; local PASS is not a
substitute for hosted integration. No live-host integration script was run.

## Deliberate limitations and next authority

History is UNKNOWN even with records on every date: CSV retention/continuity
and real gate coverage cannot be proven. Empty dates can be idle OR missing.
One dump uses one bounded refresh and can be incomplete while catching up;
capacity/file limits and malformed records stay visible. Partial buffers may
temporarily hold unparsed input but are never exported. IP digests are salted;
no raw IP, URI/query, UA or reason is emitted.

No real SSH/production or visual-emulator deployment verification for this new
expansion; no production logs, website changes, monitoring or archiving jobs.
Previous production version remains in place. Merge/deploy requires a new
explicit approval after review. Future deploy must include all runtime modules
and separately verify SHA, SSH PTY and unchanged service identities.
