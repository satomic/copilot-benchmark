"""Thread-safe LRU cache with lazy per-entry TTL expiry."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

from .stats import CacheStats

_UNSET = object()


class LRUCache:
    """Size-bounded cache with least-recently-used eviction and lazy TTL expiry."""

    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError(f"capacity must be an int, got {type(capacity).__name__}")
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")

        self._capacity = capacity
        self._default_ttl = None if ttl is None else _check_ttl(ttl)
        self._time_fn = time_fn
        self._lock = threading.RLock()

        # key -> (value, deadline or None); ordered least- to most-recently used
        self._entries: OrderedDict[Hashable, tuple[Any, float | None]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # ------------------------------------------------------------- reads ----

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return default
            if self._is_expired(entry[1]):
                del self._entries[key]
                self._expirations += 1
                self._misses += 1
                return default
            self._entries.move_to_end(key)
            self._hits += 1
            return entry[0]

    def keys(self) -> list:
        """Live keys, most-recently-used first. Does not mutate cache or stats."""
        with self._lock:
            return [
                key
                for key, (_, deadline) in reversed(self._entries.items())
                if not self._is_expired(deadline)
            ]

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                expirations=self._expirations,
            )

    # ------------------------------------------------------------ writes ----

    def set(self, key: Hashable, value: Any, ttl: float | None = _UNSET) -> None:  # type: ignore[assignment]
        with self._lock:
            if ttl is _UNSET:
                lifetime = self._default_ttl
            elif ttl is None:
                lifetime = None
            else:
                lifetime = _check_ttl(ttl)

            deadline = None if lifetime is None else self._time_fn() + lifetime

            if key in self._entries:
                self._entries[key] = (value, deadline)
                self._entries.move_to_end(key)
                return

            if len(self._entries) >= self._capacity:
                self._reclaim()
            if len(self._entries) >= self._capacity:
                self._entries.popitem(last=False)
                self._evictions += 1

            self._entries[key] = (value, deadline)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            del self._entries[key]
            if self._is_expired(entry[1]):
                self._expirations += 1
                return False
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def purge_expired(self) -> int:
        with self._lock:
            return self._reclaim()

    # ----------------------------------------------------------- dunders ----

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            entry = self._entries.get(key)  # type: ignore[arg-type]
            if entry is None:
                return False
            if self._is_expired(entry[1]):
                del self._entries[key]  # type: ignore[arg-type]
                self._expirations += 1
                return False
            return True

    # ---------------------------------------------------------- internals ---

    def _is_expired(self, deadline: float | None) -> bool:
        return deadline is not None and self._time_fn() >= deadline

    def _reclaim(self) -> int:
        """Drop every expired entry. Caller must hold the lock."""
        now = self._time_fn()
        stale = [
            key
            for key, (_, deadline) in self._entries.items()
            if deadline is not None and now >= deadline
        ]
        for key in stale:
            del self._entries[key]
        self._expirations += len(stale)
        return len(stale)


def _check_ttl(ttl: object) -> float:
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
        raise ValueError(f"ttl must be a positive number, got {ttl!r}")
    if ttl <= 0:
        raise ValueError(f"ttl must be > 0, got {ttl!r}")
    return float(ttl)
