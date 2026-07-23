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

## Why the model is conservative

Small servers often sit behind NAT, receive legitimate crawlers and host admin
routes. Request volume or a generic User-Agent is therefore insufficient to
justify a block. Immution v0.1 requires error responses or high-confidence
probe paths before those contextual signals matter.

## Changing the threshold

Edit `/etc/immution/daemon.json` and restart the daemon. Do not lower the
threshold until monitor-mode results from the actual workload have been
reviewed.
