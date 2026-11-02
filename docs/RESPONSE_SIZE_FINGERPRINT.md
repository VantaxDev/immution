# response_size_fingerprint (monitor only)

This independent heuristic identifies route-encoding mutation patterns, not an
exploit, WordPress signature, malicious identity or proof of vulnerability.
It emits a bounded JSON message prefixed `[MONITOR response_size_fingerprint]`
to stdout/journald. It **never** changes score, state files, bans, the PHP gate,
CSV schemas, whitelist behavior, or throttling, even with the gate in block mode.
There is no enforcement/429 implementation or PHP sleep. A future 429 hook is
intentionally absent/disabled; any enforcement needs a separate reviewed change.

## Explicit trusted host provenance

Apache Combined has no virtual-host column. Neither the input filename nor a
request Host header reliably identifies a vhost. By default `fingerprint_hosts`
is empty and this monitor skips all sources. Existing scoring remains active.
After independently verifying Apache configuration, an operator may explicitly
assert **dedicated single-host logs** in daemon JSON, for example:

```json
{
  "fingerprint_hosts": {
    "/var/log/apache2/example-only.log": "example.test"
  }
}
```

Keys must be absolute paths and are resolved through realpath, just like followed
logs. Values are bounded host identifiers, lowercased. Only explicitly mapped
sources participate. Never map a shared, default, catch-all, unknown or
attacker-selected Host log to one host. Misconfiguration defeats isolation.
This version does not support shared logs; use separate dedicated logs or await
a separately reviewed parser for a trusted server/vhost column. Do not feed
multiple copies of the same requests. Source aliases for the same host share
that host's bucket intentionally.

## Detection semantics

The bucket is `(effective client IP, verified host, HTTP method, canonical
endpoint)`. Only status **200**, known integer response sizes **>=512 bytes**,
and valid Apache timestamps qualify. A missing byte field `-` is `None`, not
zero. Status 201/3xx/4xx/5xx do not enter this detector. These conservative
eligibility restrictions are inherited from the supplied reference proposal.

Within **120 seconds**, require **>=12 observations**, **>=3 distinct route
spellings**, **>=2 distinct suspicious spellings**, and **>=85% exactly equal
response sizes**. Suspicious spellings include encoded slash/dot/backslash,
partial slash encoding and dot segments. This does not depend on particular
endpoint names. Generic path variants are supported; the optional root
`/?rest_route=...` adapter correlates the supplied query-routing example without
requiring WordPress installation or exploit signatures.

Decode once; collapse dot segments for correlation only. Do not use this
normalization for authorization or routing. Double encoding stays distinct.
Malformed/ambiguous targets (absolute URLs, authorities, fragments, duplicate
route keys, control characters, decoded delimiters/backslashes) are rejected.
Other query parameters, including UTM/session values, never count as new route
variants. Root query routes and path routes may correlate by canonical endpoint;
applications can assign them different semantics, another reason to monitor only.

State starts only at a suspicious variant. Ordinary observations before that
are not retained, so the >=12 threshold is conservative. The monitor runs before
the untracked-IP successful-traffic early return, but after existing loopback
exclusions. No successful request creates an IP scoring record just because this
monitor emits a finding.

## Time and resource bounds

Use event time from Apache `DD/Mon/YYYY:HH:MM:SS +/-HHMM`, parsed independently
of locale and timezone. Invalid dates skip only monitoring, not existing scoring.
Existing scoring continues using processing time, unchanged. Replay speed cannot
turn widely separated event timestamps into one window. A per-key event-time
high-water mark rejects too-old out-of-order events and prunes all expired
samples. Backdated requests cannot move the watermark backward.

Maximum **1024 buckets**, LRU eviction; **48 samples per bucket**; target length
**2048** and route/variant length **256** characters. Variants and size histograms
are derived only from those bounded samples, never retained in unbounded sets.
If samples overflow, findings are suppressed until all discarded samples have
expired from the advertised window; a capped suffix is not misrepresented as
full-window 85% consistency. High-volume scans can therefore be missed.
Idle buckets expire after 120 seconds of monotonic processing inactivity on the
next observation or daemon cleanup (normally every 60 seconds). A lock serializes
monitor updates; there are no monitor disk writes. Alerts have a 180-second
per-bucket event-time cooldown; eviction/idle expiry resets it, so it is not a
durable global alert rate limit. Restart loses all monitor state.

## Limitations and false positives

Equal bytes can result from static/error templates, compression, cache behavior,
API validation, legitimate encoded links or automated route compatibility checks.
NAT/proxy users share an IP; this is not a bot identity. A generic 200 response
can conceal arbitrary origin behavior. No POST body, upload or response content
is inspected. Benign query-only changes do not qualify. Short responses, unique
sizes, low-rate/distributed patterns, unknown/shared hosts and capped hot buckets
can evade detection. Monitoring occurs after the response; it cannot stop an
initial exploit or establish a CVE-specific mitigation. Validate findings for
each site's routing and log byte semantics before contemplating enforcement.

JSON escaping prevents control characters from becoming log injection; host,
method and endpoint lengths are bounded. Findings still include client IP and
endpoint path (no unrelated query values), so journald access/retention matters.

## Packaging and verification

`route_mutation.py` is installed beside `immution.py` and compiled by preflight,
source checks and Python CI. Existing installer snapshots/restores the entire
application directory, so upgrades/rollback include the module; uninstall removes
that directory. Ubuntu integration CI verifies installed imports and module
contents after installation and rollback. It runs only on disposable CI hosts,
not production.

The supplied archive was inspected before use; its 11 tests and 21-line synthetic
fixture are included. Additional integration/boundary tests cover unknown/shared
sources, successful untracked IPs, state equivalence, Apache event time/bytes,
normalization, method/status isolation, bounded memory, overflow and installed
imports. Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s experimental/dashboard -v
node experimental/dashboard/test_ui.cjs
./scripts/check-release.sh
```

Actual runtime results and CI status are reported in the PR, not inferred from
syntax checks. Supported Python floor remains 3.6; no external package is added.
