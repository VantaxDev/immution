"""Detect endpoint-encoding mutation scans from Apache access log metadata.

Only stdlib, Python 3.6+. Read-only detection: this module cannot ban IPs.
Do not use the normalized route for request routing or security authorization.
"""

import math
import time
import posixpath
import re
import threading
from collections import Counter, OrderedDict, deque, namedtuple
from urllib.parse import unquote, urlsplit


Finding = namedtuple(
    'Finding',
    'ip scope method route requests variants suspicious_variants '
    'response_size matching_responses consistency'
)

# Escaped slash/dot/backslash, including a further encoded percent sign.
_ESCAPE_RE = re.compile(r'%(?:2f|2e|5c|25(?:2f|2e|5c))', re.IGNORECASE)
_DOT_RE = re.compile(r'(?:^|/)\.{1,2}(?:/|$)')


def _extract_route(target):
    """Return (canonical_route, raw_route_variant, is_suspicious).

    Ignore unrelated query variables when computing the raw route variant.
    Decode *once* only; double-decoding may coalesce different server routes.
    """
    if not isinstance(target, str) or len(target) > 2048:
        return None
    try:
        parts = urlsplit(target)
    except ValueError:
        return None

    if parts.scheme or parts.netloc or parts.fragment or not target.startswith('/'):
        return None
    raw_route = parts.path or '/'
    # WordPress REST query routing: /?rest_route=/batch/v1
    route_values = []
    for element in parts.query.split('&'):
        key, equal, value = element.partition('=')
        if equal and unquote(key) == 'rest_route':
            route_values.append(value)
    if route_values:
        if len(route_values) != 1 or parts.path != '/':
            return None
        raw_route = route_values[0]

    # Bound retained attacker-controlled variants even if the URL is short enough.
    if len(raw_route) > 256:
        return None
    # Decoding exactly once is critical: %252F != %2F.
    if re.search(r'%(?![0-9a-fA-F]{2})', raw_route):
        return None
    try:
        decoded = unquote(raw_route, errors='strict')
    except UnicodeError:
        return None
    if (not re.match(r'^(?:/|%2[fF]|%252[fF])', raw_route)
            or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
            or any(c in decoded for c in ('?', '#', '\\'))):
        return None
    # Collapsing dot segments is for correlation only, not for enforcement.
    normalized = posixpath.normpath('/' + decoded.lstrip('/'))
    is_suspicious = bool(
        _ESCAPE_RE.search(raw_route)
        or _DOT_RE.search(decoded)
        or '//' in decoded
    )
    return normalized, raw_route[:2048], is_suspicious


class RouteMutationDetector(object):
    """Bounded, thread-safe in-memory detector. Independent of Immution state.

    The scope must identify a *single verified vhost*.
    One global Combined log cannot distinguish virtual hosts. Callers must
    supply a verified host identity, NOT infer it from the source filename.
    """

    def __init__(self, window_seconds=120, min_requests=12,
                 min_variants=3, min_suspicious_variants=2,
                 min_consistency=0.85, min_response_bytes=512,
                 max_keys=1024, max_samples=48, cooldown_seconds=180):
        self.window_seconds = float(window_seconds)
        self.min_requests = int(min_requests)
        self.min_variants = int(min_variants)
        self.min_suspicious_variants = int(min_suspicious_variants)
        self.min_consistency = float(min_consistency)
        self.min_response_bytes = int(min_response_bytes)
        self.max_keys = int(max_keys)
        self.max_samples = int(max_samples)
        self.cooldown_seconds = float(cooldown_seconds)
        if (not math.isfinite(self.window_seconds) or self.window_seconds <= 0
                or not math.isfinite(self.cooldown_seconds) or self.cooldown_seconds < 0
                or self.min_requests < 1 or self.max_samples < self.min_requests
                or self.max_keys < 1 or self.min_variants < 1
                or self.min_suspicious_variants < 1
                or not 0 < self.min_consistency <= 1):
            raise ValueError('invalid detector bounds')
        self._buckets = OrderedDict()
        self._lock = threading.Lock()

    def _prune_locked(self, clock):
        # Ordered by last processing activity; monotonic time, not remote log time.
        while self._buckets:
            key = next(iter(self._buckets))
            if clock - self._buckets[key]['touched'] <= self.window_seconds:
                break
            self._buckets.popitem(last=False)

    def prune(self, clock=None):
        with self._lock:
            self._prune_locked(time.monotonic() if clock is None else clock)

    def observe(self, ip, scope, method, target, status, response_bytes, now):
        """Observe one completed response. Return Finding or None.

        IP and scope must come from trusted log metadata, never URL or headers.
        `now` is the parsed Apache event timestamp in seconds, not replay time.
        """
        if (status != 200 or not isinstance(method, str) or len(method) > 32
                or not re.fullmatch(r'[A-Za-z]+', method)
                or not isinstance(scope, str) or not scope or len(scope) > 253
                or not isinstance(ip, str) or not ip or len(ip) > 45):
            return None
        if isinstance(response_bytes, bool) or not isinstance(response_bytes, int):
            return None
        try:
            size = int(response_bytes)
            timestamp = float(now)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(timestamp) or size < self.min_response_bytes or size > 2**63 - 1:
            return None
        route_info = _extract_route(target)
        if route_info is None:
            return None
        route, variant, anomalous = route_info
        key = (scope, ip, method.upper(), route)

        with self._lock:
            clock = time.monotonic()
            self._prune_locked(clock)
            bucket = self._buckets.get(key)
            # Do not allocate state for ordinary traffic.
            if bucket is None:
                if not anomalous:
                    return None
                bucket = {'samples': deque(maxlen=self.max_samples),
                          'last_alert': float('-inf'), 'touched': clock,
                          'watermark': timestamp, 'overflow_until': float('-inf')}
                if len(self._buckets) >= self.max_keys:
                    self._buckets.popitem(last=False)
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)

            bucket['touched'] = clock
            bucket['watermark'] = max(timestamp, bucket['watermark'])
            watermark = bucket['watermark']
            cutoff = watermark - self.window_seconds
            samples = deque((row for row in bucket['samples'] if row[0] >= cutoff),
                            maxlen=self.max_samples)
            bucket['samples'] = samples
            if timestamp < cutoff:
                return None
            if len(samples) == self.max_samples:
                # Never turn a capped suffix into a falsely high consistency
                # over the advertised full window. Suppress until lost data expires.
                bucket['overflow_until'] = max(bucket['overflow_until'],
                                               samples[0][0] + self.window_seconds)
            samples.append((timestamp, variant, size, anomalous))
            if watermark <= bucket['overflow_until']:
                return None

            if len(samples) < self.min_requests:
                return None
            variants = set(row[1] for row in samples)
            if len(variants) < self.min_variants:
                return None
            odd_variants = set(row[1] for row in samples if row[3])
            if len(odd_variants) < self.min_suspicious_variants:
                return None

            dominant_size, matching = Counter(row[2] for row in samples).most_common(1)[0]
            consistency = matching / float(len(samples))
            if consistency < self.min_consistency:
                return None
            if watermark - bucket['last_alert'] < self.cooldown_seconds:
                return None

            bucket['last_alert'] = watermark
            return Finding(ip, scope, method.upper(), route,
                           len(samples), len(variants), len(odd_variants),
                           dominant_size, matching, round(consistency, 4))
