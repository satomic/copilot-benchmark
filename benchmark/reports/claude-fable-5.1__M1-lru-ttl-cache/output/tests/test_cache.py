import threading

import pytest

from cache import LRUCache, CacheStats


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


def make(capacity=3, ttl=None, clock=None):
    return LRUCache(capacity=capacity, ttl=ttl, time_fn=clock or FakeClock())


# --------------------------------------------------------------- construction


@pytest.mark.parametrize("bad", [0, -1])
def test_capacity_below_one_raises_value_error(bad):
    with pytest.raises(ValueError):
        LRUCache(capacity=bad)


@pytest.mark.parametrize("bad", [True, False, 1.0, "2", None])
def test_non_int_capacity_raises_type_error(bad):
    with pytest.raises(TypeError):
        LRUCache(capacity=bad)


@pytest.mark.parametrize("bad", [0, -1, -0.5, "10", True, float("nan")])
def test_invalid_default_ttl_raises_value_error(bad):
    with pytest.raises(ValueError):
        LRUCache(capacity=1, ttl=bad)


def test_valid_construction_and_package_surface():
    import cache

    assert cache.__all__ == ["LRUCache", "CacheStats"]
    c = LRUCache(capacity=1)
    assert len(c) == 0
    assert c.stats() == CacheStats()
    c2 = LRUCache(capacity=1, ttl=2.5)
    assert c2.keys() == []


# ------------------------------------------------------------------- LRU core


def test_capacity_eviction_order_is_lru(clock):
    c = make(capacity=2, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # evicts 'a'
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3
    assert c.stats().evictions == 1
    assert len(c) == 2


def test_get_refreshes_lru_position(clock):
    c = make(capacity=2, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # 'a' becomes MRU
    c.set("c", 3)  # evicts 'b'
    assert "b" not in c
    assert c.keys() == ["c", "a"]
    assert c.stats().evictions == 1


def test_set_existing_key_updates_value_and_moves_to_mru(clock):
    c = make(capacity=2, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("a", 10)
    assert c.keys() == ["a", "b"]
    assert len(c) == 2
    c.set("c", 3)  # evicts 'b', the LRU
    assert c.keys() == ["c", "a"]
    assert c.get("a") == 10
    assert c.stats().evictions == 1


def test_get_default_and_miss_counting(clock):
    c = make(clock=clock)
    assert c.get("missing") is None
    assert c.get("missing", "dflt") == "dflt"
    assert c.stats() == CacheStats(hits=0, misses=2)


# ------------------------------------------------------------------------ TTL


def test_ttl_expiry_via_get_at_exact_deadline(clock):
    c = make(capacity=2, ttl=10, clock=clock)
    c.set("a", 1)
    clock.advance(9.999)
    assert c.get("a") == 1
    clock.advance(0.001)  # now == t0 + ttl -> already expired
    assert c.get("a") is None
    assert c.get("a", "d") == "d"  # gone: plain miss, no second expiration
    assert c.stats() == CacheStats(hits=1, misses=2, evictions=0, expirations=1)
    assert len(c) == 0


def test_set_restarts_ttl(clock):
    c = make(ttl=10, clock=clock)
    c.set("a", 1)
    clock.advance(8)
    c.set("a", 2)
    clock.advance(8)
    assert c.get("a") == 2
    clock.advance(2)
    assert c.get("a") is None


def test_per_entry_ttl_overrides_default(clock):
    c = make(ttl=10, clock=clock)
    c.set("short", 1, ttl=2)
    c.set("long", 2, ttl=50)
    c.set("default", 3)
    clock.advance(2)
    assert c.get("short") is None
    assert c.get("long") == 2
    assert c.get("default") == 3
    clock.advance(8)
    assert c.get("default") is None
    assert c.get("long") == 2
    clock.advance(40)
    assert c.get("long") is None
    assert c.stats().expirations == 3


def test_ttl_none_override_never_expires(clock):
    c = make(capacity=8, ttl=5, clock=clock)
    c.set("forever", 1, ttl=None)
    c.set("temp", 2)
    clock.advance(1000)
    assert c.get("forever") == 1
    assert c.get("temp") is None
    assert "forever" in c
    assert c.keys() == ["forever"]


def test_default_ttl_none_means_never_expire(clock):
    c = make(ttl=None, clock=clock)
    c.set("a", 1)
    clock.advance(1e9)
    assert c.get("a") == 1
    assert c.purge_expired() == 0


@pytest.mark.parametrize("bad", [0, -1, -2.5, "5", True, float("nan")])
def test_set_with_invalid_ttl_raises_value_error(bad, clock):
    c = make(clock=clock)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=bad)
    assert len(c) == 0


def test_expired_entries_dropped_before_evicting_live_ones(clock):
    c = make(capacity=3, ttl=10, clock=clock)
    c.set("a", 1, ttl=1)
    c.set("b", 2)
    c.set("c", 3)
    clock.advance(1)
    assert len(c) == 3  # 'a' expired but not yet purged
    c.set("d", 4)  # room made by dropping expired 'a'; no eviction
    assert c.stats().evictions == 0
    assert c.stats().expirations == 1
    assert c.keys() == ["d", "c", "b"]
    c.set("e", 5)  # no expired entries -> LRU 'b' evicted
    assert c.stats().evictions == 1
    assert c.keys() == ["e", "d", "c"]
    assert len(c) == 3


def test_expired_entry_with_re_set_deadline_is_not_wrongly_dropped(clock):
    c = make(capacity=2, ttl=10, clock=clock)
    c.set("a", 1, ttl=1)
    c.set("a", 1, ttl=100)  # stale heap item for old deadline must be ignored
    c.set("b", 2)
    clock.advance(5)
    c.set("c", 3)  # nothing expired -> LRU 'a' is evicted, not expired
    assert c.stats().expirations == 0
    assert c.stats().evictions == 1
    assert c.keys() == ["c", "b"]


def test_purge_expired_removes_only_expired_and_counts(clock):
    c = make(capacity=5, ttl=10, clock=clock)
    c.set("a", 1, ttl=1)
    c.set("b", 2, ttl=2)
    c.set("c", 3)
    c.set("d", 4, ttl=None)
    clock.advance(2)
    assert c.purge_expired() == 2
    assert c.purge_expired() == 0
    assert len(c) == 2
    assert c.keys() == ["d", "c"]
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=2)


# ------------------------------------------------------------ other operations


def test_delete_return_values_and_stats(clock):
    c = make(ttl=10, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.delete("a") is True
    assert c.delete("a") is False
    assert c.delete("nope") is False
    clock.advance(10)
    assert c.delete("b") is False  # expired: counts an expiration
    assert len(c) == 0
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=1)


def test_clear_removes_entries_but_keeps_stats(clock):
    c = make(capacity=2, ttl=10, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    c.get("c")
    c.get("zzz")
    before = c.stats()
    assert before == CacheStats(hits=1, misses=1, evictions=1, expirations=0)
    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.stats() == before
    c.set("x", 1)
    assert c.get("x") == 1
    assert c.stats().hits == 2


def test_keys_ordering_mru_first_excludes_expired_without_mutation(clock):
    c = make(capacity=4, ttl=10, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3, ttl=1)
    c.set("d", 4)
    assert c.keys() == ["d", "c", "b", "a"]
    c.get("a")
    assert c.keys() == ["a", "d", "c", "b"]
    clock.advance(1)
    stats_before = c.stats()
    assert c.keys() == ["a", "d", "b"]
    assert len(c) == 4  # keys() did not remove the expired entry
    assert c.stats() == stats_before


def test_contains_does_not_count_hits_or_misses(clock):
    c = make(ttl=10, clock=clock)
    c.set("a", 1)
    assert "a" in c
    assert "b" not in c
    assert c.stats() == CacheStats()
    clock.advance(10)
    assert "a" not in c  # lazily removed, one expiration
    assert len(c) == 0
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=1)


def test_contains_does_not_refresh_lru(clock):
    c = make(capacity=2, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert "a" in c
    assert c.keys() == ["b", "a"]


def test_len_includes_expired_and_never_exceeds_capacity(clock):
    c = make(capacity=2, ttl=1, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(1)
    assert len(c) == 2
    c.set("c", 3)
    assert len(c) <= 2
    assert c.keys() == ["c"]


def test_stats_snapshot_is_immutable_and_independent(clock):
    c = make(clock=clock)
    c.set("a", 1)
    snap = c.stats()
    c.get("a")
    c.get("b")
    assert snap == CacheStats()
    assert c.stats() == CacheStats(hits=1, misses=1)
    with pytest.raises(Exception):
        snap.hits = 5  # frozen dataclass


def test_mixed_key_types_with_equal_deadlines(clock):
    c = make(capacity=4, ttl=10, clock=clock)
    c.set("s", 1)
    c.set(1, 2)
    c.set((1, 2), 3)
    c.set(None, 4)
    clock.advance(10)
    c.set("new", 5)  # drops expired entries; must not compare keys
    assert c.keys() == ["new"]
    assert c.stats().expirations == 4


def test_only_time_fn_is_used_as_time_source(monkeypatch, clock):
    import time as _time

    def boom(*_a, **_k):
        raise AssertionError("cache must not call time.* directly")

    monkeypatch.setattr(_time, "monotonic", boom)
    monkeypatch.setattr(_time, "time", boom)
    c = make(capacity=2, ttl=5, clock=clock)
    c.set("a", 1)
    assert c.get("a") == 1
    assert "a" in c
    c.keys()
    c.purge_expired()
    c.delete("a")


# ---------------------------------------------------------------- concurrency


def test_thread_safety_under_concurrent_access(clock):
    c = make(capacity=50, ttl=1000, clock=clock)
    errors = []

    def worker(n):
        try:
            for i in range(500):
                key = (n, i % 20)
                c.set(key, i)
                c.get(key)
                c.get(("other", i))
                if i % 7 == 0:
                    c.delete(key)
                if i % 50 == 0:
                    c.keys()
                    c.purge_expired()
                    _ = key in c
                    len(c)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(c) <= 50
    s = c.stats()
    assert s.hits + s.misses == 8 * 500 * 2
