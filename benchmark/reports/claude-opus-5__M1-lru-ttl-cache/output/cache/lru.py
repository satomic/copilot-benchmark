"""A thread-safe, size-bounded LRU cache with lazy per-entry TTL expiry."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from numbers import Real
from typing import Any, Callable, Hashable

from .stats import CacheStats

__all__ = ["LRUCache"]

# Sentinel distinguishing "ttl argument omitted" (use the cache default) from an
# explicit ``ttl=None`` (this entry never expires).
_UNSET: Any = object()


class LRUCache:
    """Least-recently-used cache with optional time-to-live per entry.

    Entries are stored most-recently-used last in an ``OrderedDict``, which gives
    O(1) lookup, insertion, reordering and LRU eviction. Expiry is entirely lazy:
    no threads and no timers are used; entries are only dropped when touched or
    when :meth:`purge_expired` is called.

    All time comes from ``time_fn``; the class never reads the wall clock itself.
    """

    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        # ``bool`` is a subclass of ``int``, so reject it explicitly first.
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError(f"capacity must be an int, got {type(capacity).__name__}")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if not callable(time_fn):
            raise TypeError("time_fn must be callable")

        self._capacity = capacity
        self._default_ttl = self._validate_ttl(ttl)
        self._time_fn = time_fn
        self._lock = threading.RLock()
        self._data: OrderedDict[Hashable, tuple[Any, float | None]] = OrderedDict()

        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # -- helpers (callers must hold the lock, except _validate_ttl) --------

    @staticmethod
    def _validate_ttl(ttl: float | None) -> float | None:
        """Return a validated TTL. ``None`` means 'never expires'.

        A bad TTL always raises ``ValueError`` (including non-numbers), per spec.
        """
        if ttl is None:
            return None
        if isinstance(ttl, bool) or not isinstance(ttl, Real):
            raise ValueError(f"ttl must be a real number > 0, got {ttl!r}")
        ttl = float(ttl)
        if not ttl > 0:
            raise ValueError(f"ttl must be > 0, got {ttl!r}")
        return ttl

    @staticmethod
    def _is_expired(expires_at: float | None, now: float) -> bool:
        # Exactly at the deadline the entry is already expired.
        return expires_at is not None and now >= expires_at

    def _drop_expired_from_lru_end(self, now: float) -> int:
        """Drop already-expired entries starting from the LRU end.

        Interpretation of the "prefer expired entries over live ones" rule: to
        keep ``set`` O(1) amortised we do not scan the whole cache. We pop from
        the least-recently-used end while the entries there are expired, which
        reclaims space without an eviction whenever possible.
        """
        removed = 0
        for key in list(self._data.keys()):
            _value, expires_at = self._data[key]
            if not self._is_expired(expires_at, now):
                break
            del self._data[key]
            removed += 1
        self._expirations += removed
        return removed

    # -- public API --------------------------------------------------------

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

    def set(self, key: Hashable, value: Any, ttl: float | None = _UNSET) -> None:
        with self._lock:
            effective_ttl = (
                self._default_ttl if ttl is _UNSET else self._validate_ttl(ttl)
            )
            now = self._time_fn()
            expires_at = None if effective_ttl is None else now + effective_ttl

            if key in self._data:
                # Update value, restart TTL, and make it most recently used.
                self._data[key] = (value, expires_at)
                self._data.move_to_end(key)
                return

            if len(self._data) >= self._capacity:
                if self._drop_expired_from_lru_end(now) == 0:
                    self._data.popitem(last=False)
                    self._evictions += 1

            self._data[key] = (value, expires_at)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            _value, expires_at = entry
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
            expired = [
                key
                for key, (_value, expires_at) in self._data.items()
                if self._is_expired(expires_at, now)
            ]
            for key in expired:
                del self._data[key]
            self._expirations += len(expired)
            return len(expired)

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                key
                for key, (_value, expires_at) in reversed(self._data.items())
                if not self._is_expired(expires_at, now)
            ]

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
            _value, expires_at = entry
            if self._is_expired(expires_at, self._time_fn()):
                del self._data[key]
                self._expirations += 1
                return False
            return True
