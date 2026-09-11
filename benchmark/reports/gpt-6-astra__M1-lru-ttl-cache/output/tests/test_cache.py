from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from fractions import Fraction
import random
from threading import Barrier

import pytest

import cache
from cache import CacheStats, LRUCache


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


def test_package_surface():
    assert cache.__all__ == ["LRUCache", "CacheStats"]
    assert CacheStats() == CacheStats(0, 0, 0, 0)


@pytest.mark.parametrize("capacity", [0, -1, -100])
def test_nonpositive_capacity(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity)


@pytest.mark.parametrize("capacity", [True, False, 1.0, "2", None, []])
def test_noninteger_capacity(capacity):
    with pytest.raises(TypeError):
        LRUCache(capacity)


@pytest.mark.parametrize(
    "ttl", [0, -1, float("nan"), -float("inf"), "1", [], 1j, True, False]
)
def test_invalid_ttl_in_constructor_and_set(ttl, clock):
    with pytest.raises(ValueError):
        LRUCache(1, ttl=ttl, time_fn=clock)
    c = LRUCache(1, time_fn=clock)
    c.set("a", 1)
    with pytest.raises(ValueError):
        c.set("a", 2, ttl=ttl)
    assert c.keys() == ["a"]
    assert c.stats() == CacheStats()
    assert c.get("a") == 1


def test_capacity_eviction_order(clock):
    c = LRUCache(2, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["c", "b"]
    assert c.get("a") is None
    assert c.stats() == CacheStats(misses=1, evictions=1)


def test_get_refreshes_lru(clock):
    c = LRUCache(2, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert c.keys() == ["c", "a"]
    assert c.get("b") is None
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1)
    clock.now = 10.0
    assert c.get("a") is None
    assert c.stats().expirations == 1


def test_expiration_boundary_and_no_ttl_refresh_on_get(clock):
    c = LRUCache(1, ttl=5, time_fn=clock)
    c.set("a", 1)
    clock.now = 4.999
    assert c.get("a") == 1
    clock.now = 5.0
    assert c.get("a", "expired") == "expired"
    assert c.get("a") is None
    assert len(c) == 0
    assert c.stats() == CacheStats(hits=1, misses=2, expirations=1)


def test_per_entry_ttl_override(clock):
    c = LRUCache(3, ttl=5, time_fn=clock)
    c.set("default", 1)
    c.set("short", 2, ttl=1)
    c.set("long", 3, ttl=10)
    clock.advance(1)
    assert c.get("short") is None
    assert c.get("default") == 1
    clock.advance(4)
    assert c.get("default") is None
    assert c.get("long") == 3
    clock.advance(5)
    assert c.get("long") is None


def test_explicit_none_overrides_default(clock):
    c = LRUCache(8, ttl=5, time_fn=clock)
    c.set("forever", 1, ttl=None)
    c.set("default", 2)
    clock.advance(1000)
    assert c.get("forever") == 1
    assert c.get("default") is None


def test_no_default_ttl(clock):
    c = LRUCache(2, time_fn=clock)
    c.set("forever", None)
    clock.advance(1e20)
    assert c.get("forever", "missing") is None
    assert c.stats() == CacheStats(hits=1)


def test_update_restarts_ttl_and_refreshes_recency(clock):
    c = LRUCache(2, ttl=5, time_fn=clock)
    c.set("a", 1, ttl=1)
    c.set("b", 2)
    clock.advance(0.5)
    c.set("a", 3)
    assert c.keys() == ["a", "b"]
    clock.now = 1.0
    assert c.purge_expired() == 0
    assert c.get("a") == 3
    clock.now = 5.5
    assert c.get("a") is None
    assert c.stats().evictions == 0


def test_update_between_finite_and_infinite_ttl(clock):
    c = LRUCache(1, ttl=1, time_fn=clock)
    c.set("a", 1)
    c.set("a", 2, ttl=None)
    clock.advance(10)
    assert c.purge_expired() == 0
    assert c.get("a") == 2
    c.set("a", 3)
    clock.advance(1)
    assert c.purge_expired() == 1
    assert c.stats().evictions == 0


def test_setting_expired_key_counts_expiration(clock):
    c = LRUCache(1, ttl=1, time_fn=clock)
    c.set("a", 1)
    clock.advance(1)
    c.set("a", 2)
    assert c.get("a") == 2
    assert c.stats() == CacheStats(hits=1, expirations=1)


def test_expired_mru_preferred_over_live_lru(clock):
    c = LRUCache(3, time_fn=clock)
    c.set("old-live", 1)
    c.set("expired-1", 2, ttl=2)
    c.set("expired-2", 3, ttl=1)
    clock.advance(2)
    c.set("new", 4)
    assert c.keys() == ["new", "old-live"]
    assert len(c) == 2
    assert c.stats() == CacheStats(expirations=2)


def test_purge_all_expired_with_unordered_deadlines(clock):
    c = LRUCache(6, time_fn=clock)
    for key, ttl in [("a", 9), ("b", 1), ("c", 5), ("d", 1), ("e", 2)]:
        c.set(key, key, ttl=ttl)
    c.set("forever", 0)
    clock.advance(5)
    assert c.purge_expired() == 4
    assert c.purge_expired() == 0
    assert c.keys() == ["forever", "a"]
    assert c.stats() == CacheStats(expirations=4)


def test_delete_live_missing_and_expired(clock):
    c = LRUCache(2, time_fn=clock)
    c.set("live", 1)
    c.set("expired", 2, ttl=1)
    clock.advance(1)
    assert c.delete("live") is True
    assert c.delete("live") is False
    assert c.delete("missing") is False
    assert c.delete("expired") is False
    assert c.delete("expired") is False
    assert c.stats() == CacheStats(expirations=1)
    assert c.purge_expired() == 0


def test_clear_preserves_all_statistics(clock):
    c = LRUCache(1, ttl=1, time_fn=clock)
    c.set("a", 1)
    c.get("a")
    c.set("b", 2)
    clock.advance(1)
    c.get("b")
    c.set("c", 3)
    before = c.stats()
    assert before == CacheStats(hits=1, misses=1, evictions=1, expirations=1)
    clock.advance(1)
    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.purge_expired() == 0
    assert c.stats() == before
    c.set("d", 4)
    assert c.get("d") == 4


def test_keys_order_and_no_mutation(clock):
    c = LRUCache(3, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=1)
    c.set("c", 3)
    assert c.keys() == ["c", "b", "a"]
    c.get("a")
    clock.advance(1)
    before = c.stats()
    keys = c.keys()
    assert keys == ["a", "c"]
    keys.clear()
    assert c.keys() == ["a", "c"]
    assert len(c) == 3
    assert c.stats() == before
    assert c.purge_expired() == 1


def test_len_includes_unpurged_expired_entries(clock):
    c = LRUCache(2, ttl=1, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(1)
    assert len(c) == 2
    assert c.stats() == CacheStats()
    assert c.purge_expired() == 2
    assert len(c) == 0


def test_contains_does_not_count_access_or_refresh_recency(clock):
    c = LRUCache(2, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=1)
    assert "a" in c
    assert "missing" not in c
    assert c.keys() == ["b", "a"]
    assert c.stats() == CacheStats()
    clock.advance(1)
    assert "b" not in c
    assert "b" not in c
    assert len(c) == 1
    assert c.stats() == CacheStats(expirations=1)


def test_stats_are_immutable_snapshots(clock):
    c = LRUCache(1, time_fn=clock)
    before = c.stats()
    with pytest.raises(FrozenInstanceError):
        before.hits = 10
    c.get("missing")
    assert before == CacheStats()
    assert c.stats() == CacheStats(misses=1)
    assert c.stats() is not c.stats()


def test_hashable_keys_and_arbitrary_values(clock):
    c = LRUCache(4, time_fn=clock)
    values = [None, [], {}, object()]
    keys = [None, ("tuple", 1), 42, object()]
    for key, value in zip(keys, values):
        c.set(key, value, ttl=1)
        assert c.get(key) is value
    clock.advance(1)
    assert c.purge_expired() == 4


def test_positive_real_and_infinite_ttls(clock):
    c = LRUCache(3, time_fn=clock)
    c.set("fraction", 1, ttl=Fraction(1, 2))
    c.set("infinite", 2, ttl=float("inf"))
    c.set("large", 3, ttl=10**1000)
    clock.advance(0.5)
    assert c.purge_expired() == 1
    assert c.keys() == ["large", "infinite"]


def test_negative_clock_and_signed_zero_deadlines():
    clock = Clock(-10.0)
    c = LRUCache(4, time_fn=clock)
    c.set("positive", 1, ttl=11)
    c.set("negative", 2, ttl=1)
    c.set("zero", 3, ttl=10)
    clock.now = -9.0
    assert c.purge_expired() == 1
    clock.now = -0.0
    assert c.purge_expired() == 1
    assert c.keys() == ["positive"]


def test_expiration_index_reclaims_updated_and_deleted_entries(clock):
    c = LRUCache(2, time_fn=clock)
    for i in range(1000):
        c.set("a", i, ttl=i + 1)
        c.set("b", i, ttl=i + 2)
        assert c.delete("b")
    c.delete("a")
    assert not c._expiry.children
    assert c.purge_expired() == 0
    assert c.stats() == CacheStats()


def test_set_and_get_do_not_scan_resident_entries(clock):
    from collections import OrderedDict

    class NoScanEntries(OrderedDict):
        def __iter__(self):
            raise AssertionError("unexpected entry scan")

        def items(self):
            raise AssertionError("unexpected entry scan")

        def values(self):
            raise AssertionError("unexpected entry scan")

    c = LRUCache(1000, time_fn=clock)
    for i in range(999):
        c.set(i, i, ttl=100)
    c.set("expired", 0, ttl=1)
    c._entries = NoScanEntries(c._entries)
    clock.advance(1)
    c.set("new", 1)
    c.set("new", 2, ttl=20)
    assert c.get("new") == 2
    assert c.stats() == CacheStats(hits=1, expirations=1)


def test_randomized_against_simple_reference(clock):
    rng = random.Random(8128)
    c = LRUCache(7, ttl=3, time_fn=clock)
    entries = {}
    counts = dict(hits=0, misses=0, evictions=0, expirations=0)

    def expired(key):
        deadline = entries[key][1]
        return deadline is not None and clock.now >= deadline

    def purge():
        dead = [key for key in entries if expired(key)]
        for key in dead:
            del entries[key]
        counts["expirations"] += len(dead)
        return len(dead)

    for i in range(3000):
        key = rng.randrange(12)
        op = rng.choice(["set", "get", "delete", "contains", "purge", "keys", "clear"])
        if op == "set":
            ttl = rng.choice([None, 0.25, 1, 3, 10])
            if key in entries:
                counts["expirations"] += int(expired(key))
                del entries[key]
            elif len(entries) == 7:
                purge()
                if len(entries) == 7:
                    del entries[next(iter(entries))]
                    counts["evictions"] += 1
            entries[key] = (i, None if ttl is None else clock.now + ttl)
            c.set(key, i, ttl=ttl)
        elif op in ("get", "delete", "contains"):
            if key in entries and expired(key):
                del entries[key]
                counts["expirations"] += 1
            present = key in entries
            if op == "get":
                expected = entries[key][0] if present else "missing"
                counts["hits" if present else "misses"] += 1
                if present:
                    entries[key] = entries.pop(key)
                assert c.get(key, "missing") == expected
            elif op == "delete":
                if present:
                    del entries[key]
                assert c.delete(key) is present
            else:
                assert (key in c) is present
        elif op == "purge":
            assert c.purge_expired() == purge()
        elif op == "clear":
            c.clear()
            entries.clear()
        assert c.keys() == [key for key in reversed(entries) if not expired(key)]
        assert len(c) == len(entries) <= 7
        assert c.stats() == CacheStats(**counts)
        clock.advance(rng.choice([0, 0.25, 1]))


def test_concurrent_operations_preserve_entries_and_counters(clock):
    workers = 8
    rounds = 100
    c = LRUCache(workers * rounds, time_fn=clock)
    barrier = Barrier(workers)

    def work(worker):
        barrier.wait(timeout=10)
        for i in range(rounds):
            key = (worker, i)
            c.set(key, i, ttl=10)
            assert c.get(key) == i
            assert key in c
            assert c.get(("missing", worker, i)) is None
            assert c.delete(key)
            assert not c.delete(key)
            assert c.purge_expired() == 0
            assert 0 <= len(c) <= workers * rounds
            c.keys()
            c.stats()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, range(workers)))
    assert len(c) == 0
    assert c.stats() == CacheStats(hits=workers * rounds, misses=workers * rounds)


def test_concurrent_clear_and_eviction_stay_bounded(clock):
    c = LRUCache(5, ttl=1, time_fn=clock)
    barrier = Barrier(6)

    def work(worker):
        barrier.wait(timeout=10)
        for i in range(200):
            key = (worker, i % 10)
            c.set(key, i)
            c.get(key)
            c.delete((worker, (i + 1) % 10))
            if i % 17 == 0:
                c.clear()
            c.purge_expired()
            assert len(c) <= 5
            assert len(c.keys()) <= 5
            assert c.stats().expirations == 0

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(work, range(6)))
    clock.advance(1)
    c.purge_expired()
    assert len(c) == 0
