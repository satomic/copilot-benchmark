"""Test suite for the ``cache`` package.

Time is always injected through ``time_fn``; no test ever sleeps.
"""

from __future__ import annotations

import threading

import pytest

from cache import CacheStats, LRUCache


class FakeClock:
    """A manually advanced, monotonically non-decreasing clock."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


def make_cache(capacity: int = 2, ttl: float | None = 10.0):
    clock = FakeClock()
    return LRUCache(capacity=capacity, ttl=ttl, time_fn=clock), clock


def test_acceptance_scenario():
    clock = FakeClock()
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

    c2 = LRUCache(capacity=8, ttl=5, time_fn=clock)
    c2.set("forever", 1, ttl=None)
    clock.advance(1000)
    assert c2.get("forever") == 1


def test_constructor_validation():
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=-3)
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(TypeError):
        LRUCache(capacity=2.0)
    with pytest.raises(TypeError):
        LRUCache(capacity="2")
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=-1)
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl="10")
    assert len(LRUCache(capacity=1)) == 0


def test_capacity_eviction_order():
    c, _clock = make_cache(capacity=3, ttl=None)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    c.set("d", 4)  # evicts 'a', the LRU entry

    assert c.keys() == ["d", "c", "b"]
    assert len(c) == 3
    assert c.stats().evictions == 1
    assert "a" not in c


def test_get_refreshes_lru_order():
    c, _clock = make_cache(capacity=3, ttl=None)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)

    assert c.get("a") == 1  # 'a' becomes MRU, 'b' is now LRU
    c.set("d", 4)

    assert c.keys() == ["d", "a", "c"]
    assert c.get("b") is None


def test_set_existing_key_updates_and_refreshes():
    c, clock = make_cache(capacity=2, ttl=10.0)
    c.set("a", 1)
    c.set("b", 2)

    clock.advance(5)
    c.set("a", 99)  # updates value, restarts TTL, becomes MRU
    assert c.keys() == ["a", "b"]
    assert len(c) == 2

    clock.advance(6)  # 'b' deadline was 10.0, 'a' deadline is 15.0
    assert c.get("b") is None
    assert c.get("a") == 99


def test_ttl_expiry_via_get_is_exact_at_deadline():
    c, clock = make_cache(capacity=4, ttl=10.0)
    c.set("a", 1)

    clock.now = 9.999
    assert c.get("a") == 1

    clock.now = 10.0  # exactly at the deadline -> already expired
    assert c.get("a", "fallback") == "fallback"

    stats = c.stats()
    assert stats.expirations == 1
    assert stats.misses == 1
    assert stats.hits == 1
    assert len(c) == 0


def test_per_entry_ttl_overrides_default():
    c, clock = make_cache(capacity=4, ttl=10.0)
    c.set("short", 1, ttl=2)
    c.set("default", 2)
    c.set("long", 3, ttl=100)

    clock.advance(3)
    assert c.get("short") is None
    assert c.get("default") == 2
    assert c.get("long") == 3

    clock.advance(50)
    assert c.get("default") is None
    assert c.get("long") == 3

    with pytest.raises(ValueError):
        c.set("bad", 1, ttl=0)
    with pytest.raises(ValueError):
        c.set("bad", 1, ttl=-5)
    with pytest.raises(ValueError):
        c.set("bad", 1, ttl="5")


def test_ttl_none_override_never_expires():
    c, clock = make_cache(capacity=4, ttl=1.0)
    c.set("forever", "v", ttl=None)
    c.set("mortal", "v")

    clock.advance(10_000)
    assert c.get("forever") == "v"
    assert c.get("mortal") is None

    # A cache with no default TTL still honours a per-entry TTL.
    c2, clock2 = make_cache(capacity=4, ttl=None)
    c2.set("a", 1)
    c2.set("b", 2, ttl=5)
    clock2.advance(5)
    assert c2.get("a") == 1
    assert c2.get("b") is None


def test_purge_expired():
    c, clock = make_cache(capacity=5, ttl=None)
    c.set("a", 1, ttl=1)
    c.set("b", 2, ttl=1)
    c.set("c", 3)

    assert c.purge_expired() == 0
    clock.advance(1)

    assert len(c) == 3  # nothing removed yet: expiry is lazy
    assert c.purge_expired() == 2
    assert c.purge_expired() == 0
    assert c.keys() == ["c"]
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=2)


def test_expired_entries_reclaimed_before_eviction():
    c, clock = make_cache(capacity=2, ttl=None)
    c.set("old", 1, ttl=5)
    c.set("live", 2)

    clock.advance(5)
    c.set("new", 3)  # 'old' is expired, so it is reclaimed instead of evicting

    stats = c.stats()
    assert stats.evictions == 0
    assert stats.expirations == 1
    assert sorted(c.keys()) == ["live", "new"]


def test_delete_return_values_and_stats():
    c, clock = make_cache(capacity=4, ttl=10.0)
    c.set("a", 1)
    c.set("gone", 2, ttl=1)

    assert c.delete("missing") is False
    assert c.delete("a") is True
    assert c.delete("a") is False

    clock.advance(1)
    assert c.delete("gone") is False  # expired -> False, counted as an expiration
    assert len(c) == 0

    stats = c.stats()
    assert stats.hits == 0
    assert stats.misses == 0
    assert stats.expirations == 1
    assert stats.evictions == 0


def test_clear_does_not_reset_stats():
    c, _clock = make_cache(capacity=2, ttl=None)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")
    c.get("zzz")
    c.set("c", 3)  # evicts 'b'

    before = c.stats()
    assert before == CacheStats(hits=1, misses=1, evictions=1, expirations=0)

    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.stats() == before


def test_keys_ordering_and_purity():
    c, clock = make_cache(capacity=3, ttl=None)
    c.set("a", 1, ttl=5)
    c.set("b", 2)
    c.set("c", 3)
    c.get("b")  # 'b' becomes MRU

    assert c.keys() == ["b", "c", "a"]

    clock.advance(5)
    before = c.stats()
    assert c.keys() == ["b", "c"]  # expired 'a' hidden but not removed
    assert len(c) == 3
    assert c.stats() == before


def test_contains_does_not_count_hits_or_misses():
    c, clock = make_cache(capacity=4, ttl=10.0)
    c.set("a", 1)
    c.set("gone", 2, ttl=1)

    assert ("a" in c) is True
    assert ("missing" in c) is False
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=0)

    clock.advance(1)
    assert ("gone" in c) is False  # lazily removed, counted as an expiration
    assert len(c) == 1

    stats = c.stats()
    assert stats.hits == 0
    assert stats.misses == 0
    assert stats.expirations == 1


def test_len_includes_expired_and_never_exceeds_capacity():
    c, clock = make_cache(capacity=2, ttl=1.0)
    c.set("a", 1)
    c.set("b", 2)
    clock.advance(1)

    assert len(c) == 2  # expired but not yet purged
    for i in range(20):
        c.set(f"k{i}", i)
        assert len(c) <= 2


def test_stats_snapshot_is_immutable():
    c, _clock = make_cache(capacity=2, ttl=None)
    c.set("a", 1)
    snapshot = c.get("a") and c.stats()

    c.get("a")
    c.get("nope")

    assert snapshot == CacheStats(hits=1, misses=0, evictions=0, expirations=0)
    assert c.stats() != snapshot
    with pytest.raises(Exception):
        snapshot.hits = 5  # frozen dataclass


def test_thread_safety_under_concurrent_access():
    clock = FakeClock()
    c = LRUCache(capacity=32, ttl=None, time_fn=clock)
    errors: list[BaseException] = []

    def worker(worker_id: int) -> None:
        try:
            for i in range(500):
                key = f"{worker_id}-{i % 40}"
                c.set(key, i)
                c.get(key)
                c.keys()
                key in c
                len(c)
                if i % 50 == 0:
                    c.purge_expired()
                    c.delete(key)
        except BaseException as exc:  # pragma: no cover - only on a real bug
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(c) <= 32
    assert len(c.keys()) <= 32
