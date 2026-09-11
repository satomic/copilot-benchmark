"""Tests for cache.lru.LRUCache using an injected fake clock (no real sleeping)."""

import threading

import pytest

from cache import CacheStats, LRUCache


class FakeClock:
    """A simple mutable monotonic clock for deterministic TTL tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


def test_capacity_eviction_order():
    clock = FakeClock()
    c = LRUCache(capacity=2, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # 'a' is LRU, should be evicted
    assert c.keys() == ["c", "b"]
    assert c.get("a") is None
    assert c.stats().evictions == 1


def test_lru_refresh_on_get():
    clock = FakeClock()
    c = LRUCache(capacity=2, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # 'a' becomes MRU
    c.set("c", 3)  # should evict 'b', not 'a'
    assert c.get("b") is None
    assert c.keys() == ["c", "a"]
    assert c.get("a") == 1


def test_ttl_expiry_via_get():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    clock.advance(10)  # exactly at deadline -> already expired
    assert c.get("a") is None
    assert c.stats().expirations == 1
    assert c.stats().misses == 1


def test_ttl_not_expired_before_deadline():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    clock.advance(9.999)
    assert c.get("a") == 1


def test_per_entry_ttl_overrides_default():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=100, time_fn=clock)
    c.set("short", 1, ttl=1)
    clock.advance(1)
    assert c.get("short") is None  # expired despite long default ttl


def test_ttl_none_override_never_expires():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=5, time_fn=clock)
    c.set("forever", 1, ttl=None)
    clock.advance(1000)
    assert c.get("forever") == 1


def test_purge_expired_removes_and_counts():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=None)
    clock.advance(10)
    removed = c.purge_expired()
    assert removed == 1
    assert c.stats().expirations == 1
    assert c.get("b") == 2
    assert len(c) == 1


def test_delete_return_values():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    assert c.delete("a") is True
    assert c.delete("a") is False  # already gone
    assert c.delete("missing") is False

    c.set("b", 2)
    clock.advance(10)  # expired
    assert c.delete("b") is False
    assert c.stats().expirations == 1


def test_clear_does_not_reset_stats():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.get("a")
    c.get("missing")
    stats_before_clear = c.stats()
    c.clear()
    assert len(c) == 0
    assert c.stats() == stats_before_clear


def test_keys_ordering_mru_first():
    clock = FakeClock()
    c = LRUCache(capacity=4, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["c", "b", "a"]
    c.get("a")
    assert c.keys() == ["a", "c", "b"]


def test_keys_excludes_expired_without_mutating():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=None)
    clock.advance(10)
    assert c.keys() == ["b"]
    # keys() must not mutate the cache or stats
    assert len(c) == 2
    assert c.stats().expirations == 0


def test_contains_does_not_count_hits_or_misses():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    assert "a" in c
    assert "missing" not in c
    stats = c.stats()
    assert stats.hits == 0
    assert stats.misses == 0


def test_contains_lazily_expires_and_counts_expiration():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    clock.advance(10)
    assert "a" not in c
    assert c.stats().expirations == 1
    assert len(c) == 0


def test_constructor_validation():
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(TypeError):
        LRUCache(capacity="2")
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=-5)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl="oops")


def test_set_ttl_argument_validation():
    clock = FakeClock()
    c = LRUCache(capacity=4, time_fn=clock)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=0)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=-1)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl="nope")


def test_len_includes_expired_but_not_purged_entries():
    clock = FakeClock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(10)
    assert len(c) == 2  # still present, just expired


def test_expired_entries_preferred_over_eviction():
    clock = FakeClock()
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=None)  # never expires
    clock.advance(10)  # 'a' is now expired
    c.set("c", 3)  # should purge expired 'a', not evict 'b'
    assert c.stats().expirations == 1
    assert c.stats().evictions == 0
    assert set(c.keys()) == {"b", "c"}


def test_set_existing_key_restarts_ttl_and_becomes_mru():
    clock = FakeClock()
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(5)
    c.set("a", 100)  # restarts ttl, becomes MRU
    assert c.keys() == ["a", "b"]
    clock.advance(5)  # t=10; 'a' was reset at t=5 with ttl=10, so not expired until t=15
    assert c.get("a") == 100


def test_thread_safety_smoke():
    clock = FakeClock()
    c = LRUCache(capacity=50, time_fn=clock)

    def worker(n):
        for i in range(200):
            c.set(f"key-{n}-{i}", i)
            c.get(f"key-{n}-{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(c) <= 50
    stats = c.stats()
    assert stats.hits + stats.misses > 0
