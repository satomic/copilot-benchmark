from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

from .stats import CacheStats

# Distinguishes omitted ttl (use cache default) from ttl=None (never expire).
_UNSET = object()


class _Entry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, expires_at: float | None) -> None:
        self.value = value
        self.expires_at = expires_at


class LRUCache:
    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(capacity) is not int:
            raise TypeError("capacity must be an int")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._default_ttl = self._validate_ttl(ttl)
        self._time_fn = time_fn
        self._data: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    @staticmethod
    def _validate_ttl(ttl: object) -> float | None:
        if ttl is None:
            return None
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
            raise ValueError("ttl must be a real number > 0")
        if ttl <= 0:
            raise ValueError("ttl must be a real number > 0")
        return float(ttl)

    def _now(self) -> float:
        return self._time_fn()

    def _is_expired(self, entry: _Entry, now: float) -> bool:
        return entry.expires_at is not None and now >= entry.expires_at

    def _purge_expired_locked(self) -> int:
        now = self._now()
        dead = [
            key
            for key, entry in self._data.items()
            if self._is_expired(entry, now)
        ]
        for key in dead:
            del self._data[key]
        n = len(dead)
        self._expirations += n
        return n

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default
            if self._is_expired(entry, self._now()):
                del self._data[key]
                self._expirations += 1
                self._misses += 1
                return default
            self._hits += 1
            self._data.move_to_end(key)
            return entry.value

    def set(self, key: Hashable, value: Any, ttl: float | None = _UNSET) -> None:  # type: ignore[assignment]
        with self._lock:
            if ttl is _UNSET:
                effective = self._default_ttl
            elif ttl is None:
                effective = None
            else:
                effective = self._validate_ttl(ttl)
            now = self._now()
            expires_at = None if effective is None else now + effective
            if key in self._data:
                self._data[key] = _Entry(value, expires_at)
                self._data.move_to_end(key)
                return
            # When full, drop expired entries first (count as expirations) so a
            # live LRU is not evicted if expired items already free a slot.
            if len(self._data) >= self._capacity:
                self._purge_expired_locked()
            if len(self._data) >= self._capacity:
                self._data.popitem(last=False)
                self._evictions += 1
            self._data[key] = _Entry(value, expires_at)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            if self._is_expired(entry, self._now()):
                del self._data[key]
                self._expirations += 1
                return False
            del self._data[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked()

    def keys(self) -> list:
        with self._lock:
            now = self._now()
            return [
                key
                for key, entry in reversed(self._data.items())
                if not self._is_expired(entry, now)
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
            entry = self._data.get(key)  # type: ignore[arg-type]
            if entry is None:
                return False
            if self._is_expired(entry, self._now()):
                del self._data[key]  # type: ignore[arg-type]
                self._expirations += 1
                return False
            return True
