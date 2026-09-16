import pytest

from cache import CacheStats, LRUCache


def make_cache(capacity=3, ttl=10):
    clock = [0.0]
    return LRUCache(capacity, ttl, lambda: clock[0]), clock


def test_capacity_eviction_order():
    cache, _ = make_cache(2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.keys() == ["c", "b"]
    assert cache.stats().evictions == 1


def test_get_refreshes_lru_order():
    cache, _ = make_cache(3)
    for key in "abc":
        cache.set(key, key)
    assert cache.get("a") == "a"
    assert cache.keys() == ["a", "c", "b"]


def test_get_expiration_at_deadline():
    cache, clock = make_cache(ttl=5)
    cache.set("a", 1)
    clock[0] = 5
    assert cache.get("a", "missing") == "missing"
    assert cache.stats() == CacheStats(misses=1, expirations=1)


def test_per_entry_ttl_overrides_default():
    cache, clock = make_cache(ttl=10)
    cache.set("short", 1, ttl=2)
    clock[0] = 2
    assert "short" not in cache


def test_none_ttl_override_never_expires():
    cache, clock = make_cache(ttl=1)
    cache.set("forever", 1, ttl=None)
    clock[0] = 100
    assert cache.get("forever") == 1


def test_purge_expired_removes_all_and_counts():
    cache, clock = make_cache(ttl=2)
    cache.set("a", 1)
    cache.set("b", 2, ttl=4)
    clock[0] = 4
    assert cache.purge_expired() == 2
    assert len(cache) == 0
    assert cache.stats().expirations == 2


def test_delete_return_values_and_expired_count():
    cache, clock = make_cache(ttl=2)
    cache.set("a", 1)
    assert cache.delete("a") is True
    assert cache.delete("a") is False
    cache.set("b", 2)
    clock[0] = 2
    assert cache.delete("b") is False
    assert cache.stats().expirations == 1


def test_clear_does_not_reset_stats():
    cache, _ = make_cache(1)
    cache.set("a", 1)
    cache.get("missing")
    cache.clear()
    assert len(cache) == 0
    assert cache.stats().misses == 1


def test_keys_are_mru_first_and_exclude_expired_without_mutation():
    cache, clock = make_cache(ttl=3)
    cache.set("a", 1)
    cache.set("b", 2, ttl=1)
    cache.get("a")
    clock[0] = 1
    before = cache.stats()
    assert cache.keys() == ["a"]
    assert cache.stats() == before
    assert len(cache) == 2


def test_contains_does_not_count_hits_or_misses():
    cache, _ = make_cache()
    cache.set("a", 1)
    assert "a" in cache
    assert "missing" not in cache
    assert cache.stats() == CacheStats()


def test_contains_expired_counts_only_expiration():
    cache, clock = make_cache(ttl=1)
    cache.set("a", 1)
    clock[0] = 1
    assert ("a" in cache) is False
    assert cache.stats() == CacheStats(expirations=1)


def test_constructor_validation():
    with pytest.raises(ValueError):
        LRUCache(0)
    with pytest.raises(TypeError):
        LRUCache(True)
    with pytest.raises(ValueError):
        LRUCache(1, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(1, ttl="bad")


def test_set_validation_and_snapshot():
    cache, _ = make_cache()
    with pytest.raises(ValueError):
        cache.set("a", 1, ttl=0)
    snapshot = cache.stats()
    cache.set("a", 1)
    assert snapshot == CacheStats()
    assert cache.stats().hits == 0


def test_expired_entries_preferred_before_live_eviction():
    cache, clock = make_cache(2, ttl=1)
    cache.set("old", 1)
    cache.set("live", 2, ttl=10)
    clock[0] = 1
    cache.set("new", 3)
    assert cache.keys() == ["new", "live"]
    assert cache.stats().evictions == 0
    assert cache.stats().expirations == 1
