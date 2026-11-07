#!/usr/bin/env python3
"""Run actual installer/uninstaller filesystem transactions in a disposable prefix.
Host accounts, ownership, Apache and systemctl are substitutes, not live evidence.
Run explicitly; intentionally outside default tests discovery.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(os.environ.get('IMMUTION_LIFECYCLE_EVIDENCE', str(ROOT/'lifecycle-evidence')))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def files(path):
    if not path.exists():
        return None
    return {str(p.relative_to(path)): (sha(p.read_bytes()), p.stat().st_mode & 0o777)
            for p in sorted(path.rglob('*')) if p.is_file()}


class InstallerPrefix(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='immution-lifecycle-')
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name)
        self.release = self.prefix/'release'
        shutil.copytree(ROOT, self.release,
                        ignore=shutil.ignore_patterns('.git', '__pycache__', 'lifecycle-evidence'))
        self.bin = self.prefix/'bin'
        self.bin.mkdir()
        self.record = []
        self.adaptations = {}
        self.app = self.prefix/'opt/immution'
        self.config = self.prefix/'etc/immution'
        self.ini = self.prefix/'etc/php/8.3/apache2/conf.d/99-immution.ini'
        self.service = self.prefix/'etc/systemd/system/immution.service'
        self.rotate = self.prefix/'etc/logrotate.d/immution'
        for directory in (self.ini.parent, self.service.parent, self.rotate.parent,
                          self.prefix/'tmp', self.prefix/'site'):
            directory.mkdir(parents=True, exist_ok=True)
        self.site = self.prefix/'site/index.php'
        self.site.write_text('<?php echo "SYNTHETIC_SITE";\n')
        self.host_state = self.prefix/'host-state.json'
        self.host_state.write_text(json.dumps(dict(active=False, enabled=False)))
        helper = self.bin/'fake_host.py'
        shutil.copyfile(ROOT/'tests/acceptance/fake_host.py', helper)
        for command in ('php', 'install', 'mv', 'date', 'apache2ctl', 'systemctl', 'getent',
                        'id', 'useradd', 'usermod', 'userdel', 'journalctl'):
            (self.bin/command).symlink_to(helper)
        helper.chmod(0o755)
        for name in ('install.sh', 'uninstall.sh'):
            path = self.release/'scripts'/name
            source = path.read_text()
            adapted = source
            changes = {'${EUID:-$(id -u)}': '0',
                       '/etc/': str(self.prefix)+'/etc/',
                       '/opt/immution': str(self.prefix)+'/opt/immution',
                       '/var/log/immution': str(self.prefix)+'/var/log/immution',
                       '/run/immution': str(self.prefix)+'/run/immution',
                       '/tmp/immution-': str(self.prefix)+'/tmp/immution-'}
            replacements = []
            # One pass prevents re-translating the generated /tmp prefix.
            for old, new in changes.items():
                count = source.count(old)
                replacements.append(dict(old=old, new=new, count=count))
            pattern = '|'.join(re.escape(token) for token in changes)
            adapted = re.sub(pattern, lambda hit: changes[hit.group(0)], source)
            path.write_text(adapted)
            self.adaptations[name] = dict(source_sha256=sha(source.encode()),
                                         adapted_sha256=sha(adapted.encode()),
                                         substitutions=replacements)
        self.env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                        IMMUTION_TEST_PREFIX=str(self.prefix), PYTHONDONTWRITEBYTECODE='1')
        self.out = EVIDENCE/self._testMethodName
        self.out.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.save_evidence)

    def save_evidence(self):
        (self.out/'runs.json').write_text(json.dumps(self.record, indent=2)+'\n')
        (self.out/'adaptations.json').write_text(json.dumps(self.adaptations, indent=2)+'\n')
        calls = self.prefix/'calls.jsonl'
        if calls.exists():
            shutil.copyfile(calls, self.out/'host-boundary-calls.jsonl')

    def run_script(self, script='install.sh', fault=None, arguments=(), recovery_failure=None):
        env = dict(self.env)
        if fault:
            env['IMMUTION_TEST_FAULT'] = fault
        if recovery_failure:
            env['IMMUTION_TEST_RECOVERY_FAILURE'] = recovery_failure
        marker = self.prefix/'fault-fired'
        if marker.exists():
            marker.unlink()
        p = subprocess.run(['bash', str(self.release/'scripts'/script)]+list(arguments),
                           cwd=str(self.release), env=env, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        self.record.append(dict(script=script, fault=fault, args=arguments, returncode=p.returncode,
                                stdout=p.stdout, stderr=p.stderr, recovery_failure=recovery_failure))
        return p

    def success(self, p):
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

    def install(self):
        self.success(self.run_script())
        self.assertTrue((self.app/'route_mutation.py').is_file())
        self.assertEqual((self.app/'gate.php').read_bytes(), (self.release/'src/gate.php').read_bytes())
        self.assertEqual(self.ini.read_text().count('auto_prepend_file = '), 1)
        self.assertIn(str(self.app/'gate.php'), self.ini.read_text())

    def customize(self):
        # Preserve non-default site settings, mode and arbitrary operator keys.
        (self.config/'gate-config.php').write_text("<?php return ['mode'=>'block', 'enabled'=>true, 'site_marker'=>'KEEP'];\n")
        (self.config/'daemon.json').write_text('{"threshold":91,"fingerprint_hosts":{},"operator":"KEEP"}\n')
        (self.app/'operator-note.txt').write_text('application tree marker\n')
        (self.prefix/'var/log/immution/events.csv').write_text('synthetic log preservation\n')

    def snapshot(self):
        targets = (self.app, self.config, self.ini, self.service, self.rotate, self.site)
        return {str(p.relative_to(self.prefix)): files(p) if p.is_dir() else
                (sha(p.read_bytes()), p.stat().st_mode & 0o777) if p.exists() else None for p in targets}

    def failed_recovery(self, primary, recovery, status):
        self.install()
        self.customize()
        before = self.snapshot()
        host_before = self.host_state.read_text()
        ini_before = self.ini.read_bytes()
        logs_before = files(self.prefix/'var/log/immution')
        # Consider only calls belonging to the failing uninstall, not setup.
        calls_path = self.prefix/'calls.jsonl'
        start = len(calls_path.read_text().splitlines())
        p = self.run_script('uninstall.sh', fault=primary, recovery_failure=recovery)
        failed = json.loads((self.prefix/'recovery-failed.json').read_text())
        self.record[-1]['recovery_boundary'] = failed
        self.assertEqual(failed['boundary'], recovery)
        self.assertEqual(failed['ini'].encode(), ini_before)
        self.assertTrue(failed['gate_exists'])
        self.assertEqual(p.returncode, status, 'preserve primary error/signal, not secondary failure status')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.host_state.read_text(), host_before)
        self.assertEqual(files(self.prefix/'var/log/immution'), logs_before)
        self.assertIn('manual Apache recovery required', p.stderr)
        self.assertIn('installation retained', p.stderr)
        self.assertNotIn('Immution removed.', p.stdout)
        match = re.search(r'Snapshot: (.+)', p.stderr)
        self.assertIsNotNone(match, p.stderr)
        snapshot = Path(match.group(1))
        self.assertIn(self.prefix, snapshot.resolve().parents)
        saved_ini = snapshot / str(self.ini).lstrip('/')
        self.assertEqual(saved_ini.read_bytes(), ini_before)
        self.assertEqual(saved_ini.stat().st_mode & 0o777, self.ini.stat().st_mode & 0o777)
        calls = [json.loads(line) for line in calls_path.read_text().splitlines()[start:]]
        expected_tail = [['apache2ctl', 'configtest']]
        if recovery == 'reload':
            expected_tail.append(['systemctl', 'reload', 'apache2'])
        self.assertEqual(calls, [['apache2ctl', 'configtest'], ['systemctl', 'reload', 'apache2']] + expected_tail)
        self.assertFalse(any(c[0] == 'userdel' or c[:2] == ['systemctl', 'disable'] for c in calls))
        self.record[-1]['retained_snapshot'] = files(snapshot)
        self.record[-1]['uninstall_calls'] = calls
        config_before = files(self.config)
        self.success(self.run_script('uninstall.sh'))
        self.assertFalse(self.app.exists())
        self.assertFalse(self.ini.exists())
        self.assertEqual(files(self.config), config_before)
        self.assertEqual(files(self.prefix/'var/log/immution'), logs_before)
        self.assertEqual(saved_ini.read_bytes(), ini_before, 'retry must not discard diagnostic snapshot')
        self.assertEqual(self.site.read_text(), '<?php echo "SYNTHETIC_SITE";\n')

    def test_recovery_reload_failure_after_term(self):
        self.failed_recovery('term-uninstall-after-reload', 'reload', 143)

    def test_recovery_configtest_failure_after_term(self):
        self.failed_recovery('term-uninstall-after-reload', 'configtest', 143)

    def test_recovery_reload_failure_after_error(self):
        self.failed_recovery('reload-apache', 'reload', 43)

    def test_recovery_configtest_failure_after_error(self):
        self.failed_recovery('reload-apache', 'configtest', 43)

    def interrupted_uninstall(self, name, status, boundary):
        self.install()
        self.customize()
        before = self.snapshot()
        host_before = self.host_state.read_text()
        p = self.run_script('uninstall.sh', fault=name + '-uninstall-' + boundary)
        point = json.loads((self.prefix/'interruption.json').read_text())
        self.record[-1]['interruption'] = point
        self.assertFalse(point['ini_exists'], 'signal must occur after real ini removal')
        self.assertTrue(point['gate_exists'])
        self.assertEqual(self.snapshot(), before, 'interrupted detach must restore managed ini and entire installation')
        self.assertEqual(p.returncode, status)
        self.assertEqual(self.host_state.read_text(), host_before)
        self.assertIn('installation retained', p.stderr)
        calls = [json.loads(line) for line in (self.prefix/'calls.jsonl').read_text().splitlines()]
        self.assertEqual(calls[-2:], [['apache2ctl', 'configtest'], ['systemctl', 'reload', 'apache2']],
                         'restored ini must be revalidated and reloaded before exit')
        self.assertNotIn('SIMULATED broken include', p.stderr)
        # A retry must detach safely and preserve operator data (not purge).
        config_before = files(self.config)
        self.success(self.run_script('uninstall.sh'))
        self.assertFalse(self.app.exists())
        self.assertFalse(self.ini.exists())
        self.assertEqual(files(self.config), config_before)
        self.assertTrue(self.site.is_file())
        self.assertEqual((self.prefix/'var/log/immution/events.csv').read_text(), 'synthetic log preservation\n')

    def test_uninstall_hup_before_reload(self):
        self.interrupted_uninstall('hup', 129, 'before-reload')

    def test_uninstall_hup_after_reload(self):
        self.interrupted_uninstall('hup', 129, 'after-reload')

    def test_uninstall_int_before_reload(self):
        self.interrupted_uninstall('int', 130, 'before-reload')

    def test_uninstall_int_after_reload(self):
        self.interrupted_uninstall('int', 130, 'after-reload')

    def test_uninstall_term_before_reload(self):
        self.interrupted_uninstall('term', 143, 'before-reload')

    def test_uninstall_term_after_reload(self):
        self.interrupted_uninstall('term', 143, 'after-reload')

    def test_preexisting_bootstrap_aborts_without_changes(self):
        bootstrap = self.prefix/'site/bootstrap.php'
        bootstrap.write_text('<?php // pre-existing include\n')
        existing = self.ini.with_name('98-existing.ini')
        existing.write_text('auto_prepend_file = '+str(bootstrap)+'\n')
        before = files(self.prefix/'etc')
        p = self.run_script()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Existing auto_prepend_file configuration detected', p.stderr)
        self.assertEqual(files(self.prefix/'etc'), before)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.config.exists())

    def test_repeat_upgrade_preserves_settings_and_distinct_backups(self):
        self.install()
        self.customize()
        config_before = files(self.config)
        self.success(self.run_script(arguments=('--mode', 'monitor')))
        first_backups = sorted(self.app.parent.glob('immution.backup-*'))
        self.assertEqual(len(first_backups), 1)
        first_payload = first_backups[0]/'app' if (first_backups[0]/'app').is_dir() else first_backups[0]
        self.assertEqual((first_payload/'operator-note.txt').read_text(), 'application tree marker\n')
        self.success(self.run_script(arguments=('--mode', 'monitor')))
        self.assertEqual(files(self.config), config_before)
        self.assertEqual(self.ini.read_text().count('auto_prepend_file = '), 1)
        self.assertEqual((self.prefix/'var/log/immution/events.csv').read_text(), 'synthetic log preservation\n')
        backups = sorted(self.app.parent.glob('immution.backup-*'))
        self.assertEqual(len(backups), 2, 'repeat installs within one timestamp must retain distinct complete snapshots')
        self.assertTrue(all((b/'app/gate.php').is_file() or (b/'gate.php').is_file() for b in backups))
        self.assertTrue(all(not (b/'immution').exists() for b in backups), 'must not nest prior installs')
        self.assertIn('Configured mode: block', self.record[-1]['stdout'])

    def test_upgrade_restart_failure_restores_entire_installation(self):
        self.install()
        self.customize()
        before = self.snapshot()
        host_before = json.loads(self.host_state.read_text())
        p = self.run_script(fault='restart')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('rolling back', p.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(json.loads(self.host_state.read_text()), host_before)
        self.assertTrue((self.app/'gate.php').is_file())

    def test_term_after_backup_restores_gate_before_reload(self):
        self.install()
        self.customize()
        before = self.snapshot()
        p = self.run_script(fault='term-after-backup')
        self.assertNotEqual(p.returncode, 0)
        after = self.snapshot()
        self.record[-1]['gate_exists_after'] = (self.app/'gate.php').is_file()
        self.record[-1]['tree_restored'] = after == before
        self.assertEqual(after, before, 'TERM must restore app and include/config, not strand prepend')
        self.assertEqual(p.returncode, 143, 'interrupted install should report TERM convention')
        self.assertTrue((self.app/'gate.php').is_file())
        self.assertIn('rolling back', p.stderr)
        self.assertNotIn('SIMULATED broken include', p.stderr)

    def test_failed_backup_move_does_not_replace_original_with_empty_reservation(self):
        self.install()
        self.customize()
        before = self.snapshot()
        p = self.run_script(fault='move-backup')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('rolling back', p.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.app/'operator-note.txt').is_file())

    def test_fresh_partial_failure_removes_new_include_and_app(self):
        before = self.snapshot()
        p = self.run_script(fault='restart')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('rolling back', p.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.ini.exists())
        self.assertFalse(self.config.exists())
        self.assertEqual(json.loads(self.host_state.read_text()), dict(active=False, enabled=False))

    def test_uninstall_reload_failure_retains_install_then_detaches_safely(self):
        self.install()
        self.customize()
        before = self.snapshot()
        p = self.run_script('uninstall.sh', fault='reload-apache')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.snapshot(), before)
        self.success(self.run_script('uninstall.sh'))
        self.assertFalse(self.app.exists())
        self.assertFalse(self.ini.exists())
        self.assertFalse(self.service.exists())
        self.assertEqual(files(self.config), before['etc/immution'])
        self.assertEqual(self.site.read_text(), '<?php echo "SYNTHETIC_SITE";\n')
        self.assertTrue((self.prefix/'var/log/immution/events.csv').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
