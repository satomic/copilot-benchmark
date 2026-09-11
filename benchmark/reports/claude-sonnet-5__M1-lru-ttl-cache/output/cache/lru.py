"""A thread-safe, size-bounded LRU cache with per-entry time-to-live (TTL)."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

from .stats import CacheStats

# Sentinel used to distinguish "ttl argument omitted" (use the cache's default
# ttl) from "ttl=None" explicitly passed (this entry never expires).
_MISSING = object()


class LRUCache:
    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError("capacity must be an int")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")

        if ttl is not None:
            if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
                raise ValueError("ttl must be a real number > 0 or None")

        self._capacity = capacity
        self._default_ttl = ttl
        self._time_fn = time_fn

        # key -> (value, expire_at). expire_at is None for entries that never
        # expire, otherwise an absolute time_fn() timestamp.
        self._data: "OrderedDict[Hashable, tuple[Any, float | None]]" = OrderedDict()

        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

        self._lock = threading.RLock()

    @staticmethod
    def _validate_entry_ttl(ttl: float) -> None:
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
            raise ValueError("ttl must be a real number > 0")

    def _is_expired(self, expire_at: float | None, now: float) -> bool:
        return expire_at is not None and now >= expire_at

    def _make_room(self) -> None:
        # Called only when inserting a brand-new key while at capacity.
        # Preference: drop already-expired entries (as expirations) before
        # evicting a live LRU entry. Each iteration removes exactly one entry,
        # and every entry is only ever removed once, so this loop is
        # amortised O(1) across the cache's lifetime even though a single
        # call may inspect a few already-doomed entries.
        while len(self._data) >= self._capacity:
            old_key, (_, expire_at) = next(iter(self._data.items()))
            now = self._time_fn()
            if self._is_expired(expire_at, now):
                del self._data[old_key]
                self._expirations += 1
                continue
            del self._data[old_key]
            self._evictions += 1
            break

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default

            value, expire_at = entry
            now = self._time_fn()
            if self._is_expired(expire_at, now):
                del self._data[key]
                self._expirations += 1
                self._misses += 1
                return default

            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: Hashable, value: Any, ttl: float | None = _MISSING) -> None:
        with self._lock:
            if ttl is _MISSING:
                effective_ttl = self._default_ttl
            elif ttl is None:
                effective_ttl = None
            else:
                self._validate_entry_ttl(ttl)
                effective_ttl = ttl

            now = self._time_fn()
            expire_at = None if effective_ttl is None else now + effective_ttl

            if key in self._data:
                del self._data[key]
            else:
                self._make_room()

            self._data[key] = (value, expire_at)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False

            _, expire_at = entry
            now = self._time_fn()
            if self._is_expired(expire_at, now):
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
            now = self._time_fn()
            expired_keys = [
                key
                for key, (_, expire_at) in self._data.items()
                if self._is_expired(expire_at, now)
            ]
            for key in expired_keys:
                del self._data[key]
            self._expirations += len(expired_keys)
            return len(expired_keys)

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                key
                for key, (_, expire_at) in reversed(list(self._data.items()))
                if not self._is_expired(expire_at, now)
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

            _, expire_at = entry
            now = self._time_fn()
            if self._is_expired(expire_at, now):
                del self._data[key]
                self._expirations += 1
                return False

            return True
