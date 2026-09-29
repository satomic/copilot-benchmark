from __future__ import annotations

import heapq
import itertools
import numbers
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

from .stats import CacheStats

_MISSING = object()


def _validate_ttl(ttl: Any) -> float:
    # bool is technically an int subclass but is not a meaningful TTL; reject it.
    if isinstance(ttl, bool) or not isinstance(ttl, numbers.Real):
        raise ValueError(f"ttl must be a real number > 0 or None, got {ttl!r}")
    if not ttl > 0:  # also rejects NaN
        raise ValueError(f"ttl must be > 0, got {ttl!r}")
    return float(ttl)


class _Entry:
    __slots__ = ("value", "expires_at", "seq")

    def __init__(self, value: Any, expires_at: float | None, seq: int) -> None:
        self.value = value
        self.expires_at = expires_at
        self.seq = seq


class LRUCache:
    """Thread-safe LRU cache with optional per-entry TTL and lazy expiry.

    An OrderedDict keeps recency order (LRU at the front, MRU at the end).
    A min-heap of (expires_at, seq, key) lets ``set`` find already-expired
    entries when making room without scanning the whole cache. Heap records
    are invalidated lazily by comparing ``seq`` with the live entry.
    """

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
        if not callable(time_fn):
            raise TypeError("time_fn must be callable")
        self._capacity = capacity
        self._default_ttl = None if ttl is None else _validate_ttl(ttl)
        self._time_fn = time_fn
        self._data: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._heap: list[tuple[float, int, Hashable]] = []
        self._seq = itertools.count()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # -- internal helpers (caller must hold the lock) --------------------------

    @staticmethod
    def _is_expired(entry: _Entry, now: float) -> bool:
        return entry.expires_at is not None and now >= entry.expires_at

    def _remove_expired(self, key: Hashable) -> None:
        del self._data[key]
        self._expirations += 1

    def _drop_expired_from_heap(self, now: float) -> None:
        heap = self._heap
        while heap and heap[0][0] <= now:
            _, seq, key = heapq.heappop(heap)
            entry = self._data.get(key)
            if entry is not None and entry.seq == seq:
                self._remove_expired(key)

    def _rebuild_heap(self) -> None:
        self._heap = [
            (e.expires_at, e.seq, k)
            for k, e in self._data.items()
            if e.expires_at is not None
        ]
        heapq.heapify(self._heap)

    # -- public API ------------------------------------------------------------

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default
            if self._is_expired(entry, self._time_fn()):
                self._remove_expired(key)
                self._misses += 1
                return default
            self._data.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: Hashable, value: Any, ttl: Any = _MISSING) -> None:
        with self._lock:
            if ttl is _MISSING:
                effective_ttl = self._default_ttl
            elif ttl is None:
                effective_ttl = None
            else:
                effective_ttl = _validate_ttl(ttl)

            now = self._time_fn()
            if key in self._data:
                self._data.move_to_end(key)
            else:
                if len(self._data) >= self._capacity:
                    self._drop_expired_from_heap(now)
                if len(self._data) >= self._capacity:
                    self._data.popitem(last=False)
                    self._evictions += 1

            seq = next(self._seq)
            expires_at = None if effective_ttl is None else now + effective_ttl
            self._data[key] = _Entry(value, expires_at, seq)
            if expires_at is not None:
                heapq.heappush(self._heap, (expires_at, seq, key))
                # Compact stale heap records; amortised O(1) per set.
                if len(self._heap) > 2 * self._capacity + 16:
                    self._rebuild_heap()

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            if self._is_expired(entry, self._time_fn()):
                self._remove_expired(key)
                return False
            del self._data[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            now = self._time_fn()
            expired = [k for k, e in self._data.items() if self._is_expired(e, now)]
            for k in expired:
                self._remove_expired(k)
            self._rebuild_heap()
            return len(expired)

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                k for k, e in reversed(self._data.items())
                if not self._is_expired(e, now)
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
            try:
                entry = self._data.get(key)  # type: ignore[arg-type]
            except TypeError:  # unhashable key cannot be present
                return False
            if entry is None:
                return False
            if self._is_expired(entry, self._time_fn()):
                self._remove_expired(key)  # type: ignore[arg-type]
                return False
            return True
