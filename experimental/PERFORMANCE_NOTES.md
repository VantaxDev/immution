# Immution — experimental performance notes

> **Not a supported benchmark.** The figures below were inherited from the
> pre-release prototype and have not yet been reproduced by the rc1 test suite.
> Do not quote them on the website or in release announcements. The mmap PHP
> prototype also needs an I/O and collision review before production use.

This document describes performance experiments that require **no additional
software** installation. The experimental PHP prototype is syntax-compatible
with PHP 7.0+, but it is not part of the supported or security-reviewed gate.

## Optimizations Implemented

### 1. Sharded Locks (Python)

**Problem:** Single global lock causes contention when multiple threads process requests simultaneously.

**Solution:** Divide cache into 16 shards, each with its own lock. Threads accessing different IPs don't block each other.

```python
# Before: Single lock
self.lock = threading.Lock()
with self.lock:
    self.cache[ip] = data

# After: Sharded locks
shard = hash(ip) % 16
with self.locks[shard]:
    self.shards[shard][ip] = data
```

**Impact:** ~2-4x throughput improvement under load.

---

### 2. Write Buffering (Python)

**Problem:** Writing to disk on every request creates I/O bottleneck.

**Solution:** Buffer writes in memory and flush periodically or when buffer is full.

```python
WRITE_BUFFER_SIZE = 50      # Flush after 50 updates
WRITE_BUFFER_INTERVAL = 2.0  # Or every 2 seconds
```

**Impact:** ~10x fewer disk writes.

---

### 3. Lazy Writes (Python)

**Problem:** Writing unchanged or minimally changed data wastes I/O.

**Solution:** Only write when score changes by ≥5 points or ban status changes.

```python
SCORE_CHANGE_THRESHOLD = 5.0

# Only write if significant change
if abs(new_score - last_written_score) >= SCORE_CHANGE_THRESHOLD:
    write_to_disk()
```

**Impact:** ~5x fewer writes for legitimate traffic.

---

### 4. Bloom Filter for Clean IPs (Python)

**Problem:** Reading files for IPs with no suspicious activity is wasteful.

**Solution:** Track "clean" IPs in a bloom filter. If IP is in filter, skip file read.

```python
# New IP arrives
if ip in bloom_filter:
    return new_ip_data()  # Skip file read
else:
    return read_from_file(ip)
```

**Impact:** ~50% fewer file reads for clean traffic.

---

### 5. Memory-Mapped Banned IP Table (Python + PHP)

**Problem:** PHP must read and parse JSON to check if IP is banned.

**Solution:** Python maintains a fixed-size mmap file. PHP reads directly - O(1) lookup.

```
File structure (512KB):
┌─────────────────────────────────────────┐
│ Entry 0: [4B checksum][4B timestamp]    │
│ Entry 1: [4B checksum][4B timestamp]    │
│ ...                                     │
│ Entry 65535: [4B checksum][4B timestamp]│
└─────────────────────────────────────────┘
```

PHP lookup:
```php
$idx = md5_hash($ip) % 65536;
$entry = substr($mmap, $idx * 8, 8);
$is_banned = (checksum_matches($entry, $ip));
```

**Impact:** ~100x faster ban checks in PHP.

---

### 6. Atomic File Writes (Python)

**Problem:** Partial writes can corrupt JSON if process interrupted.

**Solution:** Write to temp file, then rename (atomic operation).

```python
# Write to temp
with open(filepath + '.tmp', 'w') as f:
    json.dump(data, f)
# Atomic rename
os.rename(filepath + '.tmp', filepath)
```

**Impact:** Eliminates file corruption.

---

### 7. Compact JSON (Python)

**Problem:** Pretty-printed JSON wastes bytes and parse time.

**Solution:** Use compact separators.

```python
# Before
json.dump(data, f, indent=2)  # ~2KB per file

# After
json.dump(data, f, separators=(',', ':'))  # ~1KB per file
```

**Impact:** ~50% smaller files, faster parsing.

---

### 8. Static Variable Caching (PHP)

**Problem:** Repeated function calls for same data within request.

**Solution:** Use PHP static variables to cache results.

```php
function get_client_ip(): string {
    static $ip = null;
    if ($ip !== null) return $ip;
    // ... compute IP only once
    return $ip = $computed_ip;
}
```

**Impact:** Eliminates redundant computation.

---

### 9. Early Exit Paths (PHP)

**Problem:** Processing all checks even when not needed.

**Solution:** Return immediately when possible.

```php
// Fast exits (most common cases)
if (!IMMUTION_ENABLED) return;
if (is_excluded_path()) return;
if (is_localhost($ip)) return;
if (is_whitelisted($ip)) return;

// Only then check mmap/files
```

**Impact:** Minimal overhead for legitimate traffic.

---

## Configuration Tuning

Edit these values in `immution_optimized.py`:

```python
# Write buffering
WRITE_BUFFER_SIZE = 50        # Higher = fewer writes, more memory
WRITE_BUFFER_INTERVAL = 2.0   # Seconds between flushes

# Lazy writes
SCORE_CHANGE_THRESHOLD = 5.0  # Higher = fewer writes, less precision

# Cache sharding
NUM_SHARDS = 16               # Higher = less contention, more memory

# Bloom filter
BLOOM_SIZE = 100000           # Higher = fewer false positives
```

---

## Expected Performance

| Metric | Original | Optimized | Improvement |
|--------|----------|-----------|-------------|
| Disk writes/sec | 1000 | 50-100 | ~10-20x fewer |
| Ban check latency | ~2ms | ~0.02ms | ~100x faster |
| Cache lock contention | High | Low | ~4x throughput |
| File reads for clean IPs | All | ~50% | ~2x fewer |
| Memory usage | ~10MB | ~20MB | Acceptable tradeoff |

---

## Installation

```bash
# Replace original files
cp immution_optimized.py /opt/immution/immution.py
cp gate_optimized.php /opt/immution/gate.php

# Restart
sudo systemctl restart immution
sudo systemctl restart apache2
```

---

## Monitoring

```bash
# Watch write buffer flushes
journalctl -u immution -f | grep "Cleanup\|flush"

# Check mmap file
ls -la /dev/shm/immution/banned.mmap

# Count active IPs
ls /dev/shm/immution/*.txt | wc -l

# Monitor file I/O
inotifywait -m /dev/shm/immution/ -e create,modify,delete
```

---

## Advanced Optimizations (Require Additional Software)

If you can install additional packages, these provide further improvements:

| Package | Command | Benefit |
|---------|---------|---------|
| msgpack | `pip install msgpack` | 3-5x faster serialization |
| APCu | `apt install php-apcu` | PHP in-memory cache |
| Redis | `apt install redis` | Centralized state, clustering |

See the extended documentation for details on these options.
