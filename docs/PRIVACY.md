# Operational data and privacy

Immution processes Apache access logs locally. It does not transmit telemetry.

## Data stored

Runtime state in `/run/immution` contains:

- client IP address (encoded in the filename);
- score, temporary-ban state and timestamps;
- request/404/probe counters;
- recent scoring reasons and truncated request paths.

The default one-hour inactivity TTL removes runtime state automatically.

`/var/log/immution/events.csv` can additionally contain host, request URI and
User-Agent. Logrotate keeps 30 daily rotations by default. Administrators should
shorten this period when their operational need does not justify it.

## Publication and support

Never attach real access logs, event files or runtime state to a public issue.
Create a minimal reproduction with documentation-only networks (`192.0.2.0/24`,
`198.51.100.0/24`, `203.0.113.0/24` and `2001:db8::/32`). Remove hostnames,
cookies, query values and identifiers before sharing a private support sample.

The administrator remains responsible for the lawful basis, notice, access
controls and retention policy appropriate to the deployed service.
