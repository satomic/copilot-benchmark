from collections import OrderedDict
import heapq
import numbers
import threading
import time
from typing import Any, Callable, Hashable

from .stats import CacheStats


_DEFAULT_TTL = object()


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
        self._validate_ttl(ttl)
        if not callable(time_fn):
            raise TypeError("time_fn must be callable")

        self._capacity = capacity
        self._ttl = ttl
        self._time_fn = time_fn
        self._entries: OrderedDict[Hashable, tuple[Any, float | None, int]] = (
            OrderedDict()
        )
        self._expiry_heap: list[tuple[float, int, Hashable]] = []
        self._expiry_serial = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
        self._lock = threading.RLock()

    @staticmethod
    def _validate_ttl(ttl: float | None) -> None:
        if ttl is not None and (
            isinstance(ttl, bool) or not isinstance(ttl, numbers.Real) or not ttl > 0
        ):
            raise ValueError("ttl must be a positive real number or None")

    def _remove_expired_entry(self, key: Hashable) -> None:
        del self._entries[key]
        self._expirations += 1

    def _purge_expired_locked(self, now: float) -> int:
        removed = 0
        while self._expiry_heap and self._expiry_heap[0][0] <= now:
            deadline, serial, key = heapq.heappop(self._expiry_heap)
            entry = self._entries.get(key)
            if entry is None or entry[1] != deadline or entry[2] != serial:
                continue
            self._remove_expired_entry(key)
            removed += 1
        return removed

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return default
            if entry[1] is not None and self._time_fn() >= entry[1]:
                self._remove_expired_entry(key)
                self._misses += 1
                return default
            self._entries.move_to_end(key)
            self._hits += 1
            return entry[0]

    def set(
        self, key: Hashable, value: Any, ttl: float | None | object = _DEFAULT_TTL
    ) -> None:
        with self._lock:
            entry_ttl = self._ttl if ttl is _DEFAULT_TTL else ttl
            self._validate_ttl(entry_ttl)
            now = self._time_fn()

            if key in self._entries:
                del self._entries[key]
            else:
                self._purge_expired_locked(now)
                if len(self._entries) >= self._capacity:
                    self._entries.popitem(last=False)
                    self._evictions += 1

            deadline = None if entry_ttl is None else now + entry_ttl
            self._expiry_serial += 1
            serial = self._expiry_serial
            self._entries[key] = (value, deadline, serial)
            self._entries.move_to_end(key)
            if deadline is not None:
                heapq.heappush(self._expiry_heap, (deadline, serial, key))

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if entry[1] is not None and self._time_fn() >= entry[1]:
                self._remove_expired_entry(key)
                return False
            del self._entries[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._expiry_heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked(self._time_fn())

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                key
                for key, entry in reversed(self._entries.items())
                if entry[1] is None or now < entry[1]
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
            if entry[1] is not None and self._time_fn() >= entry[1]:
                self._remove_expired_entry(key)  # type: ignore[arg-type]
                return False
            return True
