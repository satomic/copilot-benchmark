# Task M1 — LRU Cache with TTL

**Difficulty:** Medium

## Working agreement (read this first)

- This folder is the project root. Do not read or write anything outside it.
- Python 3.11 and `pytest` are available. Use the **standard library only** — do not install
  any third-party package and do not access the network.
- Create **exactly** the files listed under *Deliverables*. Do not add extra files
  (no `README.md`, no `requirements.txt`, no `setup.py`, no `pyproject.toml`, no scratch files).
- Do not ask clarifying questions. If something is genuinely ambiguous, choose the most
  reasonable interpretation, implement it, and record the choice in a short code comment.
- When the deliverables satisfy the acceptance criteria, stop.

## Goal

Implement a thread-safe, size-bounded cache with per-entry time-to-live, plus a test suite
for it.

## Deliverables

```
cache/__init__.py       # package surface: re-exports LRUCache and CacheStats, defines __all__
cache/lru.py            # LRUCache implementation
cache/stats.py          # CacheStats
tests/test_cache.py     # your own test suite
```

No other files. `tests/` needs no `__init__.py`.

## Public API

`cache/stats.py`:

```python
@dataclass(frozen=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
```

`cache/lru.py`:

```python
class LRUCache:
    def __init__(
        self,
        capacity: int,
        ttl: float | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None: ...

    def get(self, key: Hashable, default: Any = None) -> Any: ...
    def set(self, key: Hashable, value: Any, ttl: float | None = ...) -> None: ...
    def delete(self, key: Hashable) -> bool: ...
    def clear(self) -> None: ...
    def purge_expired(self) -> int: ...
    def keys(self) -> list: ...
    def stats(self) -> CacheStats: ...
    def __len__(self) -> int: ...
    def __contains__(self, key: object) -> bool: ...
```

`cache/__init__.py` must make `from cache import LRUCache, CacheStats` work and must set
`__all__ = ["LRUCache", "CacheStats"]`.

## Behaviour specification

### Construction

1. `capacity` must be an `int` >= 1. Anything else raises `ValueError`
   (a non-`int`, including `bool`, raises `TypeError`).
2. `ttl` is the **default** time-to-live in seconds for entries. `None` means entries never
   expire. A given `ttl` must be a real number > 0, otherwise `ValueError`.
3. `time_fn` is a zero-argument callable returning a monotonically non-decreasing float.
   It is the **only** source of time in the whole class — never call `time.time()` or
   `time.monotonic()` directly anywhere else. Tests inject a fake clock through it.

### `set`

4. `set(key, value)` stores the entry using the cache's default `ttl`.
5. `set(key, value, ttl=X)` with a number `X > 0` gives that entry its own TTL.
   `X <= 0` or a non-number raises `ValueError`.
6. `set(key, value, ttl=None)` makes **that entry** never expire, regardless of the cache
   default. Omitting the argument and passing `None` must therefore behave differently —
   use a private sentinel to tell them apart.
7. Setting an existing key updates its value, restarts its TTL, and makes it the most
   recently used entry.
8. Inserting a **new** key when the cache is already at `capacity` evicts the least recently
   used entry first and increments `evictions`.
9. Expired entries are preferred over live ones when making room: before evicting an LRU
   entry, drop entries that have already expired (counting them as `expirations`, not
   `evictions`). If that frees space, no eviction occurs.

### `get`

10. A live entry: returns the value, counts one `hit`, and becomes the most recently used.
11. A missing key: returns `default`, counts one `miss`.
12. An expired entry: it is removed, counts one `expiration` **and** one `miss`, and `default`
    is returned.

### Expiry semantics

13. An entry with TTL `t` stored at time `t0` expires when `time_fn() >= t0 + t`.
    Exactly at `t0 + t` it is **already expired**.
14. Expiry is lazy: nothing runs in the background, no threads, no timers.
15. `purge_expired()` removes every currently expired entry, counts each as an `expiration`,
    and returns how many were removed.

### Other operations

16. `delete(key)` removes the entry and returns `True`; returns `False` if the key is absent
    or expired. A `delete` of an expired entry counts one `expiration` and returns `False`.
    `delete` never counts hits or misses.
17. `clear()` removes all entries. It does **not** reset the statistics.
18. `keys()` returns the live keys, most-recently-used **first**, least-recently-used last.
    Expired entries are excluded but `keys()` does not mutate the cache or the stats.
19. `__len__` returns the number of entries **including** expired-but-not-yet-purged ones,
    so `len(c)` never exceeds `capacity`.
20. `key in c` returns whether a **live** entry exists. It lazily removes an expired entry
    (counting one `expiration`) and does **not** count hits or misses.
21. `stats()` returns a `CacheStats` snapshot. Mutating the cache afterwards must not change
    a previously returned snapshot.

### Concurrency

22. Every public method must be safe to call from multiple threads. Use a single
    `threading.RLock` held for the duration of each public method. No other locks.
23. `get` and `set` must be O(1) amortised. Do not scan the whole cache on the hot path
    (`purge_expired` may scan; `keys` may scan).

## Your test suite

24. `tests/test_cache.py` must contain **at least 12** test functions and must pass:
    `python -m pytest tests -q` reports 0 failures.
25. It must use an injected fake clock (through `time_fn`) rather than `time.sleep`.
    No test may sleep.
26. It must cover at least: capacity eviction order, LRU refresh on `get`, TTL expiry via
    `get`, per-entry TTL overriding the default, `ttl=None` override, `purge_expired`,
    `delete` return values, `clear` not resetting stats, `keys()` ordering,
    `__contains__` not counting hits/misses, and constructor validation.

## Acceptance criteria

```python
from cache import LRUCache, CacheStats

clock = [0.0]
c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

c.set("a", 1)
c.set("b", 2)
assert c.get("a") == 1              # 'a' is now MRU
c.set("c", 3)                       # evicts 'b'
assert c.keys() == ["c", "a"]
assert c.get("b") is None
assert c.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)

clock[0] = 10.0                     # exactly at the deadline -> already expired
assert c.get("a") is None
assert c.stats().expirations == 1

c2 = LRUCache(capacity=8, ttl=5, time_fn=lambda: clock[0])
c2.set("forever", 1, ttl=None)
clock[0] += 1000
assert c2.get("forever") == 1

import pytest
with pytest.raises(ValueError):
    LRUCache(capacity=0)
with pytest.raises(TypeError):
    LRUCache(capacity=True)
```

## Definition of done

All four files exist, `python -m pytest tests -q` passes with at least 12 tests, and every
item under *Behaviour specification* holds.
