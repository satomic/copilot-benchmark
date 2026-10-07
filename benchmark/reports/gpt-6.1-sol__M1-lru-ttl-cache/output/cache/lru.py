import struct
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from numbers import Real
from typing import Any

from .stats import CacheStats


class _DefaultTTL:
    pass


_DEFAULT_TTL = _DefaultTTL()
_SIGN_BIT = 1 << 63
_WORD_MASK = (1 << 64) - 1


@dataclass
class _Entry:
    value: Any
    deadline: float | None
    expiry_token: int | None


@dataclass
class _ExpiryNode:
    children: dict[int, "_ExpiryNode"] = field(default_factory=dict)
    keys: OrderedDict[Hashable, None] = field(default_factory=OrderedDict)


def _validate_ttl(ttl: Any) -> None:
    # Booleans are flags, not durations; NaN also fails the positive check.
    if ttl is not None and (
        isinstance(ttl, bool) or not isinstance(ttl, Real) or not ttl > 0
    ):
        raise ValueError("ttl must be a positive real number or None")


def _deadline_token(deadline: float) -> int:
    bits = struct.unpack(">Q", struct.pack(">d", deadline))[0]
    return (~bits & _WORD_MASK) if bits & _SIGN_BIT else bits ^ _SIGN_BIT


class LRUCache:
    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lock = threading.RLock()
        with self._lock:
            if isinstance(capacity, bool) or not isinstance(capacity, int):
                raise TypeError("capacity must be an integer")
            if capacity < 1:
                raise ValueError("capacity must be at least one")
            _validate_ttl(ttl)
            if not callable(time_fn):
                raise TypeError("time_fn must be callable")
            self._capacity = capacity
            self._ttl = ttl
            self._time_fn = time_fn
            self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
            self._expiry = _ExpiryNode()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expirations = 0

    def _index_expiry(self, key: Hashable, token: int) -> None:
        # IEEE-754 sortable tokens make this trie a fixed 64-step index:
        # unlike a heap, insertion/removal/minimum are O(1) in cache size.
        node = self._expiry
        for shift in range(63, -1, -1):
            bit = (token >> shift) & 1
            child = node.children.get(bit)
            if child is None:
                child = _ExpiryNode()
                node.children[bit] = child
            node = child
        node.keys[key] = None

    def _unindex_expiry(self, key: Hashable, token: int) -> None:
        node = self._expiry
        path = []
        for shift in range(63, -1, -1):
            bit = (token >> shift) & 1
            path.append((node, bit))
            node = node.children[bit]
        del node.keys[key]
        for parent, bit in reversed(path):
            if node.keys or node.children:
                break
            del parent.children[bit]
            node = parent

    def _remove(self, key: Hashable) -> _Entry:
        entry = self._entries.pop(key)
        if entry.expiry_token is not None:
            self._unindex_expiry(key, entry.expiry_token)
        return entry

    def _purge(self, now: float) -> int:
        removed = 0
        while self._expiry.children:
            node = self._expiry
            for _ in range(64):
                node = node.children[0 if 0 in node.children else 1]
            key = next(iter(node.keys))
            deadline = self._entries[key].deadline
            if deadline is None or now < deadline:
                break
            self._remove(key)
            removed += 1
        self._expirations += removed
        return removed

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return default
            if entry.deadline is not None and self._time_fn() >= entry.deadline:
                self._remove(key)
                self._expirations += 1
                self._misses += 1
                return default
            self._entries.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None | _DefaultTTL = _DEFAULT_TTL,
    ) -> None:
        with self._lock:
            duration = self._ttl if isinstance(ttl, _DefaultTTL) else ttl
            _validate_ttl(duration)
            hash(key)
            now = self._time_fn()
            deadline = None if duration is None else now + duration
            token = None if deadline is None else _deadline_token(deadline)
            if key in self._entries:
                previous = self._remove(key)
                # Replacing an expired entry observes its expiration, not eviction.
                if previous.deadline is not None and now >= previous.deadline:
                    self._expirations += 1
            elif len(self._entries) >= self._capacity:
                self._purge(now)
                if len(self._entries) >= self._capacity:
                    self._remove(next(iter(self._entries)))
                    self._evictions += 1
            self._entries[key] = _Entry(value, deadline, token)
            if token is not None:
                self._index_expiry(key, token)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            expired = entry.deadline is not None and self._time_fn() >= entry.deadline
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
            return self._purge(self._time_fn())

    def keys(self) -> list:
        with self._lock:
            now = self._time_fn()
            return [
                key
                for key, entry in reversed(self._entries.items())
                if entry.deadline is None or now < entry.deadline
            ]

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                self._hits, self._misses, self._evictions, self._expirations
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            if not isinstance(key, Hashable):
                raise TypeError("cache keys must be hashable")
            entry = self._entries.get(key)
            if entry is None:
                return False
            if entry.deadline is not None and self._time_fn() >= entry.deadline:
                self._remove(key)
                self._expirations += 1
                return False
            return True
