import pytest

from cache import CacheStats, LRUCache


@pytest.fixture
def clock():
    return [0.0]


def make_cache(clock, capacity=3, ttl=10):
    return LRUCache(capacity, ttl=ttl, time_fn=lambda: clock[0])


def test_capacity_eviction_order(clock):
    cache = make_cache(clock, capacity=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.keys() == ["c", "b"]
    assert cache.stats().evictions == 1


def test_get_refreshes_lru(clock):
    cache = make_cache(clock, capacity=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    cache.set("c", 3)
    assert cache.keys() == ["c", "a"]


def test_get_expired_entry_is_miss(clock):
    cache = make_cache(clock)
    cache.set("a", 1)
    clock[0] = 10
    assert cache.get("a", "missing") == "missing"
    assert cache.stats() == CacheStats(misses=1, expirations=1)


def test_per_entry_ttl_overrides_default(clock):
    cache = make_cache(clock, ttl=10)
    cache.set("short", 1, ttl=2)
    clock[0] = 2
    assert "short" not in cache
    assert cache.stats().expirations == 1


def test_none_ttl_override_never_expires(clock):
    cache = make_cache(clock, ttl=1)
    cache.set("forever", 1, ttl=None)
    clock[0] = 100
    assert cache.get("forever") == 1


def test_purge_expired(clock):
    cache = make_cache(clock)
    cache.set("a", 1, ttl=1)
    cache.set("b", 2, ttl=2)
    clock[0] = 2
    assert cache.purge_expired() == 2
    assert len(cache) == 0
    assert cache.stats().expirations == 2


def test_expired_entries_are_preferred_to_eviction(clock):
    cache = make_cache(clock, capacity=2, ttl=1)
    cache.set("a", 1)
    cache.set("b", 2)
    clock[0] = 1
    cache.set("c", 3)
    assert cache.stats().evictions == 0
    assert cache.stats().expirations == 2


def test_delete_return_values(clock):
    cache = make_cache(clock)
    cache.set("a", 1, ttl=1)
    assert cache.delete("a") is True
    assert cache.delete("a") is False
    cache.set("b", 2, ttl=1)
    clock[0] = 1
    assert cache.delete("b") is False
    assert cache.stats().expirations == 1


def test_clear_does_not_reset_stats(clock):
    cache = make_cache(clock)
    cache.set("a", 1)
    assert cache.get("a") == 1
    cache.get("missing")
    cache.clear()
    assert cache.stats() == CacheStats(hits=1, misses=1)


def test_keys_are_mru_first_and_exclude_expired_without_mutation(clock):
    cache = make_cache(clock)
    cache.set("a", 1)
    cache.set("b", 2, ttl=1)
    cache.get("a")
    clock[0] = 1
    assert cache.keys() == ["a"]
    assert len(cache) == 2
    assert cache.stats() == CacheStats(hits=1)


def test_contains_does_not_count_hits_or_misses(clock):
    cache = make_cache(clock)
    cache.set("a", 1, ttl=1)
    assert "a" in cache
    clock[0] = 1
    assert "a" not in cache
    assert cache.stats() == CacheStats(expirations=1)


def test_constructor_validation(clock):
    with pytest.raises(ValueError):
        LRUCache(0)
    with pytest.raises(TypeError):
        LRUCache(1.5)
    with pytest.raises(TypeError):
        LRUCache(True)
    with pytest.raises(ValueError):
        LRUCache(1, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(1, ttl="bad")
    with pytest.raises(ValueError):
        LRUCache(1, ttl=float("nan"))
    with pytest.raises(TypeError):
        LRUCache(1, time_fn=0)


def test_set_validation_and_restart(clock):
    cache = make_cache(clock, ttl=5)
    cache.set("a", 1, ttl=2)
    clock[0] = 1
    cache.set("a", 2, ttl=2)
    clock[0] = 2.9
    assert cache.get("a") == 2
    with pytest.raises(ValueError):
        cache.set("b", 2, ttl=0)
    with pytest.raises(ValueError):
        cache.set("b", 2, ttl=True)


def test_len_includes_expired_entries_and_stats_are_snapshots(clock):
    cache = make_cache(clock)
    cache.set("a", 1, ttl=1)
    snapshot = cache.stats()
    clock[0] = 1
    assert len(cache) == 1
    cache.get("a")
    assert snapshot == CacheStats()
    assert cache.stats().expirations == 1


def test_setting_existing_key_restarts_default_ttl(clock):
    cache = make_cache(clock, ttl=2)
    cache.set("a", 1)
    clock[0] = 1
    cache.set("a", 2)
    clock[0] = 2
    assert cache.get("a") == 2
    clock[0] = 3
    assert cache.get("a") is None


def test_missing_delete_does_not_change_statistics(clock):
    cache = make_cache(clock)
    assert cache.delete("missing") is False
    assert cache.stats() == CacheStats()
