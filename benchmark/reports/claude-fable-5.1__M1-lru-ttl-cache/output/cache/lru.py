from __future__ import annotations

import heapq
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

from .stats import CacheStats

# Sentinel distinguishing "ttl argument omitted" from an explicit ``ttl=None``.
_MISSING = object()


class LRUCache:
    """Thread-safe LRU cache with lazy per-entry time-to-live.

    Entries live in an ``OrderedDict`` (least recently used first, most recently
    used last) mapped to ``[value, expires_at]`` where ``expires_at`` is ``None``
    for entries that never expire.

    An expiry min-heap of ``(expires_at, seq, key)`` lets ``set`` drop already-expired
    entries when the cache is full without scanning every entry. Heap items may
    be stale (the key was deleted or re-set with a different deadline); they are
    validated against the live entry when popped and discarded otherwise. The
    heap is rebuilt whenever it grows past twice the number of entries, keeping
    the per-operation cost amortised constant.
    """

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
            self._validate_ttl(ttl)
        if not callable(time_fn):
            raise TypeError("time_fn must be callable")

        self._capacity = capacity
        self._default_ttl = ttl
        self._time_fn = time_fn
        self._lock = threading.RLock()
        self._data: OrderedDict[Hashable, list] = OrderedDict()
        # (expires_at, seq, key); seq breaks ties so keys are never compared.
        self._expiry_heap: list[tuple[float, int, Hashable]] = []
        self._seq = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _validate_ttl(ttl: Any) -> None:
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
            raise ValueError("ttl must be a real number > 0")
        if not ttl > 0:  # also rejects NaN
            raise ValueError("ttl must be a real number > 0")

    def _is_expired(self, entry: list, now: float) -> bool:
        expires_at = entry[1]
        return expires_at is not None and now >= expires_at

    def _expire(self, key: Hashable) -> None:
        del self._data[key]
        self._expirations += 1

    def _pop_expired_from_heap(self, now: float) -> int:
        """Remove every entry whose deadline has passed; returns count removed."""
        removed = 0
        heap = self._expiry_heap
        while heap and heap[0][0] <= now:
            expires_at, _, key = heapq.heappop(heap)
            entry = self._data.get(key)
            # Skip stale heap items: key gone or deadline was replaced by a set().
            if entry is not None and entry[1] == expires_at:
                self._expire(key)
                removed += 1
        return removed

    def _push_heap(self, expires_at: float, key: Hashable) -> None:
        self._seq += 1
        heapq.heappush(self._expiry_heap, (expires_at, self._seq, key))

    def _rebuild_heap(self) -> None:
        self._expiry_heap = []
        for key, entry in self._data.items():
            if entry[1] is not None:
                self._seq += 1
                self._expiry_heap.append((entry[1], self._seq, key))
        heapq.heapify(self._expiry_heap)

    def _maybe_compact_heap(self) -> None:
        if len(self._expiry_heap) > 2 * len(self._data) + 16:
            self._rebuild_heap()

    # ------------------------------------------------------------------ public

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default
            if self._is_expired(entry, self._time_fn()):
                self._expire(key)
                self._misses += 1
                return default
            self._data.move_to_end(key)
            self._hits += 1
            return entry[0]

    def set(self, key: Hashable, value: Any, ttl: float | None = _MISSING) -> None:
        if ttl is _MISSING:
            ttl = self._default_ttl
        elif ttl is not None:
            self._validate_ttl(ttl)

        with self._lock:
            now = self._time_fn()
            expires_at = None if ttl is None else now + ttl

            if key in self._data:
                entry = self._data[key]
                entry[0] = value
                entry[1] = expires_at
                self._data.move_to_end(key)
            else:
                if len(self._data) >= self._capacity:
                    self._pop_expired_from_heap(now)
                if len(self._data) >= self._capacity:
                    self._data.popitem(last=False)
                    self._evictions += 1
                self._data[key] = [value, expires_at]

            if expires_at is not None:
                self._push_heap(expires_at, key)
                self._maybe_compact_heap()

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            if self._is_expired(entry, self._time_fn()):
                self._expire(key)
                return False
            del self._data[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._expiry_heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            now = self._time_fn()
            expired = [k for k, e in self._data.items() if self._is_expired(e, now)]
            for k in expired:
                self._expire(k)
            # Rebuild the heap so stale items do not accumulate.
            self._rebuild_heap()
            return len(expired)

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                k for k, e in reversed(self._data.items()) if not self._is_expired(e, now)
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
            if self._is_expired(entry, self._time_fn()):
                self._expire(key)
                return False
            return True
