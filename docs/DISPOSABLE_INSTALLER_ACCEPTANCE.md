# Disposable-prefix installer acceptance

Run explicitly with Python 3.8+ and existing Bash, PHP CLI and GNU coreutils:

```bash
IMMUTION_LIFECYCLE_EVIDENCE=/tmp/immution-prefix-results python3 tests/acceptance/installer_prefix.py
```

No sudo, package installation, running service or network is needed. This is
not the Ubuntu/Apache integration workflow and is intentionally not auto-run by
default test discovery.

The harness copies the release to TemporaryDirectory. In that copy only it
maps absolute system/config/log/snapshot paths to a disposable prefix and bypasses
the installer root check. Per-script original/adapted SHA256 and the exact token
mapping are recorded. It executes the actual installer/uninstaller transaction
logic, `cp`, `mv`, `rm`, `mktemp`, config loading/lint and Python preflight locally.
`install` uses the real coreutil minus owner/group switches; modes remain real.
PHP uses the real CLI with -n, avoiding ambient system php.ini/auto_prepend.
No source installation path is made configurable in the product itself.

Fake-host commands replace account/group lookups and mutation, systemctl and
apache2ctl. A synthetic configtest checks whether ini include targets exist;
it is NOT an Apache parser. Service states are explicitly fake. Command logs
identify those boundaries. Date is fixed so backup collisions reproduce without
timing guesses. Faults fire once at precise file/host boundaries. Tests clean up
all staged roots, including retained rollback snapshots.

Initial seven cases:

1. Existing application prepend refuses installation before config mutation.
2. Repeated upgrades within one timestamp retain distinct backups, preserve
   operator config/block mode, keep logs and emit one managed prepend directive.
3. Restart failure restores the complete previous app, config/unit/logrotate/ini
   and simulated service state.
4. TERM after app rename restores gate and include before simulated reload,
   exits 143 rather than stranding the old ini with no target.
5. Failed backup rename preserves the original app, not an empty reservation.
6. Fresh partial failure removes new app/config/include and preserves the site.
7. Uninstall reload failure retains the install; retry detaches before deletion
   and retains config/logs without purge.

Installer fixes characterized by these tests: previous backup names had only
second precision, so `mv` nested a subsequent install inside an old backup;
ERR-only rollback did not handle TERM. Backups now use a unique reserved
container with an `app` payload. The printed backup path points to that payload.
No payload exists before a successful rename. Rollback records whether an app
existed at entry; it removes a no-backup app only for a fresh install. Catchable
HUP/INT/TERM share rollback with conventional status codes; TERM is exercised.
SIGKILL, power loss, concurrent installers, repeated signals during rollback and
failures of rollback's own filesystem writes are not claimed to be covered.

This harness does not establish real ownership, privilege boundaries, mod_php,
systemd activation, service liveness, or HTTP/auto_prepend behavior. Those remain
separate integration checks requiring an appropriately authorized environment.
No production/customer readiness or CVE effectiveness follows from these tests.

## Repository integration (2026-11-07)

The reviewed local lifecycle fixes and their accumulated acceptance cases now
travel together. The Ubuntu integration workflow runs the 17 disposable-prefix
cases, then continues to its separate real Apache/systemd installation tests.
The prefix harness still substitutes ownership/accounts/services and does not
gain real-service coverage merely by running in CI.

Two additional repository-relative harnesses preserve the completed local
cross-component acceptance work (Python 3.9+ for the dashboard, PHP CLI):

```bash
python3 tests/acceptance/pipeline_compatibility.py
python3 tests/acceptance/php_pipeline.py
```

The first has three synthetic monitor/report/privacy tests. The second has two
real PHP CLI → would_block CSV → bandwidth/dashboard tests, with monitor mode
both explicit and omitted. It adapts only the isolated gate config path; it is
not HTTP/mod_php. PHP evidence defaults to the test's disposable directory or
the explicit IMMUTION_PIPELINE_EVIDENCE directory. No production logs are used.
These harnesses remain outside default unit-test discovery and are explicitly
invoked in Ubuntu integration CI. All input data are synthetic.

## Interrupted uninstall detach (2026-11-04 follow-up)

Six additional regressions send HUP, INT and TERM to the disposable uninstaller
parent at two exact boundaries: after real ini removal before configtest, and
immediately after a successful simulated Apache reload. Each records ini absence
and gate presence at injection, asserts complete file/mode restoration, unchanged
simulated service state, conventional exit 129/130/143, and configtest/reload after
restoration. A successful retry must preserve operator configuration, site and logs.

Run only these and the existing reload-error regression (changed recovery path):

```bash
IMMUTION_LIFECYCLE_EVIDENCE=/tmp/immution-detach-results python3 tests/acceptance/installer_prefix.py -k test_uninstall_
```

Before the fix all six signal cases fail: HUP/TERM abandon the removed ini;
INT can continue uninstalling rather than abort. The existing error-only case
passes. After the fix all seven selected tests pass. The detach transaction now
handles ERR/HUP/INT/TERM and reloads the restored ini, including when detachment
was already accepted. Reload recovery failure emits an explicit manual-recovery
message; that secondary-failure branch is not tested here. Signal traps end at
successful detach, before destructive removal; this is not a fully transactional
uninstall or protection against signals during later deletion. Existing limits
on real Apache, ownership, SIGKILL, concurrency and repeated signals still apply.

## Secondary recovery failures (2026-11-05)

Four new acceptance cases cover configtest or reload failure during recovery,
after TERM immediately following a successful detach reload, or after an initial
reload error. They test existing product behavior, not a new product fix:

```bash
IMMUTION_LIFECYCLE_EVIDENCE=/tmp/immution-recovery-results python3 tests/acceptance/installer_prefix.py -k test_recovery_
```

A separate recovery fault is armed only after the primary one-shot fault fires.
The adapter records the restored ini and existing gate at that exact boundary.
Assertions check the original exit status (143 or 43), unchanged files/modes and
simulated daemon state, exact validation/reload call sequence (no reload after
failed validation), no disable/user deletion, explicit manual-recovery warning,
and retained snapshot bytes/mode. A successful non-purge retry preserves config,
site, logs and the previous diagnostic snapshot. Temporary roots are removed
at test teardown; only synthetic evidence persists. Two disposable negative
controls remove the warning or delete the snapshot and must fail the new tests.

These cases close the previously untested secondary-failure diagnostic branch.
They do not establish live Apache protection: a failed recovery reload can leave
a running server using detached configuration despite restored on-disk ini.
Real Apache/HTTP/systemd, failed filesystem restore writes, repeated recovery
signals, SIGKILL and concurrent lifecycle operations remain outside this proof.
