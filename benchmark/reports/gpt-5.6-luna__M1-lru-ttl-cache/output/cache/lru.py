from collections import OrderedDict
from dataclasses import dataclass
import heapq
import numbers
import threading
import time
from typing import Any, Callable, Hashable

from .stats import CacheStats


_DEFAULT = object()


@dataclass
class _Entry:
    value: Any
    expires_at: float | None
    token: int


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
        self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._expiry_heap: list[tuple[float, int, Hashable]] = []
        self._next_token = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
        self._lock = threading.RLock()

    @staticmethod
    def _validate_ttl(ttl: float | None) -> None:
        if ttl is not None and (
            isinstance(ttl, bool) or not isinstance(ttl, numbers.Real) or ttl <= 0
        ):
            raise ValueError("ttl must be a real number greater than zero or None")

    def _remove_expired_locked(self, now: float) -> int:
        removed = 0
        while self._expiry_heap and self._expiry_heap[0][0] <= now:
            deadline, token, key = heapq.heappop(self._expiry_heap)
            entry = self._entries.get(key)
            if entry is not None and entry.token == token and entry.expires_at == deadline:
                del self._entries[key]
                removed += 1
        self._expirations += removed
        return removed

    def _expiry_for(self, ttl: float | None, now: float) -> float | None:
        return None if ttl is None else now + ttl

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return default
            if entry.expires_at is not None and self._time_fn() >= entry.expires_at:
                del self._entries[key]
                self._expirations += 1
                self._misses += 1
                return default
            self._entries.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: Hashable, value: Any, ttl: float | None | object = _DEFAULT) -> None:
        with self._lock:
            if ttl is not _DEFAULT:
                self._validate_ttl(ttl)  # type: ignore[arg-type]
                entry_ttl = ttl
            else:
                entry_ttl = self._ttl

            now = self._time_fn()
            expires_at = self._expiry_for(entry_ttl, now)  # type: ignore[arg-type]
            self._next_token += 1
            entry = _Entry(value, expires_at, self._next_token)
            if key in self._entries:
                self._entries[key] = entry
                self._entries.move_to_end(key)
            else:
                if len(self._entries) >= self._capacity:
                    self._remove_expired_locked(now)
                if len(self._entries) >= self._capacity:
                    self._entries.popitem(last=False)
                    self._evictions += 1
                self._entries[key] = entry
            if expires_at is not None:
                heapq.heappush(self._expiry_heap, (expires_at, entry.token, key))

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if entry.expires_at is not None and self._time_fn() >= entry.expires_at:
                del self._entries[key]
                self._expirations += 1
                return False
            del self._entries[key]
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._expiry_heap.clear()

    def purge_expired(self) -> int:
        with self._lock:
            return self._remove_expired_locked(self._time_fn())

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                key
                for key, entry in reversed(self._entries.items())
                if entry.expires_at is None or now < entry.expires_at
            ]

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(self._hits, self._misses, self._evictions, self._expirations)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if entry.expires_at is not None and self._time_fn() >= entry.expires_at:
                del self._entries[key]  # type: ignore[arg-type]
                self._expirations += 1
                return False
            return True
