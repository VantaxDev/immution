# Changelog

## Unreleased — source review 2026-09-15

- Coordinate scoring, cleanup and unblock; prevent 403 score feedback.
- Expire stale PHP state, normalize IPv6 and serialize CSV header creation.
- Validate thresholds and detect stopped log followers.
- Correct upgrade mode output, rollback, removal order and logrotate identity.
- Add maintainer contracts, targeted regressions and clearer installation limits.
- See docs/REVIEW_2026-09-15.md for completed and outstanding validation.

## 0.1.0-rc4 — 2026-07-23

### Compatibility

- the daemon and installed command-line tool now support Python 3.6 and newer;
- Python 3.7-only postponed annotations, `subprocess` text mode,
  `datetime.fromisoformat()` and required `argparse` subcommands were replaced
  with Python 3.6-compatible equivalents;
- the installer checks the Python version and compiles installed Python files
  before changing the system;
- CI exercises the supported Python code on Python 3.6, 3.8 and a current
  runtime.

## 0.1.0-rc3 — 2026-07-22

### Compatibility

- the supported PHP gate now targets PHP 7.0 through PHP 8.4;
- PHP 8-only string helpers, PHP 7.1 nullable/`void` return types and PHP 7.1
  array destructuring were removed from the gate;
- PHP 7.0, 7.4, 8.3 and 8.4 syntax and behavior checks are release-gated;
- CSV writing uses an explicit escape character compatible with PHP 7.0 and
  avoids the PHP 8.4 default-escape deprecation.

## 0.1.0-rc2 — 2026-07-22

### Reliability

- an address removed with `immutionctl unblock` is also invalidated from the
  daemon's in-process cache instead of being recreated on the next request;
- an automated Ubuntu 24.04 integration workflow covers fresh install,
  `auto_prepend_file` conflict handling, monitor/block HTTP behavior, service
  identity, state permissions, IPv4/IPv6 commands and uninstall;
- `scripts/check-release.sh` consolidates local source validation;
- `immutionctl report` produces a monitor-period summary without printing IP
  addresses or query strings.

## 0.1.0-rc1 — 2026-07-10

First public-release candidate.

### Safety

- monitor mode is the installation default;
- forwarding headers are no longer trusted directly;
- legitimate WordPress routes and generic bot User-Agents no longer score by
  themselves;
- state writes are atomic and use restricted permissions;
- daemon runs without root privileges;
- installer refuses to overwrite an existing `auto_prepend_file`;
- global custom 404 handling was removed from the supported installation path.

### Project

- clean repository structure, MIT license and security policy;
- scoring, privacy and threat-model documentation;
- regression tests with anonymized fixtures;
- local status, explanation and unblock commands;
- experimental mmap implementation separated from supported code.
