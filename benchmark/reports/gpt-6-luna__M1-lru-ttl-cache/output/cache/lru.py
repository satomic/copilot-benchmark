import heapq
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from numbers import Real
from typing import Any, Callable, Hashable

from .stats import CacheStats

_DEFAULT_TTL = object()


@dataclass
class _Entry:
    value: Any
    deadline: float | None
    version: int


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
            raise ValueError("capacity must be at least 1")
        ttl = self._validated_ttl(ttl)
        if not callable(time_fn):
            raise TypeError("time_fn must be callable")

        self._capacity = capacity
        self._ttl = ttl
        self._time_fn = time_fn
        self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._expiry_heap: list[tuple[float, int, Hashable]] = []
        self._version = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
        self._lock = threading.RLock()

    @staticmethod
    def _validated_ttl(ttl: object) -> Real | None:
        if ttl is None:
            return None
        if isinstance(ttl, bool) or not isinstance(ttl, Real):
            raise ValueError("ttl must be a positive real number or None")
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("ttl must be a positive finite number or None")
        return ttl

    def _add_entry(self, key: Hashable, value: Any, ttl: float | None, now: float) -> None:
        self._version += 1
        deadline = None if ttl is None else now + ttl
        self._entries[key] = _Entry(value, deadline, self._version)
        self._entries.move_to_end(key)
        if deadline is not None:
            heapq.heappush(self._expiry_heap, (deadline, self._version, key))

    def _purge_expired(self, now: float) -> int:
        removed = 0
        while self._expiry_heap and self._expiry_heap[0][0] <= now:
            deadline, version, key = heapq.heappop(self._expiry_heap)
            entry = self._entries.get(key)
            if entry is not None and entry.version == version and entry.deadline == deadline:
                del self._entries[key]
                removed += 1
        self._expirations += removed
        return removed

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return default

            now = self._time_fn()
            if entry.deadline is not None and now >= entry.deadline:
                del self._entries[key]
                self._expirations += 1
                self._misses += 1
                return default

            self._entries.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None | object = _DEFAULT_TTL,
    ) -> None:
        with self._lock:
            effective_ttl = self._ttl if ttl is _DEFAULT_TTL else ttl
            effective_ttl = self._validated_ttl(effective_ttl)
            now = self._time_fn()

            if key not in self._entries and len(self._entries) >= self._capacity:
                self._purge_expired(now)
                if len(self._entries) >= self._capacity:
                    self._entries.popitem(last=False)
                    self._evictions += 1

            self._add_entry(key, value, effective_ttl, now)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            now = self._time_fn()
            del self._entries[key]
            if entry.deadline is not None and now >= entry.deadline:
                self._expirations += 1
                return False
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._expiry_heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired(self._time_fn())

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                key
                for key, entry in reversed(self._entries.items())
                if entry.deadline is None or now < entry.deadline
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
            return len(self._entries)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            now = self._time_fn()
            if entry.deadline is not None and now >= entry.deadline:
                del self._entries[key]
                self._expirations += 1
                return False
            return True
