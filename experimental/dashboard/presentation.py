"""Bounded terminal overview and deterministic, privacy-preserving text dumps."""
from collections import Counter
from datetime import timezone
from decimal import Decimal, localcontext
from heapq import nsmallest


def safe(value):
    return ''.join(c if 32 <= ord(c) < 127 else '?' for c in str(value))


DIGITS = {
    '0': (' _ ', '| |', '|_|'), '1': ('   ', '  |', '  |'),
    '2': (' _ ', ' _|', '|_ '), '3': (' _ ', ' _|', ' _|'),
    '4': ('   ', '|_|', '  |'), '5': (' _ ', '|_ ', ' _|'),
    '6': (' _ ', '|_ ', '|_|'), '7': (' _ ', '  |', '  |'),
    '8': (' _ ', '|_|', '|_|'), '9': (' _ ', '|_|', ' _|'),
    '.': (' ', ' ', '.'), '-': ('   ', ' _ ', '   '),
}


def savings_rows(count, width, baseline=None, block_bytes=None):
    if baseline is None or block_bytes is None:
        return ['MB RISPARMIATI: N/D',
                'No response-byte evidence / baseline. Not measurable from event counts.']
    with localcontext() as context:
        context.prec = 40
        mb = Decimal(count) * (Decimal(baseline) - Decimal(block_bytes)) / Decimal(1000000)
        number = format(mb, '.2f')
    result = ['MB RISPARMIATI / STIMA: ' + number]
    if len(number) * 4 - 1 <= width:
        result += [' '.join(DIGITS[c][i] for c in number) for i in range(3)]
    return result + ['STIMA: blocked x (%s - %s) bytes / 1,000,000' % (baseline, block_bytes)]


def top_hosts(summary, limit, site='all'):
    cache = summary.setdefault('_top', {})
    key = (limit, site)
    if key in cache:
        return cache[key]
    scoped = [(host, counts) for host, counts in summary['sites'].items()
              if site == 'all' or site == host]
    ranked = nsmallest(max(0, limit), (item for item in scoped if item[1]['blocked'] > 0),
                       key=lambda item: (-item[1]['blocked'], item[0]))
    chosen = {host for host, _ in ranked}
    other = Counter({action: summary['counts'][action] - sum(c[action] for _, c in ranked)
                     for action in ('blocked', 'would_block')})
    result = (ranked, other, sum(host not in chosen for host, _ in scoped))
    cache[key] = result
    return result


def history_note(reader):
    days = (reader.window.end.date() - reader.window.start.date()).days
    seen = len(reader.summary()['dates'])
    return 'History UNKNOWN: event evidence %s/%s dates (idle OR gaps on others)' % (seen, days)


def dump_text(reader, site='all', status='unknown', top_n=5, baseline=None, block_bytes=None):
    s = reader.summary(site)
    c, u = s['counts'], s['unique']
    ranked, other, other_hosts = top_hosts(s, top_n, site)
    rows = ['IMMUTION | LIVE LOGS | READ ONLY',
            'Generated: ' + reader.cutoff.astimezone(timezone.utc).isoformat(),
            'Timeframe: ' + reader.window.name + ' | timezone: Europe/Rome',
            'Range [start, end): [%s, %s)' % (reader.window.start.isoformat(), reader.window.end.isoformat()),
            'Effective end (exclusive, as of generation): ' + s['effective_end'].isoformat(),
            'Scope claimed Host: ' + site + ' (UNTRUSTED; not verified vhost)',
            'TOTAL BLOCKED %d | unique IPs %d' % (c['blocked'], u.get('blocked', 0)),
            'TOTAL WOULD_BLOCK %d | unique IPs %d (allowed, not blocked)' % (c['would_block'], u.get('would_block', 0)),
            'IPs are not bots; distinct counts overlap. No IPs/queries displayed.']
    rows += savings_rows(c['blocked'], 0, baseline, block_bytes)
    rows += ['TOP %s CLAIMED HOST (untrusted; ranked by blocked records, ties by name)' % top_n,
             'CLAIMED HOST | BLOCKED | WOULD_BLOCK']
    rows += ['%s | %d | %d' % (host, counts['blocked'], counts['would_block']) for host, counts in ranked]
    if not ranked:
        rows.append('(no claimed Host with blocked records)')
    rows += ['OTHER HOSTS %d (including monitor-only) | %d | %d' %
             (other_hosts, other['blocked'], other['would_block']),
             'SELFTEST markers excluded: blocked=%d would_block=%d (spoofable)' %
             (s['tests']['blocked'], s['tests']['would_block']),
             'Future records excluded as of generation: %d' % s['future'],
             'Coverage: UNKNOWN; available events.csv rotations only, not all HTTP traffic.',
             history_note(reader),
             'Retention, logging continuity and gate/follower freshness cannot be proven.',
             'Source counts are file provenance, not verified sites.']
    for source in range(1, len(reader.paths) + 1):
        values = s['sources'][source]
        rows.append('source %d: blocked=%d would_block=%d' %
                    (source, values['blocked'], values['would_block']))
    rows += ['Warnings: ' + ('; '.join(sorted(set(reader.warnings))) or 'none'),
             'Read issues: ' + (', '.join('%s=%s' % pair for pair in sorted(reader.issues.items())) or 'none'),
             'Malformed, copytruncate, capacity/read limits can make counts INCOMPLETE.',
             'Services sampled: ' + status]
    return '\n'.join(safe(line) for line in rows) + '\n'


def lines(reader, site, status, help_visible=False):
    return dump_text(reader, site, status).splitlines()


def panel_rows(reader, site, status, width, help_visible=False, baseline=None,
               block_bytes=None, height=24, top_n=5):
    """One viewport, never a scrollable document. Hidden hosts go into OTHER."""
    width, height = max(1, width), max(0, height)
    if height == 0:
        return []
    s = reader.summary(site)
    c, u = s['counts'], s['unique']
    warnings = len(set(reader.warnings))
    problems = sum(v for k, v in reader.issues.items()
                   if k not in ('outside_range', 'rotation_compression_seen'))
    rows = []
    def add(text, style='normal'):
        text = safe(text)
        rows.append((text if len(text) <= width else text[:max(0, width - 1)] + '~', style))
    legend = 'q quit 1 today 2 yest 3 last7 4 prev-week t cycle ? help r refresh'
    if height < 18 or width < 58:
        add('IMMUTION | ' + reader.window.name + (' | ' + site if site != 'all' else ''), 'title')
        add(savings_rows(c['blocked'], 0, baseline, block_bytes)[0], 'metric')
        add('B %s | M %s (allowed)' % (c['blocked'], c['would_block']), 'metric')
        add('[%s,' % reader.window.start.date())
        add(' %s) Europe/Rome' % reader.window.end.date())
        add('UNKNOWN | warnings %s issues %s' % (warnings, problems), 'section')
        if height >= 10:
            add('Scope: ' + site + ' [untrusted]')
        if help_visible:
            for line in ('HELP: 1/2/3/4 or t range', 'n/p Host; 0 all; r refresh', '--once / --export for detail'):
                add(line)
        else:
            slots = max(0, min(top_n, height - len(rows) - 2))
            ranked, other, _ = top_hosts(s, slots, site)
            for host, values in ranked:
                add('%s B=%s M=%s' % (host, values['blocked'], values['would_block']))
            add('Other B=%s M=%s' % (other['blocked'], other['would_block']))
        footer = 'q quit t range ? help'
    else:
        add('IMMUTION / READ ONLY | ' + reader.window.name, 'title')
        add('[%s, %s) Europe/Rome' % (reader.window.start.date(), reader.window.end.date()))
        add('As of %s | end exclusive' % reader.cutoff.astimezone(reader.window.start.tzinfo).isoformat(timespec='seconds'), 'dim')
        add('Scope: ' + site + ' [claimed Host; UNTRUSTED]')
        # Three ASCII rows only if both width and actual remaining height allow.
        big_width = width if height >= 20 + top_n and not help_visible else 0
        for text in savings_rows(c['blocked'], big_width, baseline, block_bytes):
            add(text, 'metric')
        add('TOTAL BLOCKED %s | unique IPs %s' % (c['blocked'], u.get('blocked', 0)), 'metric')
        add('TOTAL MONITOR %s | unique IPs %s (allowed; not blocked)' % (c['would_block'], u.get('would_block', 0)), 'metric')
        if help_visible:
            add('HELP / READ ONLY', 'section')
            for text in ('1 today; 2 yesterday; 3 last7 incl today; 4 previous calendar week',
                         't cycles ranges; CLI --start DATE --end DATE for custom [start,end)',
                         'n/p or Tab: Host filter; 0: all; r: bounded refresh; q: quit',
                         'No scrolling: hidden Hosts aggregated in Other; --top N sets limit',
                         '--once or --export FILE: full sanitized dump, exclusive file create'):
                add(text)
        else:
            # Fixed rows after this block: Other + selftest + history + warnings
            # + issues + health + footer. Reserve a header and at least one row.
            slots = max(0, min(top_n, height - len(rows) - 9))
            ranked, other, other_hosts = top_hosts(s, slots, site)
            add('TOP CLAIMED HOST / UNTRUSTED (blocked records, not protected sites)', 'section')
            add('%-*s %8s %8s' % (max(8, width - 20), 'NAME (~ shortened)', 'BLOCKED', 'MONITOR'), 'dim')
            for host, values in ranked:
                name_width = max(8, width - 20)
                name = host if len(host) <= name_width else host[:name_width - 1] + '~'
                add('%s%-*s %8d %8d' % ('> ' if site == host else '  ', name_width - 2,
                    name, values['blocked'], values['would_block']), 'selected' if site == host else 'normal')
            if not ranked:
                add('(no blocked Host rows; empty OR unavailable history)')
            add('OTHER %s hosts incl hidden/monitor-only: B %s | M %s' %
                (other_hosts, other['blocked'], other['would_block']))
        add('Selftest excluded B=%s M=%s (spoofable) | IPs != bots' %
            (s['tests']['blocked'], s['tests']['would_block']), 'dim')
        add(history_note(reader), 'dim')
        add('Warnings (%s): %s' % (warnings, '; '.join(sorted(set(reader.warnings))) or 'none'), 'section' if warnings else 'dim')
        add('Issues %s | future excluded %s | details: --once / --export' % (problems, s['future']), 'dim')
        add('Services: ' + status + ' | gate freshness UNKNOWN', 'dim')
        footer = legend
    # Keep a dedicated quit/control row even at 1x1. No off-screen body exists.
    rows = rows[:max(0, height - 1)]
    if width < 58:
        footer = 'q quit t range ? help'
    text = safe(footer)[:width]
    return rows + [(text, 'section')]
