#!/usr/bin/env python3
"""Small local inspection tool for Immution state."""

import argparse
import csv
import fcntl
import ipaddress
import json
import os
import sys
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlsplit


DEFAULT_RUNTIME_DIR = "/run/immution"
DEFAULT_EVENTS_FILE = "/var/log/immution/events.csv"


def canonical_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def state_path(runtime_dir: str, ip: str) -> str:
    return os.path.join(runtime_dir, ip.replace(":", "_") + ".json")


def load_state(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def command_status(runtime_dir: str) -> int:
    tracked = 0
    banned = 0
    try:
        names = os.listdir(runtime_dir)
    except OSError as exc:
        print(f"cannot read {runtime_dir}: {exc}", file=sys.stderr)
        return 1

    for name in names:
        if not name.endswith(".json"):
            continue
        state = load_state(os.path.join(runtime_dir, name))
        if state is None:
            continue
        tracked += 1
        banned += int(bool(state.get("banned")))

    print(f"runtime_dir: {runtime_dir}")
    print(f"tracked: {tracked}")
    print(f"banned: {banned}")
    return 0


def command_explain(runtime_dir: str, ip: str) -> int:
    path = state_path(runtime_dir, ip)
    state = load_state(path)
    if state is None:
        print(f"No active state for {ip}")
        return 1

    print(f"IP: {ip}")
    print(f"Score: {float(state.get('score', 0)):.1f}")
    print(f"Banned: {'yes' if state.get('banned') else 'no'}")
    print(f"Requests while tracked: {int(state.get('requests', 0))}")
    print(f"404 responses: {int(state.get('errors_404', 0))}")
    print(f"Probe paths: {int(state.get('probes', 0))}")
    print("Reasons:")
    reasons = state.get("reasons", [])
    if not isinstance(reasons, list) or not reasons:
        print("  (none)")
    else:
        for reason in reasons[:10]:
            print(f"  - {reason}")
    return 0


def command_unblock(runtime_dir: str, ip: str) -> int:
    path = state_path(runtime_dir, ip)
    try:
        # Same persistent lock as the daemon: wait for an in-flight write,
        # then remove its result. Do not unlink .state.lock after releasing it.
        with open(os.path.join(runtime_dir, ".state.lock"), "r") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            os.unlink(path)
    except FileNotFoundError:
        print(f"No active state for {ip}")
        return 1
    except OSError as exc:
        print(f"cannot remove {path}: {exc}", file=sys.stderr)
        return 1
    print(f"Removed active state for {ip}")
    return 0


def _display_path(value: str) -> str:
    """Return a bounded path without a potentially sensitive query string."""
    try:
        parsed = urlsplit(value)
        path = parsed.path or "/"
    except ValueError:
        path = value.split("?", 1)[0] or "/"
    return path[:160]


def _parse_iso_timestamp(value: str) -> datetime:
    """Parse the ISO-8601 timestamps emitted by the PHP gate on Python 3.6+."""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+0000"
    elif (
        len(normalized) >= 6
        and normalized[-6] in "+-"
        and normalized[-3] == ":"
    ):
        normalized = normalized[:-3] + normalized[-2:]

    formats = (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    )
    for date_format in formats:
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            pass
    raise ValueError("invalid ISO-8601 timestamp")


def command_report(events_file: str, top: int) -> int:
    """Summarize monitor events without printing addresses or query strings."""
    actions = Counter()
    paths = Counter()
    addresses = set()
    timestamps = []
    invalid_rows = 0

    try:
        with open(events_file, "r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                action = str(row.get("action", "") or "unknown")
                ip = str(row.get("ip", "") or "")
                uri = str(row.get("request_uri", "") or "/")
                timestamp = str(row.get("timestamp", "") or "")
                actions[action] += 1
                paths[_display_path(uri)] += 1
                if ip:
                    addresses.add(ip)
                try:
                    timestamps.append(_parse_iso_timestamp(timestamp))
                except ValueError:
                    invalid_rows += 1
    except OSError as exc:
        print(f"cannot read {events_file}: {exc}", file=sys.stderr)
        return 1

    total = sum(actions.values())
    print("Immution monitor report")
    print(f"events_file: {events_file}")
    print(f"events: {total}")
    print(f"unique_addresses: {len(addresses)}")
    if timestamps:
        print(f"first_event: {min(timestamps).isoformat()}")
        print(f"last_event: {max(timestamps).isoformat()}")
    print("actions:")
    if actions:
        for action, count in actions.most_common():
            print(f"  {action}: {count}")
    else:
        print("  (none)")
    print("top_paths (query strings omitted):")
    if paths:
        for path, count in paths.most_common(max(1, top)):
            print(f"  {count:>6}  {path}")
    else:
        print("  (none)")
    if invalid_rows:
        print(f"warning: {invalid_rows} row(s) had an invalid timestamp")
    if actions.get("blocked", 0):
        print("warning: blocked events are present; this was not a monitor-only period")
    print("review_required: classify the listed paths as hostile or legitimate before block mode")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Immution runtime state")
    parser.add_argument("--runtime-dir", default=DEFAULT_RUNTIME_DIR)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="show tracked and banned counts")
    explain = subparsers.add_parser("explain", help="explain the state for one IP")
    explain.add_argument("ip", type=canonical_ip)
    unblock = subparsers.add_parser("unblock", help="remove state for one IP")
    unblock.add_argument("ip", type=canonical_ip)
    report = subparsers.add_parser("report", help="summarize monitor/block events")
    report.add_argument("--events", default=DEFAULT_EVENTS_FILE)
    report.add_argument("--top", type=int, default=15)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    if args.command == "status":
        return command_status(args.runtime_dir)
    if args.command == "explain":
        return command_explain(args.runtime_dir, args.ip)
    if args.command == "unblock":
        return command_unblock(args.runtime_dir, args.ip)
    if args.command == "report":
        return command_report(args.events, args.top)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
