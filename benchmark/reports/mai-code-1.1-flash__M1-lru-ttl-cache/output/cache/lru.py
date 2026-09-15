from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from numbers import Real
from typing import Any, Callable, Hashable

from .stats import CacheStats

_MISSING = object()


class LRUCache:
    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(capacity, bool) or type(capacity) is not int:
            raise TypeError("capacity must be an int")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if ttl is not None:
            if isinstance(ttl, bool) or not isinstance(ttl, Real):
                raise ValueError("ttl must be a positive real number or None")
            ttl_value = float(ttl)
            if not math.isfinite(ttl_value) or ttl_value <= 0:
                raise ValueError("ttl must be a positive real number or None")
            ttl = ttl_value
        if not callable(time_fn):
            raise TypeError("time_fn must be callable")

        self._capacity = capacity
        self._default_ttl = ttl
        self._time_fn = time_fn
        self._entries: OrderedDict[Hashable, dict[str, Any]] = OrderedDict()
        self._stats = CacheStats()
        self._lock = threading.RLock()

    def _record_stats(self, *, hits: int = 0, misses: int = 0, evictions: int = 0, expirations: int = 0) -> None:
        self._stats = CacheStats(
            hits=self._stats.hits + hits,
            misses=self._stats.misses + misses,
            evictions=self._stats.evictions + evictions,
            expirations=self._stats.expirations + expirations,
        )

    def _now(self) -> float:
        return float(self._time_fn())

    @staticmethod
    def _validate_ttl(value: Any, *, allow_none: bool) -> float | None:
        if value is None:
            if allow_none:
                return None
            raise ValueError("ttl must be a positive real number or None")
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("ttl must be a positive real number or None")
        value_float = float(value)
        if not math.isfinite(value_float) or value_float <= 0:
            raise ValueError("ttl must be a positive real number or None")
        return value_float

    def _expires_at(self, ttl: float | None) -> float | None:
        if ttl is None:
            return None
        return self._now() + ttl

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and self._now() >= expires_at

    def _purge_expired_locked(self) -> int:
        expired_keys = [key for key, entry in list(self._entries.items()) if self._is_expired(entry)]
        for key in expired_keys:
            del self._entries[key]
        if expired_keys:
            self._record_stats(expirations=len(expired_keys))
        return len(expired_keys)

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._record_stats(misses=1)
                return default
            if self._is_expired(entry):
                del self._entries[key]
                self._record_stats(expirations=1, misses=1)
                return default
            self._entries.move_to_end(key)
            self._record_stats(hits=1)
            return entry["value"]

    def set(self, key: Hashable, value: Any, ttl: float | None = _MISSING) -> None:
        with self._lock:
            if ttl is _MISSING:
                ttl = self._default_ttl
            elif ttl is not None:
                ttl = self._validate_ttl(ttl, allow_none=False)
            else:
                ttl = None

            if key in self._entries and self._is_expired(self._entries[key]):
                del self._entries[key]
                self._record_stats(expirations=1)

            if key in self._entries:
                self._entries[key] = {"value": value, "expires_at": self._expires_at(ttl)}
                self._entries.move_to_end(key)
                return

            if len(self._entries) >= self._capacity:
                self._purge_expired_locked()
                if len(self._entries) >= self._capacity:
                    self._entries.popitem(last=False)
                    self._record_stats(evictions=1)

            self._entries[key] = {"value": value, "expires_at": self._expires_at(ttl)}

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if self._is_expired(entry):
                del self._entries[key]
                self._record_stats(expirations=1)
                return False
            del self._entries[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked()

    def keys(self) -> list:
        with self._lock:
            return [
                key
                for key in reversed(list(self._entries.keys()))
                if not self._is_expired(self._entries[key])
            ]

    def stats(self) -> CacheStats:
        with self._lock:
            return self._stats

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if self._is_expired(entry):
                del self._entries[key]
                self._record_stats(expirations=1)
                return False
            return True
