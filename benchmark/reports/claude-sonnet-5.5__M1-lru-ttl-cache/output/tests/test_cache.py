import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cache import CacheStats, LRUCache  # noqa: E402


@pytest.fixture
def clock():
    return [0.0]


def make(clock, capacity=2, ttl=None):
    return LRUCache(capacity, ttl=ttl, time_fn=lambda: clock[0])


def test_eviction_order(clock):
    c = make(clock, 2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["c", "b"]
    assert c.stats().evictions == 1
    assert len(c) == 2


def test_get_refreshes_lru(clock):
    c = make(clock, 2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert c.get("b") is None
    assert c.keys() == ["c", "a"]
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)


def test_set_existing_updates_and_refreshes(clock):
    c = make(clock, 2, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    clock[0] = 5
    c.set("a", 9)
    assert c.keys() == ["a", "b"]
    clock[0] = 12
    assert c.get("a") == 9  # TTL restarted at t=5
    assert c.get("b") is None


def test_ttl_expiry_via_get_exact_deadline(clock):
    c = make(clock, 2, ttl=10)
    c.set("a", 1)
    clock[0] = 9.999
    assert c.get("a") == 1
    clock[0] = 10.0
    assert c.get("a", "d") == "d"
    s = c.stats()
    assert (s.expirations, s.misses, s.hits) == (1, 1, 1)
    assert len(c) == 0


def test_per_entry_ttl_overrides_default(clock):
    c = make(clock, 4, ttl=10)
    c.set("short", 1, ttl=2)
    c.set("long", 2, ttl=100)
    c.set("default", 3)
    clock[0] = 5
    assert c.get("short") is None
    assert c.get("default") == 3
    clock[0] = 50
    assert c.get("default") is None
    assert c.get("long") == 2


def test_ttl_none_override_never_expires(clock):
    c = make(clock, 4, ttl=5)
    c.set("forever", 1, ttl=None)
    c.set("normal", 2)
    clock[0] += 1000
    assert c.get("forever") == 1
    assert c.get("normal") is None


def test_purge_expired(clock):
    c = make(clock, 5, ttl=10)
    c.set("a", 1)
    c.set("b", 2, ttl=20)
    c.set("c", 3, ttl=None)
    clock[0] = 10
    assert c.purge_expired() == 1
    assert len(c) == 2
    assert c.stats().expirations == 1
    assert c.purge_expired() == 0


def test_delete_return_values(clock):
    c = make(clock, 3, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    assert c.delete("a") is True
    assert c.delete("a") is False
    clock[0] = 10
    assert c.delete("b") is False
    s = c.stats()
    assert (s.expirations, s.hits, s.misses) == (1, 0, 0)


def test_clear_keeps_stats(clock):
    c = make(clock, 2)
    c.set("a", 1)
    c.get("a")
    c.get("x")
    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.stats() == CacheStats(hits=1, misses=1)


def test_keys_ordering_and_no_mutation(clock):
    c = make(clock, 3, ttl=10)
    c.set("a", 1)
    c.set("b", 2, ttl=100)
    c.set("c", 3)
    c.get("a")
    assert c.keys() == ["a", "c", "b"]
    clock[0] = 10
    before = c.stats()
    assert c.keys() == ["a", "c", "b"][2:]
    assert c.stats() == before
    assert len(c) == 3


def test_contains_no_hit_miss(clock):
    c = make(clock, 2, ttl=10)
    c.set("a", 1)
    assert "a" in c
    assert "z" not in c
    clock[0] = 10
    assert "a" not in c
    assert c.stats() == CacheStats(expirations=1)
    assert len(c) == 0


def test_expired_preferred_over_lru_eviction(clock):
    c = make(clock, 2)
    c.set("old", 1, ttl=5)
    c.set("live", 2, ttl=None)
    c.get("old")
    clock[0] = 5
    c.set("new", 3)
    assert c.keys() == ["new", "live"]
    assert c.stats() == CacheStats(hits=1, expirations=1, evictions=0)


def test_stats_snapshot_is_immutable(clock):
    c = make(clock)
    snap = c.stats()
    c.set("a", 1)
    c.get("a")
    assert snap == CacheStats()
    assert c.stats().hits == 1


def test_constructor_validation():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            LRUCache(bad)
    for bad in (True, 1.5, "3", None):
        with pytest.raises(TypeError):
            LRUCache(bad)
    for bad in (0, -1, "x", True):
        with pytest.raises(ValueError):
            LRUCache(2, ttl=bad)
    assert LRUCache(1, ttl=0.5) is not None


def test_set_ttl_validation(clock):
    c = make(clock)
    for bad in (0, -3, "x"):
        with pytest.raises(ValueError):
            c.set("a", 1, ttl=bad)
    assert len(c) == 0


def test_many_overwrites_keep_heap_bounded(clock):
    c = make(clock, 2, ttl=10)
    for i in range(1000):
        c.set("a", i)
    assert len(c._heap) <= 2 * 2 + 16 + 1
    assert c.get("a") == 999
