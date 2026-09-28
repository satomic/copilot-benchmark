import pytest

from cache import CacheStats, LRUCache


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_capacity_evicts_least_recently_used():
    cache = LRUCache(2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    assert cache.keys() == ["c", "b"]
    assert cache.get("a") is None
    assert cache.stats().evictions == 1


def test_get_refreshes_lru_order():
    cache = LRUCache(2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    cache.set("c", 3)

    assert cache.get("b") is None
    assert cache.keys() == ["c", "a"]


def test_get_expires_at_exact_deadline_and_counts_miss():
    clock = FakeClock()
    cache = LRUCache(2, ttl=5, time_fn=clock)
    cache.set("a", 1)
    clock.now = 5

    assert cache.get("a", "missing") == "missing"
    assert cache.stats() == CacheStats(misses=1, expirations=1)


def test_per_entry_ttl_overrides_default():
    clock = FakeClock()
    cache = LRUCache(3, ttl=10, time_fn=clock)
    cache.set("short", 1, ttl=2)
    cache.set("long", 2, ttl=20)
    clock.now = 3

    assert cache.get("short") is None
    assert cache.get("long") == 2


def test_none_ttl_override_never_expires():
    clock = FakeClock()
    cache = LRUCache(2, ttl=1, time_fn=clock)
    cache.set("forever", 1, ttl=None)
    clock.now = 100

    assert cache.get("forever") == 1


def test_set_without_ttl_uses_default_but_none_disables_it():
    clock = FakeClock()
    cache = LRUCache(2, ttl=2, time_fn=clock)
    cache.set("default", 1)
    cache.set("forever", 2, ttl=None)
    clock.now = 3

    assert cache.get("default") is None
    assert cache.get("forever") == 2


def test_purge_expired_removes_all_and_counts_them():
    clock = FakeClock()
    cache = LRUCache(4, time_fn=clock)
    cache.set("a", 1, ttl=1)
    cache.set("b", 2, ttl=2)
    cache.set("live", 3, ttl=None)
    clock.now = 2

    assert cache.purge_expired() == 2
    assert len(cache) == 1
    assert cache.stats().expirations == 2


def test_expired_entries_are_removed_before_lru_eviction():
    clock = FakeClock()
    cache = LRUCache(2, time_fn=clock)
    cache.set("expired", 1, ttl=1)
    cache.set("live", 2, ttl=None)
    clock.now = 1

    cache.set("new", 3)

    assert cache.keys() == ["new", "live"]
    assert cache.stats().evictions == 0
    assert cache.stats().expirations == 1


def test_delete_return_values_and_expiration():
    clock = FakeClock()
    cache = LRUCache(2, time_fn=clock)
    cache.set("present", 1, ttl=1)
    assert cache.delete("present") is True
    assert cache.delete("absent") is False
    cache.set("expired", 2, ttl=1)
    clock.now = 1

    assert cache.delete("expired") is False
    assert cache.stats() == CacheStats(expirations=1)


def test_clear_does_not_reset_stats():
    cache = LRUCache(2)
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None
    before = cache.stats()

    cache.clear()

    assert len(cache) == 0
    assert cache.stats() == before


def test_keys_are_mru_first_and_do_not_mutate_expired_entries():
    clock = FakeClock()
    cache = LRUCache(3, time_fn=clock)
    cache.set("expired", 1, ttl=1)
    cache.set("b", 2, ttl=None)
    cache.set("c", 3, ttl=None)
    clock.now = 1

    assert cache.keys() == ["c", "b"]
    assert len(cache) == 3
    assert cache.stats().expirations == 0


def test_contains_lazily_expires_without_hits_or_misses():
    clock = FakeClock()
    cache = LRUCache(2, time_fn=clock)
    cache.set("a", 1, ttl=1)
    assert "a" in cache
    clock.now = 1

    assert "a" not in cache
    assert cache.stats() == CacheStats(expirations=1)


def test_existing_key_update_restarts_ttl_and_refreshes_order():
    clock = FakeClock()
    cache = LRUCache(2, ttl=5, time_fn=clock)
    cache.set("a", 1)
    cache.set("b", 2, ttl=None)
    clock.now = 4
    cache.set("a", 10)
    clock.now = 6

    assert cache.get("a") == 10
    assert cache.keys() == ["a", "b"]


@pytest.mark.parametrize("capacity", [0, -1])
def test_invalid_capacity_value_raises_value_error(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity)


@pytest.mark.parametrize("capacity", [True, 1.5, "2"])
def test_invalid_capacity_type_raises_type_error(capacity):
    with pytest.raises(TypeError):
        LRUCache(capacity)


@pytest.mark.parametrize("ttl", [0, -1, float("nan"), float("inf"), "2", True])
def test_invalid_default_ttl_raises_value_error(ttl):
    with pytest.raises(ValueError):
        LRUCache(1, ttl=ttl)


def test_invalid_per_entry_ttl_raises_value_error():
    cache = LRUCache(1)

    with pytest.raises(ValueError):
        cache.set("a", 1, ttl=0)
