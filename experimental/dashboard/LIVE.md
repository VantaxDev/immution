# Live terminal dashboard (experimental, Python 3.9+)

Read-only gate-event viewer, separate from the engine, installer and unchanged
offline terminal.py prototype. Standard library only: curses, zoneinfo and
system Europe/Rome timezone data. No packages, endpoints or services added.
Run from this checkout: **live.py, presentation.py and timeframes.py must stay
together** (copying only live.py from an older installation is not enough).

```sh
python3 experimental/dashboard/live.py --log /path/to/events.csv
python3 experimental/dashboard/live.py --log /path/to/events.csv --timeframe previous-week
python3 experimental/dashboard/live.py --log /path/to/events.csv --timeframe last7 --top 5
```

Without --log, reads /var/log/immution/events.csv and
/var/log/immution/prioris/events.csv. Repeat --log for independent sources,
not duplicate aliases of the same file. Source numbers are file provenance,
not verified sites. Use an account permitted to read the logs.

## One screen, not a scrollable report

Target **80x24** (79 printable columns to avoid terminal wrap). Metrics, range,
top claimed Hosts, Other, warnings, coverage and controls fit one viewport.
There is no scrolling offset: j/k, up/down and PageUp/Down do not scroll.
Help replaces the host area instead of appending a document. Resize recomputes
the layout. Small terminals show compact metrics/range and UNKNOWN coverage;
extreme sizes necessarily omit detail. Quit stays on the final row, even at
1x1. Use a dump for full text and unabbreviated names.

--top N sets a maximum of 1..20 (default 5), reduced further if the viewport
needs room for metrics. Ranking uses **blocked event records only**, descending,
with claimed hostname as deterministic tie-breaker. Monitor-only Hosts do not
enter the top. **Other includes every omitted Host**, including monitor-only
and rows hidden by height/top limit. Top + Other equals complete selected-scope
totals. IP unique counts overlap and must not be summed. A ~ marks a shortened
label, never a verified site identity or proof of a protected site.

- 1: today; 2: yesterday; 3: last7; 4: previous calendar week.
- t: cycle presets (from a custom range, return to today).
- Tab / n / p / left / right: claimed Host filter; 0: all Hosts.
- r: bounded refresh; ?: help; q: quit.

--site example.org selects an untrusted claimed Host, not a trusted vhost.
IP/URL scope arguments are rejected; unknown selects rejected/non-domain claims.
Scope is explicit at 80x24; tiny views can abbreviate it. Default colors are
inherited from the terminal, including SSH light/dark themes. No palette
redefinition or forced background; curses restores terminal state.

## Calendar windows

All windows are **[inclusive start, exclusive end)** at local midnight in
**Europe/Rome**, not UTC dates or fixed 24-hour durations:

| Preset | Calendar window |
|---|---|
| today (default) | Today 00:00 to tomorrow 00:00 |
| yesterday | Yesterday 00:00 to today 00:00 |
| last7 | Six calendar dates before today through today; end tomorrow |
| previous-week | Previous Monday 00:00 to following Monday 00:00 (Mon-Sun) |

On Friday 2026-10-30, previous-week is
[2026-10-19T00:00:00+02:00, 2026-10-26T00:00:00+01:00), **169 hours**.
last7 instead starts 2026-10-24. DST days can be 23 or 25 hours; repeated hours
remain distinct by date and UTC offset internally. Event timestamps must be
timezone-aware; invalid/overflowing conversions are counted as malformed.

Custom ranges take dates, not ambiguous local clock times. Both options are
required, --end is exclusive and later than --start, and --timeframe cannot
be combined with them:

```sh
python3 experimental/dashboard/live.py --log /path/to/events.csv \
  --start 2026-10-19 --end 2026-10-26
```

Generated/as-of time is shown. Records at or after the earlier of generation
time and requested end are excluded. Future portions are not observations.
Presets move at local midnight (previous-week on Monday); custom dates stay
fixed. Changing actual bounds resets the event cache and rereads available
logs **once**, incrementally under the normal budget. Re-selecting identical
bounds does not reread them.

## Snapshot and manual historical dump

--once prints a deterministic, ordered plain-text snapshot, not the compact
screen. Non-TTY and dumb-terminal fallback do the same. Same input state,
cutoff and sampled service status produce the same output; generation time is
intentionally included. Dumps contain UTC generation, explicit range with
offsets/timezone, effective cutoff, complete selected totals, top N plus Other,
selftest/future exclusions, per-source counts, issues, warnings and coverage.
No raw IP, URI, query, UA or reason is emitted.

```sh
python3 experimental/dashboard/live.py --log /path/to/events.csv \
  --timeframe previous-week --once

# NEW private file (0600); existing files AND symlinks are refused.
python3 experimental/dashboard/live.py --log /path/to/events.csv \
  --timeframe previous-week --top 10 --export ./immution-2026-W43.txt

python3 experimental/dashboard/live.py --log /path/to/events.csv \
  --start 2026-10-19 --end 2026-10-26 --export ./immution-custom.txt
```

--export FILE implies a single snapshot, writes no dashboard to stdout and
does not create parent directories. Choose fresh filenames: no overwrite flag.
Shell redirection follows shell overwrite rules; use --export for no-clobber.
Host aggregates can still be private: review before sharing. **No scheduled
archival, cron or service is created.**

## Coverage and bounded work

Counts are parsed gate event records, not all HTTP requests, bots, verified
sites protected or effectiveness. blocked and would_block (allowed) remain
separate. Exact known selftest host+URI+UA markers are excluded/reported, but
spoofable. Parsed-event cache retains salted IP digests, not raw IP/URI/UA or
reasons. A bounded partial-record buffer can temporarily hold unparsed input;
it is never dumped.

Numeric and YYYYMMDD rotations, optionally gzip, are recognized. No legacy
blocked.csv or missing historical data is synthesized. Budget: **8 MiB
decompressed per refresh**, **128 descriptors**, **300000 selected-range
events**. A snapshot/export performs one refresh and may therefore show
CATCHING UP / INCOMPLETE on large histories. It does not silently force a full
scan to manufacture completeness. Interactive refreshes catch up. In-memory
summaries/top rankings are cached between refreshes; normal ticks read appended
bytes, not all historical bytes again.

Renamed inodes are retained; compression of consumed rotations is skipped.
Copytruncate is racy and flagged; rapid truncate-and-regrow can evade detection.
Bad gzip/DEFLATE produces READ ERROR without stopping healthy files. Partial
records wait for newline; multiline/malformed records are skipped visibly.
Empty/wrong headers, missing/unreadable sources and capacity/read/file/rotation
limits stay explicit.

**History/coverage always UNKNOWN.** Dates with parsed event evidence are shown,
but no records can mean idle traffic OR missing logs; neither gaps nor
completeness are inferred. Evidence on every date does not prove continuity.
Retention loss, logging failures and gate coverage cannot be reconstructed.
Service samples are not a follower heartbeat. No production-count audit implied.

## MB saved

MB RISPARMIATI: N/D stays prominent by default: events.csv has no byte evidence.
No heuristic defaults are imported. BOTH optional integers --baseline-bytes N
and --block-bytes N (0..10^15) enable an explicit **STIMA**: blocked records *
(baseline - block bytes) / 1,000,000. Negative estimates stay negative. Selected
range/Host applies; monitor and selftest records save no bytes. This is not
measured network traffic. Three ASCII digit rows appear only when height AND
width suffice, never causing scrolling.

## Verification and deployment boundary

```sh
python3 -m unittest discover -s experimental/dashboard -v
node experimental/dashboard/test_ui.cjs
./scripts/check-release.sh
```

See [synthetic compact/dump demo](COMPACT_DEMO.txt). PTY tests cover 80x24,
presets, navigation, help, resize, colors and terminal restoration. Regressions
cover DST, exclusive ends, cache switching, gzip rotations, incomplete history,
totals conservation, sanitized/no-clobber exports and bounded viewports. They
use no production logs and do not certify every terminal emulator visually.

This expansion stays branch/PR-only until separately approved for merge/deploy.
Future additive/versioned installation must copy all three runtime modules,
with launcher rollback. Do not modify engine, gate, logs, Apache or services.
Production validation must separately verify SHA, SSH PTY and service identities.
