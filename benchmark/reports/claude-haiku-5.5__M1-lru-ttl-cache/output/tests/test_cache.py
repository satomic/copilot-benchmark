import threading

import pytest

from cache import CacheStats, LRUCache


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(capacity=3, ttl=None):
    clock = FakeClock()
    return LRUCache(capacity=capacity, ttl=ttl, time_fn=clock), clock


def test_capacity_eviction_order():
    c, _ = make(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # evicts 'a' (LRU)
    assert c.keys() == ["c", "b"]
    assert c.get("a") is None
    assert c.stats().evictions == 1
    assert len(c) == 2


def test_get_refreshes_lru_position():
    c, _ = make(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)  # evicts 'b', not 'a'
    assert c.keys() == ["c", "a"]
    assert "b" not in c


def test_ttl_expiry_via_get_exact_deadline():
    c, clock = make(capacity=4, ttl=10)
    c.set("k", "v")
    clock.advance(9.999)
    assert c.get("k") == "v"
    clock.advance(0.001)  # exactly t0 + ttl -> already expired
    assert c.get("k", "gone") == "gone"
    s = c.stats()
    assert s.expirations == 1
    assert s.misses == 1
    assert s.hits == 1
    assert len(c) == 0


def test_per_entry_ttl_overrides_default():
    c, clock = make(capacity=4, ttl=10)
    c.set("short", 1, ttl=2)
    c.set("default", 2)
    clock.advance(2)
    assert c.get("short") is None
    assert c.get("default") == 2


def test_ttl_none_overrides_default_ttl():
    c, clock = make(capacity=4, ttl=5)
    c.set("forever", 1, ttl=None)
    c.set("normal", 2)
    clock.advance(1000)
    assert c.get("forever") == 1
    assert c.get("normal") is None


def test_purge_expired_removes_and_counts():
    c, clock = make(capacity=5, ttl=10)
    c.set("a", 1)
    c.set("b", 2, ttl=3)
    c.set("forever", 3, ttl=None)
    clock.advance(5)
    assert c.purge_expired() == 1  # only 'b'
    clock.advance(5)
    assert c.purge_expired() == 1  # 'a'
    assert c.purge_expired() == 0
    assert c.stats().expirations == 2
    assert c.keys() == ["forever"]


def test_delete_return_values_and_stats():
    c, clock = make(capacity=4, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    assert c.delete("a") is True
    assert c.delete("a") is False
    assert c.delete("missing") is False
    clock.advance(10)
    assert c.delete("b") is False  # expired
    s = c.stats()
    assert s.expirations == 1
    assert s.hits == 0 and s.misses == 0
    assert len(c) == 0


def test_clear_does_not_reset_stats():
    c, _ = make(capacity=2)
    c.set("a", 1)
    c.get("a")
    c.get("zzz")
    c.set("b", 2)
    c.set("c", 3)
    before = c.stats()
    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.stats() == before


def test_keys_ordering_excludes_expired_without_mutating():
    c, clock = make(capacity=4)
    c.set("a", 1, ttl=5)
    c.set("b", 2)
    c.set("c", 3, ttl=100)
    c.get("a")  # MRU order: a, c, b (most recent first)
    assert c.keys() == ["a", "c", "b"]
    clock.advance(5)  # 'a' expired
    stats_before = c.stats()
    assert c.keys() == ["c", "b"]
    assert len(c) == 3  # expired entry still counted until purged
    assert c.stats() == stats_before


def test_contains_does_not_count_hits_or_misses():
    c, clock = make(capacity=4, ttl=5)
    c.set("a", 1)
    assert "a" in c
    assert "missing" not in c
    assert c.stats() == CacheStats()
    clock.advance(5)
    assert "a" not in c
    s = c.stats()
    assert s.expirations == 1
    assert s.hits == 0 and s.misses == 0
    assert len(c) == 0


def test_constructor_validation():
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=-1)
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(TypeError):
        LRUCache(capacity=2.0)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=-3)
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl="10")
    LRUCache(capacity=1, ttl=None)  # valid


def test_set_rejects_invalid_ttl():
    c, _ = make()
    for bad in (0, -1, "5", True, float("nan")):
        with pytest.raises(ValueError):
            c.set("k", 1, ttl=bad)
    assert len(c) == 0


def test_expired_entries_make_room_before_lru_eviction():
    c, clock = make(capacity=2)
    c.set("short", 1, ttl=1)
    c.set("long", 2, ttl=100)
    clock.advance(1)
    c.set("new", 3)  # 'short' expired -> dropped, no eviction
    assert c.stats().expirations == 1
    assert c.stats().evictions == 0
    assert c.keys() == ["new", "long"]


def test_set_existing_key_restarts_ttl_and_refreshes_lru():
    c, clock = make(capacity=2, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(8)
    c.set("a", 10)  # new value, new deadline, now MRU
    clock.advance(8)  # 'b' expired (t=16 >= 10), 'a' still live (deadline 18)
    assert c.get("a") == 10
    assert c.get("b") is None
    assert len(c) == 1


def test_stats_snapshot_is_immutable_copy():
    c, _ = make(capacity=2)
    c.set("a", 1)
    snap = c.stats()
    c.get("a")
    c.get("x")
    assert snap == CacheStats(hits=0, misses=0, evictions=0, expirations=0)
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=0, expirations=0)
    with pytest.raises(Exception):
        snap.hits = 99  # frozen dataclass


def test_len_counts_expired_until_purged():
    c, clock = make(capacity=3, ttl=1)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(1)
    assert len(c) == 2
    assert c.purge_expired() == 2
    assert len(c) == 0


def test_heap_compaction_under_churn_keeps_behaviour():
    c, clock = make(capacity=4, ttl=50)
    for i in range(5000):
        c.set("k", i)  # repeated replacement leaves stale heap items
    assert c.get("k") == 4999
    assert len(c) == 1
    clock.advance(50)
    assert c.purge_expired() == 1
    assert c.stats().expirations == 1


def test_concurrent_access_from_threads():
    c, clock = make(capacity=32, ttl=1000)
    errors = []

    def worker(n):
        try:
            for i in range(500):
                c.set((n, i % 40), i)
                c.get((n, (i * 7) % 40))
                c.delete((n, (i * 3) % 40))
                _ = (n, 0) in c
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(c) <= 32


def test_spec_acceptance_example():
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
