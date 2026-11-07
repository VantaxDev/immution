#!/usr/bin/env python3
"""Host-boundary substitutes for disposable installer acceptance, never services.
Real file operations remain GNU coreutils. Every mutation destination is checked.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

prefix = Path(os.environ['IMMUTION_TEST_PREFIX']).resolve()
assert str(prefix).startswith('/tmp/immution-lifecycle-'), prefix
command = Path(sys.argv[0]).name
args = sys.argv[1:]
with (prefix/'calls.jsonl').open('a') as output:
    output.write(json.dumps([command] + args) + '\n')

def within(value):
    p = Path(value)
    assert p.is_absolute() and prefix in p.resolve().parents, value

def fault(point):
    marker = prefix/'fault-fired'
    if os.environ.get('IMMUTION_TEST_FAULT') == point and not marker.exists():
        marker.write_text(point)
        return True
    return False

def recovery_failure(boundary):
    # The primary one-shot fault must already have fired. Never affect install.
    if (os.environ.get('IMMUTION_TEST_RECOVERY_FAILURE') == boundary
            and (prefix/'fault-fired').exists()
            and not (prefix/'recovery-failed.json').exists()):
        ini = prefix/'etc/php/8.3/apache2/conf.d/99-immution.ini'
        (prefix/'recovery-failed.json').write_text(json.dumps(dict(
            boundary=boundary, ini=ini.read_text() if ini.exists() else None,
            gate_exists=(prefix/'opt/immution/gate.php').is_file())))
        print('SIMULATED recovery ' + boundary + ' failure', file=sys.stderr)
        return True
    return False

def interrupt_uninstall(boundary):
    for name in ('hup', 'int', 'term'):
        if fault(name + '-uninstall-' + boundary):
            # Only target our disposable parent, and record the actual detached state.
            (prefix/'interruption.json').write_text(json.dumps(dict(
                boundary=boundary, signal=name,
                ini_exists=(prefix/'etc/php/8.3/apache2/conf.d/99-immution.ini').exists(),
                gate_exists=(prefix/'opt/immution/gate.php').is_file())))
            os.kill(os.getppid(), getattr(signal, 'SIG' + name.upper()))

if command == 'php':
    # Real CLI, without ambient system php.ini/auto_prepend or extensions.
    os.execv('/usr/bin/php', ['/usr/bin/php', '-n'] + args)

if command in ('install', 'mv'):
    operands = []
    clean = []
    i = 0
    while i < len(args):
        value = args[i]
        if command == 'install' and value in ('-o', '-g'):
            i += 2
            continue
        clean.append(value)
        if value in ('-m', '-t'):
            i += 1
            clean.append(args[i])
        elif not value.startswith('-'):
            operands.append(value)
        i += 1
    if command == 'install' and '-d' in clean:
        for value in operands:
            within(value)
    else:
        within(operands[-1])
    if command == 'mv' and operands[0] == str(prefix/'opt/immution') and fault('move-backup'):
        sys.exit(44)
    result = subprocess.run(['/usr/bin/' + command] + clean)
    if result.returncode:
        sys.exit(result.returncode)
    if command == 'mv' and operands[0] == str(prefix/'opt/immution') and fault('term-after-backup'):
        os.kill(os.getppid(), signal.SIGTERM)
    sys.exit(0)

if command == 'date':
    if args == ['+%Y%m%d-%H%M%S']:
        print('20261104-225100')
        sys.exit(0)
    os.execv('/usr/bin/date', ['/usr/bin/date'] + args)

if command == 'apache2ctl':
    if args == ['-M']:
        print(' php_module (shared)')
    elif args == ['configtest']:
        if recovery_failure('configtest'):
            sys.exit(45)
        interrupt_uninstall('before-reload')
        for ini in (prefix/'etc/php').glob('*/apache2/conf.d/*.ini'):
            for line in ini.read_text().splitlines():
                if line.startswith('auto_prepend_file = '):
                    include = line.split(' = ', 1)[1].strip('"\'')
                    within(include)
                    if not Path(include).is_file():
                        print('SIMULATED broken include: ' + include, file=sys.stderr)
                        sys.exit(1)
        print('SIMULATED Syntax OK')
    else:
        raise AssertionError(args)
    sys.exit(0)

if command == 'systemctl':
    state_file = prefix/'host-state.json'
    state = json.loads(state_file.read_text())
    op = args[0]
    if op == 'is-active':
        sys.exit(0 if state['active'] else 3)
    if op == 'is-enabled':
        sys.exit(0 if state['enabled'] else 1)
    if op == 'restart' and args[-1] == 'immution' and fault('restart'):
        sys.exit(42)
    if op == 'reload' and args[-1] == 'apache2' and recovery_failure('reload'):
        sys.exit(46)
    if op == 'reload' and args[-1] == 'apache2' and fault('reload-apache'):
        sys.exit(43)
    if op in ('start', 'restart'):
        state['active'] = True
    elif op == 'stop':
        state['active'] = False
    elif op == 'enable':
        state['enabled'] = True
    elif op == 'disable':
        state['enabled'] = False
        if '--now' in args:
            state['active'] = False
    elif op not in ('daemon-reload', 'reload'):
        raise AssertionError(args)
    state_file.write_text(json.dumps(state))
    if op == 'reload' and args[-1] == 'apache2':
        interrupt_uninstall('after-reload')
    sys.exit(0)

if command == 'getent':
    assert args in (['group', 'www-data'], ['group', 'adm'])
    sys.exit(0)
if command == 'id':
    assert args == ['immution']
    sys.exit(0)
if command in ('useradd', 'usermod', 'userdel', 'journalctl'):
    sys.exit(0)
raise AssertionError((command, args))
