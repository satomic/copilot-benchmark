from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import heapq
import math
import threading
import time
from typing import Any, Callable, Hashable

from cache.stats import CacheStats

_DEFAULT_TTL = object()


@dataclass
class _Entry:
    value: Any
    expire_at: float | None
    entry_id: int


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
            if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or math.isnan(ttl) or math.isinf(ttl) or ttl <= 0:
                raise ValueError("ttl must be a real number > 0")
            self._default_ttl: float | None = float(ttl)
        else:
            self._default_ttl = None

        if not callable(time_fn):
            raise TypeError("time_fn must be callable")
        self._time_fn = time_fn

        self._capacity = capacity
        self._cache: OrderedDict[Any, _Entry] = OrderedDict()
        self._expiry_heap: list[tuple[float, int, Any]] = []
        self._entry_seq = 0
        self._lock = threading.RLock()

        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def _drop_expired_heap(self, now: float) -> None:
        while self._expiry_heap and self._expiry_heap[0][0] <= now:
            expire_at, entry_id, k = heapq.heappop(self._expiry_heap)
            node = self._cache.get(k)
            if node is not None and node.entry_id == entry_id:
                del self._cache[k]
                self._expirations += 1

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return default
            node = self._cache[key]
            now = self._time_fn()
            if node.expire_at is not None and now >= node.expire_at:
                del self._cache[key]
                self._expirations += 1
                self._misses += 1
                return default
            self._hits += 1
            self._cache.move_to_end(key, last=True)
            return node.value

    def set(self, key: Hashable, value: Any, ttl: float | None = _DEFAULT_TTL) -> None:
        with self._lock:
            now = self._time_fn()
            if ttl is _DEFAULT_TTL:
                entry_ttl = self._default_ttl
            elif ttl is None:
                entry_ttl = None
            else:
                if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or math.isnan(ttl) or math.isinf(ttl) or ttl <= 0:
                    raise ValueError("ttl must be a number > 0")
                entry_ttl = float(ttl)

            expire_at = (now + entry_ttl) if entry_ttl is not None else None
            self._entry_seq += 1
            entry_id = self._entry_seq

            if key in self._cache:
                self._cache[key] = _Entry(value, expire_at, entry_id)
                self._cache.move_to_end(key, last=True)
            else:
                if len(self._cache) >= self._capacity:
                    self._drop_expired_heap(now)
                    if len(self._cache) >= self._capacity:
                        self._cache.popitem(last=False)
                        self._evictions += 1
                self._cache[key] = _Entry(value, expire_at, entry_id)

            if expire_at is not None:
                heapq.heappush(self._expiry_heap, (expire_at, entry_id, key))

            if len(self._expiry_heap) > max(16, 4 * self._capacity):
                self._expiry_heap = [
                    (node.expire_at, node.entry_id, k)
                    for k, node in self._cache.items()
                    if node.expire_at is not None
                ]
                heapq.heapify(self._expiry_heap)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            if key not in self._cache:
                return False
            node = self._cache[key]
            now = self._time_fn()
            if node.expire_at is not None and now >= node.expire_at:
                del self._cache[key]
                self._expirations += 1
                return False
            del self._cache[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._expiry_heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            now = self._time_fn()
            count = 0
            expired_keys = [
                k for k, node in self._cache.items()
                if node.expire_at is not None and now >= node.expire_at
            ]
            for k in expired_keys:
                del self._cache[k]
                count += 1
            self._expirations += count
            self._expiry_heap = [
                (node.expire_at, node.entry_id, k)
                for k, node in self._cache.items()
                if node.expire_at is not None
            ]
            heapq.heapify(self._expiry_heap)
            return count

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                k for k in reversed(self._cache)
                if self._cache[k].expire_at is None or now < self._cache[k].expire_at
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
            return len(self._cache)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            if key not in self._cache:
                return False
            node = self._cache[key]
            now = self._time_fn()
            if node.expire_at is not None and now >= node.expire_at:
                del self._cache[key]
                self._expirations += 1
                return False
            return True
