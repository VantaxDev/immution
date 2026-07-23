# Source audit — 10 July 2026

Input archive SHA-256:
`eefa1d3a7616e78494bdf97a4f3a29c96e8ee280a847c6f8e03eb35481abb1f7`

This was a focused release-readiness review, not a formal penetration test.

## Archive hygiene

- No obvious passwords, API keys, private keys or production log files were
  found by pattern-based scanning of the working tree and its two Git commits.
- The archive included the entire `.git` directory and its remote metadata.
- The Git working tree was not clean: `immution_bandwidth.py` contained an
  uncommitted rewrite with 48 insertions and 122 deletions.
- The original ZIP should not be published as a release artifact.

## Findings addressed in rc1

| Severity | Finding | rc1 disposition |
| --- | --- | --- |
| High | PHP trusted `CF-Connecting-IP`, `X-Forwarded-For` and `X-Real-IP` from any client. This could bypass or misapply state when Apache logs used a different address. | Gate now uses only `REMOTE_ADDR`; proxy deployments must configure `mod_remoteip`. |
| High | `/wp-login.php`, `/wp-admin`, `/admin` and `/graphql` were classified as probes even when legitimate. | Removed from high-confidence probe rules. Probe points now require an error response. |
| High | Generic `bot`, `curl`, `wget`, Java and other normal automation User-Agents accumulated points on successful traffic. | User-Agent cannot score successful traffic by itself; only explicit scanner names add context to an error/probe. |
| High | Runtime directory was `0777`, state files `0666`, and the daemon ran as root. | Dedicated unprivileged user, `0750` runtime directory, `0640` atomic state files. |
| High | A fresh installation had no safe observation phase before enforcement. | Installer defaults to `monitor`; gate records `would_block` without returning 403. |
| Medium | Direct state writes could expose partially written JSON to concurrent PHP requests. | Temporary file plus atomic `os.replace`. |
| Medium | Installer could coexist unpredictably with another `auto_prepend_file`. | Preflight aborts instead of overwriting or silently replacing it. |
| Medium | Global custom 404 configuration changed all virtual hosts and increased deployment risk. | Removed from the supported installer path. Apache logs still provide 404 observations. |
| Medium | Optimized mmap code and `100x`-style performance claims were not backed by release tests; PHP read the whole table with `file_get_contents`. | Preserved under `experimental/`; excluded from installation and supported claims. |
| Medium | README described `--config`, but the daemon did not implement that option. | JSON configuration and `--check-config` implemented and tested. |
| Low | CSV fields came from request headers/paths and could begin with spreadsheet formula characters. | Potential formula fields are prefixed before CSV output. |
| Low | The block page used a `javascript:` retry link despite the JavaScript-free claim. | Replaced with a normal same-page link and restrictive response headers. |

## Checks completed in this workspace

- Python source compilation;
- six scoring and regression tests;
- shell syntax checks;
- JSON validation;
- systemd unit verification;
- path traversal check on the input archive;
- heuristic secret scan of current files and Git history.

PHP CLI was not available in the review container, so `php -l src/gate.php` must
run in CI and on the disposable target server before publication.

## rc2 follow-up — 22 July 2026

The source audit above records the rc1 review. rc2 fixes external unblock cache
invalidation and adds a full Ubuntu 24.04 integration workflow. The workflow
now performs the disposable-server checks; the remaining human work is reduced
to real-traffic review, proxy identity verification where applicable, repository
settings, website claims and release tagging. See `RELEASE_CHECKLIST.md`.

## Remaining release gates

1. Obtain a green result from both GitHub Actions workflows on the release
   commit.
2. Verify `REMOTE_ADDR` and Apache's first log field are identical on the trial
   host when Cloudflare or another reverse proxy is present.
3. Observe at least five normal days in monitor mode on a WordPress workload
   and review the generated aggregate report.
4. Remove the current public performance multipliers or publish the benchmark,
   raw fixture and exact commands that reproduce them.

## rc3 follow-up — 22 July 2026

The supported gate was made compatible with PHP 7.0 without adding a legacy
branch or a polyfill loaded on every request. CI now runs the same gate smoke
test on PHP 7.0, 7.4, 8.3 and 8.4. The complete Apache/systemd installer test
continues to run on Ubuntu 24.04; this PHP compatibility work does not claim
automatic installer support for end-of-life Ubuntu releases.

## rc4 follow-up — 23 July 2026

The supported daemon and installed command-line tool now target Python 3.6 and
newer. Python 3.7-only runtime APIs and postponed annotations were replaced;
the installer rejects older runtimes before modifying Apache or system files.
CI runs the same Python behavior tests on Python 3.6, 3.8 and a current
runtime. The full integration path remains Ubuntu 24.04; Python 3.6
compatibility does not make end-of-life operating systems supported.
