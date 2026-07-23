#!/usr/bin/env python3
"""
Immution - Optimized Version (No External Dependencies)

Performance improvements using only Python standard library:
1. Sharded locks - reduce lock contention
2. Write buffering - batch writes to reduce I/O
3. Lazy writes - only write when score changes significantly
4. Memory-mapped banned IP table - O(1) ban lookups from PHP
5. Optimized file handling - reduce syscalls
6. In-memory bloom filter - skip reads for clean IPs
"""

import re
import os
import sys
import glob
import json
import time
import signal
import argparse
import subprocess
import threading
import hashlib
import struct
import mmap
from datetime import datetime
from collections import deque
from typing import Dict, Optional
import math

# =============================================================================
# CONFIGURATION
# =============================================================================

SHM_DIR = '/dev/shm/immution'
MMAP_FILE = '/dev/shm/immution/banned.mmap'

# Scoring (same as original)
SCORE_404_BASE = 2
SCORE_PROBE_BASE = 6
SCORE_NO_UA = 8
SCORE_BOT_UA = 12

BONUS_REQ_SOFT = 10
BONUS_REQ_HARD = 25
BONUS_404_BURST = 20
BONUS_PROBE_BURST = 35
BONUS_SCAN = 30

THRESHOLD_BAN = 50

THRESH_REQ_10S_SOFT = 25
THRESH_REQ_10S_HARD = 60
THRESH_404_60S = 10
THRESH_PROBE_60S = 5
THRESH_UNIQUE_PATHS_60S = 20

SCORE_HALFLIFE = 20 * 60.0
DECAY_EPS = 1e-6

SCORE_TTL = 3600
CLEANUP_INTERVAL = 60

WINDOW_10S = 10.0
WINDOW_60S = 60.0
BONUS_COOLDOWN = 30.0

# === PERFORMANCE TUNING ===
WRITE_BUFFER_SIZE = 50          # Buffer this many updates before flushing
WRITE_BUFFER_INTERVAL = 2.0     # Flush every N seconds
SCORE_CHANGE_THRESHOLD = 5.0    # Only write if score changed by this much
NUM_SHARDS = 16                 # Number of lock shards
BLOOM_SIZE = 100000             # Bloom filter size
BLOOM_HASHES = 3                # Number of hash functions

# Detection patterns (pre-compiled)
PROBE_PATHS = [
    r'/wp-', r'/wordpress', r'/wp-admin', r'/wp-login',
    r'/\.env', r'/\.git', r'/\.htaccess', r'/\.htpasswd',
    r'/phpmyadmin', r'/pma', r'/mysql', r'/adminer',
    r'/config\.', r'/database\.', r'/db\.', r'/backup',
    r'/shell', r'/cmd', r'/eval', r'/exec',
    r'/admin', r'/administrator', r'/manager',
    r'/cgi-bin', r'/scripts',
    r'/actuator', r'/api/swagger', r'/swagger',
    r'/graphql', r'/console', r'/debug',
    r'/\.aws', r'/\.ssh', r'/id_rsa',
    r'/etc/passwd', r'/proc/self',
    r'\.sql$', r'\.bak$', r'\.zip$', r'\.tar',
    r'/xmlrpc\.php', r'/wlwmanifest\.xml',
]

BOT_USERAGENTS = [
    r'bot', r'crawler', r'spider', r'scraper',
    r'curl', r'wget', r'python-requests', r'python-urllib',
    r'go-http-client', r'java/', r'libwww',
    r'nikto', r'nmap', r'sqlmap', r'masscan', r'zgrab',
    r'semrush', r'ahrefs', r'mj12bot', r'dotbot',
    r'petalbot', r'bytespider', r'gptbot',
    r'headless', r'phantom', r'selenium',
]

PROBE_REGEX = re.compile('|'.join(PROBE_PATHS), re.IGNORECASE)
BOT_UA_REGEX = re.compile('|'.join(BOT_USERAGENTS), re.IGNORECASE)

LOG_REGEX = re.compile(
    r'^(\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+'
    r'"(\S+)\s+(\S+)[^"]*"\s+(\d+)\s+(\d+|-)\s*'
    r'"([^"]*)"\s*"([^"]*)"'
)


def decay(value: float, dt: float, window: float) -> float:
    """Apply exponential decay."""
    if value <= 0:
        return 0.0
    k = math.log(2.0) / max(window, DECAY_EPS)
    return value * math.exp(-k * dt)


class BloomFilter:
    """
    Simple Bloom filter for tracking "clean" IPs.
    Uses only standard library (hashlib).
    """
    
    def __init__(self, size: int = BLOOM_SIZE, num_hashes: int = BLOOM_HASHES):
        self.size = size
        self.num_hashes = num_hashes
        self.bits = bytearray(size // 8 + 1)
        self.lock = threading.Lock()
    
    def _hashes(self, item: str) -> list:
        """Generate hash values using MD5 with different seeds."""
        hashes = []
        for i in range(self.num_hashes):
            h = hashlib.md5(f"{item}{i}".encode()).digest()
            hashes.append(int.from_bytes(h[:4], 'little') % self.size)
        return hashes
    
    def add(self, item: str) -> None:
        with self.lock:
            for h in self._hashes(item):
                self.bits[h // 8] |= (1 << (h % 8))
    
    def remove(self, item: str) -> None:
        with self.lock:
            for h in self._hashes(item):
                self.bits[h // 8] &= ~(1 << (h % 8))
    
    def __contains__(self, item: str) -> bool:
        with self.lock:
            for h in self._hashes(item):
                if not (self.bits[h // 8] & (1 << (h % 8))):
                    return False
            return True


class BannedIPMap:
    """
    Memory-mapped file for O(1) banned IP lookups from PHP.
    Each entry: 4 bytes checksum + 4 bytes timestamp = 8 bytes
    """
    
    ENTRY_SIZE = 8
    DEFAULT_SIZE = 65536
    
    def __init__(self, filepath: str = MMAP_FILE, size: int = DEFAULT_SIZE):
        self.filepath = filepath
        self.size = size
        self.file_size = size * self.ENTRY_SIZE
        self.lock = threading.Lock()
        self.mm = None
        self.file = None
        self._init_file()
    
    def _init_file(self):
        try:
            if not os.path.exists(self.filepath):
                with open(self.filepath, 'wb') as f:
                    f.write(b'\x00' * self.file_size)
                os.chmod(self.filepath, 0o666)
            
            self.file = open(self.filepath, 'r+b')
            self.mm = mmap.mmap(self.file.fileno(), self.file_size)
        except Exception as e:
            print(f"[!] Could not initialize mmap: {e}")
            self.mm = None
    
    def _ip_hash(self, ip: str) -> int:
        h = hashlib.md5(ip.encode()).digest()
        return int.from_bytes(h[:4], 'little') % self.size
    
    def _ip_checksum(self, ip: str) -> int:
        return int.from_bytes(hashlib.md5(ip.encode()).digest()[:4], 'little')
    
    def ban(self, ip: str) -> None:
        if self.mm is None:
            return
        idx = self._ip_hash(ip)
        offset = idx * self.ENTRY_SIZE
        timestamp = int(time.time())
        checksum = self._ip_checksum(ip)
        
        with self.lock:
            self.mm[offset:offset+4] = struct.pack('<I', checksum)
            self.mm[offset+4:offset+8] = struct.pack('<I', timestamp)
            self.mm.flush()
    
    def unban(self, ip: str) -> None:
        if self.mm is None:
            return
        idx = self._ip_hash(ip)
        offset = idx * self.ENTRY_SIZE
        
        with self.lock:
            self.mm[offset:offset+8] = b'\x00' * 8
            self.mm.flush()
    
    def close(self):
        if self.mm:
            self.mm.close()
        if self.file:
            self.file.close()


class ShardedCache:
    """Sharded cache with multiple locks to reduce contention."""
    
    def __init__(self, num_shards: int = NUM_SHARDS):
        self.num_shards = num_shards
        self.shards = [{} for _ in range(num_shards)]
        self.locks = [threading.Lock() for _ in range(num_shards)]
    
    def _get_shard(self, ip: str) -> int:
        return hash(ip) % self.num_shards
    
    def get(self, ip: str) -> Optional[dict]:
        shard = self._get_shard(ip)
        with self.locks[shard]:
            data = self.shards[shard].get(ip)
            return data.copy() if data else None
    
    def set(self, ip: str, data: dict) -> None:
        shard = self._get_shard(ip)
        with self.locks[shard]:
            self.shards[shard][ip] = data.copy()
    
    def delete(self, ip: str) -> None:
        shard = self._get_shard(ip)
        with self.locks[shard]:
            self.shards[shard].pop(ip, None)


class WriteBuffer:
    """Buffers writes to disk to reduce I/O operations."""
    
    def __init__(self, max_size: int = WRITE_BUFFER_SIZE, 
                 flush_interval: float = WRITE_BUFFER_INTERVAL):
        self.max_size = max_size
        self.flush_interval = flush_interval
        self.buffer: Dict[str, dict] = {}
        self.lock = threading.Lock()
        self.last_flush = time.time()
    
    def add(self, ip: str, data: dict) -> bool:
        with self.lock:
            self.buffer[ip] = data.copy()
            
            should_flush = (
                len(self.buffer) >= self.max_size or
                time.time() - self.last_flush > self.flush_interval
            )
            
            if should_flush:
                self._flush_locked()
                return True
            return False
    
    def _flush_locked(self) -> None:
        if not self.buffer:
            return
        
        for ip, data in self.buffer.items():
            filepath = os.path.join(SHM_DIR, f"{ip.replace(':', '_')}.txt")
            try:
                tmp_path = filepath + '.tmp'
                with open(tmp_path, 'w') as f:
                    json.dump(data, f, separators=(',', ':'))
                os.rename(tmp_path, filepath)
                os.chmod(filepath, 0o666)
            except IOError as e:
                print(f"[!] Error writing {filepath}: {e}")
        
        self.buffer.clear()
        self.last_flush = time.time()
    
    def flush(self) -> None:
        with self.lock:
            self._flush_locked()


class ImmutionOptimized:
    """Optimized Immution daemon - no external dependencies."""
    
    def __init__(self):
        self.cache = ShardedCache()
        self.write_buffer = WriteBuffer()
        self.bloom_clean = BloomFilter()
        self.banned_map = BannedIPMap()
        self.running = True
        self.last_written_score: Dict[str, float] = {}
        self.score_lock = threading.Lock()
        
        os.makedirs(SHM_DIR, exist_ok=True)
        os.chmod(SHM_DIR, 0o777)
        
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        print(f"\n[*] Received signal {signum}, shutting down...")
        self.write_buffer.flush()
        self.banned_map.close()
        self.running = False
    
    def new_ip_data(self) -> dict:
        now = time.time()
        return {
            'score': 0.0, 'banned': False, 'requests': 0,
            'errors_404': 0, 'probes': 0, 'first_seen': now,
            'updated': now, 'req_10s': 0.0, 'req_60s': 0.0,
            'e404_60s': 0.0, 'probe_60s': 0.0, 'unique_paths': [],
            'last_bonus': {}, 'last_score_ts': now, 'reasons': []
        }
    
    def load_ip_data(self, ip: str) -> dict:
        # Layer 1: Cache
        cached = self.cache.get(ip)
        if cached is not None:
            return cached
        
        # Layer 2: Bloom filter
        if ip in self.bloom_clean:
            data = self.new_ip_data()
            self.cache.set(ip, data)
            return data.copy()
        
        # Layer 3: File
        filepath = os.path.join(SHM_DIR, f"{ip.replace(':', '_')}.txt")
        
        if not os.path.exists(filepath):
            data = self.new_ip_data()
            self.cache.set(ip, data)
            self.bloom_clean.add(ip)
            return data.copy()
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            base = self.new_ip_data()
            for k, v in base.items():
                data.setdefault(k, v)
            self.cache.set(ip, data)
            return data.copy()
        except Exception:
            data = self.new_ip_data()
            self.cache.set(ip, data)
            return data.copy()
    
    def save_ip_data(self, ip: str, data: dict, force: bool = False) -> None:
        data['updated'] = time.time()
        was_banned = data.get('banned', False)
        data['banned'] = data['score'] >= THRESHOLD_BAN
        
        self.cache.set(ip, data)
        
        if data['banned'] and not was_banned:
            self.banned_map.ban(ip)
            self.bloom_clean.remove(ip)
            force = True
            print(f"[BAN] {ip} score={int(data['score'])}")
        elif not data['banned'] and was_banned:
            self.banned_map.unban(ip)
            force = True
        
        with self.score_lock:
            last_score = self.last_written_score.get(ip, 0)
            if force or abs(data['score'] - last_score) >= SCORE_CHANGE_THRESHOLD:
                self.write_buffer.add(ip, data)
                self.last_written_score[ip] = data['score']
    
    def add_reason(self, data: dict, points: float, reason: str) -> None:
        ts = datetime.now().strftime('%H:%M:%S')
        data['reasons'].insert(0, f"{ts} +{int(points)}: {reason}")
        data['reasons'] = data['reasons'][:20]
    
    def apply_score_decay(self, data: dict, now: float) -> None:
        dt = now - data['last_score_ts']
        if dt <= 0:
            return
        k = math.log(2.0) / max(SCORE_HALFLIFE, DECAY_EPS)
        data['score'] *= math.exp(-k * dt)
        data['last_score_ts'] = now
    
    def bonus_allowed(self, data: dict, name: str, now: float) -> bool:
        last = data['last_bonus'].get(name, 0)
        if now - last < BONUS_COOLDOWN:
            return False
        data['last_bonus'][name] = now
        return True
    
    def analyze_line(self, line: str) -> None:
        m = LOG_REGEX.match(line)
        if not m:
            return
        
        ip, ts, method, path, status, _, referrer, ua = m.groups()
        status = int(status)
        now = time.time()
        
        if ip.startswith('127.') or ip == '::1':
            return
        
        data = self.load_ip_data(ip)
        self.apply_score_decay(data, now)
        
        last_upd = data.get('updated', now)
        dt = max(now - last_upd, 0.0001)
        
        data['req_10s'] = decay(data['req_10s'], dt, WINDOW_10S)
        data['req_60s'] = decay(data['req_60s'], dt, WINDOW_60S)
        data['e404_60s'] = decay(data['e404_60s'], dt, WINDOW_60S)
        data['probe_60s'] = decay(data['probe_60s'], dt, WINDOW_60S)
        
        data['requests'] += 1
        data['req_10s'] += 1
        data['req_60s'] += 1
        
        score_delta = 0.0
        is_probe = bool(PROBE_REGEX.search(path))
        is_bot_ua = bool(ua and BOT_UA_REGEX.search(ua))
        no_ua = (not ua or ua == '-')
        
        if status == 404:
            data['errors_404'] += 1
            data['e404_60s'] += 1
            inc = SCORE_404_BASE * (1.0 + data['e404_60s'] / 5.0)
            score_delta += inc
            self.add_reason(data, inc, f"404: {path[:60]}")
        
        if is_probe:
            data['probes'] += 1
            data['probe_60s'] += 1
            inc = SCORE_PROBE_BASE * (1.0 + data['probe_60s'] / 3.0)
            score_delta += inc
            self.add_reason(data, inc, f"Probe: {path[:60]}")
        
        if data['req_10s'] > THRESH_REQ_10S_SOFT:
            if self.bonus_allowed(data, 'req_soft', now):
                score_delta += BONUS_REQ_SOFT
                self.add_reason(data, BONUS_REQ_SOFT, "Burst req soft")
        
        if data['req_10s'] > THRESH_REQ_10S_HARD:
            if self.bonus_allowed(data, 'req_hard', now):
                score_delta += BONUS_REQ_HARD
                self.add_reason(data, BONUS_REQ_HARD, "Burst req hard")
        
        if data['e404_60s'] > THRESH_404_60S:
            if self.bonus_allowed(data, '404_burst', now):
                score_delta += BONUS_404_BURST
                self.add_reason(data, BONUS_404_BURST, "404 burst")
        
        if data['probe_60s'] > THRESH_PROBE_60S:
            if self.bonus_allowed(data, 'probe_burst', now):
                score_delta += BONUS_PROBE_BURST
                self.add_reason(data, BONUS_PROBE_BURST, "Probe burst")
        
        up = deque(data.get('unique_paths', []), maxlen=64)
        if path not in up:
            up.append(path)
        data['unique_paths'] = list(up)
        
        if len(up) > THRESH_UNIQUE_PATHS_60S and data['req_60s'] > THRESH_REQ_10S_SOFT:
            if self.bonus_allowed(data, 'scan', now):
                score_delta += BONUS_SCAN
                self.add_reason(data, BONUS_SCAN, "Scanning pattern")
        
        if no_ua:
            score_delta += SCORE_NO_UA
            self.add_reason(data, SCORE_NO_UA, "No user-agent")
        elif is_bot_ua:
            score_delta += SCORE_BOT_UA
            self.add_reason(data, SCORE_BOT_UA, f"Bot UA: {ua[:40]}")
        
        if score_delta > 0:
            data['score'] += score_delta
        
        self.save_ip_data(ip, data)
    
    def cleanup_old_files(self) -> None:
        self.write_buffer.flush()
        now = time.time()
        removed = 0
        
        try:
            for filename in os.listdir(SHM_DIR):
                if not filename.endswith('.txt'):
                    continue
                filepath = os.path.join(SHM_DIR, filename)
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    if now - data.get('updated', now) > SCORE_TTL:
                        os.remove(filepath)
                        ip = filename[:-4].replace('_', ':')
                        self.cache.delete(ip)
                        with self.score_lock:
                            self.last_written_score.pop(ip, None)
                        self.banned_map.unban(ip)
                        removed += 1
                except Exception:
                    pass
        except Exception as e:
            print(f"[!] Cleanup error: {e}")
        
        if removed:
            print(f"[*] Cleanup removed {removed} files")
    
    def tail_single_log(self, log_path: str) -> None:
        print(f"[+] Watching: {log_path}")
        process = subprocess.Popen(
            ['tail', '-F', '-n', '0', log_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )
        try:
            while self.running:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                line = line.strip()
                if line:
                    self.analyze_line(line)
        finally:
            process.terminate()
            print(f"[-] Stopped: {log_path}")
    
    def run(self, log_paths: list) -> None:
        print("[*] Immution Optimized started")
        print(f"[*] Cache shards: {NUM_SHARDS}")
        print(f"[*] Write buffer: {WRITE_BUFFER_SIZE} / {WRITE_BUFFER_INTERVAL}s")
        print(f"[*] Lazy write threshold: {SCORE_CHANGE_THRESHOLD} pts")
        print(f"[*] Ban threshold: {THRESHOLD_BAN}")
        print(f"[*] Logs: {len(log_paths)}")
        
        threads = []
        for log_path in log_paths:
            if not os.path.exists(log_path):
                print(f"[!] Missing: {log_path}")
                continue
            t = threading.Thread(target=self.tail_single_log, args=(log_path,), daemon=True)
            t.start()
            threads.append(t)
        
        if not threads:
            print("[!] No valid logs")
            return
        
        last_cleanup = last_flush = time.time()
        while self.running:
            time.sleep(0.5)
            if time.time() - last_flush > WRITE_BUFFER_INTERVAL:
                self.write_buffer.flush()
                last_flush = time.time()
            if time.time() - last_cleanup > CLEANUP_INTERVAL:
                self.cleanup_old_files()
                last_cleanup = time.time()


def find_access_logs(directory: str) -> list:
    patterns = [
        os.path.join(directory, '*access*.log'),
        os.path.join(directory, '*-access.log'),
        os.path.join(directory, 'access.log'),
    ]
    logs = set()
    for pattern in patterns:
        logs.update(glob.glob(pattern))
    return sorted(logs)


def main():
    parser = argparse.ArgumentParser(description='Immution Optimized')
    parser.add_argument('logs', nargs='*')
    parser.add_argument('--auto', metavar='DIR')
    args = parser.parse_args()
    
    if args.auto:
        log_paths = find_access_logs(args.auto)
    elif args.logs:
        log_paths = args.logs
    else:
        default = '/var/log/apache2/access.log'
        log_paths = [default] if os.path.exists(default) else []
    
    if not log_paths:
        print("[!] No logs found")
        sys.exit(1)
    
    ImmutionOptimized().run(log_paths)


if __name__ == '__main__':
    main()
