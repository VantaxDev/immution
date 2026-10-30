#!/usr/bin/env python3
"""Read-only synthetic terminal demo; Python standard library only."""
import argparse
import json
import os
import sys
import textwrap

from generate import ROOT, aggregate

HELP = [
    "AIUTO - sola lettura; nessun ban o comando di servizio",
    "Tab / destra / n: sito successivo; sinistra / p: precedente",
    "0: tutti i siti; su/giu oppure k/j: scorri; Home: inizio",
    "r: rileggi fixture locale (non live); ?: aiuto; q: esci",
    "Monitor = would_block: richieste NON bloccate.",
    "IP unici = token sintetici distinti per modalita; non sommarli.",
    "Salute globale simulata; eta eventi riferita allo snapshot.",
    "Nessun evento non significa guasto. Nessun accesso alla rete.",
]
FOOTER = "q esci | ? aiuto | Tab/n/p sito | 0 tutti | j/k scorri | r rileggi"


def safe(value):
    # ASCII also guarantees one terminal cell per character; strip control codes.
    return ''.join(c if 32 <= ord(c) < 127 else '?' for c in str(value))


def load_model():
    return aggregate(json.loads((ROOT / "fixture.json").read_text(encoding="utf-8")))


def site_list(model):
    return [{"id": "all", "label": "Tutti i siti"}] + model["sites"]


def lines(model, site="all", width=80, help_visible=False):
    sites = site_list(model)
    label = next(s["label"] for s in sites if s["id"] == site)
    view = model["views"][site]
    b, m = view["blocked"], view["would_block"]
    health = model["health"]
    rows = ["IMMUTION | DEMO SYNTHETIC | NON LIVE | sola lettura",
            f"Snapshot: {model['generated']}",
            f"Finestra: {model['start']} -> {model['end']} (fine esclusa)",
            f"Sito: {label} [{site}]",
            f"BLOCCATE {b['count']} | IP unici {b['unique']}",
            f"MONITOR  {m['count']} | IP unici {m['unique']} (would_block)",
            "IP = identita sintetiche; distinti separati, non sommabili.",
            f"Salute GLOBALE simulata: follower {health['followers']}/{health['expected']}",
            f"Ultimo evento: {view['last'] or 'nessuno'} | eta snapshot: {view['age_seconds'] if view['age_seconds'] is not None else '-'} s"]
    if help_visible:
        rows.extend([""] + HELP)
    rows += ["", "TIMELINE Europe/Rome | B=bloccate M=monitor (scala comune)"]
    peak = max(b["timeline"] + m["timeline"] + [1])
    bar_width = min(18, max(0, (width - 30) // 2))
    for hour, bc, mc in zip(model["labels"], b["timeline"], m["timeline"]):
        bars = ""
        if bar_width:
            bars = f" | {'#' * round(bc / peak * bar_width):<{bar_width}} {'+' * round(mc / peak * bar_width)}"
        rows.append(f"{hour} B {bc:4} M {mc:4}{bars}")
    rows += ["", "MOTIVI                       B      M"]
    for br, mr in zip(b["reasons"], m["reasons"]):
        rows.append(f"{br['label']:<26} {br['count']:6} {mr['count']:6}")
    rows += ["", "SITI (Tab/n/p per filtrare)   B      M"]
    for s in sites:
        v = model["views"][s["id"]]
        rows.append(f"{'>' if s['id'] == site else ' '} {safe(s['label'])[:24]:24} {v['blocked']['count']:6} {v['would_block']['count']:6}")
    if not b["count"] and not m["count"]:
        rows.append("Nessun evento nella finestra; non indica un guasto.")
    rows.append("Esclusi: " + ", ".join(f"{k}={v}" for k, v in sorted(model["ignored"].items())))
    # Wrap instead of silently losing metrics on narrow terminals.
    return [part for row in rows for part in (textwrap.wrap(safe(row), max(1, width), replace_whitespace=False) or [""])]


def run_screen(screen, curses, model, site):
    screen.keypad(True)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    offset, help_visible, status = 0, False, ""
    while True:
        height, width = screen.getmaxyx()
        content = lines(model, site, max(1, width - 1), help_visible)
        body_height = max(1, height - 2)
        offset = min(offset, max(0, len(content) - body_height))
        screen.erase()
        visible = content[offset:offset + body_height]
        if height >= 3:
            visible += [status or f"DEMO NON LIVE | righe {offset + 1}-{min(offset + body_height, len(content))}/{len(content)}", FOOTER]
        for y, row in enumerate(visible[:height]):
            try:
                screen.addnstr(y, 0, row, max(0, width - 1))
            except curses.error:
                pass  # Resize or bottom-right cell; redraw on next input.
        screen.refresh()
        key = screen.getch()
        ids = [s["id"] for s in site_list(model)]
        if key in (ord('q'), ord('Q')):
            return
        if key in (9, curses.KEY_RIGHT, ord('n'), curses.KEY_LEFT, ord('p')):
            delta = -1 if key in (curses.KEY_LEFT, ord('p')) else 1
            site, offset = ids[(ids.index(site) + delta) % len(ids)], 0
        elif key == ord('0'):
            site, offset = "all", 0
        elif key in (curses.KEY_DOWN, ord('j')):
            offset += 1
        elif key in (curses.KEY_UP, ord('k')):
            offset = max(0, offset - 1)
        elif key == curses.KEY_HOME:
            offset = 0
        elif key == ord('?'):
            help_visible, offset = not help_visible, 0
        elif key == ord('r'):
            try:
                model = load_model()
                if site not in model["views"]:
                    site = "all"
                status = "Fixture riletta; snapshot sintetico, NON LIVE."
            except (OSError, ValueError, KeyError, TypeError) as exc:
                status = "Lettura fallita; dati precedenti: " + safe(exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Immution da shell: prototipo SYNTHETIC offline, sola lettura.")
    parser.add_argument("--demo", action="store_true", required=True, help="usa solo fixture sintetica locale")
    parser.add_argument("--once", action="store_true", help="stampa snapshot e termina, senza curses")
    parser.add_argument("--site", default="all", help="ID sito, es. journal, shop, docs, default, quiet, unknown")
    parser.add_argument("--width", type=int, default=80, help="larghezza testo --once (20..240)")
    args = parser.parse_args(argv)
    if not 20 <= args.width <= 240:
        parser.error("--width deve essere fra 20 e 240")
    try:
        model = load_model()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Fixture non disponibile/valida: " + safe(exc) + "\n")
    if args.site not in model["views"]:
        parser.error("--site sconosciuto; usare " + ", ".join(model["views"]))
    if not args.once and sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") not in (None, "", "dumb"):
        try:
            import curses
        except ImportError:
            print("Curses assente: snapshot testuale.", file=sys.stderr)
        else:
            try:
                curses.wrapper(run_screen, curses, model, args.site)
                return 0
            except curses.error:
                print("Terminale non compatibile: snapshot testuale.", file=sys.stderr)
            except KeyboardInterrupt:
                return 0
    print("\n".join(lines(model, args.site, args.width)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
