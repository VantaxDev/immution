# Maintainer guide

## State and concurrency contract

`analyze_line` takes a thread lock and Linux flock on `.state.lock` around the
read/modify/atomic-replace transaction. Cleanup and CLI unblock use the same
lock. Keep the inode until the runtime directory is removed. Never delete it
as part of unblock. PHP reads JSON snapshots without locking; a request already
reading a snapshot may complete its earlier decision while unblock runs.

Atomic rename prevents truncated JSON; it alone does not prevent lost updates.
The daemon cache checks file existence to invalidate externally unblocked IPs.
Cache eviction runs in cleanup even when no disk file expires. Clean requests
without tracked state avoid writes. Serialize all new state-mutating commands
using this protocol. It intentionally serializes writers; benchmark before
claiming throughput. The cache and disk state can still grow with many active
suspicious addresses; there is no hard cardinality budget yet.

## Scoring and expiry

Apache emits records after handling the request. Scores use processing time,
not the log timestamp; backlog/replay can distort bursts. Do not score the same
request from duplicate log files. The accepted input is Combined with IP first.

Once a state is banned, 403 responses only decay the score. Otherwise our gate
could turn its own refusals into repeated probe evidence. The log cannot tell
origin and gate 403s apart: origin 403s on banned IPs are discounted too, even
in monitor mode. Other status codes keep their normal rules.

Keep `SCORE_TTL` (3600 seconds) aligned with the PHP state freshness check.
The gate fails open on missing/invalid/stale timestamps, even if the daemon has
stopped. This TTL is not the score half-life. It is not a guarantee of an exact
20-minute ban: unbounded scores may take longer to decay. A trusted local writer
owns the JSON schema; compromised local accounts are outside the threat model.

## PHP contract and privacy

Canonicalize IPv6 to match Python filenames, including IPv4-mapped addresses.
Trust REMOTE_ADDR only. Never introduce forwarding-header fallbacks or UA-only
Googlebot whitelists. Gate exclusions do not exclude events from scoring.

The CSV header check belongs inside flock. Requests and headers are untrusted;
keep output bounds and spreadsheet formula neutralization. The raw CSV and
state reasons contain paths and query strings. The report omits explicit IP
fields and queries, but paths may still contain personal data. Log retention is
30 daily rotations; the default report currently reads only the active file.
PHP's event log is best-effort; logging failures do not disable blocking.

## Install and removal

Fresh installs default to monitor; existing config wins over --mode. The CLI
PHP version does not prove the version loaded by Apache. The installer checks
that mod_php is loaded, but mixed PHP installations still need inspection.
The prepend conflict check scans PHP ini files; it cannot prove absence of
VirtualHost/.htaccess overrides. Never claim universal auto_prepend coverage.

Rollback snapshots config, unit, logrotate and ini files and restores previous
application sources where available. Failed installs can leave the service
account, log directory and diagnostic snapshot for inspection. Removal must
reload Apache without prepend before deleting gate.php. Do not weaken runtime
permissions to make tests pass; privileged assertions need sudo.

## Verification

Run `./scripts/check-release.sh`. It checks every Bash file individually.
The PHP matrix runs 7.0, 7.4, 8.3, 8.4; Python runs 3.6, 3.8 and current.
Only the Ubuntu integration workflow validates a real systemd/Apache lifecycle.
An IPv6 CLI test is not an end-to-end IPv6 HTTP test. Require actual results,
not merely workflow presence. Keep synthetic `tests/fixtures/access.log` in Git.
