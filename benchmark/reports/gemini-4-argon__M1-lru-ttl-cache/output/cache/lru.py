from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
import heapq
import math
import numbers
import threading
import time
from typing import Any

from .stats import CacheStats

_UNSET: Any = object()


def _validate_ttl(ttl: Any) -> float | None:
    if ttl is None:
        return None
    if isinstance(ttl, bool) or not isinstance(ttl, numbers.Real):
        raise ValueError("ttl must be a real number > 0")
    val = float(ttl)
    if not math.isfinite(val) or val <= 0.0:
        raise ValueError("ttl must be > 0")
    return val


class _Entry:
    __slots__ = ("value", "expires_at", "seq")

    def __init__(self, value: Any, expires_at: float | None, seq: int) -> None:
        self.value = value
        self.expires_at = expires_at
        self.seq = seq


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
        if not callable(time_fn):
            raise TypeError("time_fn must be callable")

        self._capacity: int = capacity
        self._default_ttl: float | None = _validate_ttl(ttl)
        self._time_fn: Callable[[], float] = time_fn
        self._lock = threading.RLock()

        # OrderedDict from LRU (front) to MRU (back).
        self._data: OrderedDict[Hashable, _Entry] = OrderedDict()
        # Min-heap of (expires_at, seq, key) for O(1) amortised expiry checks when full.
        self._expiry_heap: list[tuple[float, int, Hashable]] = []
        self._seq: int = 0

        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0
        self._expirations: int = 0

    def _drop_expired_at(self, now: float) -> int:
        removed = 0
        heap = self._expiry_heap
        data = self._data
        while heap and heap[0][0] <= now:
            _, seq, key = heapq.heappop(heap)
            entry = data.get(key)
            if entry is not None and entry.seq == seq:
                del data[key]
                self._expirations += 1
                removed += 1
        return removed

    def _compact_heap_if_needed(self) -> None:
        if len(self._expiry_heap) > max(64, 4 * self._capacity):
            new_heap: list[tuple[float, int, Hashable]] = [
                (entry.expires_at, entry.seq, k)
                for k, entry in self._data.items()
                if entry.expires_at is not None
            ]
            heapq.heapify(new_heap)
            self._expiry_heap = new_heap

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default

            if entry.expires_at is not None and self._time_fn() >= entry.expires_at:
                del self._data[key]
                self._expirations += 1
                self._misses += 1
                return default

            self._data.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: Hashable, value: Any, ttl: float | None = _UNSET) -> None:
        with self._lock:
            if ttl is _UNSET:
                effective_ttl = self._default_ttl
            else:
                effective_ttl = _validate_ttl(ttl)

            is_existing = key in self._data
            now = self._time_fn()

            if not is_existing and len(self._data) >= self._capacity:
                self._drop_expired_at(now)
                if len(self._data) >= self._capacity:
                    self._data.popitem(last=False)
                    self._evictions += 1

            self._seq += 1
            seq = self._seq
            expires_at = (now + effective_ttl) if effective_ttl is not None else None
            self._data[key] = _Entry(value=value, expires_at=expires_at, seq=seq)
            if is_existing:
                self._data.move_to_end(key)

            if expires_at is not None:
                heapq.heappush(self._expiry_heap, (expires_at, seq, key))
                self._compact_heap_if_needed()

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._data.pop(key, None)
            if entry is None:
                return False
            if entry.expires_at is not None and self._time_fn() >= entry.expires_at:
                self._expirations += 1
                return False
            return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._expiry_heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            now = self._time_fn()
            return self._drop_expired_at(now)

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                k
                for k, entry in reversed(self._data.items())
                if entry.expires_at is None or now < entry.expires_at
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
            if entry.expires_at is not None and self._time_fn() >= entry.expires_at:
                del self._data[key]
                self._expirations += 1
                return False
            return True
