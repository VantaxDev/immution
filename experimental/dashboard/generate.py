#!/usr/bin/env python3
"""Local synthetic dashboard. Python 3.9+ standard library only."""
import html
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ROME = ZoneInfo("Europe/Rome")
REASONS = {"probe": "File sensibili", "burst": "Raffica di richieste", "scanner": "Scanner noto", "404": "Sequenza 404", "other": "Altro"}


def instant(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def aggregate(data):
    if data.get("classification") != "SYNTHETIC":
        raise ValueError("Only explicitly SYNTHETIC fixtures are supported")
    start, end, generated = (instant(data[k]) for k in ("start", "end", "generated_at"))
    if not start < end <= generated or end - start > timedelta(days=2):
        raise ValueError("Invalid time window (maximum 48 hours)")
    mapping = data["sources"]  # Trusted configured source ID, NEVER request Host.
    sites = dict(data["sites"])
    if "all" in sites or "unknown" in sites or any(v not in sites for v in mapping.values()):
        raise ValueError("Invalid site mapping")
    sites["unknown"] = "Sorgente non mappata"
    buckets = []
    t = start
    while t < end:
        buckets.append(t)
        t += timedelta(hours=1)
    groups = {key: [] for key in ["all"] + list(sites)}
    ignored = Counter()
    for event in data["events"]:
        if event.get("test", False):
            ignored["tests"] += 1
            continue
        if event["action"] not in ("blocked", "would_block"):
            ignored["actions"] += 1
            continue
        at = instant(event["at"])
        if not start <= at < end:
            ignored["outside"] += 1
            continue
        client = event["client"]
        if not isinstance(client, str) or not client.startswith("synthetic-client-"):
            raise ValueError("Only synthetic client tokens accepted")
        clean = {"at": at, "action": event["action"], "client": client,
                 "reason": event.get("reason") if event.get("reason") in REASONS else "other"}
        site = mapping.get(event.get("source"), "unknown")
        groups["all"].append(clean)
        groups[site].append(clean)
    views = {}
    for key, events in groups.items():
        modes = {}
        for mode in ("blocked", "would_block"):
            selected = [e for e in events if e["action"] == mode]
            counts = Counter(int((e["at"] - start).total_seconds() // 3600) for e in selected)
            reasons = Counter(e["reason"] for e in selected)
            modes[mode] = {"count": len(selected), "unique": len({e["client"] for e in selected}),
                           "timeline": [counts[i] for i in range(len(buckets))],
                           "reasons": [{"label": label, "count": reasons[r]} for r, label in REASONS.items()]}
        last = max((e["at"] for e in events), default=None)
        modes["last"] = last.astimezone(ROME).isoformat() if last else None
        modes["age_seconds"] = int((generated - last).total_seconds()) if last else None
        views[key] = modes
    health = data["health"]
    if any(type(health[k]) is not int or health[k] < 0 for k in ("followers", "expected")):
        raise ValueError("Invalid synthetic health")
    return {"sites": [{"id": k, "label": v} for k, v in sites.items()], "views": views,
            "labels": [t.astimezone(ROME).strftime("%H:%M %z") for t in buckets],
            "start": start.astimezone(ROME).isoformat(), "end": end.astimezone(ROME).isoformat(),
            "generated": generated.astimezone(ROME).isoformat(), "ignored": dict(ignored),
            "health": {k: health[k] for k in ("followers", "expected")}}


def render(data):
    model = aggregate(data)
    # Escape script-ending tags, HTML metacharacters and JS line separators.
    payload = json.dumps(model, ensure_ascii=True).replace("<", chr(92) + "u003c").replace(">", chr(92) + "u003e").replace("&", chr(92) + "u0026")
    template = (ROOT / "template.html").read_text(encoding="utf-8")
    return template.replace("@@DATA@@", payload).replace("@@GENERATED@@", html.escape(model["generated"]))


def main():
    # No CLI output paths, no paths derived from input; refuse a symlink target.
    target = ROOT / "dashboard.html"
    if target.is_symlink():
        raise ValueError("Refusing symlink output")
    result = render(json.loads((ROOT / "fixture.json").read_text(encoding="utf-8")))
    target.write_text(result, encoding="utf-8")
    print("Generated", target)


if __name__ == "__main__":
    main()
