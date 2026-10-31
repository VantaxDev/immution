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
from collections import Counter, defaultdict
from timeframes import ROME, PRESETS, calendar_date, resolve_window
from presentation import safe, savings_rows, panel_rows, dump_text, lines

HEADER = 'timestamp,action,ip,host,request_uri,score,requests,errors_404,probes,user_agent,reasons'.split(',')
DEFAULTS = ['/var/log/immution/events.csv', '/var/log/immution/prioris/events.csv']
BUDGET = 8 * 1024 * 1024  # total decompressed bytes per refresh
MAX_RECORD = 65536
MAX_EVENTS = 300000

def claimed(value):
    # Only domain-shaped claims are displayed. Never display URLs, queries or IPs.
    value = value.lower().strip()
    if re.fullmatch(r'[^:]+:[0-9]{1,5}', value):
        value = value.split(':')[0]
    # ipaddress intentionally rejects legacy/ambiguous numeric spellings
    # (leading zeros, shortened or integer IPv4). Do not expose those as DNS
    # labels merely because they fail strict IP parsing. No DNS resolution.
    if re.fullmatch(r'[0-9.]+', value):
        return 'unknown'
    try:
        ipaddress.ip_address(value)
        return 'unknown'
    except ValueError:
        pass
    return value if len(value) <= 253 and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) else 'unknown'

class Reader:
    def __init__(self, paths, timeframe='today', start=None, end=None):
        self.paths = [Path(p) for p in paths]
        self.files = {}
        self.events = []
        self.issues = Counter()
        self.warnings = []
        self.day = None
        self.cutoff = None
        self.bytes_read = 0
        self.salt = os.urandom(16)
        self.timeframe = timeframe
        self.custom_start, self.custom_end = start, end
        self.window = None
        self._summaries = {}

    def set_timeframe(self, name):
        if name not in PRESETS:
            raise ValueError('unknown timeframe')
        self.timeframe = name

    def close(self):
        for state in self.files.values():
            state['file'].close()
        self.files.clear()

    def refresh(self, now=None):
        now = now or datetime.now(timezone.utc)
        window = resolve_window(self.timeframe, now, self.custom_start, self.custom_end)
        day = now.astimezone(ROME).date()
        if self.window is None or window.key != self.window.key:
            self.close()
            self.events.clear()
            self.issues.clear()
        self.day = day
        self.window = window
        self.cutoff = now
        self._summaries.clear()
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
            stamp = stamp.astimezone(timezone.utc)
            if not self.window.key[0] <= stamp < self.window.key[1]:
                self.issues['outside_range'] += 1
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
        except (ValueError, OverflowError, UnicodeError, csv.Error, StopIteration):
            self.issues['malformed'] += 1

    def summary(self, site='all'):
        if site in self._summaries:
            return self._summaries[site]
        if site != 'all':
            # Keep global + current scope only, not one full summary per Host.
            for previous in list(self._summaries):
                if previous != 'all':
                    del self._summaries[previous]
        counts, unique, tests, hours = Counter(), defaultdict(set), Counter(), Counter()
        sites, sources = defaultdict(Counter), defaultdict(Counter)
        last = None
        future = 0
        dates = set()
        effective_end = min(self.cutoff, self.window.key[1])
        for stamp, action, ip, host, source, test in self.events:
            if stamp >= effective_end:
                future += 1
                continue
            local = stamp.astimezone(ROME)
            dates.add(local.date())
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
            hours[(local.strftime('%Y-%m-%d %H %z'), action)] += 1
            last = max(last, stamp) if last else stamp
        result = dict(counts=counts, unique={k: len(v) for k,v in unique.items()}, tests=tests,
                      hours=hours, sites=sites, sources=sources, last=last, future=future,
                      dates=dates, effective_end=effective_end)
        self._summaries[site] = result
        return result

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


def screen_main(screen, curses, reader, args):
    base = terminal_theme(screen, curses)
    screen.keypad(True)
    screen.timeout(200)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    site, show_help = args.site, False
    due, status = 0, 'unknown'
    while True:
        if time.monotonic() >= due:
            reader.refresh()
            status = health()
            due = time.monotonic() + args.interval
        h, w = screen.getmaxyx()
        width = max(1, w - 1)
        rows = panel_rows(reader, site, status, width, show_help,
                          args.baseline_bytes, args.block_bytes, height=h, top_n=args.top)
        styles = {'normal': base, 'title': base | curses.A_BOLD,
                  'section': base | curses.A_BOLD | curses.A_UNDERLINE,
                  'selected': base | curses.A_BOLD, 'metric': base | curses.A_BOLD,
                  'dim': base | curses.A_DIM}
        screen.erase()
        for y, (row, style) in enumerate(rows):
            try:
                screen.addnstr(y, 0, row, max(0, w - 1), styles[style])
            except curses.error:
                pass
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'),ord('Q')):
            return
        if key in (9, ord('n'),ord('p'),curses.KEY_LEFT,curses.KEY_RIGHT):
            ids = ['all'] + sorted(reader.summary()['sites'])
            if site not in ids:
                ids.append(site)
            site = ids[(ids.index(site)+(-1 if key in (ord('p'),curses.KEY_LEFT) else 1)) % len(ids)]
        elif key == ord('0'):
            site = 'all'
        elif key == ord('?'):
            show_help = not show_help
        elif key in tuple(map(ord, '1234t')):
            if key == ord('t'):
                index = (PRESETS.index(reader.timeframe) + 1) % len(PRESETS) if reader.timeframe in PRESETS else 0
            else:
                index = key - ord('1')
            reader.set_timeframe(PRESETS[index])
            due = 0
        elif key == ord('r'):
            due = 0


def save_export(path, text):
    # O_EXCL also refuses existing symlinks. Aggregates are private by default.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as output:
        output.write(text)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--once',action='store_true')
    p.add_argument('--interval',type=float,default=5,help='refresh seconds (2..3600)')
    p.add_argument('--site',default='all',help='untrusted claimed Host, not a verified vhost')
    p.add_argument('--log',action='append',help='CSV source; repeat (default global and prioris)')
    p.add_argument('--timeframe', choices=PRESETS, help='default today; last7 includes today')
    p.add_argument('--start', type=calendar_date, help='custom inclusive YYYY-MM-DD, Rome midnight')
    p.add_argument('--end', type=calendar_date, help='custom EXCLUSIVE YYYY-MM-DD, Rome midnight')
    p.add_argument('--top', type=int, default=5, help='top blocked claimed Hosts (1..20, default 5)')
    p.add_argument('--export', metavar='FILE', help='write one sanitized snapshot to a NEW private file; no overwrite')
    p.add_argument('--baseline-bytes', type=int, help='explicit estimated average unblocked response bytes')
    p.add_argument('--block-bytes', type=int, help='explicit known average block response bytes')
    a = p.parse_args(argv)
    if (a.baseline_bytes is None) != (a.block_bytes is None):
        p.error('provide both --baseline-bytes and --block-bytes, or neither')
    if any(v is not None and not 0 <= v <= 10**15 for v in (a.baseline_bytes, a.block_bytes)):
        p.error('byte assumptions must be integers in 0..10^15')
    if not 2 <= a.interval <= 3600:
        p.error('interval must be 2..3600')
    if not 1 <= a.top <= 20:
        p.error('top must be 1..20')
    if (a.start is None) != (a.end is None):
        p.error('provide both --start and --end (end is exclusive)')
    if a.start is not None and a.timeframe is not None:
        p.error('choose --timeframe OR --start/--end')
    a.timeframe = 'custom' if a.start is not None else (a.timeframe or 'today')
    try:
        resolve_window(a.timeframe, datetime.now(timezone.utc), a.start, a.end)
    except (ValueError, OverflowError):
        p.error('invalid or unrepresentable range; use --start < --end, exclusive end')
    normalized = claimed(a.site)
    if a.site != 'all' and normalized == 'unknown' and a.site != 'unknown':
        p.error('site must be a claimed hostname or unknown (never an IP or URL)')
    a.site = normalized
    r = Reader(a.log or DEFAULTS, a.timeframe, a.start, a.end)
    try:
        if not a.once and not a.export and sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get('TERM') not in (None,'','dumb'):
            try:
                import curses
                curses.wrapper(screen_main,curses,r,a)
                return 0
            except ImportError:
                print('Curses unavailable; text snapshot.',file=sys.stderr)
            except curses.error:
                print('Curses unavailable; text snapshot.',file=sys.stderr)
        r.refresh()
        text = dump_text(r, a.site, health(), a.top, a.baseline_bytes, a.block_bytes)
        if a.export:
            try:
                save_export(a.export, text)
            except OSError as exc:
                p.error('cannot create export (no overwrite): ' + (exc.strerror or 'I/O error'))
        else:
            print(text, end='')
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        r.close()

if __name__ == '__main__':
    sys.exit(main())
