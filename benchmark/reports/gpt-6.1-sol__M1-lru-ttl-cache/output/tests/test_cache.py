import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

import cache
from cache import CacheStats, LRUCache


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_package_surface():
    assert cache.__all__ == ["LRUCache", "CacheStats"]
    assert CacheStats() == CacheStats(0, 0, 0, 0)


@pytest.mark.parametrize("capacity", [True, False, 1.0, "2", None])
def test_capacity_type_validation(capacity):
    with pytest.raises(TypeError):
        LRUCache(capacity)


@pytest.mark.parametrize("capacity", [0, -1])
def test_capacity_value_validation(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity)


@pytest.mark.parametrize("ttl", [0, -1, "5", object(), True, float("nan")])
def test_ttl_validation(ttl):
    with pytest.raises(ValueError):
        LRUCache(1, ttl=ttl)
    c = LRUCache(1, time_fn=Clock())
    c.set("a", 1)
    with pytest.raises(ValueError):
        c.set("a", 2, ttl=ttl)
    assert c.get("a") == 1


def test_time_function_validation():
    with pytest.raises(TypeError):
        LRUCache(1, time_fn=None)


def test_capacity_eviction_order():
    c = LRUCache(2, time_fn=Clock())
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["c", "b"]
    assert c.get("a", "missing") == "missing"
    assert c.stats() == CacheStats(misses=1, evictions=1)


def test_get_refreshes_lru():
    c = LRUCache(2, time_fn=Clock())
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert c.keys() == ["c", "a"]
    assert c.get("b") is None
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1)


def test_expiry_get_at_exact_deadline():
    clock = Clock()
    c = LRUCache(2, ttl=10, time_fn=clock)
    c.set("a", None)
    clock.advance(9)
    assert c.get("a", "missing") is None
    clock.advance(1)
    assert c.get("a", "missing") == "missing"
    assert c.get("a") is None
    assert c.stats() == CacheStats(hits=1, misses=2, expirations=1)
    assert len(c) == 0


def test_per_entry_ttl_and_none_override():
    clock = Clock()
    c = LRUCache(4, ttl=5, time_fn=clock)
    c.set("default", 1)
    c.set("short", 2, ttl=1)
    c.set("long", 3, ttl=10)
    c.set("forever", 4, ttl=None)
    clock.advance(5)
    assert c.get("default") is None
    assert c.get("short") is None
    assert c.get("long") == 3
    clock.advance(1000)
    assert c.get("long") is None
    assert c.get("forever") == 4


def test_no_default_ttl():
    clock = Clock()
    c = LRUCache(2, time_fn=clock)
    c.set("forever", 1)
    c.set("temporary", 2, ttl=2)
    clock.advance(1000)
    assert c.get("forever") == 1
    assert c.get("temporary") is None


def test_update_restarts_ttl_and_refreshes_lru():
    clock = Clock()
    c = LRUCache(2, ttl=5, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(4)
    c.set("a", 3)
    assert c.keys() == ["a", "b"]
    clock.advance(1)
    assert c.get("a") == 3
    assert c.purge_expired() == 1
    clock.advance(4)
    assert c.get("a") is None
    assert c.stats() == CacheStats(hits=1, misses=1, expirations=2)


def test_update_changes_expiry_policy_without_stale_index():
    clock = Clock()
    c = LRUCache(1, ttl=2, time_fn=clock)
    c.set("a", 1)
    c.set("a", 2, ttl=None)
    clock.advance(2)
    assert c.purge_expired() == 0
    c.set("a", 3, ttl=1)
    clock.advance(1)
    c.set("a", 4)
    assert c.stats() == CacheStats(expirations=1)
    assert c.get("a") == 4


def test_expired_mru_preferred_over_live_lru():
    clock = Clock()
    c = LRUCache(2, time_fn=clock)
    c.set("live", 1)
    c.set("expired", 2, ttl=1)
    clock.advance(1)
    c.set("new", 3)
    assert c.keys() == ["new", "live"]
    assert c.stats() == CacheStats(expirations=1)


def test_purge_all_expired_before_capacity_eviction():
    clock = Clock()
    c = LRUCache(3, time_fn=clock)
    c.set("a", 1, ttl=2)
    c.set("b", 2, ttl=1)
    c.set("c", 3, ttl=2)
    clock.advance(2)
    c.set("d", 4)
    assert c.keys() == ["d"]
    assert c.stats() == CacheStats(expirations=3)


def test_purge_expired_with_out_of_order_and_shared_deadlines():
    clock = Clock(-10.0)
    c = LRUCache(5, time_fn=clock)
    c.set("last", 1, ttl=20)
    c.set("first", 2, ttl=1)
    c.set("same", 3, ttl=1)
    c.set("middle", 4, ttl=10)
    c.set("forever", 5)
    clock.advance(1)
    assert c.purge_expired() == 2
    assert c.purge_expired() == 0
    clock.advance(9)
    assert c.purge_expired() == 1
    assert c.keys() == ["forever", "last"]
    clock.advance(10)
    assert c.purge_expired() == 1
    assert c.stats() == CacheStats(expirations=4)


def test_delete_return_values_and_statistics():
    clock = Clock()
    c = LRUCache(2, time_fn=clock)
    c.set("live", 1)
    c.set("expired", 2, ttl=1)
    assert c.delete("live") is True
    assert c.delete("live") is False
    clock.advance(1)
    assert c.delete("expired") is False
    assert c.delete("absent") is False
    assert c.stats() == CacheStats(expirations=1)
    assert c.purge_expired() == 0


def test_clear_preserves_statistics_and_clears_expiry_index():
    clock = Clock()
    c = LRUCache(1, ttl=1, time_fn=clock)
    c.set("a", 1)
    assert c.get("a") == 1
    c.set("b", 2)
    clock.advance(1)
    assert c.get("b") is None
    c.set("c", 3)
    before = c.stats()
    c.clear()
    clock.advance(1)
    assert len(c) == 0
    assert c.keys() == []
    assert c.purge_expired() == 0
    assert c.stats() == before == CacheStats(1, 1, 1, 1)


def test_keys_filters_without_mutation_and_len_includes_expired():
    clock = Clock()
    c = LRUCache(3, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=1)
    c.set("c", 3)
    clock.advance(1)
    before = c.stats()
    assert c.keys() == ["c", "a"]
    assert c.keys() == ["c", "a"]
    assert len(c) == 3
    assert c.stats() == before
    assert c.purge_expired() == 1
    assert c.keys() == ["c", "a"]


def test_contains_does_not_count_accesses_or_refresh_lru():
    clock = Clock()
    c = LRUCache(2, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=1)
    assert "a" in c
    assert "absent" not in c
    assert c.keys() == ["b", "a"]
    clock.advance(1)
    assert "b" not in c
    assert "b" not in c
    assert c.stats() == CacheStats(expirations=1)
    assert len(c) == 1


def test_stats_are_immutable_snapshots():
    c = LRUCache(1, time_fn=Clock())
    snapshot = c.stats()
    c.get("missing")
    assert snapshot == CacheStats()
    assert c.stats() == CacheStats(misses=1)
    with pytest.raises(FrozenInstanceError):
        snapshot.hits = 10


def test_arbitrary_hashable_keys_and_values():
    c = LRUCache(3, time_fn=Clock())
    value = object()
    for key in (None, ("tuple", 1), 42):
        c.set(key, value, ttl=1)
        assert c.get(key) is value
    assert c.keys() == [42, ("tuple", 1), None]


def test_expiry_index_matches_randomized_reference():
    clock = Clock(-100.0)
    c = LRUCache(100, time_fn=clock)
    expected = {}
    rng = random.Random(42)
    for _ in range(1000):
        clock.advance(rng.random())
        key = rng.randrange(80)
        if rng.randrange(4) == 0:
            expected.pop(key, None)
            c.delete(key)
        else:
            ttl = rng.choice([None, 0.5, 1, 5, 100])
            c.set(key, key, ttl=ttl)
            expected[key] = None if ttl is None else clock.now + ttl
        expired = [
            key for key, deadline in expected.items()
            if deadline is not None and clock.now >= deadline
        ]
        assert c.purge_expired() == len(expired)
        for key in expired:
            del expected[key]
        assert set(c.keys()) == set(expected)
        assert len(c) == len(expected)


def test_thread_safe_public_operations():
    c = LRUCache(32, time_fn=Clock())

    def worker(worker_id):
        for i in range(200):
            key = (worker_id, i % 8)
            c.set(key, i, ttl=1 if i % 2 else None)
            c.get(key)
            key in c
            c.keys()
            c.stats()
            assert len(c) <= 32
            c.purge_expired()
            c.delete(key)
            if i % 50 == 0:
                c.clear()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))
    assert len(c) <= 32
    assert c.stats().hits + c.stats().misses == 1600
