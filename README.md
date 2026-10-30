# Immution

**Explainable abuse protection for small Apache servers.**

Immution observes Apache access logs, assigns a documented score to suspicious
behaviour and can temporarily stop flagged addresses before PHP application
code runs. It works locally, adds no browser JavaScript and has no third-party
Python or PHP package dependencies.

> **Release status:** `0.1.0-rc4` is a release candidate. The installer starts
> in **monitor mode** and does not block requests until an administrator reviews
> the results and explicitly enables block mode.

## What it is for

- repeated requests for sensitive files such as `.env` and `.git/config`;
- bursts of missing pages and high-confidence probe paths;
- small Apache/PHP servers where a CDN or enterprise WAF would be excessive;
- administrators who want to see why an address was flagged.

Immution is not network-level DDoS mitigation, a vulnerability scanner, a bot
identity service or a replacement for backups and patch management.

## Experimental terminal dashboard

A separate **read-only** Python 3.9+ dashboard is available in this source
branch under experimental/dashboard; it is not bundled by the v0.1.0-rc4
installer or offered as a new release. No engine rules or services are changed.
Use a checkout containing these files, with system Europe/Rome timezone data.
No pip dependencies are needed; the interactive Linux UI uses standard curses.

    # From the repository root; use an account allowed to read the chosen log.
    python3 experimental/dashboard/live.py --log /path/to/events.csv --once
    python3 experimental/dashboard/live.py --log /path/to/events.csv --interval 5
    # Offline demonstration with explicitly synthetic data:
    python3 experimental/dashboard/terminal.py --demo --once

Run directly from source: the core installer does **not** install an
immution-dashboard command. Repeat --log for additional event CSV files.
Refresh runs only while the terminal is open. Keys: Tab/n/p claimed-host
filter, 0 all, ? help, j/k scroll, r refresh, q quit.
Numbered panels preserve your terminal foreground and background. Blocked and
monitor-only events stay separate; claimed Host values are untrusted, and IP
counts are not bot counts. Missing data and coverage limits remain visible.

**MB saved is N/D by default**, not measured from event counts. Only explicit
--baseline-bytes N and --block-bytes N enable a labelled estimate:
blocked * (baseline - block) / 1,000,000 decimal MB. Large three-line digits
appear when space allows; negative estimates are retained. No assumed baseline.
See [dashboard usage and limitations](experimental/dashboard/LIVE.md).

    python3 -m unittest discover -s experimental/dashboard -v
    python3 -m unittest discover -s tests -v
    ./scripts/check-release.sh

## Safety properties

- **Monitor first:** a new installation writes `would_block` events but allows
  the request.
- **Explainable:** every state file contains the score and recent reasons.
- **Temporary:** scores decay with a 20-minute half-life and inactive state is
  removed after one hour.
- **Local:** access logs and IP state stay on the server.
- **Fail open:** missing or unreadable state does not stop the application.
- **Reversible:** one command removes the active state for an address.

## Compatibility and tested paths for v0.1

- complete installer integration: Ubuntu 24.04 LTS, Apache 2.4, PHP 8.3
  `mod_php`, Python 3.12 and systemd;
- supported Python daemon and command-line tools: Python 3.6, 3.8 and current
  Python syntax and behavior matrix;
- supported PHP gate: PHP 7.0, 7.4, 8.3 and 8.4 syntax and smoke-test matrix;
- Apache input: Combined Log Format with the effective client IP first.

The daemon and installed command-line tool support Python 3.6+. PHP-FPM,
Nginx, older Ubuntu releases and non-Debian packaging are not covered by the
automatic installer. PHP 7.0 support refers to the request gate; it does not
turn an end-of-life Ubuntu installation into a supported platform.

## Architecture

```text
Apache access logs ──> Python daemon ──> /run/immution/<ip>.json
                                              │
PHP request ── auto_prepend_file ──> gate.php ┘
                         │
                         ├─ monitor: log would_block and continue
                         └─ block:   return a small HTTP 403 page
```

The daemon runs as an unprivileged `immution` user. Runtime files are readable
by the `www-data` group and are atomically replaced so PHP never sees partially
written JSON.

## Install

On a disposable Ubuntu 24.04 server, install the prerequisites first:

```bash
sudo apt-get update
sudo apt-get install -y git apache2 libapache2-mod-php php-cli python3
sudo systemctl enable --now apache2
git clone https://github.com/VantaxDev/immution.git
cd immution
./scripts/check-release.sh
```

Require green `tests` and `ubuntu-integration` workflows for the commit you
install. Source checks alone do not validate the live Apache installation.
Review `scripts/install.sh`, then run from the repository root:

```bash
sudo ./scripts/install.sh
```

The installer:

1. checks for an existing `auto_prepend_file` and stops instead of overriding it;
2. installs the daemon and gate under `/opt/immution`;
3. creates an unprivileged service account;
4. enables the systemd service;
5. adds the PHP `auto_prepend_file` configuration;
6. validates Apache before reloading it;
7. starts **fresh installations** in monitor mode; upgrades preserve the existing mode.

Check the result:

```bash
sudo systemctl status immution
sudo journalctl -u immution -f
sudo /opt/immution/immutionctl.py status
sudo tail -F /var/log/immution/events.csv
```

The events file is created only when a subsequent PHP request encounters a
flagged IP. Its absence does not prove the detector works or has failed.
`status` reports scored addresses, not necessarily requests actually blocked.

After the observation period, generate a privacy-conscious summary (IP
addresses and query strings are not printed):

```bash
sudo /opt/immution/immutionctl.py report
```

The default report reads only the current events.csv, not rotated files.
Its paths can still contain identifiers or secrets; review before sharing.
It reduces the data to review but cannot decide whether an application
path is legitimate, nor prove false positives are absent. Classify its top paths before enabling block mode.

## Review monitor-mode decisions

When an event is recorded, inspect the corresponding state:

```bash
sudo /opt/immution/immutionctl.py explain 192.0.2.10
```

Example output:

```text
IP: 192.0.2.10
Score: 54.0
Banned: yes
Requests while tracked: 3
404 responses: 3
Probe paths: 3
Reasons:
  - 12:04:03 +16.0: probe /.git/config
  - 12:04:03 +3.5: 404 /.git/config
```

Use documentation-only addresses such as `192.0.2.0/24` in examples and tests;
do not publish real event logs in bug reports.

## Enable blocking

Run in monitor mode for at least several days on the target workload. Review
false positives, add necessary exclusions and whitelist only trusted addresses.

Then run `sudoedit /etc/immution/gate-config.php` and set:

```php
'mode' => 'block',
```

Validate the PHP configuration and reload Apache:

```bash
sudo php -l /etc/immution/gate-config.php
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Return to monitor mode immediately if legitimate traffic is affected.

## Unblock one address

```bash
sudo /opt/immution/immutionctl.py unblock 192.0.2.10
```

Unblock waits for an in-flight daemon write and removes the resulting state.
A later suspicious request can start a new score; this is not a whitelist.

## Reverse proxies and CDNs

The PHP gate intentionally trusts only `REMOTE_ADDR`. It does not accept
`X-Forwarded-For`, `X-Real-IP` or `CF-Connecting-IP` directly because clients
can spoof those headers.

When Apache is behind a trusted proxy or CDN, configure `mod_remoteip` so both
`REMOTE_ADDR` and the first field of the access log contain the same effective
client address. Use `%a` as the first field in a dedicated Combined access log and trust only
explicit proxy addresses. The parser does not accept Apache's default
`other_vhosts_access.log` format with a virtual-host prefix. Set explicit
`logs` in daemon.json to client-IP-first Combined files, avoiding duplicates.
New log files are discovered at startup; restart after adding a virtual host.
Do not enable block mode until the gate/log address match has been verified.

## Configuration

Daemon settings: `/etc/immution/daemon.json`

```json
{
  "auto_dir": "/var/log/apache2",
  "logs": [],
  "runtime_dir": "/run/immution",
  "threshold": 50
}
```

Gate settings: `/etc/immution/gate-config.php`

- `mode`: `monitor` or `block`;
- `whitelist`: exact IPv4/IPv6 addresses or CIDR ranges;
- `exclude_paths`: anchored regular expressions (gate bypass only; the daemon still scores these requests);
- `log_enabled` and `log_file`.

After daemon changes:

```bash
sudo systemctl restart immution
```

## Test

```bash
./scripts/check-release.sh
```

The complete source check needs Python 3.6+, PHP CLI and systemd tooling. CI
runs the Python tests on Python 3.6, 3.8 and a current runtime, and the PHP gate
smoke tests on PHP 7.0, 7.4, 8.3 and 8.4. A second workflow
performs a fresh Apache/mod_php installation on Ubuntu 24.04 and tests the
installer, monitor and block responses, permissions, IPv4/IPv6, external
unblocking and uninstall.

## Uninstall

Preserve configuration and logs:

```bash
sudo ./scripts/uninstall.sh
```

Remove configuration, state and logs too:

```bash
sudo ./scripts/uninstall.sh --purge
```

## Repository map

```text
src/           supported daemon and PHP gate
config/        safe default configuration
packaging/     systemd and logrotate files
scripts/       installer and uninstaller
tools/         local inspection and reporting utilities
tests/         regression tests and anonymized log fixtures
docs/          architecture, scoring, privacy and threat model
experimental/  preserved research; not installed or supported
```

## Privacy

`events.csv` can contain IP addresses, requested paths, hostnames and user-agent
strings. Treat it as operational security data, restrict access and keep it only
as long as necessary. See [docs/PRIVACY.md](docs/PRIVACY.md).

## Security reports

Do not publish exploit details in a normal issue. Follow [SECURITY.md](SECURITY.md).

## License and professional support

Immution is available under the [MIT License](LICENSE). The supported product is
not feature-gated: professional installation, tuning and operational support
are separate services. Project information is available at
[immution.com](https://www.immution.com/).

## Operational limits and developer notes

Detection follows completed access-log records, so first requests already reach
Apache and the application. The gate only intercepts PHP, consumes some CPU,
and does not stop bandwidth exhaustion or ordinary HTTP 200 floods. Shared IPs
share one score across all configured logs and virtual hosts. Googlebot is not
authenticated or automatically whitelisted.

Read [the maintainer guide](docs/MAINTAINERS.md) before changing locking,
scoring or installation. Read [the review](docs/REVIEW_2026-09-15.md) for
remaining limitations and what was actually tested.
