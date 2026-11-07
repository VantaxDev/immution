# Scoring model

Immution v0.1 uses a small, documented rule set. The score has a 20-minute
half-life and reaches the temporary-ban state at 50 points by default.

## Per-event points

| Signal | Points | Conditions |
| --- | ---: | --- |
| 404 response | `2 + min(recent_404, 10) × 0.5` | Every 404 while the address is tracked |
| High-confidence probe path | `10 + min(recent_probes, 5) × 2` | Only with HTTP 400, 401, 403 or 404 |
| Missing User-Agent | 3 | Only on a 404 or probe request |
| Known security-scanner User-Agent | 4 | Only on a 404 or probe request |
| 404 burst | 20 | At least 10 within 60 seconds; 30-second cooldown |
| Probe burst | 30 | At least 4 within 60 seconds; 30-second cooldown |
| Error-path scan | 30 | At least 20 distinct error paths within 60 seconds |

Successful requests do not receive points solely because their User-Agent
contains `bot`, `curl`, `python` or another automation-related word. Legitimate
routes such as `/wp-login.php`, `/wp-admin`, `/admin` and `/graphql` are not
probe paths by themselves.

## Cumulative 404s are not a rate or bot verdict

The state `errors_404` counter is cumulative while that state is tracked. It
does not reset every minute. Only `error_times` is pruned to the recent
60-second window. A burst condition adds a bonus; it is **not a prerequisite**
for reaching the configured threshold. Ordinary 404 points can accumulate
across several minutes even with no probes and no burst bonus. Conversely,
probe errors can reach the threshold without any 404 responses.

For example, the synthetic [metadata fixture](../tests/fixtures/metadata-404.json)
contains 29 requests across three fictional log sources in 887 seconds:
19 metadata 404s, eight 200s and two redirects. There are at most six 404s in
any 60-second window, no scanner/missing-UA points, no probes and no bonuses.
Ordinary 404 additions total 61 points before decay; after decay the final
score is about **52.363**, which crosses the default threshold of 50. Each
source alone stays below threshold, but the current model pools them by IP.
This characterizes current policy; it does not label metadata discovery as
malicious or establish that a person was identified.

`robots.txt`, `security.txt`, `/.well-known/security.txt` and favicon requests
may be legitimate discovery even when a site returns 404. User-Agent changes
do not prove malice. Shared NAT/proxy users and multiple virtual hosts share
one IP score. `immutionctl explain` therefore distinguishes cumulative counts,
limited recent reasons and a state flag from verified identity or actual gate
enforcement. The snapshot does not store the active configured threshold;
consult the daemon configuration instead of assuming 50. Reason lists are
bounded and cannot reconstruct the complete decayed score on their own.

## Possible metadata policy: proposal only, not implemented

There is currently **no metadata exemption or configurable metadata weight**.
Do not add the proposed setting below to a live configuration and assume it
is supported. Gate `exclude_paths` bypasses enforcement only: it does not
remove 404 points from the daemon or prevent cross-site penalties.

A narrow candidate for separate review is an opt-in `metadata_404_multiplier`
with default 1 (unchanged behavior). It would apply only to ordinary 404 points
for exact GET/HEAD paths `/robots.txt`, `/security.txt`,
`/.well-known/security.txt` and `/favicon.ico`, not prefix matches or encoded
path variants. Probe points, scanner/missing-UA additions and existing burst
bonuses would remain unscaled; counters would still record the observations.
It must not whitelist an IP, trust a UA, or exempt sensitive paths. Validation
would reject booleans, non-finite values and values outside 0..1; legacy
configs would retain today's behavior.

For the **pre-enforcement synthetic fixture only**, with no extra additions
or bonuses, linear decay makes a multiplier comparison exact:

| Hypothetical ordinary-404 multiplier | Final score | Threshold reached at 50? |
| --- | ---: | --- |
| 1 (current behavior) | 52.363 | Yes |
| 0.5 (candidate, not implemented) | 26.182 | No |

This arithmetic is not an implemented policy, production forecast, or measured
false-positive rate. Later responses depend on whether enforcement occurred;
reusing historical 403s unchanged would not be a valid full counterfactual.
Before implementation/default changes, require legitimate metadata, sustained
metadata abuse, mixed sensitive probes, custom thresholds, shared-IP and
backward-compatibility regressions, followed by representative monitor-mode
evidence. A broad 404 exemption or generic threshold increase is not justified
by this one fixture. No production configuration change is included here.

## Why the model is conservative

Small servers often sit behind NAT, receive legitimate crawlers and host admin
routes. Request volume or a generic User-Agent is therefore insufficient to
justify a block. Immution v0.1 requires error responses or high-confidence
probe paths before those contextual signals matter.

## Changing the threshold

Edit `/etc/immution/daemon.json` and restart the daemon. Do not lower the
threshold until monitor-mode results from the actual workload have been
reviewed.

## Preventing enforcement feedback

For an already-banned state, HTTP 403 only applies score decay. It adds no
probe/UA points or burst bonuses, because it could be generated by our gate.
Origin 403s are also discounted in this situation, including monitor mode.
Googlebot is neither authenticated nor whitelisted by the engine.
