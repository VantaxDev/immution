#!/usr/bin/env python3
"""Explicit DEMO of the real traffic renderer; no production inputs or health probes.

Run interactively, --once for text, or --preview NEW_DIRECTORY for static HTML.
The HTML is only a picture of terminal rows, not a second dashboard or live UI.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import html
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

from live import HEADER, Reader, screen_main
from presentation import dump_text, panel_rows

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
UA = 'Mozilla/5.0 (DEMO) Chrome/130.0'


def access_row(at, ip, site, path='/', ua=UA, ref='-'):
    months = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
    stamp = '%02d/%s/%04d:%s +0000' % (at.day, months[at.month-1], at.year, at.strftime('%H:%M:%S'))
    return '%s - - [%s] "GET %s HTTP/1.1" 200 100 "%s" "%s"\n' % (ip, stamp, path, ref, ua)


class DemoReader(Reader):
    demo = True

    def refresh(self, now=None):
        super().refresh(NOW)


def make_reader(root):
    """Only reserved .invalid labels and documentation addresses, private temp logs."""
    sources = []
    events = root / 'events.csv'
    with events.open('w', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(HEADER)
        for i in range(8):
            writer.writerow([(NOW-timedelta(hours=i+1)).isoformat(), 'blocked' if i % 2 else 'would_block',
                             '192.0.2.200', 'rivista.invalid', '/demo', 50, 1, 0, 1, 'DEMO', 'probe'])
    for index, site in enumerate(('rivista.invalid', 'bottega.invalid')):
        path = root / ('demo-%s.log' % index)
        lines = []
        for days_ago in range(7):
            at = NOW-timedelta(days=days_ago, hours=1)
            for client in range((7-days_ago) if index == 0 else 2):
                ip = '192.0.2.%s' % (1+client+index*32)
                lines += [access_row(at, ip, site), access_row(at+timedelta(seconds=30), ip, site, '/about', ref='https://'+site+'/')]
            lines += [access_row(at, '198.51.100.1', site),
                      access_row(at, '198.51.100.2', site, ua='DemoBot/1'),
                      access_row(at, '198.51.100.3', site, path='/.env'),
                      access_row(at, '127.0.0.1', site)]
        path.write_text(''.join(lines))
        sources.append((site, path))
    sources.append(('archivio.invalid', root / 'empty.log'))
    (root / 'empty.log').write_text('')
    reader = DemoReader([events], timeframe='last7', access_logs=sources)
    reader.refresh()
    return reader


def preview(reader, destination):
    # Refuse reuse/symlinks; never publish or serve the temporary raw fixture logs.
    destination.mkdir(mode=0o700)
    frames = (('desktop', 79, 24, 'all'), ('stretto', 39, 14, 'rivista.invalid'),
              ('sito', 79, 24, 'rivista.invalid'), ('vuoto', 79, 24, 'archivio.invalid'))
    for name, width, height, site in frames:
        rows = panel_rows(reader, site, 'DEMO', width, height=height)
        text = '\n'.join(line for line, _ in rows)
        (destination / (name+'.txt')).write_text(text+'\n')
        content = ''.join('<span class="%s">%s</span>\n' % (style, html.escape(line)) for line, style in rows)
        document = '''<!doctype html><html lang="it"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>IMMUTION DEMO / terminale</title><style>
*{box-sizing:border-box}body{margin:0;padding:24px;background:#10151d;color:#cbd5df;font:15px/1.5 monospace}
h1{font-size:18px;color:#a6d9bd}p{max-width:76ch;color:#aab7c5}pre{margin-top:24px;overflow-x:auto;padding:20px;border:1px solid #354a48;border-radius:8px;line-height:1.45;font-size:16px}
.title,.metric{font-weight:bold;color:#e2efd9}.section{font-weight:bold;text-decoration:underline;color:#aacdb9}.dim{color:#a9b4c3}
@media(max-width:600px){body{padding:12px}pre{font-size:12px;padding:8px}h1{font-size:16px}}
</style><h1>DEMO / renderer terminale reale %s x %s</h1>
<p>Dati sintetici fissi del 10 novembre 2026, non produzione. Anteprima statica: colori illustrativi; nessuna UI web live. Le righe sono quelle di panel_rows.</p><pre>%s</pre></html>''' % (width+1, height, content)
        (destination / (name+'.html')).write_text(document)
    (destination / 'report.txt').write_text(dump_text(reader, status='DEMO - no service probes'))
    for path in destination.iterdir():
        path.chmod(0o600)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--preview', type=Path, metavar='NEW_DIRECTORY')
    parser.add_argument('--view', choices=('auto', 'traffic', 'gate'), default='traffic')
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix='immution-DEMO-') as directory:
        reader = make_reader(Path(directory))
        try:
            if args.preview:
                preview(reader, args.preview)
                print('DEMO preview:', args.preview.resolve() / 'desktop.html')
            elif args.once or not sys.stdin.isatty() or not sys.stdout.isatty() or os.environ.get('TERM') in (None, '', 'dumb'):
                print('\n'.join(text for text, _ in panel_rows(reader, 'all', 'DEMO', 79, height=24, view=args.view)))
            else:
                import curses
                # No production files, systemctl, network or recurring process.
                curses.wrapper(screen_main, curses, reader, SimpleNamespace(
                    site='all', view=args.view, interval=5, top=5, baseline_bytes=None, block_bytes=None))
        finally:
            reader.close()


if __name__ == '__main__':
    main()
