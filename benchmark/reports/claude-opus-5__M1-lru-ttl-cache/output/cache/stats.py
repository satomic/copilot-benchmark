"""Immutable statistics snapshot for :class:`cache.lru.LRUCache`."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CacheStats"]


@dataclass(frozen=True)
class CacheStats:
    """A point-in-time snapshot of cache counters."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
