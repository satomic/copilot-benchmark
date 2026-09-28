from __future__ import annotations

import heapq
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

from .stats import CacheStats

# Omitted set(ttl=...) uses the cache default; explicit None never expires.
_UNSET = object()


class _Node:
    __slots__ = ("value", "expires_at", "gen")

    def __init__(self, value: Any, expires_at: float | None, gen: int) -> None:
        self.value = value
        self.expires_at = expires_at
        self.gen = gen


def _require_ttl(ttl: object) -> float:
    # bool is an int subclass, but not a duration. Invalid ttl is ValueError
    # (TypeError is only specified for a non-int capacity).
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not (ttl > 0):
        raise ValueError("ttl must be a real number > 0")
    return float(ttl)


def _is_expired(node: _Node, now: float) -> bool:
    return node.expires_at is not None and now >= node.expires_at


class LRUCache:
    """Size-bounded LRU cache with per-entry TTL.

    Time comes only from ``time_fn``. Expiry is lazy (no background threads).
    When a new key needs a free slot, every already-expired entry is dropped
    first (counted as expirations). The LRU live entry is evicted only if the
    cache is still full. Soonest-expiry order is a heap so ``get``/``set`` do
    not scan live entries.
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
            ttl = _require_ttl(ttl)
        self._capacity = capacity
        self._default_ttl = ttl
        self._time_fn = time_fn
        self._data: OrderedDict[Hashable, _Node] = OrderedDict()
        # (expires_at, gen, key). gen breaks ties so keys are never compared.
        self._heap: list[tuple[float, int, Hashable]] = []
        self._gen = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
        self._lock = threading.RLock()

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            node = self._data.get(key)
            if node is None:
                self._misses += 1
                return default
            now = self._time_fn()
            if _is_expired(node, now):
                del self._data[key]
                self._expirations += 1
                self._misses += 1
                return default
            self._data.move_to_end(key)
            self._hits += 1
            return node.value

    def set(self, key: Hashable, value: Any, ttl: float | None = _UNSET) -> None:
        with self._lock:
            if ttl is _UNSET:
                resolved: float | None = self._default_ttl
            elif ttl is None:
                resolved = None
            else:
                resolved = _require_ttl(ttl)
            now = self._time_fn()
            expires_at = None if resolved is None else now + resolved
            existing = self._data.get(key)
            if existing is None and len(self._data) >= self._capacity:
                # New key at capacity: expired victims first, then LRU.
                self._drop_expired(now)
                if len(self._data) >= self._capacity:
                    self._data.popitem(last=False)
                    self._evictions += 1
            gen = self._next_gen()
            if existing is None:
                self._data[key] = _Node(value, expires_at, gen)
            else:
                # Resident key, even if already expired: reuse the slot.
                # Not an expiry observation, so expirations are unchanged.
                existing.value = value
                existing.expires_at = expires_at
                existing.gen = gen
                self._data.move_to_end(key)
            if expires_at is not None:
                heapq.heappush(self._heap, (expires_at, gen, key))
            self._compact_heap()

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            node = self._data.get(key)
            if node is None:
                return False
            now = self._time_fn()
            if _is_expired(node, now):
                del self._data[key]
                self._expirations += 1
                return False
            del self._data[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            return self._drop_expired(self._time_fn())

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            # End of the OrderedDict is most recently used.
            return [
                key
                for key, node in reversed(self._data.items())
                if not _is_expired(node, now)
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
            node = self._data.get(key)
            if node is None:
                return False
            now = self._time_fn()
            if _is_expired(node, now):
                del self._data[key]
                self._expirations += 1
                return False
            return True

    def _next_gen(self) -> int:
        self._gen += 1
        return self._gen

    def _drop_expired(self, now: float) -> int:
        """Remove every entry already expired at ``now``. Does not scan live ones."""
        removed = 0
        heap = self._heap
        data = self._data
        while heap:
            expires_at, gen, key = heap[0]
            if expires_at > now:
                break
            heapq.heappop(heap)
            node = data.get(key)
            if node is None or node.gen != gen:
                continue
            del data[key]
            self._expirations += 1
            removed += 1
        return removed

    def _compact_heap(self) -> None:
        # Updates push a new heap record and leave the old one stale.
        if len(self._heap) <= (len(self._data) << 1) + 8:
            return
        rebuilt = [
            (node.expires_at, node.gen, key)
            for key, node in self._data.items()
            if node.expires_at is not None
        ]
        heapq.heapify(rebuilt)
        self._heap = rebuilt
