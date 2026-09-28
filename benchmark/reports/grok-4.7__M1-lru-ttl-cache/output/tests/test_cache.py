import threading

import pytest

from cache import LRUCache, CacheStats
import cache


class Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


def test_acceptance_example():
    clock = [0.0]
    c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert c.keys() == ["c", "a"]
    assert c.get("b") is None
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)

    clock[0] = 10.0
    assert c.get("a") is None
    assert c.stats().expirations == 1

    c2 = LRUCache(capacity=8, ttl=5, time_fn=lambda: clock[0])
    c2.set("forever", 1, ttl=None)
    clock[0] += 1000
    assert c2.get("forever") == 1

    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(TypeError):
        LRUCache(capacity=True)


def test_public_exports():
    assert cache.__all__ == ["LRUCache", "CacheStats"]
    assert cache.LRUCache is LRUCache
    assert cache.CacheStats is CacheStats


def test_eviction_order_and_lru_refresh_on_get():
    clock = Clock()
    c = LRUCache(capacity=3, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["c", "b", "a"]
    assert c.get("a") == 1
    c.set("d", 4)
    assert "b" not in c
    assert c.keys() == ["d", "a", "c"]
    assert c.stats() == CacheStats(hits=1, evictions=1)


def test_ttl_expiry_via_get_exact_boundary():
    clock = Clock()
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c.set("a", 1)
    clock.advance(9.0)
    assert c.get("a") == 1
    assert c.stats() == CacheStats(hits=1)
    clock.now = 10.0
    assert c.get("a", "gone") == "gone"
    assert c.stats() == CacheStats(hits=1, misses=1, expirations=1)
    assert len(c) == 0
    assert c.get("a", "gone") == "gone"
    assert c.stats() == CacheStats(hits=1, misses=2, expirations=1)


def test_per_entry_ttl_overrides_default():
    clock = Clock()
    c = LRUCache(capacity=4, ttl=5, time_fn=clock)
    c.set("short", 1)
    c.set("long", 2, ttl=50)
    c.set("custom_short", 3, ttl=1)
    clock.advance(1)
    assert c.get("custom_short") is None
    assert c.get("short") == 1
    assert c.get("long") == 2
    clock.advance(4)
    assert c.get("short") is None
    assert c.get("long") == 2
    clock.advance(45)
    assert c.get("long") is None
    assert c.stats().evictions == 0


def test_ttl_none_override_and_omitted_default():
    clock = Clock()
    c = LRUCache(capacity=4, ttl=5, time_fn=clock)
    c.set("temp", 1)
    c.set("forever", 2, ttl=None)
    clock.advance(5)
    assert c.get("temp") is None
    assert c.get("forever") == 2
    clock.advance(1000)
    assert c.get("forever") == 2

    never = LRUCache(capacity=2, ttl=None, time_fn=clock)
    never.set("a", 1)
    never.set("b", 2, ttl=3)
    clock.advance(3)
    assert never.get("a") == 1
    assert never.get("b") is None


def test_purge_expired():
    clock = Clock()
    c = LRUCache(capacity=4, ttl=10, time_fn=clock)
    c.set("a", 1, ttl=1)
    c.set("b", 2, ttl=2)
    c.set("c", 3, ttl=None)
    assert c.purge_expired() == 0
    clock.advance(1)
    assert c.purge_expired() == 1
    assert c.stats().expirations == 1
    assert len(c) == 2
    clock.advance(1)
    assert c.purge_expired() == 1
    assert "c" in c
    assert c.keys() == ["c"]
    assert c.purge_expired() == 0
    assert c.stats().hits == 0
    assert c.stats().misses == 0


def test_delete_return_values():
    clock = Clock()
    c = LRUCache(capacity=2, ttl=5, time_fn=clock)
    assert c.delete("missing") is False
    assert c.stats() == CacheStats()
    c.set("a", 1)
    c.set("b", 2)
    assert c.delete("a") is True
    assert "a" not in c
    assert c.stats() == CacheStats()
    clock.advance(5)
    assert c.delete("b") is False
    assert len(c) == 0
    assert c.stats() == CacheStats(expirations=1)
    assert c.delete("b") is False
    assert c.stats() == CacheStats(expirations=1)


def test_clear_does_not_reset_stats():
    clock = Clock()
    c = LRUCache(capacity=2, ttl=5, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")
    c.get("missing")
    c.set("c", 3)
    before = c.stats()
    assert before == CacheStats(hits=1, misses=1, evictions=1)
    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert "a" not in c
    assert c.stats() == before
    c.set("a", 1)
    clock.advance(5)
    c.clear()
    assert c.stats() == before


def test_keys_ordering_excludes_expired_without_mutation():
    clock = Clock()
    c = LRUCache(capacity=3, ttl=10, time_fn=clock)
    c.set("a", 1, ttl=1)
    c.set("b", 2)
    c.set("c", 3)
    c.get("b")
    assert c.keys() == ["b", "c", "a"]
    clock.advance(1)
    before = c.stats()
    assert c.keys() == ["b", "c"]
    assert len(c) == 3
    assert c.stats() == before
    assert c.keys() == ["b", "c"]
    assert c.purge_expired() == 1
    assert len(c) == 2


def test_contains_does_not_count_hits_or_misses():
    clock = Clock()
    c = LRUCache(capacity=2, ttl=5, time_fn=clock)
    c.set("a", 1)
    assert ("a" in c) is True
    assert ("missing" in c) is False
    assert c.stats() == CacheStats()
    assert c.keys() == ["a"]
    clock.advance(5)
    assert ("a" in c) is False
    assert c.stats() == CacheStats(expirations=1)
    assert len(c) == 0
    assert c.stats().hits == 0
    assert c.stats().misses == 0


def test_constructor_validation():
    clock = Clock()
    with pytest.raises(TypeError):
        LRUCache(True)
    with pytest.raises(TypeError):
        LRUCache(False)
    with pytest.raises(TypeError):
        LRUCache(1.5)
    with pytest.raises(TypeError):
        LRUCache("2")
    with pytest.raises(ValueError):
        LRUCache(0)
    with pytest.raises(ValueError):
        LRUCache(-3)
    with pytest.raises(ValueError):
        LRUCache(1, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(1, ttl=-1)
    with pytest.raises(ValueError):
        LRUCache(1, ttl=0.0)
    with pytest.raises(ValueError):
        LRUCache(1, ttl="5")
    with pytest.raises(ValueError):
        LRUCache(1, ttl=True)
    with pytest.raises(ValueError):
        LRUCache(1, ttl=float("nan"))
    LRUCache(1, ttl=None, time_fn=clock)
    LRUCache(1, ttl=0.25, time_fn=clock)
    LRUCache(1, ttl=2, time_fn=clock)


def test_set_ttl_validation_does_not_mutate():
    clock = Clock()
    c = LRUCache(capacity=1, ttl=10, time_fn=clock)
    c.set("keep", 1)
    for bad in (0, -1, 0.0, "1", True, False, float("nan")):
        with pytest.raises(ValueError):
            c.set("other", 2, ttl=bad)
    assert c.keys() == ["keep"]
    assert len(c) == 1
    assert c.stats() == CacheStats()
    c.set("keep", 3, ttl=None)
    clock.advance(100)
    assert c.get("keep") == 3


def test_expired_preferred_over_lru_eviction():
    clock = Clock()
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c.set("live", 1, ttl=100)
    c.set("stale", 2, ttl=1)
    clock.advance(1)
    c.set("new", 3)
    assert c.stats() == CacheStats(expirations=1)
    assert c.get("live") == 1
    assert c.get("new") == 3
    assert c.get("stale") is None
    assert c.stats() == CacheStats(hits=2, misses=1, evictions=0, expirations=1)

    both = LRUCache(capacity=2, ttl=5, time_fn=clock)
    both.set("a", 1)
    both.set("b", 2)
    clock.advance(5)
    both.set("c", 3)
    assert both.stats() == CacheStats(expirations=2)
    assert len(both) == 1
    assert both.keys() == ["c"]


def test_len_includes_unpurged_expired_and_never_exceeds_capacity():
    clock = Clock()
    c = LRUCache(capacity=2, ttl=1, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(1)
    assert len(c) == 2
    assert c.keys() == []
    assert len(c) == 2
    c.set("c", 3)
    assert len(c) == 1
    assert len(c) <= 2
    for i in range(10):
        c.set(i, i)
        assert len(c) <= 2


def test_stats_snapshot_is_independent():
    clock = Clock()
    c = LRUCache(capacity=1, time_fn=clock)
    c.set("a", 1)
    c.get("a")
    snap = c.stats()
    c.get("missing")
    c.set("b", 2)
    assert snap == CacheStats(hits=1)
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1)
    with pytest.raises(Exception):
        snap.hits = 9  # frozen dataclass


def test_update_existing_restarts_ttl_and_refreshes_lru():
    clock = Clock()
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(9)
    c.set("a", 7)
    clock.advance(9)
    assert c.get("a") == 7
    clock.now = 9 + 10
    assert c.get("a") is None
    assert c.stats().expirations == 1

    c2 = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c2.set("a", 1, ttl=1)
    c2.set("b", 2, ttl=100)
    clock.advance(1)
    c2.set("a", 5)
    assert c2.stats().expirations == 0
    assert c2.stats().evictions == 0
    assert len(c2) == 2
    c2.set("c", 3)
    assert "b" not in c2
    assert c2.get("a") == 5
    assert c2.stats().evictions == 1


def test_get_stored_none_and_custom_default():
    clock = Clock()
    c = LRUCache(capacity=2, time_fn=clock)
    assert c.get("missing", 42) == 42
    c.set("n", None)
    assert c.get("n", 42) is None
    assert "n" in c
    assert c.stats() == CacheStats(misses=1, hits=1)


def test_capacity_one_and_refresh_prevents_self_eviction():
    clock = Clock()
    c = LRUCache(capacity=1, ttl=5, time_fn=clock)
    c.set("a", 1)
    c.set("a", 2)
    assert c.stats().evictions == 0
    assert c.get("a") == 2
    c.set("b", 3)
    assert c.get("a") is None
    assert c.get("b") == 3
    assert c.stats().evictions == 1


def test_lazy_expiry_when_not_at_capacity():
    clock = Clock()
    c = LRUCache(capacity=3, ttl=1, time_fn=clock)
    c.set("a", 1)
    clock.advance(1)
    c.set("b", 2)
    assert len(c) == 2
    assert c.keys() == ["b"]
    assert c.stats().expirations == 0
    assert c.purge_expired() == 1


def test_concurrent_access_does_not_corrupt():
    c = LRUCache(capacity=32, ttl=None, time_fn=lambda: 0.0)
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(300):
                key = (n, i % 40)
                c.set(key, i)
                c.get(key)
                if i % 5 == 0:
                    c.delete(key)
                if i % 7 == 0:
                    key in c
                    len(c)
                    c.keys()
                    c.stats()
                    c.purge_expired()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(c) <= 32
    snap = c.stats()
    assert snap.hits >= 0 and snap.misses >= 0
    assert snap.evictions >= 0 and snap.expirations == 0
