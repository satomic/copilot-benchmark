import heapq
import math
import threading
import time
from collections import OrderedDict
from numbers import Real
from typing import Any, Callable, Hashable

from .stats import CacheStats

_DEFAULT = object()


def _check_ttl(ttl: Any) -> None:
    # bool is rejected as a non-number; NaN is rejected too.
    if isinstance(ttl, bool) or not isinstance(ttl, Real) or math.isnan(ttl) or ttl <= 0:
        raise ValueError(f"ttl must be a real number > 0, got {ttl!r}")


class LRUCache:
    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool):
            raise TypeError("capacity must be an int")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if ttl is not None:
            _check_ttl(ttl)
        self._capacity = capacity
        self._ttl = ttl
        self._time = time_fn
        self._lock = threading.RLock()
        # key -> (value, deadline or None, seq); ordered LRU -> MRU
        self._data: OrderedDict = OrderedDict()
        # min-heap of (deadline, seq, key); stale items are skipped lazily
        self._heap: list = []
        self._seq = 0
        self._hits = self._misses = self._evictions = self._expirations = 0

    def _drop_expired(self, now: float) -> int:
        """Remove all expired entries using the deadline heap; returns count."""
        removed = 0
        heap = self._heap
        while heap and heap[0][0] <= now:
            _, seq, key = heapq.heappop(heap)
            item = self._data.get(key)
            if item is not None and item[2] == seq:
                del self._data[key]
                removed += 1
        self._expirations += removed
        return removed

    def _remove_if_expired(self, key: Hashable, now: float) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        if item[1] is not None and now >= item[1]:
            del self._data[key]
            self._expirations += 1
            return True
        return False

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return default
            if self._remove_if_expired(key, self._time()):
                self._misses += 1
                return default
            self._data.move_to_end(key)
            self._hits += 1
            return item[0]

    def set(self, key: Hashable, value: Any, ttl: Any = _DEFAULT) -> None:
        with self._lock:
            if ttl is _DEFAULT:
                ttl = self._ttl
            elif ttl is not None:
                _check_ttl(ttl)
            now = self._time()
            if key not in self._data and len(self._data) >= self._capacity:
                self._drop_expired(now)
                if len(self._data) >= self._capacity:
                    self._data.popitem(last=False)
                    self._evictions += 1
            deadline = None if ttl is None else now + ttl
            self._seq += 1
            self._data[key] = (value, deadline, self._seq)
            self._data.move_to_end(key)
            if deadline is not None:
                heapq.heappush(self._heap, (deadline, self._seq, key))
                if len(self._heap) > 2 * self._capacity + 16:
                    self._heap = [
                        (d, s, k) for k, (_, d, s) in self._data.items() if d is not None
                    ]
                    heapq.heapify(self._heap)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            if key not in self._data:
                return False
            if self._remove_if_expired(key, self._time()):
                return False
            del self._data[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            return self._drop_expired(self._time())

    def keys(self) -> list:
        with self._lock:
            now = self._time()
            return [
                k
                for k, (_, d, _s) in reversed(self._data.items())
                if d is None or now < d
            ]

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                self._hits, self._misses, self._evictions, self._expirations
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            if key not in self._data:
                return False
            return not self._remove_if_expired(key, self._time())
