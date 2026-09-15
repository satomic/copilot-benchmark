import pytest

from cache import CacheStats, LRUCache


def test_constructor_validates_capacity_and_ttl():
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl="fast")
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=-1)
    with pytest.raises(TypeError):
        LRUCache(capacity=2, time_fn=123)


def test_capacity_eviction_order():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    cache.set("c", 3)

    assert cache.keys() == ["c", "a"]
    assert cache.get("b") is None
    assert cache.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)


def test_lru_refresh_on_get():
    clock = [0.0]
    cache = LRUCache(capacity=3, ttl=5, time_fn=lambda: clock[0])

    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") == 1
    cache.set("d", 4)

    assert cache.keys() == ["d", "a", "c"]
    assert "b" not in cache


def test_ttl_expiry_via_get_counts_miss_and_expiration():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=3, time_fn=lambda: clock[0])
    cache.set("a", 1)

    clock[0] = 3.0
    assert cache.get("a") is None
    assert cache.stats() == CacheStats(hits=0, misses=1, evictions=0, expirations=1)
    assert len(cache) == 0


def test_entry_ttl_overrides_default():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])
    cache.set("short", 1, ttl=2)
    cache.set("long", 2, ttl=20)

    clock[0] = 2.0
    assert cache.get("short") is None
    assert cache.get("long") == 2

    assert cache.stats().expirations == 1


def test_ttl_none_override_never_expires():
    clock = [0.0]
    cache = LRUCache(capacity=3, ttl=5, time_fn=lambda: clock[0])
    cache.set("forever", 1, ttl=None)

    clock[0] += 1000
    assert cache.get("forever") == 1
    assert cache.stats().hits == 1


def test_purge_expired_removes_all_and_counts_expirations():
    clock = [0.0]
    cache = LRUCache(capacity=3, ttl=5, time_fn=lambda: clock[0])
    cache.set("a", 1)
    cache.set("b", 2)

    clock[0] = 6.0
    assert cache.purge_expired() == 2
    assert cache.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=2)
    assert list(cache.keys()) == []


def test_delete_return_values_and_expired_delete():
    clock = [0.0]
    cache = LRUCache(capacity=3, ttl=5, time_fn=lambda: clock[0])

    assert cache.delete("missing") is False
    cache.set("a", 1)
    assert cache.delete("a") is True
    assert cache.delete("a") is False

    cache.set("b", 2)
    clock[0] = 6.0
    assert cache.delete("b") is False
    assert cache.stats().expirations == 1


def test_clear_does_not_reset_stats():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=5, time_fn=lambda: clock[0])
    cache.set("a", 1)
    cache.get("a")
    cache.clear()

    assert len(cache) == 0
    assert cache.stats() == CacheStats(hits=1, misses=0, evictions=0, expirations=0)


def test_keys_ordering_excludes_expired_without_mutating_stats():
    clock = [0.0]
    cache = LRUCache(capacity=3, ttl=5, time_fn=lambda: clock[0])
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")
    cache.set("c", 3)

    assert cache.keys() == ["c", "a", "b"]

    clock[0] = 6.0
    assert cache.keys() == []
    assert cache.stats() == CacheStats(hits=1, misses=0, evictions=0, expirations=0)


def test_contains_lazy_expiration_does_not_count_hit_or_miss():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=5, time_fn=lambda: clock[0])
    cache.set("a", 1)
    clock[0] = 5.0

    assert "a" not in cache
    assert cache.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=1)
    assert "a" not in cache
    assert cache.stats().expirations == 1


def test_stats_snapshot_is_independent_of_later_cache_changes():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])
    cache.set("a", 1)
    snapshot = cache.stats()

    cache.set("b", 2)
    cache.get("a")

    assert snapshot == CacheStats(hits=0, misses=0, evictions=0, expirations=0)
    assert cache.stats().hits == 1


def test_set_restarts_ttl_on_existing_key():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])
    cache.set("a", 1)
    clock[0] = 5.0
    cache.set("a", 2)
    clock[0] = 15.0
    assert cache.get("a") is None
    assert cache.stats().expirations == 1


def test_expired_entries_preferred_before_lru_eviction():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=5, time_fn=lambda: clock[0])
    cache.set("a", 1)
    cache.set("b", 2)
    clock[0] = 6.0
    cache.set("c", 3)

    assert cache.keys() == ["c"]
    assert cache.stats().expirations == 2
    assert cache.stats().evictions == 0


def test_get_missing_counts_miss_and_default():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=5, time_fn=lambda: clock[0])
    assert cache.get("missing", 42) == 42
    assert cache.stats() == CacheStats(hits=0, misses=1, evictions=0, expirations=0)


def test_set_rejects_invalid_explicit_ttl_values():
    clock = [0.0]
    cache = LRUCache(capacity=2, ttl=5, time_fn=lambda: clock[0])

    with pytest.raises(ValueError):
        cache.set("a", 1, ttl=0)
    with pytest.raises(ValueError):
        cache.set("a", 1, ttl=-1)
    with pytest.raises(ValueError):
        cache.set("a", 1, ttl="10")
    cache.set("a", 1, ttl=None)
    clock[0] = 1000
    assert cache.get("a") == 1
