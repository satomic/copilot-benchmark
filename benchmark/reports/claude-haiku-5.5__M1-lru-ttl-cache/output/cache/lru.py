import heapq
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, Optional

from .stats import CacheStats

_DEFAULT = object()  # sentinel: "ttl argument omitted" (distinct from ttl=None)


def _validate_ttl(ttl: Any) -> Optional[float]:
    if ttl is None:
        return None
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not ttl > 0:
        raise ValueError(f"ttl must be a number > 0 or None, got {ttl!r}")
    return ttl


class _Entry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, expires_at: Optional[float]) -> None:
        self.value = value
        self.expires_at = expires_at

    def is_expired(self, now: float) -> bool:
        # Exactly at the deadline the entry is already expired.
        return self.expires_at is not None and now >= self.expires_at


class LRUCache:
    """Thread-safe LRU cache with per-entry TTL and lazy expiry.

    Expiry bookkeeping uses a min-heap keyed by deadline, so finding expired
    entries when room is needed does not scan the whole cache. Heap items
    become stale when their entry is replaced or removed; they are skipped
    on pop, and the heap is rebuilt when stale items dominate.
    """

    def __init__(
        self,
        capacity: int,
        ttl: Optional[float] = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError("capacity must be an int")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._ttl = _validate_ttl(ttl)
        self._time_fn = time_fn
        self._lock = threading.RLock()
        # Order: least recently used first, most recently used last.
        self._data: "OrderedDict[Hashable, _Entry]" = OrderedDict()
        # Heap of (expires_at, seq, key, entry); seq is unique so entries are never compared.
        self._heap: list = []
        self._seq = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # ----- internal helpers (caller must hold the lock) -----

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _push_deadline(self, key: Hashable, entry: _Entry) -> None:
        heapq.heappush(self._heap, (entry.expires_at, self._next_seq(), key, entry))
        if len(self._heap) > 2 * len(self._data) + 64:
            self._heap = [
                (e.expires_at, self._next_seq(), k, e)
                for k, e in self._data.items()
                if e.expires_at is not None
            ]
            heapq.heapify(self._heap)

    def _drop_expired(self, now: float) -> int:
        removed = 0
        heap = self._heap
        while heap and heap[0][0] <= now:
            _, _, key, entry = heapq.heappop(heap)
            if self._data.get(key) is entry:  # skip stale heap items
                del self._data[key]
                self._expirations += 1
                removed += 1
        return removed

    def _remove_if_expired(self, key: Hashable, now: float) -> bool:
        entry = self._data.get(key)
        if entry is not None and entry.is_expired(now):
            del self._data[key]
            self._expirations += 1
            return True
        return False

    # ----- public API -----

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            now = self._time_fn()
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default
            if entry.is_expired(now):
                del self._data[key]
                self._expirations += 1
                self._misses += 1
                return default
            self._data.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: Hashable, value: Any, ttl: Optional[float] = _DEFAULT) -> None:  # type: ignore[assignment]
        effective = self._ttl if ttl is _DEFAULT else _validate_ttl(ttl)
        with self._lock:
            now = self._time_fn()
            if key in self._data:
                del self._data[key]  # replace in place; old heap item becomes stale
            elif len(self._data) >= self._capacity:
                # Expired entries make room first; only then evict LRU entries.
                self._drop_expired(now)
                while len(self._data) >= self._capacity:
                    self._data.popitem(last=False)
                    self._evictions += 1
            expires_at = None if effective is None else now + effective
            entry = _Entry(value, expires_at)
            self._data[key] = entry
            if expires_at is not None:
                self._push_deadline(key, entry)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            now = self._time_fn()
            if key not in self._data:
                return False
            if self._remove_if_expired(key, now):
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
            return [k for k, e in reversed(self._data.items()) if not e.is_expired(now)]

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
            now = self._time_fn()
            if key not in self._data:
                return False
            return not self._remove_if_expired(key, now)
