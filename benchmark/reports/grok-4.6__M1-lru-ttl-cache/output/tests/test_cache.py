import threading

import pytest

from cache import CacheStats, LRUCache


def _cache(capacity=2, ttl=10.0, clock=None):
    if clock is None:
        clock = [0.0]
    return LRUCache(capacity=capacity, ttl=ttl, time_fn=lambda: clock[0]), clock


def test_constructor_validation():
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=-1)
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(TypeError):
        LRUCache(capacity=1.5)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=-1)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl="1")


def test_capacity_eviction_order():
    c, _ = _cache(capacity=2, ttl=None)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["c", "b"]
    assert c.get("a") is None
    assert c.stats() == CacheStats(hits=0, misses=1, evictions=1, expirations=0)


def test_lru_refresh_on_get():
    c, clock = _cache(capacity=2, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert c.keys() == ["c", "a"]
    assert c.get("b") is None
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)


def test_ttl_expiry_via_get():
    c, clock = _cache(capacity=2, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")
    c.set("c", 3)
    clock[0] = 10.0
    assert c.get("a") is None
    assert c.stats().expirations == 1
    assert c.stats().misses == 1


def test_per_entry_ttl_overrides_default():
    c, clock = _cache(capacity=4, ttl=10)
    c.set("short", 1, ttl=2)
    c.set("default", 2)
    clock[0] = 2.0
    assert c.get("short") is None
    assert c.get("default") == 2


def test_ttl_none_override_never_expires():
    clock = [0.0]
    c = LRUCache(capacity=8, ttl=5, time_fn=lambda: clock[0])
    c.set("forever", 1, ttl=None)
    clock[0] += 1000
    assert c.get("forever") == 1


def test_purge_expired():
    c, clock = _cache(capacity=4, ttl=5)
    c.set("a", 1)
    c.set("b", 2, ttl=20)
    c.set("c", 3)
    clock[0] = 5.0
    removed = c.purge_expired()
    assert removed == 2
    assert c.keys() == ["b"]
    assert c.stats().expirations == 2
    assert len(c) == 1


def test_delete_return_values():
    c, clock = _cache(capacity=3, ttl=5)
    c.set("a", 1)
    c.set("b", 2)
    assert c.delete("a") is True
    assert c.delete("missing") is False
    clock[0] = 5.0
    assert c.delete("b") is False
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=1)
    assert "b" not in c


def test_clear_does_not_reset_stats():
    c, _ = _cache(capacity=2, ttl=None)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    c.get("b")
    c.get("missing")
    stats_before = c.stats()
    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.stats() == stats_before
    assert stats_before.evictions == 1
    assert stats_before.hits == 1
    assert stats_before.misses == 1


def test_keys_ordering_mru_first():
    c, _ = _cache(capacity=3, ttl=None)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    c.get("a")
    assert c.keys() == ["a", "c", "b"]


def test_keys_excludes_expired_without_mutating():
    c, clock = _cache(capacity=3, ttl=5)
    c.set("a", 1)
    c.set("b", 2)
    clock[0] = 5.0
    assert c.keys() == []
    assert len(c) == 2
    assert c.stats().expirations == 0


def test_contains_does_not_count_hits_or_misses():
    c, clock = _cache(capacity=2, ttl=5)
    c.set("a", 1)
    assert ("a" in c) is True
    assert ("missing" in c) is False
    clock[0] = 5.0
    assert ("a" in c) is False
    stats = c.stats()
    assert stats.hits == 0
    assert stats.misses == 0
    assert stats.expirations == 1


def test_set_existing_key_updates_and_refreshes_lru():
    c, clock = _cache(capacity=2, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    c.set("a", 9)
    assert c.get("a") == 9
    c.set("c", 3)
    assert "b" not in c
    assert c.keys() == ["c", "a"]
    clock[0] = 10.0
    c.set("a", 8)
    clock[0] = 19.9
    assert c.get("a") == 8


def test_expired_preferred_over_lru_eviction():
    c, clock = _cache(capacity=2, ttl=None)
    c.set("old", 1, ttl=5)
    c.set("live", 2, ttl=100)
    c.get("old")
    clock[0] = 5.0
    c.set("new", 3, ttl=5)
    assert c.keys() == ["new", "live"]
    assert c.stats().expirations == 1
    assert c.stats().evictions == 0


def test_len_includes_expired_until_purged():
    c, clock = _cache(capacity=2, ttl=3)
    c.set("a", 1)
    c.set("b", 2)
    clock[0] = 3.0
    assert len(c) == 2
    c.purge_expired()
    assert len(c) == 0


def test_stats_snapshot_is_independent():
    c, _ = _cache(capacity=2, ttl=None)
    c.set("a", 1)
    snap = c.stats()
    c.get("a")
    c.get("missing")
    assert snap == CacheStats(hits=0, misses=0, evictions=0, expirations=0)
    assert c.stats().hits == 1


def test_set_invalid_ttl():
    c, _ = _cache()
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=0)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=-5)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=True)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl="soon")


def test_thread_safety_smoke():
    clock = [0.0]
    c = LRUCache(capacity=50, ttl=None, time_fn=lambda: clock[0])
    errors = []

    def worker(start):
        try:
            for i in range(start, start + 40):
                c.set(i, i)
                c.get(i)
                _ = i in c
                c.keys()
                c.stats()
                len(c)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i * 40,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
