"""Thread-safe, size-bounded LRU cache with per-entry TTL.

Expiry is lazy: nothing runs in the background. All time comes from the
injected ``time_fn``; no other time source is used anywhere in this class.
"""

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

from .stats import CacheStats

# Private sentinel distinguishing "ttl argument omitted" (use the cache
# default) from an explicit ``ttl=None`` (entry never expires).
_DEFAULT_TTL = object()


def _validate_ttl(value: Any) -> float:
    # Interpretation: bool is rejected here as a non-number (ValueError),
    # matching the spec's "X <= 0 or a non-number raises ValueError".
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("ttl must be a real number > 0 or None")
    if not value > 0:
        raise ValueError("ttl must be > 0")
    return float(value)


class LRUCache:
    def __init__(
        self,
        capacity: int,
        ttl: "float | None" = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError("capacity must be an int")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if ttl is not None:
            ttl = _validate_ttl(ttl)
        self._capacity = capacity
        self._default_ttl = ttl
        self._time_fn = time_fn
        self._lock = threading.RLock()
        # key -> (value, expires_at); expires_at is None for immortal entries.
        self._data: "OrderedDict[Hashable, tuple]" = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def _is_expired(self, expires_at: "float | None", now: float) -> bool:
        # An entry stored at t0 with TTL t expires when now >= t0 + t.
        return expires_at is not None and now >= expires_at

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default
            value, expires_at = entry
            if self._is_expired(expires_at, self._time_fn()):
                del self._data[key]
                self._expirations += 1
                self._misses += 1
                return default
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: Hashable, value: Any, ttl: "float | None" = _DEFAULT_TTL) -> None:
        if ttl is _DEFAULT_TTL:
            effective_ttl = self._default_ttl
        elif ttl is None:
            effective_ttl = None
        else:
            effective_ttl = _validate_ttl(ttl)
        with self._lock:
            now = self._time_fn()
            expires_at = None if effective_ttl is None else now + effective_ttl
            if key in self._data:
                self._data[key] = (value, expires_at)
                self._data.move_to_end(key)
                return
            if len(self._data) >= self._capacity:
                # Prefer dropping already-expired entries (counted as
                # expirations) over evicting a live LRU entry.
                for k in [k for k, (_, exp) in self._data.items()
                          if self._is_expired(exp, now)]:
                    del self._data[k]
                    self._expirations += 1
                if len(self._data) >= self._capacity:
                    self._data.popitem(last=False)
                    self._evictions += 1
            self._data[key] = (value, expires_at)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            _, expires_at = entry
            del self._data[key]
            if self._is_expired(expires_at, self._time_fn()):
                self._expirations += 1
                return False
            return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def purge_expired(self) -> int:
        with self._lock:
            now = self._time_fn()
            expired = [k for k, (_, exp) in self._data.items()
                       if self._is_expired(exp, now)]
            for k in expired:
                del self._data[k]
            self._expirations += len(expired)
            return len(expired)

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [k for k, (_, exp) in reversed(self._data.items())
                    if not self._is_expired(exp, now)]

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                expirations=self._expirations,
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            _, expires_at = entry
            if self._is_expired(expires_at, self._time_fn()):
                del self._data[key]
                self._expirations += 1
                return False
            return True
