import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

from .stats import CacheStats

# Sentinel object to distinguish between set(key, value) and set(key, value, ttl=None)
_UNSET_TTL = object()


class LRUCache:
    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        # Validate capacity
        if not isinstance(capacity, int) or isinstance(capacity, bool):
            raise TypeError("capacity must be an int")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")

        # Validate default ttl
        if ttl is not None:
            if not isinstance(ttl, (int, float)) or isinstance(ttl, bool):
                raise ValueError("ttl must be a positive number or None")
            if ttl <= 0:
                raise ValueError("ttl must be > 0")

        self._capacity = capacity
        self._default_ttl = ttl
        self._time_fn = time_fn
        self._lock = threading.RLock()

        # OrderedDict maintains insertion order; we'll move items to the end when accessed
        # Structure: {key: (value, expiry_time or None)}
        self._cache: dict[Hashable, tuple[Any, float | None]] = {}
        self._order: list[Hashable] = []  # MRU order (last is MRU)

        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def _is_expired(self, expiry_time: float | None) -> bool:
        """Check if an entry has expired."""
        if expiry_time is None:
            return False
        return self._time_fn() >= expiry_time

    def _remove_entry(self, key: Hashable) -> None:
        """Remove an entry from cache and order list. Must be called with lock held."""
        if key in self._cache:
            del self._cache[key]
            if key in self._order:
                self._order.remove(key)

    def _make_mru(self, key: Hashable) -> None:
        """Move entry to the end (MRU position). Must be called with lock held."""
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)

    def _cleanup_expired(self) -> None:
        """Remove all expired entries. Must be called with lock held."""
        expired_keys = [
            k for k, (_, exp_time) in self._cache.items() if self._is_expired(exp_time)
        ]
        for key in expired_keys:
            self._remove_entry(key)
            self._expirations += 1

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return default

            value, expiry_time = self._cache[key]

            # Check if expired
            if self._is_expired(expiry_time):
                self._remove_entry(key)
                self._expirations += 1
                self._misses += 1
                return default

            # Hit: update MRU
            self._make_mru(key)
            self._hits += 1
            return value

    def set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None = _UNSET_TTL,
    ) -> None:
        with self._lock:
            # Determine effective TTL
            if ttl is _UNSET_TTL:
                # Use default TTL
                effective_ttl = self._default_ttl
            else:
                # Explicit TTL provided (could be None or a number)
                if ttl is not None:
                    if not isinstance(ttl, (int, float)) or isinstance(ttl, bool):
                        raise ValueError("ttl must be a positive number or None")
                    if ttl <= 0:
                        raise ValueError("ttl must be > 0")
                effective_ttl = ttl

            # Calculate expiry time
            if effective_ttl is None:
                expiry_time = None
            else:
                expiry_time = self._time_fn() + effective_ttl

            # Check if updating existing key
            if key in self._cache:
                self._cache[key] = (value, expiry_time)
                self._make_mru(key)
                return

            # New key: need space
            if len(self._cache) >= self._capacity:
                # First, try to purge expired entries
                self._cleanup_expired()

                # If still at capacity, evict LRU
                if len(self._cache) >= self._capacity:
                    lru_key = self._order.pop(0)
                    self._remove_entry(lru_key)
                    self._evictions += 1

            # Add new entry
            self._cache[key] = (value, expiry_time)
            self._make_mru(key)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            if key not in self._cache:
                return False

            _, expiry_time = self._cache[key]

            # Check if expired
            if self._is_expired(expiry_time):
                self._remove_entry(key)
                self._expirations += 1
                return False

            self._remove_entry(key)
            return True

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._order.clear()

    def purge_expired(self) -> int:
        with self._lock:
            count = 0
            expired_keys = [
                k for k, (_, exp_time) in self._cache.items() if self._is_expired(exp_time)
            ]
            for key in expired_keys:
                self._remove_entry(key)
                self._expirations += 1
                count += 1
            return count

    def keys(self) -> list:
        with self._lock:
            # Remove expired entries (don't count as expirations for keys())
            current_time = self._time_fn()
            live_keys = [
                k
                for k in self._order
                if k in self._cache and not self._is_expired(self._cache[k][1])
            ]
            # Return in MRU-first order (reverse of insertion order)
            return list(reversed(live_keys))

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

            _, expiry_time = self._cache[key]

            # Check if expired
            if self._is_expired(expiry_time):
                self._remove_entry(key)
                self._expirations += 1
                return False

            return True
