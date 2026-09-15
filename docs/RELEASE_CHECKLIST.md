# v0.1 release checklist

## One automated gate

The `ubuntu-integration` GitHub Actions workflow replaces the disposable-server
sub-checklist. Before promotion, require its green result. It covers:

- fresh Ubuntu 24.04, Apache and mod_php installation;
- safe refusal when `auto_prepend_file` is already in use;
- real IPv4 HTTP responses in monitor and block mode;
- IPv4/IPv6 CLI explain and unblock behavior (not IPv6 HTTP);
- invalidation of the daemon cache after an external unblock;
- service user, runtime/state permissions and Apache health;
- complete purge and a healthy origin response after uninstall.

The `tests` workflow separately runs the supported Python code on Python 3.6,
3.8 and a current runtime, and syntax-checks and smoke-tests the PHP gate on PHP
7.0, 7.4, 8.3 and 8.4.

- [ ] `tests` and `ubuntu-integration` are green on the release commit.

## Human decisions still required

- [ ] Five normal days in monitor mode have completed on one ordinary
      WordPress workload.
- [ ] `sudo /opt/immution/immutionctl.py report` has been reviewed; legitimate
      top paths and any exclusions are documented; rotated logs are reviewed separately.
- [ ] On reverse-proxy/CDN deployments, `REMOTE_ADDR` and the first Apache log
      field have been compared for the same request.
- [ ] Private vulnerability reporting is enabled in the public repository.
- [ ] Unverified performance multipliers have been removed from the website.
- [ ] The release tag and archive come from the green, clean release commit.

## Recommended launch evidence

- terminal recording: install → monitor event → explain → unblock;
- sanitized sample `events.csv`;
- CPU/RAM/throughput benchmark script and raw fixture;
- explicit supported-platform and limitation list.
