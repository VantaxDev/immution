# ASCII terminal dashboard — 2026-11-10

This is a terminal/curses restyling of the existing dashboard, not a web app.
No new dependency, collector/cache/heuristic or terminal palette change.
The default SSH foreground/background and monochrome fallback are inherited.

## Run the actual renderer without production inputs

```bash
python3 experimental/dashboard/live.py --demo --once
python3 experimental/dashboard/live.py --demo
python3 experimental/dashboard/live.py --demo --once --view gate
```

`--demo` uses fixed synthetic .invalid fixtures and the actual renderer. It
never probes services or reads live paths, refuses combinations with live
sources/exports/filters/byte assumptions, and labels output DATI SINTETICI.
It also falls back to text without a usable TTY. The existing standalone
`demo_traffic.py` remains available. This source change is not installed on
production; an existing four-module deployment does not include the demo module.

For live input, existing `--once` / `--export` retain the complete sanitized
report and now include category and block charts in addition to numeric detail.
Interactive controls are unchanged: v traffic/gate; n/p/Tab site; 0 all;
1/2/3/4 or t period; ? help; r refresh; q exit.

## Scale and attribution

- Each horizontal chart has one shared, linear integer scale. `#=N` specifies
  the number of groups or block events per full cell. `+` represents a positive
  remainder smaller than one full cell. `-` is unfilled space, not a measurement.
  Exact values are printed and aligned beside every bar; zero has no filled cell.
- N/D has no bar and is never synthesized as zero. Categories are observed
  browser-compatible / ambiguous / declared bot-tool / scanner / internal groups,
  not people or authenticated crawlers. No percentages are inferred.
- HTTP request totals remain separate from group scales. The recent-day table
  charts only browser-compatible groups on one common daily scale; the HTTP
  column is numeric only. Missing days remain N/D, not invented zero trends.
- The gate chart scales only B (blocked event records) by claimed Host, not
  verified vhost; M (allowed monitor events) is separate. Top-N plus Other retains
  all B/M counts, including hidden and monitor-only Hosts. Global unique-IP
  counts remain global, not sums of per-host counts.
- UNKNOWN/INCOMPLETE, issues, prefix-limit explanation, dates/site and controls
  stay visible on 80x24. Narrow layouts reduce detail and keep category bars at
  40x14; tiny terminals prioritize totals/coverage/quit. Width may shorten labels
  with `~`; full details remain in --once. Site/date/time never prove continuity.

## Actual --demo --once output (not hand-authored)

```
IMMUTION / TRAFFICO | DEMO / DATI SINTETICI | last7
[2026-11-04, 2026-11-11) Europe/Rome
Snapshot 2026-11-10T13:00:00+01:00
Sito: tutti i log mappati
VISITE / STIMA BROWSER 42 osservate
Non persone; non umani verificati. UA falsificabili.
Richieste HTTP 140 | gruppi != richieste
Ultimo record 10/11 12:00 +0100 (59m fa)
Record non recente (>15m); non prova salute o continuita.
Copertura UNKNOWN | problemi 0
GRUPPI OSSERVATI | #=2 | +=meno di # | -=vuoto | N/D=no dati
Browser      42 |#####################-------|
Ambigue      14 |#######---------------------|
Bot/tool UA  14 |#######---------------------|
Scanner      14 |#######---------------------|
Interne      14 |#######---------------------|
GIORNO       BROWSER  AMBIGUI BOT/UA    HTTP | #=1 browser
2026-11-08       7        2      2      22 | #######
2026-11-09       8        2      2      24 | ########
2026-11-10       9        2      2      26 | #########
Ultimi 3/7 giorni selezionati; intero periodo: --once
Gate claimed Host: B 4 | M 4 (consentite); v dettaglio
Gate != log vhost: no percentuale blocchi/visite.
q quit v blocchi n/p sito 0 tutti 1/2/3/4 periodo ? aiuto r refresh
```

## Verification

Three new acceptance regressions fail on the previous presentation/CLI and
pass after implementation. Additional characterization distinguishes unavailable
sources from observed zero on narrow charts. Four chart-specific tests cover
shared scales, tiny nonzero/zero/N/D/large values, ASCII bounds, demo CLI,
unchanged aggregates and zero collection reads during rendering.

Final local code: 95 dashboard tests PASS (including actual PTY demo navigation,
help/refresh, resizing 80x24 -> 40x14 -> 24x8 -> 80x24, exit and termios restoration),
58 core tests and release checks PASS, DOM harness PASS, diff-check PASS.
Palette/theme inheritance remains covered by existing tests. The PTY matcher
accepts a changed site prefix because curses may reuse its unchanged suffix;
full site navigation is independently asserted on renderer frames.
Hosted tests/ubuntu-integration must be green on the final published SHA;
see the PR checks. No real-data/SSH/deployment acceptance is claimed here.
