# Daily site traffic: browser-compatible session estimate

This experimental terminal dashboard is a **review candidate**, not deployed.
It does **not** report people, verified humans, unique visitors or all visits.
Its visible copy is `VISITE / STIMA BROWSER N osservate | YYYY-MM-DD`, followed
by the selected site, `non persone`, coverage `UNKNOWN`, ambiguous/bot/scanner/
internal group counts and the last observed record. With no usable source it
shows `N/D`, never a claimed zero humans. The default timeframe is today.

## Use an explicitly selected vhost log

```sh
python3 experimental/dashboard/live.py --log /path/to/events.csv \
  --access-log example.org=/path/to/example.org.access.log --site example.org
# Repeat --access-log for up to 16 independent sites; n/p selects a site.
# Counts-only full daily breakdown and existing no-clobber private export:
python3 experimental/dashboard/live.py --log /path/to/events.csv \
  --access-log example.org=/path/to/example.org.access.log --once
```

No Apache logs are discovered by default. Configure **one selected-vhost Apache
Combined log per site**, already readable by the invoking account, not a
mixed global log. The mapping is an operator assertion, not inferred from an
untrusted Host header. Use the canonical site matching the referrer host;
aliases such as www are not automatically merged or considered same-site.
No installer, logging permissions, vhost, service or scheduler is changed.
`traffic.py` must accompany live.py, presentation.py and timeframes.py.

## Metric (version 1, intentionally conservative and unvalidated)

- Parse IP, timezone-aware Apache timestamp, method/target, status, referrer and
  UA from Combined records. Unsupported/malformed formats are explicit issues.
  IPv4-mapped IPv6 addresses normalize to their IPv4 address before grouping,
  bot/probe correlation and loopback classification. Native IPv6 stays distinct;
  this is address normalization, not reconciliation of visitor identities.
- Group within each mapped site and **Europe/Rome local calendar day** by
  process-salted IP+UA digests; inactivity **greater than 30 minutes** starts
  another group. At midnight groups reset rather than spanning day attribution.
- Precedence, mutually exclusive: recognized internal/test (loopback or exact
  IMMUTION audit/self-test UA prefix), recognized probe path scanner, declared
  bot/tool/headless/monitor UA, browser-compatible evidence, ambiguous remainder.
  These are signatures, not verified bot identities or exhaustive exclusions.
- Browser-compatible evidence requires a Mozilla/5.0 browser-family UA, at
  least two successful GET200 page-like requests, at least ten seconds apart,
  with a later page request carrying a same-site HTTP(S) referrer. Pages have
  no extension or .html/.htm/.php; API/health/metrics paths are excluded. Assets,
  favicon, redirects, errors, POST and 304 alone cannot promote a group.
- Any recognized bot/tool or probe by the **same IP on that local day in any
  configured selected-range source**, even a different UA, downgrades otherwise
  browser-like groups to ambiguous. Evidence outside the selected range or
  unavailable sources is unknown. NAT can consequently downgrade real people.
- The count is browser-compatible **groups**, not a validated probability of
  human presence. Spoofed UA/referrer and scripted reloads can still qualify;
  real landing-page readers, cached pages and single hits may stay ambiguous.
  Single successful home+browser UA is not enough: 653 synthetic single-hit
  candidates remain 653 ambiguous groups, not 653 humans.

NAT/shared IP+UA can merge different people. Changing IP or UA, session timeouts
and midnight resets can split one person. There is no identity reconciliation,
unique-person claim, bot subtraction formula, confidence percentage or ground
truth. Browser-like sessions are not a lower bound on humans. All five class
counts refer to groups; separate `requests` is a record count.

## Calendar, coverage and cache

The existing half-open local-day/range resolver is reused. Local midnights use
Europe/Rome timezone transitions, including 23-hour and 25-hour days. Ordering,
timeouts, range checks and generation cutoff use UTC instants; repeated local
hours remain distinct. The current generation cutoff is exclusive. The compact
card in the gate-event view shows the latest local date with observed records in the selected range;
`--once`/`--export` lists each observed date per site. No data for a day is not
synthesized as zero. Day and exact range remain visible.

The traffic-first interactive view instead summarizes **all observed groups in
the selected period**, with a bounded recent-day table and mapped-site
comparison. `v` switches views without changing site/period. Counts remain
groups, not unique people across dates/sites. The daily table uses N/D on dates
without usable records, not invented zeros. See [LIVE.md](../experimental/dashboard/LIVE.md#traffic-first-view)
for navigation, missing-metric diagnosis, freshness caveats and a reproducible
explicit DEMO of the actual renderer.

History/coverage are **always UNKNOWN**. First/last record and snapshot time
are evidence, not proof of logging continuity or freshness. Empty, absent,
unreadable, truncated, nonregular, partial, unparseable or budget-limited inputs
never establish no visits. Any detected issue says INCOMPLETE; usable counts
remain explicitly *observed*. Copytruncate/rapid truncate-regrow, overwritten
records, duplicate rotations and upstream log loss cannot always be detected.

Bounded traffic scan: 8 MiB decompressed per changed snapshot across sources,
100000 retained selected-range records, 16 sites, 32 discovered files per site,
128 files overall and 64 KiB per line. Active then recognized numeric rotations
(including gzip) are read in numeric suffix order (.1, .2, ... .10); when the
per-site file cap is exceeded, the lowest suffixes are retained independently
of directory enumeration order, with a file_limit warning. Numeric suffixes
are a logrotate convention, not verified event-time ordering. Compression
overlap is resolved before the file cap; overlapping .N and .N.gz prefer .N, shared inodes
are not counted twice. No unbounded full-history read to manufacture complete
coverage. Large files are scanned from the **prefix**; recent records can be
outside the budget. Errors/caps are visible, not silently extrapolated. The traffic viewport names
source issue codes; when read_budget is reached it explicitly explains the
8 MiB prefix scan and possibly omitted recent records. Full issue counts remain
available via --once / --export. Narrow screens may shorten this explanation.
Regular-file/nonblocking open with opened-inode checks prevents FIFO hangs.
Gzip errors do not prevent other healthy sources from contributing.

On unchanged source size/mtime/inode/window, refresh reuses sanitized events
without rereading content. A changed snapshot replaces, not accumulates, prior
observations; lower size is flagged. A changing cutoff always recomputes
aggregates. This preserves the existing independent incremental gate-event
cache; no engine scoring or enforcement changes.

## Privacy and verification boundary

Only timestamps, operator-supplied DNS site labels, salted IP and UA digests,
and classification booleans are retained in the traffic event cache. Raw log
lines exist transiently during parsing, not in exports/cache/preview. No raw IP,
UA, URI, referrer, query or private log path is exported. Reports contain only
counts per site/day, ranges, coverage/issue names and observed timestamps.
No DNS/reputation lookup, cookies, JS beacon, external analytics, persisted
identifier or network call is added. Existing export 0600/no-clobber semantics
and gate-event privacy/nonregular-source prerequisites are retained.

Tests use synthetic documentation IP ranges, no production logs. The visual
preview is generated from the actual terminal `panel_rows` renderer, explicitly
marked synthetic; it does not certify a production terminal or deployed site.
