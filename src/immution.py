#!/usr/bin/env python3
"""Immution: explainable abuse detection from Apache access logs.

The daemon observes Apache Combined Log Format lines, keeps short-lived state in
``/run/immution`` and marks an address as banned when its documented score
reaches the configured threshold. Enforcement is performed separately by the
PHP gate, which ships in monitor-only mode by default.

Python package dependencies: none.
"""

import argparse
import copy
import glob
import ipaddress
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple


VERSION = "0.1.0-rc4"

DEFAULT_RUNTIME_DIR = "/run/immution"
DEFAULT_THRESHOLD = 50.0
SCORE_HALFLIFE = 20 * 60.0
SCORE_TTL = 60 * 60.0
CLEANUP_INTERVAL = 60.0
BONUS_COOLDOWN = 30.0

SCORE_404_BASE = 2.0
SCORE_PROBE_BASE = 10.0
SCORE_NO_UA = 3.0
SCORE_SCANNER_UA = 4.0
BONUS_404_BURST = 20.0
BONUS_PROBE_BURST = 30.0
BONUS_SCAN = 30.0

# These are deliberately high-confidence paths. Legitimate routes such as
# /wp-login.php, /wp-admin, /admin and /graphql are not probes by themselves.
PROBE_PATHS = [
    r"/(?:\.env)(?:[./?]|$)",
    r"/(?:\.git)(?:[/?]|$)",
    r"/(?:\.htpasswd)(?:$|[./?])",
    r"/wp-config\.php(?:$|[./?])",
    r"/(?:phpmyadmin|pma)(?:[/?]|$)",
    r"/adminer(?:\.php)?(?:[/?]|$)",
    r"/(?:id_rsa|\.ssh|\.aws)(?:[/?]|$)",
    r"/(?:etc/passwd|proc/self)(?:[/?]|$)",
    r"(?:\.sql|\.bak|\.old|\.tar|\.tgz|\.zip)(?:$|\?)",
    r"(?:\.\./|%2e%2e|%252e%252e)",
    r"/(?:shell|cmd|eval|exec)(?:\.php)?(?:/|$)",
]

SCANNER_USER_AGENTS = [
    r"nikto",
    r"sqlmap",
    r"masscan",
    r"zgrab",
    r"nmap scripting engine",
    r"nuclei",
    r"acunetix",
    r"nessus",
]

PROBE_REGEX = re.compile("|".join(PROBE_PATHS), re.IGNORECASE)
SCANNER_UA_REGEX = re.compile("|".join(SCANNER_USER_AGENTS), re.IGNORECASE)

# Apache Combined Log Format. The first field must be the effective client IP.
LOG_REGEX = re.compile(
    r"^(\S+)\s+"
    r"\S+\s+"
    r"\S+\s+"
    r"\[([^\]]+)\]\s+"
    r'"(\S+)\s+(\S+)[^"]*"\s+'
    r"(\d+)\s+"
    r"(\d+|-)\s*"
    r'"([^"]*)"\s*'
    r'"([^"]*)"'
)


def decay(value: float, elapsed: float, half_life: float = SCORE_HALFLIFE) -> float:
    """Apply exponential half-life decay."""
    if value <= 0:
        return 0.0
    if elapsed <= 0:
        return value
    return value * math.exp(-(math.log(2.0) / half_life) * elapsed)


def canonical_ip(value: str) -> Optional[str]:
    """Return a canonical IPv4/IPv6 string, or ``None`` for invalid input."""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def parse_log_line(line: str) -> Optional[Tuple[str, str, str, int, str]]:
    """Parse the fields needed by the scoring engine."""
    match = LOG_REGEX.match(line)
    if not match:
        return None
    raw_ip, _timestamp, method, path, status, _size, _referrer, user_agent = match.groups()
    ip = canonical_ip(raw_ip)
    if ip is None:
        return None
    return ip, method, path, int(status), user_agent


def load_json_config(path: str) -> Dict[str, Any]:
    """Load and minimally validate a daemon JSON configuration file."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("configuration root must be a JSON object")
    if "logs" in data and not isinstance(data["logs"], list):
        raise ValueError("'logs' must be a JSON array")
    if "threshold" in data and float(data["threshold"]) <= 0:
        raise ValueError("'threshold' must be greater than zero")
    return data


class Immution:
    """Thread-safe scoring engine and log follower."""

    def __init__(self, runtime_dir: str = DEFAULT_RUNTIME_DIR, threshold: float = DEFAULT_THRESHOLD):
        self.runtime_dir = runtime_dir
        self.threshold = float(threshold)
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_lock = threading.Lock()
        self.ip_locks: Dict[str, Any] = defaultdict(threading.Lock)
        self.ip_locks_guard = threading.Lock()
        self.running = True

        os.makedirs(self.runtime_dir, mode=0o750, exist_ok=True)
        try:
            os.chmod(self.runtime_dir, 0o750)
        except PermissionError:
            pass

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum: int, _frame: Any) -> None:
        print(f"[*] received signal {signum}; stopping")
        self.running = False

    def _ip_lock(self, ip: str) -> threading.Lock:
        with self.ip_locks_guard:
            return self.ip_locks[ip]

    @staticmethod
    def _filename(ip: str) -> str:
        # ip is canonical and validated before this point.
        return ip.replace(":", "_") + ".json"

    def filepath(self, ip: str) -> str:
        return os.path.join(self.runtime_dir, self._filename(ip))

    @staticmethod
    def new_ip_data(now: float) -> Dict[str, Any]:
        return {
            "score": 0.0,
            "banned": False,
            "requests": 0,
            "errors_404": 0,
            "probes": 0,
            "first_seen": now,
            "updated": now,
            "last_score_ts": now,
            "error_times": [],
            "probe_times": [],
            "error_paths": [],
            "last_bonus": {},
            "reasons": [],
        }

    def is_tracked(self, ip: str) -> bool:
        path = self.filepath(ip)
        with self.cache_lock:
            if ip in self.cache:
                if os.path.exists(path):
                    return True
                # immutionctl unblock removes the published state file. Do not
                # let a stale in-process copy silently recreate the ban.
                self.cache.pop(ip, None)
        return os.path.exists(path)

    def load_ip_data(self, ip: str, now: float) -> Dict[str, Any]:
        path = self.filepath(ip)
        with self.cache_lock:
            cached = self.cache.get(ip)
            if cached is not None:
                if os.path.exists(path):
                    return copy.deepcopy(cached)
                self.cache.pop(ip, None)

        if not os.path.exists(path):
            return self.new_ip_data(now)

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("IP state is not an object")
        except (OSError, ValueError, json.JSONDecodeError):
            return self.new_ip_data(now)

        defaults = self.new_ip_data(now)
        for key, value in defaults.items():
            data.setdefault(key, value)

        with self.cache_lock:
            self.cache[ip] = copy.deepcopy(data)
        return data

    def save_ip_data(self, ip: str, data: Dict[str, Any]) -> None:
        """Atomically publish state so PHP never reads partial JSON."""
        data["updated"] = time.time()
        data["banned"] = float(data.get("score", 0.0)) >= self.threshold

        with self.cache_lock:
            self.cache[ip] = copy.deepcopy(data)

        path = self.filepath(ip)
        temp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, separators=(",", ":"), ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o640)
            os.replace(temp_path, path)
        except OSError as exc:
            print(f"[!] cannot write {path}: {exc}", file=sys.stderr)
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    @staticmethod
    def add_reason(data: Dict[str, Any], points: float, reason: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        data["reasons"].insert(0, f"{timestamp} +{points:.1f}: {reason}")
        data["reasons"] = data["reasons"][:20]

    @staticmethod
    def bonus_allowed(data: Dict[str, Any], name: str, now: float) -> bool:
        last = float(data["last_bonus"].get(name, 0.0))
        if now - last < BONUS_COOLDOWN:
            return False
        data["last_bonus"][name] = now
        return True

    @staticmethod
    def _prune_windows(data: Dict[str, Any], now: float) -> None:
        cutoff = now - 60.0
        data["error_times"] = [float(ts) for ts in data.get("error_times", []) if float(ts) >= cutoff][-128:]
        data["probe_times"] = [float(ts) for ts in data.get("probe_times", []) if float(ts) >= cutoff][-128:]

        paths: List[List[Any]] = []
        for item in data.get("error_paths", []):
            if isinstance(item, list) and len(item) == 2 and float(item[0]) >= cutoff:
                paths.append([float(item[0]), str(item[1])[:256]])
        data["error_paths"] = paths[-128:]

    def analyze_line(self, line: str) -> None:
        parsed = parse_log_line(line)
        if parsed is None:
            return

        ip, _method, path, status, user_agent = parsed
        if ip.startswith("127.") or ip == "::1":
            return

        is_404 = status == 404
        is_probe = status in {400, 401, 403, 404} and bool(PROBE_REGEX.search(path))
        scanner_ua = bool(user_agent and SCANNER_UA_REGEX.search(user_agent))
        missing_ua = not user_agent or user_agent == "-"
        suspicious_candidate = is_404 or is_probe or ((scanner_ua or missing_ua) and status >= 400)

        # Clean traffic is not persisted. Existing records are still updated so
        # their score can decay and a temporary ban can be lifted.
        if not suspicious_candidate and not self.is_tracked(ip):
            return

        with self._ip_lock(ip):
            now = time.time()
            data = self.load_ip_data(ip, now)
            previous_score = float(data.get("score", 0.0))
            elapsed = max(0.0, now - float(data.get("last_score_ts", now)))
            data["score"] = decay(previous_score, elapsed)
            data["last_score_ts"] = now
            data["requests"] = int(data.get("requests", 0)) + 1
            self._prune_windows(data, now)

            score_delta = 0.0

            if is_404:
                data["errors_404"] = int(data.get("errors_404", 0)) + 1
                data["error_times"].append(now)
                data["error_paths"].append([now, path[:256]])
                recent_404 = len(data["error_times"])
                points = SCORE_404_BASE + min(recent_404, 10) * 0.5
                score_delta += points
                self.add_reason(data, points, f"404 {path[:80]}")

            if is_probe:
                data["probes"] = int(data.get("probes", 0)) + 1
                data["probe_times"].append(now)
                points = SCORE_PROBE_BASE + min(len(data["probe_times"]), 5) * 2.0
                score_delta += points
                self.add_reason(data, points, f"probe {path[:80]}")

            # User-Agent never causes a ban on successful traffic by itself.
            if is_404 or is_probe:
                if missing_ua:
                    score_delta += SCORE_NO_UA
                    self.add_reason(data, SCORE_NO_UA, "missing user-agent on suspicious request")
                elif scanner_ua:
                    score_delta += SCORE_SCANNER_UA
                    self.add_reason(data, SCORE_SCANNER_UA, "known scanner user-agent")

            recent_404 = len(data["error_times"])
            recent_probes = len(data["probe_times"])
            unique_error_paths = len({item[1] for item in data["error_paths"]})

            if recent_404 >= 10 and self.bonus_allowed(data, "404_burst", now):
                score_delta += BONUS_404_BURST
                self.add_reason(data, BONUS_404_BURST, "10+ 404 responses in 60 seconds")

            if recent_probes >= 4 and self.bonus_allowed(data, "probe_burst", now):
                score_delta += BONUS_PROBE_BURST
                self.add_reason(data, BONUS_PROBE_BURST, "4+ probe paths in 60 seconds")

            if unique_error_paths >= 20 and self.bonus_allowed(data, "scan", now):
                score_delta += BONUS_SCAN
                self.add_reason(data, BONUS_SCAN, "20+ unique error paths in 60 seconds")

            data["score"] = float(data["score"]) + score_delta
            was_banned = bool(data.get("banned"))
            will_be_banned = data["score"] >= self.threshold

            if will_be_banned and not was_banned:
                print(f"[BAN] {ip} score={data['score']:.1f}")
            elif was_banned and not will_be_banned:
                print(f"[UNBAN] {ip} score={data['score']:.1f}")

            self.save_ip_data(ip, data)

    def cleanup_old_files(self) -> None:
        now = time.time()
        removed = 0
        try:
            filenames = os.listdir(self.runtime_dir)
        except OSError as exc:
            print(f"[!] cleanup failed: {exc}", file=sys.stderr)
            return

        for filename in filenames:
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self.runtime_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                updated = float(data.get("updated", os.path.getmtime(path)))
                if now - updated <= SCORE_TTL:
                    continue
            except (OSError, ValueError, json.JSONDecodeError):
                try:
                    if now - os.path.getmtime(path) <= SCORE_TTL:
                        continue
                except OSError:
                    continue

            try:
                os.unlink(path)
                removed += 1
            except OSError:
                continue

        if removed:
            with self.cache_lock:
                self.cache.clear()
            print(f"[*] removed {removed} stale state files")

    def tail_single_log(self, log_path: str) -> None:
        print(f"[+] watching {log_path}")
        process = subprocess.Popen(
            ["tail", "-F", "-n", "0", log_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            assert process.stdout is not None
            while self.running:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                self.analyze_line(line.rstrip("\n"))
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def run(self, log_paths: Iterable[str]) -> None:
        paths = [os.path.realpath(path) for path in log_paths if os.path.isfile(path)]
        if not paths:
            raise RuntimeError("no readable Apache access logs found")

        print(f"[*] Immution {VERSION}")
        print(f"[*] threshold={self.threshold:g} runtime={self.runtime_dir}")
        threads = []
        for path in sorted(set(paths)):
            thread = threading.Thread(target=self.tail_single_log, args=(path,), daemon=True)
            thread.start()
            threads.append(thread)

        last_cleanup = time.time()
        while self.running:
            time.sleep(1)
            if time.time() - last_cleanup >= CLEANUP_INTERVAL:
                self.cleanup_old_files()
                last_cleanup = time.time()


def find_access_logs(directory: str) -> List[str]:
    patterns = [
        os.path.join(directory, "access.log"),
        os.path.join(directory, "*access*.log"),
        os.path.join(directory, "*-access.log"),
    ]
    found = set()
    for pattern in patterns:
        found.update(path for path in glob.glob(pattern) if os.path.isfile(path))
    return sorted(found)


def resolve_log_paths(args: argparse.Namespace, config: Dict[str, Any]) -> List[str]:
    if args.auto:
        return find_access_logs(args.auto)
    if args.logs:
        return list(args.logs)
    configured_logs = [str(item) for item in config.get("logs", [])]
    if configured_logs:
        return configured_logs
    auto_dir = str(config.get("auto_dir", "/var/log/apache2"))
    return find_access_logs(auto_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Immution Apache log analyzer")
    parser.add_argument("logs", nargs="*", help="explicit Apache access log paths")
    parser.add_argument("--auto", metavar="DIR", help="discover access logs in DIR")
    parser.add_argument("--config", metavar="FILE", help="daemon JSON configuration")
    parser.add_argument("--runtime-dir", metavar="DIR", help="state directory")
    parser.add_argument("--threshold", type=float, help="ban score threshold")
    parser.add_argument("--check-config", action="store_true", help="validate configuration and exit")
    parser.add_argument("--version", action="version", version=f"Immution {VERSION}")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_json_config(args.config) if args.config else {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[!] invalid configuration: {exc}", file=sys.stderr)
        return 2

    runtime_dir = args.runtime_dir or str(config.get("runtime_dir", DEFAULT_RUNTIME_DIR))
    threshold = args.threshold if args.threshold is not None else float(config.get("threshold", DEFAULT_THRESHOLD))
    log_paths = resolve_log_paths(args, config)

    if args.check_config:
        missing = [path for path in log_paths if not os.path.isfile(path)]
        print(f"runtime_dir={runtime_dir}")
        print(f"threshold={threshold:g}")
        print(f"logs={len(log_paths)}")
        for path in log_paths:
            print(f"  {'MISSING' if path in missing else 'OK'} {path}")
        return 1 if missing or not log_paths else 0

    if not log_paths:
        print("[!] no Apache access logs found", file=sys.stderr)
        return 1

    try:
        Immution(runtime_dir=runtime_dir, threshold=threshold).run(log_paths)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
