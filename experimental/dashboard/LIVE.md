# Live terminal dashboard (experimental, Python 3.9+)

Separate from the unchanged offline terminal.py prototype and supported core.
Standard library only, with OS Europe/Rome tzdata and optional curses.

Run: python3 live.py [--once] [--interval 5] [--site example.org]
Defaults: /var/log/immution/events.csv and /var/log/immution/prioris/events.csv.
Repeat --log for alternate CSV files. Non-TTY automatically uses --once behavior.
Tab/n/p: claimed host filter; 0: all; ?: help; j/k: scroll; r: refresh; q: quit.
Only refreshes while running; no installed service, cron, endpoint or dependencies.

Counts are gate event records, not all requests or bots. blocked and would_block
remain separate; distinct IP counts overlap. IPs are salted in-memory digests;
raw IPs, URIs, agents and reasons are not retained/displayed. Claimed host is
untrusted, never trusted vhost attribution. Source numbers identify files only.
Exact known selftest host+URI+UA markers are excluded separately; spoofable.
Service state is sampled via systemctl, not proof of follower freshness, gate
coverage or engine effectiveness. These are explicitly UNKNOWN.

Today means Europe/Rome midnight through the displayed cutoff, including DST.
At midnight caches reset and available event rotations are reread. Numeric and
YYYYMMDD suffixes, optionally gzip, are recognized. No blocked.csv legacy data.
8 MiB decompressed read budget per refresh, 128 descriptors, 300000 today events;
limits/errors are visible. --once can be incomplete on large histories; interactive
mode catches up. Existing file bytes are not reread on ordinary refresh. Renamed
inodes are retained; compression of an already consumed rotation is skipped.
copytruncate is inherently racy and flagged as coverage-uncertain; restart to
rebuild from retained files. Rapid truncate-and-regrow can evade size detection.
No claim of complete history if logs were deleted, logging failed or retention
excluded records. Multiline/malformed CSV records are skipped visibly, partial
trailing records wait for newline. Empty/wrong headers and read failures must
not be mistaken for healthy no-traffic conditions. No demo substitution.

Installation is additive: a new version directory under /opt/immution-dashboard
and a non-overwriting /usr/local/bin/immution-dashboard launcher. No changes to
/opt/immution, /etc, service units, Apache or source logs.
Rollback: remove only the dashboard launcher (after checking its target), leave
version directory for audit. No engine rollback or service restart is needed.

Validation: python3 -m unittest discover -s experimental/dashboard -v
Core: python3 -m unittest discover -s tests; ./scripts/check-release.sh
Production validation must compare fixed-cutoff independent CSV aggregation,
exercise a real SSH PTY and check unchanged service PIDs/start times. Never
commit production logs, private deployment details or production metrics.

## Terminal refinement

The live TUI uses numbered panels, bold metrics, aligned host/source tables and
paired hourly bars (# blocked / + monitor, shared peak). Selected claimed host
and a concise key legend stay visible; Home/PgUp/PgDn supplement j/k scrolling.
Narrow terminals wrap metrics/records; long table names end in ~ (select the
host to see its full name). Extreme sizes retain as much of q quit as fits.
Terminal foreground/background are inherited with curses default colors and
pair (-1,-1), including cleared space and resize; no palette redefinition,
reverse-video theme or hardcoded colors. Unsupported color initialization falls
back to monochrome attributes. Curses wrapper restores terminal state on exit
and exceptions. No new dependencies; Python 3.9+ still required.

### MB saved: unknown by default, explicitly estimated when configured

The prominent MB RISPARMIATI panel shows N/D because events.csv has no response
byte fields and blocked requests do not establish counterfactual response size.
The existing tools/immution_bandwidth.py is a separate heuristic with defaults;
those defaults are deliberately NOT imported into this live dashboard.
Optionally supply BOTH --baseline-bytes N and --block-bytes N (integers 0..10^15).
Use a documented representative unblocked-response estimate for the former and
known average served block-response bytes for the latter; nothing is assumed.
The STIMA label remains beside the number, with 3-line ASCII digits when they fit:
blocked events * (baseline bytes - block bytes) / 1,000,000 decimal MB.
Negative estimates are retained, not clamped into fictitious savings. Only
blocked events count, excluding marked selftests; selected host and today's
Europe/Rome window apply. Monitor events do not save bandwidth. N/D remains N/D
even for zero events without byte evidence; explicit estimates can be zero.
Byte assumptions are per invocation, not persisted. --once includes the label
and formula without big digits. This is not measured network traffic savings.
A defensible baseline needs owner-approved representative response-size evidence;
no production probes, content collection or monitoring changes are performed.
