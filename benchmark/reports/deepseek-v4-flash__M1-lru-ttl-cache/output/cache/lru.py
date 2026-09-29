from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable

from cache.stats import CacheStats

# Sentinel used to distinguish "no ttl argument passed" from "ttl=None".
# When the caller omits the ttl argument, the cache's default TTL is used.
# When the caller passes ttl=None explicitly, the entry never expires.
_UNSET = object()


class _Node:
    """Doubly-linked list node for O(1) LRU reordering."""

    __slots__ = ("key", "value", "expires_at", "prev", "next")

    def __init__(self, key: Hashable, value: Any, expires_at: float) -> None:
        self.key = key
        self.value = value
        self.expires_at = expires_at  # float('inf') for never-expire
        self.prev: _Node | None = None
        self.next: _Node | None = None


def _validate_capacity(capacity: int) -> None:
    """Raise TypeError/ValueError if capacity is invalid."""
    if isinstance(capacity, bool):
        raise TypeError("capacity must be an int, not bool")
    if not isinstance(capacity, int):
        raise TypeError(f"capacity must be an int, got {type(capacity).__name__}")
    if capacity < 1:
        raise ValueError(f"capacity must be >= 1, got {capacity}")


def _validate_ttl_value(ttl: Any) -> None:
    """Raise ValueError if *ttl* is not a positive real number."""
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
        raise ValueError(f"ttl must be a positive number, got {ttl!r}")
    if ttl <= 0:
        raise ValueError(f"ttl must be positive, got {ttl}")


class LRUCache:
    """Thread-safe, size-bounded cache with per-entry time-to-live.

    Entries are evicted in least-recently-used order when the cache is at
    capacity and a new entry is inserted.  Expired entries are removed lazily
    on access and are preferred over live entries when making room.
    """

    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        _validate_capacity(capacity)
        if ttl is not None:
            _validate_ttl_value(ttl)
        if not callable(time_fn):
            raise TypeError("time_fn must be callable")

        self._capacity = capacity
        self._default_ttl = ttl
        self._time_fn = time_fn

        self._lock = threading.RLock()
        self._map: dict[Hashable, _Node] = {}
        self._head: _Node | None = None  # most recently used
        self._tail: _Node | None = None  # least recently used

        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # ------------------------------------------------------------------
    # Internal helpers (must be called with self._lock held)
    # ------------------------------------------------------------------

    def _compute_expires_at(self, ttl: float | None) -> float:
        """Return the absolute expiry time for a given *ttl*."""
        if ttl is None:
            return float("inf")
        return self._time_fn() + ttl

    def _remove_node(self, node: _Node) -> None:
        """Detach *node* from the linked list."""
        prev, nxt = node.prev, node.next
        if prev:
            prev.next = nxt
        else:
            self._head = nxt
        if nxt:
            nxt.prev = prev
        else:
            self._tail = prev
        node.prev = node.next = None

    def _add_to_head(self, node: _Node) -> None:
        """Insert *node* at the MRU end of the list."""
        node.next = self._head
        node.prev = None
        if self._head:
            self._head.prev = node
        self._head = node
        if self._tail is None:
            self._tail = node

    def _move_to_head(self, node: _Node) -> None:
        """Move an already-linked *node* to the MRU position."""
        self._remove_node(node)
        self._add_to_head(node)

    def _evict_lru(self) -> None:
        """Evict the least recently used (live) entry."""
        node = self._tail
        assert node is not None  # we call this only when cache is non-empty
        self._remove_node(node)
        del self._map[node.key]
        self._evictions += 1

    def _purge_expired_locked(self) -> int:
        """Remove all expired entries and return the count.

        Must be called with self._lock held.
        """
        now = self._time_fn()
        count = 0
        node = self._tail
        while node is not None:
            prev = node.prev
            if node.expires_at <= now:
                self._remove_node(node)
                del self._map[node.key]
                count += 1
            node = prev
        self._expirations += count
        return count

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Return the value for *key* if present and live, else *default*.

        Live entries are promoted to MRU.  Expired entries are removed and
        count as one miss.
        """
        with self._lock:
            node = self._map.get(key)
            if node is None:
                self._misses += 1
                return default

            now = self._time_fn()
            if node.expires_at <= now:
                # expired – remove and count as expiration + miss
                self._remove_node(node)
                del self._map[key]
                self._expirations += 1
                self._misses += 1
                return default

            self._move_to_head(node)
            self._hits += 1
            return node.value

    def set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None | object = _UNSET,
    ) -> None:
        """Store *key* → *value* with an optional per-entry *ttl*.

        When *ttl* is omitted the cache's default TTL is used.
        ``ttl=None`` makes this particular entry never expire.
        """
        with self._lock:
            # Resolve the TTL to use for this entry.
            if ttl is _UNSET:
                entry_ttl = self._default_ttl
            elif ttl is None:
                entry_ttl = None
            else:
                _validate_ttl_value(ttl)
                entry_ttl = ttl

            expires_at = self._compute_expires_at(entry_ttl)

            existing = self._map.get(key)
            if existing is not None:
                # Update in-place and promote to MRU.
                existing.value = value
                existing.expires_at = expires_at
                self._move_to_head(existing)
                return

            # Make room if necessary – drop expired entries first.
            if len(self._map) >= self._capacity:
                self._purge_expired_locked()
            if len(self._map) >= self._capacity:
                self._evict_lru()

            node = _Node(key, value, expires_at)
            self._map[key] = node
            self._add_to_head(node)

    def delete(self, key: Hashable) -> bool:
        """Remove *key*.

        Returns ``True`` if a live entry existed (and was removed).
        Returns ``False`` if the key was absent or expired (expired entries
        are still removed and count as one expiration).
        """
        with self._lock:
            node = self._map.pop(key, None)
            if node is None:
                return False

            self._remove_node(node)

            now = self._time_fn()
            if node.expires_at <= now:
                self._expirations += 1
                return False

            return True

    def clear(self) -> None:
        """Remove all entries.  Statistics are *not* reset."""
        with self._lock:
            self._map.clear()
            self._head = None
            self._tail = None

    def purge_expired(self) -> int:
        """Remove all currently expired entries and return the count."""
        with self._lock:
            return self._purge_expired_locked()

    def keys(self) -> list:
        """Return live keys, most-recently-used first.

        Expired entries are excluded but the cache is **not** mutated.
        """
        with self._lock:
            now = self._time_fn()
            result: list = []
            node = self._head
            while node is not None:
                if node.expires_at > now:
                    result.append(node.key)
                node = node.next
            return result

    def stats(self) -> CacheStats:
        """Return an immutable snapshot of the current statistics."""
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                expirations=self._expirations,
            )

    def __len__(self) -> int:
        """Return the total entry count (including expired-but-not-purged)."""
        with self._lock:
            return len(self._map)

    def __contains__(self, key: object) -> bool:
        """Return whether *key* has a **live** entry.

        Expired entries are lazily removed (counting one expiration).
        Hits/misses are **not** affected.
        """
        with self._lock:
            node = self._map.get(key)
            if node is None:
                return False
            now = self._time_fn()
            if node.expires_at <= now:
                self._remove_node(node)
                del self._map[key]
                self._expirations += 1
                return False
            return True