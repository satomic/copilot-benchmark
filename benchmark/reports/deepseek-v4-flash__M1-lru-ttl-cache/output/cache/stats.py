from dataclasses import dataclass


@dataclass(frozen=True)
class CacheStats:
    """Immutable snapshot of cache performance counters."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0