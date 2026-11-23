"""Bounded terminal overview and deterministic, privacy-preserving text dumps."""
from collections import Counter
from datetime import timedelta, timezone
from decimal import Decimal, localcontext
from heapq import nsmallest


def safe(value):
    return ''.join(c if 32 <= ord(c) < 127 else '?' for c in str(value))


def bar_chart(entries, width, unit):
    """One linear integer scale for the whole chart; '+' is a partial cell.

    None is unavailable, zero is an observed zero. Values always accompany bars.
    Only the presentation is bounded; never change the underlying aggregates.
    """
    entries = list(entries)
    width = max(1, width)
    label_width = min(24, max((len(safe(label)) for label, _ in entries), default=1))
    digits = max((len(str(value)) for _, value in entries if value is not None), default=3)
    digits = max(3, digits)
    label_width = max(1, min(label_width, width - digits - 6))
    cells = max(0, min(28, width - label_width - digits - 5))
    maximum = max((value for _, value in entries if value is not None), default=0)
    step = max(1, (maximum + max(1, cells) - 1) // max(1, cells))
    result = [('%s | #=%s | +=meno di # | -=vuoto | N/D=no dati' % (unit, step))[:width]]
    for label, value in entries:
        label = safe(label)
        if len(label) > label_width:
            label = label[:max(0, label_width - 1)] + '~'
        number = 'N/D' if value is None else str(value)
        bar = ''
        if cells and value is not None:
            full, remainder = divmod(value, step)
            fill = '#' * full + ('+' if remainder else '')
            bar = ' |' + fill.ljust(cells, '-') + '|'
        result.append(('%-*s %*s%s' % (label_width, label, digits, number, bar))[:width])
    return result


def traffic_categories(overview):
    c = overview['counts']
    return [(label, c[key] if overview['requests'] else None) for label, key in
            (('Browser', 'browser_like'), ('Ambigue', 'ambiguous'),
             ('Bot/tool UA', 'declared_bot'), ('Scanner', 'scanner'), ('Interne', 'internal'))]


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
    rows = [('IMMUTION | DEMO / SYNTHETIC | DATI SINTETICI | READ ONLY' if getattr(reader, 'demo', False) else 'IMMUTION | LIVE LOGS | READ ONLY'),
            'Generated: ' + reader.cutoff.astimezone(timezone.utc).isoformat(),
            'Timeframe: ' + reader.window.name + ' | timezone: Europe/Rome',
            'Range [start, end): [%s, %s)' % (reader.window.start.isoformat(), reader.window.end.isoformat()),
            'Effective end (exclusive, as of generation): ' + s['effective_end'].isoformat(),
            'Scope claimed Host: ' + site + ' (UNTRUSTED; not verified vhost)',
            'TOTAL BLOCKED %d | unique IPs %d' % (c['blocked'], u.get('blocked', 0)),
            'TOTAL WOULD_BLOCK %d | unique IPs %d (allowed, not blocked)' % (c['would_block'], u.get('would_block', 0)),
            'IPs are not bots; distinct counts overlap. No IPs/queries displayed.']
    if getattr(reader, 'traffic', None):
        overview = reader.traffic.overview(site)
        rows += ['GRUPPI OSSERVATI (non persone)',
                 'Richieste HTTP %s (unita separata, non sulla scala gruppi)' %
                 (overview['requests'] if overview['requests'] else 'N/D')]
        rows += bar_chart(traffic_categories(overview), 79, 'gruppi')
        rows += reader.traffic.report(site)
    rows += savings_rows(c['blocked'], 0, baseline, block_bytes)
    rows += ['BLOCCHI / CLAIMED HOST (untrusted; scala solo B, non M o gruppi)']
    rows += bar_chart([(host, counts['blocked']) for host, counts in ranked] +
                      [('Other', other['blocked'])], 79, 'B records')
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
               block_bytes=None, height=24, top_n=5, view='auto'):
    """ASCII cockpit; collectors and the full export remain independent."""
    from cockpit import render
    return render(reader, site, status, width, height, help_visible,
                  baseline, block_bytes, top_n, view)
