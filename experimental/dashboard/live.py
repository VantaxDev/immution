#!/usr/bin/env python3
"""Read-only live dashboard (Python 3.9+); never opens Apache logs or state."""
import argparse
import csv
import gzip
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import Counter, defaultdict

ROME = ZoneInfo('Europe/Rome')
HEADER = 'timestamp,action,ip,host,request_uri,score,requests,errors_404,probes,user_agent,reasons'.split(',')
DEFAULTS = ['/var/log/immution/events.csv', '/var/log/immution/prioris/events.csv']
BUDGET = 8 * 1024 * 1024  # total decompressed bytes per refresh
MAX_RECORD = 65536
MAX_EVENTS = 300000

def safe(value):
    return ''.join(c if 32 <= ord(c) < 127 else '?' for c in str(value))

def claimed(value):
    # Only domain-shaped claims are displayed. Never display URLs, queries or IPs.
    value = value.lower().strip()
    if re.fullmatch(r'[^:]+:[0-9]{1,5}', value):
        value = value.split(':')[0]
    try:
        ipaddress.ip_address(value)
        return 'unknown'
    except ValueError:
        pass
    return value if len(value) <= 253 and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) else 'unknown'

class Reader:
    def __init__(self, paths):
        self.paths = [Path(p) for p in paths]
        self.files = {}
        self.events = []
        self.issues = Counter()
        self.warnings = []
        self.day = None
        self.cutoff = None
        self.bytes_read = 0
        self.salt = os.urandom(16)

    def close(self):
        for state in self.files.values():
            state['file'].close()
        self.files.clear()

    def refresh(self, now=None):
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(ROME).date()
        if day != self.day:
            self.close()
            self.events.clear()
            self.issues.clear()
            self.day = day
        self.cutoff = now
        self.warnings = []
        remaining = BUDGET
        found = set()
        for source, base in enumerate(self.paths):
            if not base.exists():
                self.warnings.append('MISSING active source ' + str(source + 1))
            candidates = [base] + sorted(base.parent.glob(base.name + '.*'))
            for path in candidates[:128]:
                if path != base and not re.fullmatch(re.escape(base.name) + r'\.(?:\d+|\d{8})(?:\.gz)?', path.name):
                    continue
                try:
                    st = path.stat()
                    key = (source, st.st_dev, st.st_ino)
                    found.add(key)
                    state = self.files.get(key)
                    if state is not None:
                        state['path'] = str(path)
                    if state and st.st_size < state['size']:
                        # copytruncate: old data remains counted, new bytes are read from zero.
                        state['file'].close()
                        del self.files[key]
                        state = None
                        self.issues['copytruncate_coverage_uncertain'] += 1
                    if state is None:
                        if path.suffix == '.gz' and any(
                                old['path'] == str(path)[:-3] for old in self.files.values()):
                            # Compression of an inode already consumed; retain its descriptor.
                            self.issues['rotation_compression_seen'] = 1
                            continue
                        if len(self.files) >= 128:
                            self.warnings.append('file limit reached: INCOMPLETE')
                            continue
                        f = gzip.open(path, 'rb') if path.suffix == '.gz' else open(path, 'rb')
                        state = {'file': f, 'size': st.st_size, 'buffer': b'', 'header': False, 'source': source, 'discard': False, 'path': str(path)}
                        self.files[key] = state
                    state['size'] = st.st_size
                except OSError:
                    self.warnings.append('UNREADABLE source ' + str(source + 1))
            if len(candidates) > 128:
                self.warnings.append('rotation limit reached: INCOMPLETE')
        # Keep old descriptors through rename; same inode is never counted twice.
        for key, state in list(self.files.items()):
            if remaining <= 0:
                self.warnings.append('CATCHING UP: read budget reached')
                break
            try:
                data = state['file'].read(remaining)
            except (OSError, EOFError, zlib.error):
                self.warnings.append('READ ERROR source ' + str(state['source'] + 1))
                continue
            remaining -= len(data)
            self.bytes_read += len(data)
            data = state['buffer'] + data
            chunks = data.split(b'\n')
            state['buffer'] = chunks.pop()
            for chunk in chunks:
                if state['discard']:
                    state['discard'] = False
                    continue
                self.consume(chunk, state)
            if len(state['buffer']) > MAX_RECORD:
                self.issues['oversize'] += 1
                state['buffer'] = b''
                state['discard'] = True
        if remaining == 0:
            self.warnings.append('CATCHING UP: read budget reached')
        if any(not s['header'] for s in self.files.values()):
            self.warnings.append('NO VALID HEADER: empty or invalid source; coverage UNKNOWN')
        if any(s['buffer'] or s['discard'] for s in self.files.values()):
            self.warnings.append('PARTIAL trailing record pending')

    def consume(self, chunk, state):
        try:
            if len(chunk) > MAX_RECORD:
                raise ValueError()
            row = next(csv.reader([chunk.decode('utf-8')], strict=True))
            if row == HEADER:
                state['header'] = True
                return
            if not state['header'] or len(row) != len(HEADER):
                raise ValueError()
            r = dict(zip(HEADER, row))
            stamp = datetime.fromisoformat(r['timestamp'])
            if stamp.tzinfo is None:
                raise ValueError()
            if stamp.astimezone(ROME).date() != self.day:
                self.issues['outside_today'] += 1
                return
            if r['action'] not in ('blocked', 'would_block'):
                self.issues['unknown_action'] += 1
                return
            ip = str(ipaddress.ip_address(r['ip']))
            token = hashlib.blake2b(ip.encode(), key=self.salt, digest_size=16).digest()
            test = (r['host'].lower() == 'immution-selftest.invalid' and
                    r['request_uri'] == '/immution-block-activation-selftest' and
                    r['user_agent'] == 'Immution activation self-test')
            if len(self.events) >= MAX_EVENTS:
                self.issues['capacity_dropped'] += 1
                return
            self.events.append((stamp, r['action'], token, claimed(r['host']), state['source'] + 1, test))
        except (ValueError, UnicodeError, csv.Error, StopIteration):
            self.issues['malformed'] += 1

    def summary(self, site='all'):
        counts, unique, tests, hours = Counter(), defaultdict(set), Counter(), Counter()
        sites, sources = defaultdict(Counter), defaultdict(Counter)
        last = None
        future = 0
        for stamp, action, ip, host, source, test in self.events:
            if stamp > self.cutoff:
                future += 1
                continue
            if test:
                if site == 'all' or host == site:
                    tests[action] += 1
                continue
            sites[host][action] += 1
            if site != 'all' and host != site:
                continue
            counts[action] += 1
            unique[action].add(ip)
            sources[source][action] += 1
            hours[(stamp.astimezone(ROME).strftime('%H %z'), action)] += 1
            last = max(last, stamp) if last else stamp
        return dict(counts=counts, unique={k: len(v) for k,v in unique.items()}, tests=tests,
                    hours=hours, sites=sites, sources=sources, last=last, future=future)

def health():
    result = []
    for service in ('immution', 'apache2'):
        try:
            p = subprocess.run(['systemctl', 'show', service, '-p', 'ActiveState', '-p', 'SubState'],
                               capture_output=True, text=True, timeout=2)
            info = dict(line.split('=', 1) for line in p.stdout.splitlines() if '=' in line)
            result.append(service + '=' + (info.get('ActiveState', 'unknown') + '/' + info.get('SubState', 'unknown') if p.returncode == 0 else 'unknown'))
        except (OSError, subprocess.TimeoutExpired):
            result.append(service + '=unknown')
    return ' '.join(result)

def lines(reader, site, status, help_visible=False):
    s = reader.summary(site)
    c, u = s['counts'], s['unique']
    rows = ['IMMUTION | LIVE LOGS | READ ONLY',
            'Today Europe/Rome: ' + str(reader.day) + ' 00:00 -> ' + reader.cutoff.astimezone(ROME).isoformat(timespec='seconds'),
            'Claimed Host filter: ' + site + ' (UNTRUSTED; not verified vhost)',
            'BLOCKED %d | unique IPs %d' % (c['blocked'], u.get('blocked', 0)),
            'WOULD_BLOCK %d | unique IPs %d (allowed, not blocked)' % (c['would_block'], u.get('would_block', 0)),
            'IPs are not bots; distinct counts overlap. No IPs/queries displayed.',
            'SELFTEST markers excluded: blocked=%d would_block=%d (untrusted markers)' % (s['tests']['blocked'], s['tests']['would_block']),
            'Services sampled: ' + status,
            'Follower freshness / gate coverage: UNKNOWN (no heartbeat contract)',
            'Last event: ' + (s['last'].astimezone(ROME).isoformat(timespec='seconds') + ' age=%ds' % (reader.cutoff-s['last']).total_seconds() if s['last'] else 'none; not proof of failure'),
            'Coverage: available events.csv rotations only; not all HTTP traffic.',
            'Warnings: ' + ('; '.join(sorted(set(reader.warnings))) or 'none'),
            'Read issues (nonzero may mean INCOMPLETE): ' + str(dict(reader.issues)) + ' future=' + str(s['future'])]
    if help_visible:
        rows += ['HELP: Tab/n/p cycle claimed hosts; 0 all; j/k scroll; r refresh; q quit.',
                 'Refresh reads bounded appended bytes only; no daemon, bans or service changes.',
                 'Source 1 = global events.csv; source 2 = prioris/events.csv; not vhosts.',
                 'Known selftest requires host+URI+UA; spoofable, not authenticated.',
                 'Malformed/multiline records skipped visibly. Missing history cannot be inferred.']
    rows += ['', 'SOURCE (file provenance, NOT site)       BLOCKED  WOULD_BLOCK']
    for source in range(1, len(reader.paths)+1):
        v = s['sources'][source]
        rows.append('%-40s %7d %12d' % ('source ' + str(source), v['blocked'], v['would_block']))
    rows += ['', 'CLAIMED HOST (untrusted)                  BLOCKED  WOULD_BLOCK']
    for host, v in sorted(s['sites'].items()):
        rows.append('%-40s %7d %12d' % (host[:40], v['blocked'], v['would_block']))
    rows += ['', 'HOUR Rome offset                         BLOCKED  WOULD_BLOCK']
    for hour in sorted(set(h for h,a in s['hours'])):
        rows.append('%-40s %7d %12d' % (hour, s['hours'][(hour,'blocked')], s['hours'][(hour,'would_block')]))
    return [safe(row) for row in rows]

def terminal_theme(screen, curses):
    """Inherit terminal colors; never redefine the user's palette."""
    base = curses.A_NORMAL
    try:
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, -1, -1)
            base = curses.color_pair(1)
    except curses.error:
        base = curses.A_NORMAL
    screen.bkgd(' ', base)
    screen.attrset(base)
    return base


DIGITS = {
    '0': (' _ ', '| |', '|_|'), '1': ('   ', '  |', '  |'),
    '2': (' _ ', ' _|', '|_ '), '3': (' _ ', ' _|', ' _|'),
    '4': ('   ', '|_|', '  |'), '5': (' _ ', '|_ ', ' _|'),
    '6': (' _ ', '|_ ', '|_|'), '7': (' _ ', '  |', '  |'),
    '8': (' _ ', '|_|', '|_|'), '9': (' _ ', '|_|', ' _|'),
    '.': (' ', ' ', '.'), '-': ('   ', ' _ ', '   '),
}


def savings_rows(count, width, baseline=None, block_bytes=None):
    """Explicit counterfactual estimate only; no inferred or default byte values."""
    if baseline is None or block_bytes is None:
        return ['MB RISPARMIATI: N/D',
                'No response-byte evidence / baseline. Not measurable from event counts.']
    from decimal import Decimal, localcontext
    with localcontext() as context:
        context.prec = 40
        mb = Decimal(count) * (Decimal(baseline) - Decimal(block_bytes)) / Decimal(1000000)
        number = format(mb, '.2f')
    label = 'MB RISPARMIATI / STIMA: ' + number
    result = [label]
    if len(number) * 4 - 1 <= width:
        result += [' '.join(DIGITS[c][i] for c in number) for i in range(3)]
    result += ['STIMA: blocked x (%s - %s) bytes / 1,000,000' % (baseline, block_bytes)]
    return result


def panel_rows(reader, site, status, width, help_visible=False, baseline=None, block_bytes=None):
    """Presentation only; collector and --once semantics remain unchanged."""
    import textwrap
    width = max(1, width)
    s = reader.summary(site)
    rows = []
    def add(text, style='normal'):
        text = safe(text)
        if len(text) <= width:
            rows.append((text, style))
        else:
            for part in textwrap.wrap(text, width, replace_whitespace=False) or ['']:
                rows.append((part, style))
    def section(text):
        add(text + ' ' + '-' * max(0, width - len(text) - 1), 'section')
    def table(label, values, timeline=False):
        section(label)
        if width < 42:
            for name, b, m, selected in values:
                add(('> ' if selected else '  ') + name, 'selected' if selected else 'normal')
                add('  B %s | M %s' % (b, m))
            return
        digits = max([7] + [len(str(v)) for row in values for v in row[1:3]])
        bar_width = min(18, max(0, width - 60)) if timeline else 0
        name_width = max(8, width - 2 * digits - 5 - (bar_width + 1 if bar_width else 0))
        add('  %-*s %*s %*s' % (name_width, 'HOUR / UTC OFFSET' if timeline else 'NAME', digits, 'BLOCKED', digits, 'MONITOR'), 'dim')
        peak = max([1] + [max(b, m) for _, b, m, _ in values])
        for name, b, m, selected in values:
            name = safe(name)
            if len(name) > name_width:
                name = name[:name_width - 1] + '~'
            text = '%s %-*s %*d %*d' % ('>' if selected else ' ', name_width, name, digits, b, digits, m)
            if bar_width:
                half = max(1, (bar_width - 1) // 2)
                text += ' ' + ('#' * round(b / peak * half)).ljust(half) + '/' + ('+' * round(m / peak * half)).ljust(half)
            add(text, 'selected' if selected else 'normal')
    c, u = s['counts'], s['unique']
    section('01 OVERVIEW')
    for text in savings_rows(c['blocked'], width, baseline, block_bytes):
        add(text, 'metric')
    add('Today Europe/Rome / selected host / MB = 1,000,000 bytes', 'dim')
    metrics = ['BLOCKED  %s  | IPs %s' % (format(c['blocked'], ','), u.get('blocked', 0)),
               'MONITOR  %s  | IPs %s' % (format(c['would_block'], ','), u.get('would_block', 0))]
    if width >= 70:
        add(metrics[0].ljust((width - 3) // 2) + ' | ' + metrics[1], 'metric')
    else:
        for metric in metrics:
            add(metric, 'metric')
    add('MONITOR = would_block (allowed). Distinct IPs overlap; IPs are not bots.', 'dim')
    add('Today %s 00:00 -> %s Europe/Rome' % (reader.day, reader.cutoff.astimezone(ROME).strftime('%H:%M:%S')), 'dim')
    add('Last event: ' + (s['last'].astimezone(ROME).strftime('%H:%M:%S') + ' (%ds ago)' % (reader.cutoff - s['last']).total_seconds() if s['last'] else 'none; not proof of failure'))
    if help_visible:
        section('HELP / READ ONLY')
        for text in lines(reader, site, status, True)[13:18]:
            add(text)
        add('Bars: # blocked / + monitor, common peak scale. ~ means shortened host; selected host is shown in full above.')
        add('Home: first row; PgUp/PgDn: page. ? closes help. Colors: terminal defaults, no palette changes.')
    table('02 CLAIMED HOSTS / UNTRUSTED', [(host, v['blocked'], v['would_block'], host == site) for host, v in sorted(s['sites'].items())])
    table('03 HOURLY EVENTS / # BLOCKED + MONITOR', [(hour, s['hours'][(hour, 'blocked')], s['hours'][(hour, 'would_block')], False) for hour in sorted(set(h for h, a in s['hours']))], True)
    table('04 SOURCES / FILES, NOT VHOSTS', [('source %s' % source, s['sources'][source]['blocked'], s['sources'][source]['would_block'], False) for source in range(1, len(reader.paths) + 1)])
    section('05 HEALTH & COVERAGE')
    add('Services sampled: ' + status)
    add('Follower freshness / gate coverage: UNKNOWN (no heartbeat contract)')
    add('Available events.csv rotations only; not all HTTP traffic.')
    add('Selftest markers excluded: B=%d M=%d (spoofable)' % (s['tests']['blocked'], s['tests']['would_block']))
    add('Warnings: ' + ('; '.join(sorted(set(reader.warnings))) or 'none'))
    add('Read issues: %s; future=%s' % (dict(reader.issues), s['future']))
    return rows


def screen_main(screen, curses, reader, args):
    base = terminal_theme(screen, curses)
    screen.keypad(True)
    screen.timeout(200)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    site, offset, show_help = args.site, 0, False
    due, status = 0, 'unknown'
    while True:
        if time.monotonic() >= due:
            reader.refresh()
            status = health()
            due = time.monotonic() + args.interval
        h, w = screen.getmaxyx()
        width = max(1, w - 1)
        rows = panel_rows(reader, site, status, width, show_help, args.baseline_bytes, args.block_bytes)
        import textwrap
        header = [('IMMUTION / LIVE LOGS / READ ONLY', 'title')]
        header += [(part, 'selected') for part in textwrap.wrap(safe('Host > ' + site + ' [untrusted]'), width)]
        warning = bool(reader.warnings or reader.issues)
        header.append(('! INCOMPLETE / inspect health panel' if warning else 'Coverage UNKNOWN | ? details', 'section' if warning else 'dim'))
        header = header[:max(0, min(len(header), h - 3))]
        body_height = max(0, h - len(header) - 1)
        offset = min(offset, max(0, len(rows) - body_height))
        legend = 'q quit ? help n/p host 0 all j/k scroll r refresh'
        if width >= 75:
            legend += ' | %ss | %s/%s' % (args.interval, offset + 1, len(rows))
        styles = {'normal': base, 'title': base | curses.A_BOLD,
                  'section': base | curses.A_BOLD | curses.A_UNDERLINE,
                  'selected': base | curses.A_BOLD, 'metric': base | curses.A_BOLD,
                  'dim': base | curses.A_DIM}
        screen.erase()
        visible = header + rows[offset:offset + body_height]
        for y, (row, style) in enumerate(visible):
            try:
                screen.addnstr(y, 0, row, max(0, w - 1), styles[style])
            except curses.error:
                pass
        if h:
            try:
                screen.addnstr(h - 1, 0, legend, max(0, w - 1), base | curses.A_BOLD)
            except curses.error:
                pass
        screen.refresh()
        key = screen.getch()
        ids = ['all'] + sorted(reader.summary()['sites'])
        if site not in ids:
            ids.append(site)
        if key in (ord('q'),ord('Q')):
            return
        if key in (9, ord('n'),ord('p'),curses.KEY_LEFT,curses.KEY_RIGHT):
            site = ids[(ids.index(site)+(-1 if key in (ord('p'),curses.KEY_LEFT) else 1)) % len(ids)]
            offset = 0
        elif key == ord('0'):
            site, offset = 'all',0
        elif key == ord('?'):
            show_help, offset = not show_help,0
        elif key in (ord('j'),curses.KEY_DOWN):
            offset += 1
        elif key in (ord('k'),curses.KEY_UP):
            offset = max(0,offset-1)
        elif key == curses.KEY_HOME:
            offset = 0
        elif key == curses.KEY_NPAGE:
            offset += max(1, body_height)
        elif key == curses.KEY_PPAGE:
            offset = max(0, offset - max(1, body_height))
        elif key == ord('r'):
            due = 0

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--once',action='store_true')
    p.add_argument('--interval',type=float,default=5,help='refresh seconds (2..3600)')
    p.add_argument('--site',default='all',help='untrusted claimed Host, not a verified vhost')
    p.add_argument('--log',action='append',help='CSV source; repeat (default global and prioris)')
    p.add_argument('--baseline-bytes', type=int, help='explicit estimated average unblocked response bytes')
    p.add_argument('--block-bytes', type=int, help='explicit known average block response bytes')
    a = p.parse_args(argv)
    if (a.baseline_bytes is None) != (a.block_bytes is None):
        p.error('provide both --baseline-bytes and --block-bytes, or neither')
    if any(v is not None and not 0 <= v <= 10**15 for v in (a.baseline_bytes, a.block_bytes)):
        p.error('byte assumptions must be integers in 0..10^15')
    if not 2 <= a.interval <= 3600:
        p.error('interval must be 2..3600')
    r = Reader(a.log or DEFAULTS)
    try:
        if not a.once and sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get('TERM') not in (None,'','dumb'):
            try:
                import curses
                curses.wrapper(screen_main,curses,r,a)
                return 0
            except ImportError:
                print('Curses unavailable; text snapshot.',file=sys.stderr)
            except curses.error:
                print('Curses unavailable; text snapshot.',file=sys.stderr)
        r.refresh()
        print('\n'.join(lines(r,a.site,health())))
        print('\n'.join(savings_rows(r.summary(a.site)['counts']['blocked'], 0, a.baseline_bytes, a.block_bytes)))
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        r.close()

if __name__ == '__main__':
    sys.exit(main())
