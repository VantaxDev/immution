"""Opt-in selected-vhost Combined logs: counts-only browser session heuristics.

No cookie, identity inference, network lookup or raw client/path/UA cache.
Independent of gate events: absence of gate blocks is not evidence of visits.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import stat
import zlib
from urllib.parse import unquote, urlsplit
from timeframes import ROME

BUDGET = 8 * 1024 * 1024  # decompressed across all opt-in traffic sources
MAX_RECORD = 65536
MAX_EVENTS = 100000
MAX_FILES = 128
CATEGORIES = ('browser_like', 'ambiguous', 'declared_bot', 'scanner', 'internal')
COMBINED = re.compile(
    r'^(\S+) \S+ \S+ \[([^\]]+)\] "([A-Z]+) ([^"\s]+) HTTP/[0-9.]+" '
    r'([1-5][0-9]{2}) (?:[0-9]+|-) "([^"\r\n]*)" "([^"\r\n]*)"$')
BOT = re.compile(r'bot|crawler|spider|headless|curl|wget|python|httpclient|scrapy|uptime|monitor|selenium|playwright|puppeteer', re.I)
BROWSER = re.compile(r'^Mozilla/5\.0 .*\b(?:Chrome|Firefox|Safari|Edg|OPR)/[0-9]', re.I)
PROBE = re.compile(r'(?:^|/)(?:\.env(?:\.|/|$)|\.git(?:/|$)|wp-login\.php|xmlrpc\.php|phpmyadmin|vendor/phpunit|\.aws(?:/|$))', re.I)
MONTHS = {v: i for i, v in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(), 1)}


def site_label(value):
    """Only operator-provided DNS names, never arbitrary claimed Host or IP."""
    value = value.lower()
    if value in ('all', 'unknown') or len(value) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value):
        raise ValueError('access-log site must be a DNS name')
    numeric = r'(?:[0-9]+|0x[0-9a-f]+)'
    if re.fullmatch(numeric + r'(?:\.' + numeric + r')*', value):
        raise ValueError('access-log site must not be an address')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError('access-log site must not be an address')


def source_spec(value):
    site, sep, path = value.partition('=')
    if not sep or not path:
        raise ValueError('use --access-log SITE=PATH')
    return site_label(site), Path(path)


def timestamp(value):
    # Locale-independent Apache %d/%b/%Y:%H:%M:%S %z.
    match = re.fullmatch(r'(\d{2})/([A-Z][a-z]{2})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-]\d{4})', value)
    if not match or match[2] not in MONTHS:
        raise ValueError('timestamp')
    normalized = '%s-%02d-%sT%s:%s:%s%s' % (match[3], MONTHS[match[2]], match[1], match[4], match[5], match[6], match[7])
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def regular_open(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError('nonregular')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


class Traffic:
    def __init__(self, sources=()):
        self.sources = list(sources)
        if len(self.sources) > 16 or len({s for s, _ in self.sources}) != len(self.sources):
            raise ValueError('use at most 16 distinct sites, each with one selected-vhost log')
        self.salt = os.urandom(16)
        self.events = []
        self.issues = Counter()
        self.available = set()
        self.signature = None
        self.previous_sizes = {}
        self.bytes_read = 0
        self.window = self.cutoff = None
        self._summary = None

    def token(self, value):
        return hashlib.blake2b(value.encode(), key=self.salt, digest_size=16).digest()

    def discover(self):
        files, signature, issues = [], [], Counter()
        seen = set()
        for site, base in self.sources:
            paths = [base]
            try:
                with os.scandir(base.parent) as entries:
                    for entry in entries:
                        if re.fullmatch(re.escape(base.name) + r'\.(?:[0-9]+)(?:\.gz)?', entry.name):
                            paths.append(Path(entry.path))
                            if len(paths) > 32:
                                issues[(site, 'file_limit')] += 1
                                break
            except OSError:
                issues[(site, 'unreadable_directory')] += 1
            paths = [p for p in paths if p.suffix != '.gz' or not Path(str(p)[:-3]).exists()]
            for path in sorted(paths, key=lambda p: (p != base, p.name))[:32]:
                try:
                    st = path.stat()
                    if not stat.S_ISREG(st.st_mode):
                        issues[(site, 'nonregular')] += 1
                        continue
                    key = (st.st_dev, st.st_ino)
                    if key in seen:
                        issues[(site, 'duplicate_source')] += 1
                        continue
                    seen.add(key)
                    if len(files) >= MAX_FILES:
                        issues[(site, 'file_limit')] += 1
                        continue
                    files.append((site, path))
                    signature.append((site, str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns))
                except OSError:
                    issues[(site, 'missing_or_unreadable')] += 1
        return files, (tuple(signature), tuple(sorted(issues.items()))), issues

    def refresh(self, window, now):
        self.window, self.cutoff, self._summary = window, now, None
        files, signature, discovered = self.discover()
        signature = (window.key, signature)
        if signature == self.signature:
            return  # Only sanitized events cached; cutoff still applied anew.
        self.signature = signature
        for site, path in files:
            try:
                size = path.stat().st_size
                if size < self.previous_sizes.get((site, str(path)), 0):
                    discovered[(site, 'source_shrank')] += 1
                self.previous_sizes[(site, str(path))] = size
            except OSError:
                discovered[(site, 'read_error')] += 1
        self.events, self.issues, self.available = [], discovered, set()
        remaining = BUDGET
        for site, path in files:
            if remaining <= 0:
                self.issues[(site, 'read_budget')] += 1
                continue
            try:
                with regular_open(path) as raw:
                    stream = gzip.GzipFile(fileobj=raw) if path.suffix == '.gz' else raw
                    try:
                        while remaining > 0:
                            line = stream.readline(min(MAX_RECORD + 1, remaining))
                            if not line:
                                break
                            self.bytes_read += len(line)
                            remaining -= len(line)
                            if len(line) > MAX_RECORD or not line.endswith(b'\n'):
                                self.issues[(site, 'partial_or_oversize')] += 1
                                break
                            if len(self.events) >= MAX_EVENTS:
                                self.issues[(site, 'event_limit')] += 1
                                break
                            self.consume(site, line)
                        if remaining <= 0:
                            self.issues[(site, 'read_budget')] += 1
                    finally:
                        if stream is not raw:
                            stream.close()
            except (OSError, EOFError, ValueError, zlib.error):
                self.issues[(site, 'read_error')] += 1

    def consume(self, site, line):
        try:
            match = COMBINED.fullmatch(line.decode('utf-8').rstrip('\n\r'))
            if not match:
                raise ValueError('format')
            ip, stamp, method, target, status, referrer, ua = match.groups()
            ip = ipaddress.ip_address(ip)
            # Mapped IPv4 is the same address, not a new visitor or a way to
            # separate bot/loopback evidence. Do not fold native IPv6 suffixes.
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
                ip = ip.ipv4_mapped
            stamp = timestamp(stamp)
            if not self.window.key[0] <= stamp < self.window.key[1]:
                return
            target = urlsplit(target)
            # Relative origin-form only; neither absolute-form proxy nor URI hosts
            # establish which site was visited. The mapping comes from the operator.
            if target.scheme or target.netloc or not target.path.startswith('/'):
                raise ValueError('request target')
            path = unquote(target.path).lower()
            suffix = Path(path).suffix
            page = method == 'GET' and int(status) == 200 and suffix in ('', '.html', '.htm', '.php') and not path.startswith(('/api/', '/health', '/metrics'))
            ref = urlsplit(referrer)
            same_ref = ref.scheme in ('http', 'https') and (ref.hostname or '').lower() == site
            internal = ip.is_loopback or ua.startswith(('IMMUTION-readonly-', 'Immution activation self-test'))
            bot, browser, probe = bool(BOT.search(ua)), bool(BROWSER.search(ua)), bool(PROBE.search(path))
            # No raw UA/IP/path/referrer persists beyond this method.
            self.events.append((stamp, site, self.token(str(ip)), self.token(ua), internal, bot, browser, probe, page, same_ref))
            self.available.add(site)
        except (ValueError, OverflowError, UnicodeError):
            self.issues[(site, 'unparseable')] += 1

    def summary(self):
        if self._summary is not None:
            return self._summary
        cutoff = min(self.cutoff, self.window.key[1])
        events = sorted((event for event in self.events if event[0] < cutoff), key=lambda e: e[0])
        contaminated = set()
        for stamp, site, ip, ua, internal, bot, browser, probe, page, ref in events:
            if bot or probe:
                contaminated.add((stamp.astimezone(ROME).date(), ip))
        grouped = defaultdict(list)
        records, first, last = Counter(), {}, {}
        for event in events:
            stamp, site, ip, ua = event[:4]
            day = stamp.astimezone(ROME).date()
            key = (site, day)
            records[key] += 1
            first.setdefault(key, stamp)
            last[key] = stamp
            sessions = grouped[(site, day, ip, ua)]
            if not sessions or (stamp - sessions[-1][-1][0]).total_seconds() > 1800:
                sessions.append([])
            sessions[-1].append(event)
        counts = defaultdict(Counter)
        for (site, day, ip, ua), sessions in grouped.items():
            for session in sessions:
                pages = [e for e in session if e[8] and e[6]]
                if any(e[4] for e in session):
                    category = 'internal'
                elif any(e[7] for e in session):
                    category = 'scanner'
                elif any(e[5] for e in session):
                    category = 'declared_bot'
                elif ((day, ip) not in contaminated and len(pages) >= 2 and
                      any(e[9] and (e[0] - pages[0][0]).total_seconds() >= 10 for e in pages[1:])):
                    category = 'browser_like'
                else:
                    category = 'ambiguous'
                counts[(site, day)][category] += 1
        self._summary = dict(counts=counts, records=records, first=first, last=last)
        return self._summary

    def report(self, site='all'):
        rows = ['VISITE / STIMA SESSIONI BROWSER (non persone; non umani verificati)',
                'Metric: IP+UA inactivity >30min, reset at local midnight; 2 page GET200 >=10s apart + same-site referrer.',
                'Recognized tools/probes excluded; browser spoofing still possible. Never total minus bots.',
                'NAT may merge visitors; IP/UA changes may split one visitor. No unique-person estimate.',
                'Traffic coverage UNKNOWN always; bounded prefix scan, not continuous history. Counts are observed only.']
        if not self.sources:
            return rows + ['STIMA BROWSER: N/D | no selected-vhost access log configured (gate events cannot count visits).']
        summary = self.summary()
        for label, _ in self.sources:
            if site != 'all' and label != site:
                continue
            keys = sorted(key for key in summary['records'] if key[0] == label)
            issues = ','.join('%s=%s' % (k[1], v) for k, v in sorted(self.issues.items()) if k[0] == label)
            rows.append('%s | coverage UNKNOWN%s | issues: %s' % (label, ' / INCOMPLETE' if issues else '', issues or 'none detected (not proof of completeness)'))
            if not keys:
                rows.append('STIMA BROWSER: N/D | no usable observations before cutoff; not zero humans.')
            for key in keys:
                count = summary['counts'][key]
                rows.append('%s %s | STIMA BROWSER %s observed | ambiguous %s | declared bot/tool %s | scanner %s | internal %s | requests %s' %
                            (label, key[1], count['browser_like'], count['ambiguous'], count['declared_bot'], count['scanner'], count['internal'], summary['records'][key]))
                rows.append('Observed records [%s, %s]; not continuity. Snapshot: %s' % (summary['first'][key].astimezone(ROME).isoformat(), summary['last'][key].astimezone(ROME).isoformat(), self.cutoff.isoformat()))
        if site != 'all' and site not in {s for s, _ in self.sources}:
            rows.append('STIMA BROWSER: N/D | selected Host has no mapped vhost log.')
        return rows

    def card(self, site='all'):
        labels = [s for s, _ in self.sources if site == 'all' or site == s]
        if not labels:
            return ['VISITE / STIMA BROWSER: N/D (access log non configurato)', 'Non persone; non deducibili dagli eventi del gate.']
        summary = self.summary()
        if len(labels) != 1:
            return ['VISITE / STIMA BROWSER: %s siti (n/p seleziona)' % len(labels), 'Non persone; dettaglio per sito e giorno: --once / --export']
        label = labels[0]
        keys = sorted(key for key in summary['records'] if key[0] == label)
        if not keys:
            return ['VISITE / STIMA BROWSER: N/D | ' + label, 'Nessuna osservazione utilizzabile; copertura UNKNOWN.']
        key = keys[-1]
        count = summary['counts'][key]
        partial = any(k[0] == label for k in self.issues)
        return ['VISITE / STIMA BROWSER %s osservate | %s' % (count['browser_like'], key[1]),
                'Non persone | UNKNOWN%s | %s' % ('/INCOMPLETE' if partial else '', label),
                'Ambigue %s | UA bot/tool %s | scanner %s | interne %s' % (count['ambiguous'], count['declared_bot'], count['scanner'], count['internal']),
                'Ultimo record %s | dettaglio --once' % summary['last'][key].astimezone(ROME).isoformat(timespec='seconds')]
