"""Theme-neutral, bounded ASCII cockpit over existing read-only summaries."""

def render(reader, site, status, width, height, help_visible, baseline,
           block_bytes, top_n, view):
    from presentation import safe, bar_chart, traffic_categories, top_hosts, savings_rows
    width, height = max(1, width), max(0, height)
    if not height:
        return []
    summary = reader.summary(site)
    gate = summary['counts']
    overview = reader.traffic.overview(site)
    counts, requests = overview['counts'], overview['requests']
    browser = counts['browser_like'] if requests else 'N/D'
    demo = getattr(reader, 'demo', False)
    marker = 'DEMO / DATI SINTETICI' if demo else 'READ ONLY'
    incomplete = bool(overview['issues'] or reader.warnings or any(
        value for key, value in reader.issues.items()
        if key not in ('outside_range', 'rotation_compression_seen')))
    coverage = 'UNKNOWN' + (' / INCOMPLETE' if incomplete else '')
    period = '%s..%s) Roma' % (reader.window.start.date(), reader.window.end.date())
    rows = []
    def fit(text, size):
        text = safe(text)
        return text[:size] if size < 2 else (text if len(text) <= size else text[:size-1] + '~')
    def add(text, style='normal'):
        rows.append((fit(text, width), style))
    def edge(title=''):
        if width < 4:
            add('-' * width)
        else:
            label = fit(' ' + title + ' ', width-4) if title else ''
            add('+-' + label + '-' * (width-3-len(label)) + '+', 'section')
    def line(text='', style='normal'):
        if width < 4:
            add(text, style)
        else:
            add('| ' + fit(text, width-4).ljust(width-4) + ' |', style)
    # Always reserve the last row for quit. Tiny terminals cannot show details.
    if height < 10 or width < 32:
        for text in (('DATI SINTETICI' if demo else marker), 'IMMUTION COCKPIT', coverage, 'Browser %s STIMA' % browser,
                     'Non persone; HTTP %s' % (requests or 'N/D')):
            add(text)
        return rows[:height-1] + [(fit('q quit ? help', width), 'section')]
    edge((marker + ' / COCKPIT') if width < 70 else ('IMMUTION COCKPIT / ' + marker))
    if width < 70 or height < 24:
        line('BROWSER %s | HTTP %s' % (browser, requests or 'N/D'), 'metric')
        line('STIMA sessioni, NON persone')
        line('B %s | M %s consentite' % (gate['blocked'], gate['would_block']))
        edge('COPERTURA')
        line(coverage, 'section')
        line(period)
        line('N/D = non osservato | ' + site)
        if help_visible:
            body = ['HELP / READ ONLY; n/p sito', '1/2/3/4 o t periodo', '? aiuto; r refresh; q quit']
        else:
            body = ['Amb %s | Bot UA %s' % (counts['ambiguous'] if requests else 'N/D', counts['declared_bot'] if requests else 'N/D'),
                    'Selftest esclusi B=%s M=%s' % (summary['tests']['blocked'], summary['tests']['would_block']),
                    'MB N/D senza baseline; Prioris escluso']
        for text in body[:max(0, height-10)]:
            line(text)
        while len(rows) < height-2:
            line()
        edge()
        add('q quit ? help v vista t periodo r refresh', 'section')
        return rows[:height]
    # 24-row baseline: full-width KPI deck and independent, scaled instruments.
    line('BROWSER %s STIMA | HTTP %s | BLOCK %s | MONITOR %s' %
         (browser, requests or 'N/D', gate['blocked'], gate['would_block']), 'metric')
    line('Sessioni-browser != persone | monitor consentite | IP != bot', 'dim')
    edge('TRAFFICO / GRUPPI OSSERVATI' if view != 'gate' else 'BLOCCHI / CLAIMED HOST')
    inner = width-4
    left_width = (inner-3)//2
    right_width = inner-3-left_width
    if help_visible:
        left = ['HELP / READ ONLY', 'n/p o Tab: sito; 0: tutti', 'v: traffico / blocchi', '1 oggi; 2 ieri; 3 ultimi7', '4 settimana precedente; t ciclo', 'r refresh; ? chiudi; q quit', '--once / --export: dettagli']
        right = ['LIMITI / READ ONLY', 'STIMA browser, non persone', 'UA falsificabili; NAT unisce', 'N/D: nessun record utilizzabile', 'Gate != access log vhost', 'Prioris escluso dal traffico', 'Selftest esclusi dal gate']
    else:
        left = bar_chart(traffic_categories(overview), left_width, 'gruppi')
        ranked, other, _ = top_hosts(summary, min(top_n, 3), site)
        right = bar_chart([(host, values['blocked']) for host, values in ranked] + [('Other', other['blocked'])], right_width, 'B records')
        right += ['M %s consentite, scala separata' % gate['would_block']]
        right += [savings_rows(gate['blocked'], 0, baseline, block_bytes)[0]]
    if view == 'gate' and not help_visible:
        left, right = right, left
    # Compact scale headers leave the full symbol legend on its own row.
    if not help_visible:
        left[0] = left[0].split(' | +=')[0]
        right[0] = right[0].split(' | +=')[0]
    for i in range(7):
        line(fit(left[i] if i < len(left) else '', left_width).ljust(left_width) + ' | ' + fit(right[i] if i < len(right) else '', right_width))
    line('# = scala indicata; + = frazione; - = vuoto; N/D = non osservato', 'dim')
    detail = ','.join(sorted(overview['issue_counts']))
    if overview['issue_counts'].get('read_budget'):
        detail = '8 MiB prefisso; record recenti possibilmente esclusi'
    line(('Problemi: ' + detail) if detail else 'Gate != log vhost | claimed Host non verificato', 'dim')
    edge('SITI MAPPATI / ' + fit(site, width-25))
    if site != 'all':
        rows[-1] = (rows[-1][0], 'selected')
    line('%-28s %9s %8s %8s %8s' % ('SITO', 'BROWSER', 'BOT/UA', 'AMBIGUI', 'HTTP'), 'section')
    sites = sorted(overview['sites'].items())
    slots = 3 + max(0, height-24)
    visible = slots if len(sites) <= slots else slots-1
    for name, entry in sites[:visible]:
        c = entry['counts']
        values = (c['browser_like'], c['declared_bot'], c['ambiguous'], entry['requests']) if entry['requests'] else ('N/D',)*4
        line('%-28s %9s %8s %8s %8s' % (fit(name, 28), *values))
    used = min(len(sites), visible)
    if len(sites) > visible:
        line('+ %s siti nascosti: n/p seleziona; --once tutti' % (len(sites)-visible)); used += 1
    for _ in range(slots-used):
        line()
    edge('COPERTURA ' + coverage)
    line('Selftest esclusi B=%s M=%s | Prioris escluso traffico | N/D != zero' %
         (summary['tests']['blocked'], summary['tests']['would_block']))
    line('Range [' + period + ' | ' + reader.window.name)
    line('Stato: ' + status + ' | continuita UNKNOWN', 'dim')
    edge()
    add('q quit  n/p sito  0 tutti  v vista  1/2/3/4 periodo  ? help  r refresh', 'section')
    return rows[:height]
