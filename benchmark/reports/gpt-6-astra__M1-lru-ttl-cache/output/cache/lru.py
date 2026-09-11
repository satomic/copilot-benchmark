"""Thread-safe LRU storage with lazy, per-entry expiration."""

import struct
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from numbers import Real
from threading import RLock
from typing import Any

from .stats import CacheStats


class _DefaultTTL:
    __slots__ = ()


_DEFAULT_TTL = _DefaultTTL()


@dataclass(slots=True)
class _Entry:
    value: Any
    deadline: float | None


@dataclass(slots=True)
class _ExpiryNode:
    children: dict[int, "_ExpiryNode"] = field(default_factory=dict)
    # OrderedDict keeps first-key lookup O(1) even after many shared-deadline deletions.
    keys: OrderedDict[Hashable, None] = field(default_factory=OrderedDict)


def _validate_ttl(ttl: float | None) -> float | None:
    if ttl is None:
        return None
    # Booleans are flags, not durations; positive infinity is a valid TTL.
    if isinstance(ttl, bool) or not isinstance(ttl, Real) or not ttl > 0:
        raise ValueError("ttl must be a real number greater than zero or None")
    try:
        return float(ttl)
    except OverflowError:
        # Positive durations beyond float range have an infinite deadline.
        return float("inf")


def _deadline_path(deadline: float) -> bytes:
    bits = int.from_bytes(struct.pack(">d", deadline), "big")
    # Convert IEEE-754 sign/magnitude ordering into unsigned numeric ordering.
    bits = bits ^ ((1 << 64) - 1) if bits >> 63 else bits ^ (1 << 63)
    return bits.to_bytes(8, "big")


class LRUCache:
    """A bounded cache whose reads refresh recency, but not TTL.

    Expirations use an eight-level radix trie over float deadlines, not a
    comparison heap. Index operations have fixed depth and fanout (at most
    256), independent of capacity. Reclaiming k expired entries costs O(k);
    each removal is charged to its insertion, keeping set amortized O(1).
    """

    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lock = RLock()
        with self._lock:
            if isinstance(capacity, bool) or not isinstance(capacity, int):
                raise TypeError("capacity must be an int")
            if capacity < 1:
                raise ValueError("capacity must be at least one")
            self._ttl = _validate_ttl(ttl)
            self._capacity = capacity
            self._time_fn = time_fn
            self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
            self._expiry = _ExpiryNode()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expirations = 0

    def _index(self, key: Hashable, deadline: float) -> None:
        node = self._expiry
        for part in _deadline_path(deadline):
            child = node.children.get(part)
            if child is None:
                child = node.children[part] = _ExpiryNode()
            node = child
        node.keys[key] = None

    def _remove(self, key: Hashable) -> _Entry:
        entry = self._entries.pop(key)
        if entry.deadline is not None:
            node = self._expiry
            path = []
            for part in _deadline_path(entry.deadline):
                path.append((node, part))
                node = node.children[part]
            del node.keys[key]
            for parent, part in reversed(path):
                if node.keys or node.children:
                    break
                del parent.children[part]
                node = parent
        return entry

    @staticmethod
    def _expired(entry: _Entry, now: float) -> bool:
        return entry.deadline is not None and now >= entry.deadline

    def _purge_expired(self, now: float) -> int:
        removed = 0
        while self._expiry.children:
            node = self._expiry
            while node.children:
                node = node.children[min(node.children)]
            key = next(iter(node.keys))
            if not self._expired(self._entries[key], now):
                break
            for key in tuple(node.keys):
                self._remove(key)
                removed += 1
                self._expirations += 1
        return removed

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                if not self._expired(entry, self._time_fn()):
                    self._entries.move_to_end(key)
                    self._hits += 1
                    return entry.value
                self._remove(key)
                self._expirations += 1
            self._misses += 1
            return default

    def set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None | _DefaultTTL = _DEFAULT_TTL,
    ) -> None:
        with self._lock:
            duration = self._ttl if isinstance(ttl, _DefaultTTL) else _validate_ttl(ttl)
            entry = self._entries.get(key)
            now = self._time_fn()
            if entry is not None:
                # Replacing an expired entry observes and counts its expiration.
                if self._expired(entry, now):
                    self._expirations += 1
                self._remove(key)
            elif len(self._entries) == self._capacity:
                self._purge_expired(now)
                if len(self._entries) == self._capacity:
                    self._remove(next(iter(self._entries)))
                    self._evictions += 1
            deadline = None if duration is None else now + duration
            self._entries[key] = _Entry(value, deadline)
            if deadline is not None:
                self._index(key, deadline)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            expired = self._expired(entry, self._time_fn())
            self._remove(key)
            if expired:
                self._expirations += 1
            return not expired

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._expiry = _ExpiryNode()

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired(self._time_fn())

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                key
                for key in reversed(self._entries)
                if not self._expired(self._entries[key], now)
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
            if not isinstance(key, Hashable):
                raise TypeError(f"unhashable type: '{type(key).__name__}'")
            entry = self._entries.get(key)
            if entry is None:
                return False
            if self._expired(entry, self._time_fn()):
                self._remove(key)
                self._expirations += 1
                return False
            return True
