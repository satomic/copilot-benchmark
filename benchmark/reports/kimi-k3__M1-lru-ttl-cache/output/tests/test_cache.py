"""Test suite for cache.LRUCache. All tests use an injected fake clock."""

import threading

import pytest

from cache import LRUCache, CacheStats


class FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_cache(capacity=3, ttl=None, clock=None):
    clock = clock or FakeClock()
    return LRUCache(capacity=capacity, ttl=ttl, time_fn=clock), clock


def test_constructor_rejects_zero_and_negative_capacity():
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=-5)


def test_constructor_rejects_non_int_capacity():
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(TypeError):
        LRUCache(capacity=2.0)
    with pytest.raises(TypeError):
        LRUCache(capacity="3")


def test_constructor_rejects_bad_default_ttl():
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=-1)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl="10")


def test_capacity_eviction_order():
    c, _ = make_cache(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # evicts LRU entry 'a'
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3
    assert c.stats().evictions == 1


def test_lru_refresh_on_get():
    c, _ = make_cache(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # 'a' becomes MRU
    c.set("c", 3)           # evicts 'b', not 'a'
    assert c.keys() == ["c", "a"]
    assert c.get("b") is None
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)


def test_set_existing_key_updates_value_and_refreshes():
    c, clock = make_cache(capacity=2, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(9)
    c.set("a", 100)  # restart TTL, become MRU
    clock.advance(9)
    assert c.get("a") == 100
    c.set("c", 3)  # evicts 'b'
    assert c.get("b") is None
    assert c.get("c") == 3


def test_ttl_expiry_via_get():
    c, clock = make_cache(capacity=3, ttl=10)
    c.set("a", 1)
    clock.advance(9.9)
    assert c.get("a") == 1
    clock.advance(0.1)  # exactly at deadline -> expired
    assert c.get("a") is None
    assert len(c) == 0
    stats = c.stats()
    assert stats.expirations == 1
    assert stats.misses == 1
    assert stats.hits == 1


def test_per_entry_ttl_overrides_default():
    c, clock = make_cache(capacity=3, ttl=100)
    c.set("short", 1, ttl=5)
    c.set("long", 2)
    clock.advance(10)
    assert c.get("short") is None
    assert c.get("long") == 2


def test_ttl_none_override_never_expires():
    c, clock = make_cache(capacity=3, ttl=5)
    c.set("forever", 1, ttl=None)
    clock.advance(1000)
    assert c.get("forever") == 1
    assert c.stats().expirations == 0


def test_set_rejects_bad_entry_ttl():
    c, _ = make_cache()
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=0)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=-2)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl="x")


def test_purge_expired():
    c, clock = make_cache(capacity=5, ttl=10)
    c.set("a", 1)
    c.set("b", 2, ttl=None)
    clock.advance(5)
    c.set("c", 3)
    clock.advance(5)  # 'a' expired, 'c' still live
    assert c.purge_expired() == 1
    assert c.get("b") == 2
    assert c.get("c") == 3
    assert c.stats().expirations == 1
    assert c.purge_expired() == 0


def test_expired_entries_preferred_over_eviction():
    c, clock = make_cache(capacity=2, ttl=10)
    c.set("a", 1)
    clock.advance(20)  # 'a' expired
    c.set("b", 2)      # full, but 'a' is expired -> drop it, no eviction
    c.set("c", 3)      # room now -> still no eviction
    stats = c.stats()
    assert stats.expirations == 1
    assert stats.evictions == 0
    assert c.keys() == ["c", "b"]
    c.set("d", 4)      # now full of live entries -> evicts LRU 'b'
    assert c.stats().evictions == 1
    assert c.get("b") is None
    assert c.keys() == ["d", "c"]


def test_delete_return_values():
    c, clock = make_cache(capacity=3, ttl=10)
    c.set("a", 1)
    assert c.delete("a") is True
    assert c.delete("a") is False
    c.set("b", 2)
    clock.advance(10)
    assert c.delete("b") is False  # expired delete counts an expiration
    assert c.stats().expirations == 1
    stats = c.stats()
    assert stats.hits == 0 and stats.misses == 0


def test_clear_does_not_reset_stats():
    c, _ = make_cache(capacity=3)
    c.set("a", 1)
    c.get("a")
    c.get("missing")
    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=0, expirations=0)


def test_keys_ordering_and_no_mutation():
    c, clock = make_cache(capacity=4, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    c.get("a")  # 'a' now MRU
    assert c.keys() == ["a", "c", "b"]
    clock.advance(10)  # all expired
    assert c.keys() == []  # expired excluded
    assert len(c) == 3     # keys() does not mutate
    assert c.stats().expirations == 0  # keys() does not touch stats


def test_contains_no_hit_or_miss():
    c, clock = make_cache(capacity=3, ttl=10)
    c.set("a", 1)
    assert "a" in c
    assert "missing" not in c
    clock.advance(10)
    assert "a" not in c  # lazily removes expired entry
    assert len(c) == 0
    stats = c.stats()
    assert stats.hits == 0 and stats.misses == 0
    assert stats.expirations == 1


def test_stats_snapshot_is_independent():
    c, _ = make_cache(capacity=3)
    c.set("a", 1)
    c.get("a")
    snap = c.stats()
    assert snap == CacheStats(hits=1)
    c.get("a")
    c.get("nope")
    assert snap == CacheStats(hits=1)  # earlier snapshot unchanged
    assert c.stats() == CacheStats(hits=2, misses=1)


def test_len_includes_unpurged_expired_and_caps_at_capacity():
    c, clock = make_cache(capacity=2, ttl=5)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(5)
    assert len(c) == 2
    c.set("c", 3)  # drops both expired entries, no eviction
    assert len(c) == 1
    assert c.stats().evictions == 0
    assert c.stats().expirations == 2


def test_default_returned_for_missing_key():
    c, _ = make_cache()
    assert c.get("nope") is None
    assert c.get("nope", default=42) == 42
    assert c.stats().misses == 2


def test_thread_safety_concurrent_access():
    c, _ = make_cache(capacity=50, ttl=1000)
    errors = []

    def worker(n):
        try:
            for i in range(200):
                key = (n, i % 30)
                c.set(key, i)
                c.get(key)
                key in c
                c.delete(("odd", n)) if n % 2 else None
                len(c)
                c.keys()
                c.stats()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(c) <= 50
    stats = c.stats()
    assert stats.hits + stats.misses > 0
