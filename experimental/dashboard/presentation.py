"""Bounded terminal overview and deterministic, privacy-preserving text dumps."""
from collections import Counter
from datetime import timedelta, timezone
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
    rows = [('IMMUTION | DEMO / SYNTHETIC | READ ONLY' if getattr(reader, 'demo', False) else 'IMMUTION | LIVE LOGS | READ ONLY'),
            'Generated: ' + reader.cutoff.astimezone(timezone.utc).isoformat(),
            'Timeframe: ' + reader.window.name + ' | timezone: Europe/Rome',
            'Range [start, end): [%s, %s)' % (reader.window.start.isoformat(), reader.window.end.isoformat()),
            'Effective end (exclusive, as of generation): ' + s['effective_end'].isoformat(),
            'Scope claimed Host: ' + site + ' (UNTRUSTED; not verified vhost)',
            'TOTAL BLOCKED %d | unique IPs %d' % (c['blocked'], u.get('blocked', 0)),
            'TOTAL WOULD_BLOCK %d | unique IPs %d (allowed, not blocked)' % (c['would_block'], u.get('would_block', 0)),
            'IPs are not bots; distinct counts overlap. No IPs/queries displayed.']
    if getattr(reader, 'traffic', None):
        rows += reader.traffic.report(site)
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


def traffic_panel_rows(reader, site, width, height, help_visible=False):
    """Traffic-first viewport using the existing conservative session heuristic.

    Unobserved dates/sources are N/D, never interpolated as zero. No enforcement
    ratios: selected-vhost traffic and claimed-Host gate events differ in scope.
    """
    rows = []
    def add(text, style='normal'):
        text = safe(text)
        rows.append((text if len(text) <= width else text[:max(0, width - 1)] + '~', style))
    footer = 'q quit v blocchi n/p sito 0 tutti 1/2/3/4 periodo ? aiuto r refresh'
    if width < 58:
        footer = 'q quit v vista n/p sito t periodo'
    marker = 'DEMO | ' if getattr(reader, 'demo', False) else ''
    add('IMMUTION / TRAFFICO | ' + marker + reader.window.name, 'title')
    add('[%s, %s) Europe/Rome' % (reader.window.start.date(), reader.window.end.date()), 'dim')
    if height >= 18 and width >= 58:
        add('Snapshot ' + reader.cutoff.astimezone(reader.window.start.tzinfo).isoformat(timespec='seconds'), 'dim')
    add('Sito: ' + ('tutti i log mappati' if site == 'all' else site), 'section')
    traffic = reader.traffic
    overview = traffic.overview(site)
    c, requests = overview['counts'], overview['requests']
    if height < 10:
        rows.clear()
        add('IMMUTION / TRAFFICO' + (' / DEMO' if marker else ''), 'title')
        add('BROWSER %s gruppi' % (c['browser_like'] if requests else 'N/D'), 'metric')
        add('Non persone; UA falsificabili', 'dim')
        add('Amb %s | Bot UA %s' % (c['ambiguous'], c['declared_bot']))
        add('HTTP %s' % (requests if requests else 'N/D'))
        add('UNKNOWN%s' % (' / INCOMPLETE' if overview['issues'] else ''), 'section')
        return rows[:max(0, height - 1)] + [(safe(footer)[:width], 'section')]
    if not overview['sites']:
        add('VISITE / STIMA BROWSER: N/D', 'metric')
        add('Access log non configurato per la selezione.')
        add('Usa --access-log SITO=FILE (Combined per vhost).')
        add('Gli eventi del gate non misurano le visite.', 'dim')
    elif not requests:
        add('VISITE / STIMA BROWSER: N/D', 'metric')
        add('Nessun record utilizzabile prima del cutoff.')
        add('Non significa zero visite o zero persone.', 'dim')
    else:
        add('VISITE / STIMA BROWSER %s osservate' % c['browser_like'], 'metric')
        add('Non persone; non umani verificati. UA falsificabili.', 'dim')
        if width >= 58:
            add('Ambigue %s | Bot/tool UA %s | Scanner %s | Interne %s' %
                (c['ambiguous'], c['declared_bot'], c['scanner'], c['internal']))
        else:
            add('Ambigue %s | Bot/tool UA %s' % (c['ambiguous'], c['declared_bot']))
            if height >= 14:
                add('Scanner %s | Interne %s' % (c['scanner'], c['internal']))
        add('Richieste HTTP %s | gruppi != richieste' % requests, 'metric')
        age = max(0, int((reader.cutoff - overview['last']).total_seconds()) // 60)
        add('Ultimo record %s (%sm fa)' %
            (overview['last'].astimezone(reader.window.start.tzinfo).strftime('%d/%m %H:%M %z'), age), 'dim')
        if height >= 18:
            add('Record %s; non prova salute o continuita.' % ('non recente (>15m)' if age > 15 else 'recente (<=15m)'), 'dim')
    add('Copertura UNKNOWN%s | problemi %s' %
        (' / INCOMPLETE' if overview['issues'] else '', overview['issues']), 'section')
    if help_visible:
        add('HELP / READ ONLY', 'section')
        for text in ('v: traffico / blocchi; n/p o Tab: sito; 0: tutti',
                     '1 oggi; 2 ieri; 3 ultimi7; 4 settimana precedente; t ciclo',
                     '2 pagine GET200 >=10s + referrer stesso sito; gap >30min',
                     'IP+UA/giorno: NAT unisce, cambio IP/UA divide; no persone',
                     'Bot/tool: UA dichiarato, non crawler verificato via DNS',
                     'N/D: nessuna osservazione; non uno zero misurato',
                     'Barre: gruppi browser osservati, non probabilita umana',
                     '--once / --export FILE: tutti i giorni/siti e problemi'):
            add(text)
    elif height >= 18 and width >= 58:
        # Reserve two gate/caveat lines and controls; fit days and sites together.
        room = max(0, height - len(rows) - 3)
        if room >= 3:
            span = (reader.window.end.date() - reader.window.start.date()).days
            days = min(span, 7, max(1, room - 7))
            add('GIORNO       BROWSER  AMBIGUI BOT/UA    HTTP | andamento browser', 'section')
            last_day = reader.window.end.date() - timedelta(days=1)
            days_to_show = [last_day - timedelta(days=i) for i in reversed(range(days))]
            maximum = max((overview['daily'].get(day, {}).get('counts', {}).get('browser_like', 0)
                           for day in days_to_show), default=0)
            for day in days_to_show:
                entry = overview['daily'].get(day)
                if entry:
                    count = entry['counts']
                    bar = '#' * max(1, round(count['browser_like'] / maximum * 10)) if count['browser_like'] and maximum else '-'
                    add('%s %7s %8s %6s %7s | %s' % (day, count['browser_like'], count['ambiguous'], count['declared_bot'], entry['requests'], bar))
                else:
                    add('%s     N/D      N/D    N/D     N/D | nessun record' % day)
            if span > days:
                add('Ultimi %s/%s giorni selezionati; intero periodo: --once' % (days, span), 'dim')
            remaining = height - len(rows) - 3
            if remaining >= 2:
                add('SITO MAPPATO (periodo)          BROWSER  BOT/UA AMBIGUI    HTTP', 'section')
                sites = sorted(overview['sites'].items())
                slots = remaining - 1
                # Reserve one row to disclose hidden sites, even if none fit.
                visible = slots if len(sites) <= slots else max(0, slots - 1)
                for label, entry in sites[:visible]:
                    count = entry['counts']
                    values = [count['browser_like'], count['declared_bot'], count['ambiguous'], entry['requests']] if entry['requests'] else ['N/D'] * 4
                    name = label if len(label) <= 28 else label[:27] + '~'
                    add('%-28s %7s %7s %7s %7s' % (name, *values))
                if len(sites) > visible:
                    add('+ %s siti non mostrati: n/p seleziona; --once tutti' % (len(sites) - visible), 'dim')
    if height >= 14:
        gate = reader.summary(site)['counts']
        add('Gate claimed Host: B %s | M %s (consentite); v dettaglio' % (gate['blocked'], gate['would_block']), 'dim')
        add('Gate != log vhost: no percentuale blocchi/visite.', 'dim')
    rows = rows[:max(0, height - 1)]
    return rows + [(safe(footer)[:width], 'section')]


def panel_rows(reader, site, status, width, help_visible=False, baseline=None,
               block_bytes=None, height=24, top_n=5, view='auto'):
    """One viewport, never a scrollable document. Hidden hosts go into OTHER."""
    width, height = max(1, width), max(0, height)
    if height == 0:
        return []
    if view == 'traffic' or (view == 'auto' and getattr(reader, 'traffic', None) and reader.traffic.sources):
        return traffic_panel_rows(reader, site, width, height, help_visible)
    s = reader.summary(site)
    c, u = s['counts'], s['unique']
    warnings = len(set(reader.warnings))
    problems = sum(v for k, v in reader.issues.items()
                   if k not in ('outside_range', 'rotation_compression_seen'))
    rows = []
    def add(text, style='normal'):
        text = safe(text)
        rows.append((text if len(text) <= width else text[:max(0, width - 1)] + '~', style))
    legend = 'q quit v traffico 1/2/3/4 periodo t cycle ? help r refresh'
    if height < 18 or width < 58:
        add('IMMUTION | ' + ('DEMO | ' if getattr(reader, 'demo', False) else '') + reader.window.name + (' | ' + site if site != 'all' else ''), 'title')
        add(savings_rows(c['blocked'], 0, baseline, block_bytes)[0], 'metric')
        add('B %s | M %s (allowed)' % (c['blocked'], c['would_block']), 'metric')
        if getattr(reader, 'traffic', None) and height >= 10:
            add(reader.traffic.card(site)[0], 'section')
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
        add('IMMUTION / READ ONLY | ' + ('DEMO | ' if getattr(reader, 'demo', False) else '') + reader.window.name, 'title')
        add('[%s, %s) Europe/Rome' % (reader.window.start.date(), reader.window.end.date()))
        add('As of %s | end exclusive' % reader.cutoff.astimezone(reader.window.start.tzinfo).isoformat(timespec='seconds'), 'dim')
        add('Scope: ' + site + ' [claimed Host; UNTRUSTED]')
        # Three ASCII rows only if both width and actual remaining height allow.
        traffic_rows = len(reader.traffic.card(site)) if getattr(reader, 'traffic', None) else 0
        big_width = width if height >= 20 + top_n + traffic_rows and not help_visible else 0
        for text in savings_rows(c['blocked'], big_width, baseline, block_bytes):
            add(text, 'metric')
        add('TOTAL BLOCKED %s | unique IPs %s' % (c['blocked'], u.get('blocked', 0)), 'metric')
        add('TOTAL MONITOR %s | unique IPs %s (allowed; not blocked)' % (c['would_block'], u.get('would_block', 0)), 'metric')
        if getattr(reader, 'traffic', None):
            for index, text in enumerate(reader.traffic.card(site)):
                add(text, 'section' if index == 0 else 'dim')
        if help_visible:
            add('HELP / READ ONLY', 'section')
            for text in ('1 today; 2 yesterday; 3 last7 incl today; 4 previous calendar week',
                         't cycles ranges; CLI --start DATE --end DATE for custom [start,end)',
                         'v: traffic view; n/p or Tab: Host; 0: all; r refresh; q quit',
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
