#!/usr/bin/env python3
"""Estimate bandwidth avoided by Immution block responses.

This is an estimate, not a measured counter. By default only rows whose action
is ``blocked`` are counted; monitor-mode ``would_block`` rows are excluded.
"""

import argparse
import csv
import glob
import os
import statistics
from collections import defaultdict


def parse_args():
    parser = argparse.ArgumentParser(description="Estimate bandwidth avoided by Immution")
    parser.add_argument("--events", required=True, help="Immution events.csv")
    parser.add_argument("--access", nargs="+", required=True, help="Apache logs or glob patterns")
    parser.add_argument("--action", choices=["blocked", "would_block", "all"], default="blocked")
    parser.add_argument("--block-bytes", type=int, default=2500, help="measured block page size")
    parser.add_argument("--fallback-bytes", type=int, default=50000, help="assumed response size")
    return parser.parse_args()


def parse_access_line(line):
    try:
        parts = line.split('"')
        request = parts[1].split()
        response = parts[2].strip().split()
        if len(request) < 2 or len(response) < 2:
            return None
        return request[1], int(response[0]), int(response[1]) if response[1].isdigit() else None
    except (IndexError, ValueError):
        return None


def expand_paths(patterns):
    result = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        result.extend(matches if matches else [pattern])
    return sorted(set(result))


def main():
    args = parse_args()
    sizes = defaultdict(list)

    for path in expand_paths(args.access):
        if not os.path.isfile(path):
            print(f"[!] access log not found: {path}")
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parsed = parse_access_line(line)
                if parsed is None:
                    continue
                request_path, status, size = parsed
                if status == 200 and size is not None:
                    sizes[request_path].append(size)

    medians = {path: int(statistics.median(values)) for path, values in sizes.items() if values}
    if not os.path.isfile(args.events):
        raise SystemExit(f"events file not found: {args.events}")

    count = 0
    estimated_allowed = 0
    with open(args.events, "r", encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            action = row.get("action", "blocked")
            if args.action != "all" and action != args.action:
                continue
            path = row.get("request_uri", "/")
            estimated_allowed += medians.get(path, args.fallback_bytes)
            count += 1

    served = count * args.block_bytes
    difference = estimated_allowed - served
    label = "potentially avoided" if args.action == "would_block" else "estimated avoided"

    print("Immution bandwidth estimate")
    print(f"events ({args.action}): {count:,}")
    print(f"estimated original responses: {estimated_allowed / 1024 / 1024:,.2f} MiB")
    print(f"block responses: {served / 1024 / 1024:,.2f} MiB")
    print(f"{label}: {difference / 1024 / 1024:,.2f} MiB")
    print()
    print("Assumptions: historical median size for matching 200 responses; otherwise")
    print(f"{args.fallback_bytes:,} bytes per request. This is not a measured traffic counter.")


if __name__ == "__main__":
    main()
