import threading

import pytest

from cache import CacheStats, LRUCache


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


@pytest.fixture
def clock():
    return FakeClock()


def test_acceptance_scenario(clock):
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert c.keys() == ["c", "a"]
    assert c.get("b") is None
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)
    clock.now = 10.0
    assert c.get("a") is None
    assert c.stats().expirations == 1


def test_capacity_eviction_order(clock):
    c = LRUCache(capacity=3, time_fn=clock)
    for k in "abcd":
        c.set(k, k)
    assert "a" not in c
    assert c.keys() == ["d", "c", "b"]
    c.set("e", 5)
    assert c.keys() == ["e", "d", "c"]
    assert c.stats().evictions == 2
    assert len(c) == 3


def test_get_refreshes_lru(clock):
    c = LRUCache(capacity=2, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert c.keys() == ["c", "a"]
    assert c.get("b", "dflt") == "dflt"


def test_set_existing_updates_value_restarts_ttl_and_refreshes(clock):
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(8)
    c.set("a", 11)
    assert c.keys() == ["a", "b"]
    clock.advance(5)  # t=13: 'b' expired (deadline 10), 'a' alive until 18
    assert c.get("a") == 11
    assert c.get("b") is None
    assert c.stats().evictions == 0


def test_ttl_expiry_via_get_exact_boundary(clock):
    c = LRUCache(capacity=4, ttl=5, time_fn=clock)
    c.set("a", 1)
    clock.now = 4.999
    assert c.get("a") == 1
    clock.now = 5.0
    assert c.get("a", "gone") == "gone"
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=0, expirations=1)
    assert len(c) == 0


def test_per_entry_ttl_overrides_default(clock):
    c = LRUCache(capacity=4, ttl=100, time_fn=clock)
    c.set("short", 1, ttl=2)
    c.set("default", 2)
    clock.advance(2)
    assert c.get("short") is None
    assert c.get("default") == 2
    c2 = LRUCache(capacity=4, time_fn=clock)
    c2.set("x", 1, ttl=3)
    clock.advance(3)
    assert c2.get("x") is None


def test_ttl_none_override_never_expires(clock):
    c = LRUCache(capacity=8, ttl=5, time_fn=clock)
    c.set("forever", 1, ttl=None)
    c.set("normal", 2)
    clock.advance(1000)
    assert c.get("forever") == 1
    assert c.get("normal") is None


def test_invalid_set_ttl(clock):
    c = LRUCache(capacity=2, time_fn=clock)
    for bad in (0, -1, -0.5, "5", True, float("nan")):
        with pytest.raises(ValueError):
            c.set("a", 1, ttl=bad)
    assert len(c) == 0


def test_expired_entries_preferred_over_eviction(clock):
    c = LRUCache(capacity=3, time_fn=clock)
    c.set("lru", 1)
    c.set("short", 2, ttl=1)
    c.set("mru", 3)
    clock.advance(1)
    c.set("new", 4)
    assert c.stats().evictions == 0
    assert c.stats().expirations == 1
    assert c.keys() == ["new", "mru", "lru"]


def test_purge_expired(clock):
    c = LRUCache(capacity=5, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=3)
    c.set("c", 3, ttl=None)
    clock.advance(3)
    assert len(c) == 3
    assert c.purge_expired() == 1
    assert len(c) == 2
    clock.advance(7)
    assert c.purge_expired() == 1
    assert c.purge_expired() == 0
    assert c.keys() == ["c"]
    assert c.stats().expirations == 2


def test_delete_return_values(clock):
    c = LRUCache(capacity=4, ttl=5, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.delete("a") is True
    assert c.delete("a") is False
    assert c.delete("missing") is False
    clock.advance(5)
    assert c.delete("b") is False
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=1)


def test_clear_does_not_reset_stats(clock):
    c = LRUCache(capacity=1, time_fn=clock)
    c.set("a", 1)
    c.get("a")
    c.get("x")
    c.set("b", 2)
    before = c.stats()
    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.stats() == before == CacheStats(hits=1, misses=1, evictions=1)


def test_keys_order_and_no_mutation(clock):
    c = LRUCache(capacity=4, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=1)
    c.set("c", 3)
    c.get("a")
    assert c.keys() == ["a", "c", "b"]
    clock.advance(1)
    stats = c.stats()
    assert c.keys() == ["a", "c"]
    assert len(c) == 3
    assert c.stats() == stats


def test_contains_does_not_count_hits_or_misses(clock):
    c = LRUCache(capacity=2, ttl=5, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert "a" in c
    assert "zzz" not in c
    assert c.stats() == CacheStats()
    # __contains__ must not refresh LRU order
    c.set("c", 3)
    assert "a" not in c
    clock.advance(5)
    assert "b" not in c
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=1, expirations=1)
    assert len(c) == 1


def test_len_includes_expired(clock):
    c = LRUCache(capacity=2, ttl=1, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(1)
    assert len(c) == 2
    assert c.keys() == []


def test_stats_snapshot_is_immutable(clock):
    c = LRUCache(capacity=2, time_fn=clock)
    snap = c.stats()
    c.get("x")
    assert snap == CacheStats()
    assert c.stats().misses == 1
    with pytest.raises(Exception):
        snap.hits = 5  # type: ignore[misc]


@pytest.mark.parametrize("cap", [1.0, "3", None, True, False])
def test_constructor_capacity_type_error(cap):
    with pytest.raises(TypeError):
        LRUCache(capacity=cap)


@pytest.mark.parametrize("cap", [0, -1])
def test_constructor_capacity_value_error(cap):
    with pytest.raises(ValueError):
        LRUCache(capacity=cap)


@pytest.mark.parametrize("ttl", [0, -3, "10", float("nan")])
def test_constructor_ttl_validation(ttl):
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=ttl)


def test_many_resets_do_not_leak(clock):
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    for i in range(1000):
        c.set("a", i)
    assert c.get("a") == 999
    assert len(c._heap) <= 2 * 2 + 16


def test_thread_safety(clock):
    c = LRUCache(capacity=50, time_fn=clock)

    def worker(n):
        for i in range(2000):
            c.set((n, i % 100), i)
            c.get((n, (i * 7) % 100))
            (n, i % 10) in c

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    s = c.stats()
    assert len(c) <= 50
    assert s.hits + s.misses == 8 * 2000
