import math
import threading
import pytest

from cache import LRUCache, CacheStats


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._time = start
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._time

    def advance(self, delta: float) -> None:
        with self._lock:
            self._time += delta

    def set(self, value: float) -> None:
        with self._lock:
            self._time = value


def test_acceptance_criteria():
    clock = [0.0]
    c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # 'a' is now MRU
    c.set("c", 3)  # evicts 'b'
    assert c.keys() == ["c", "a"]
    assert c.get("b") is None
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)

    clock[0] = 10.0  # exactly at the deadline -> already expired
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


def test_constructor_validation():
    # Capacity validation
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(TypeError):
        LRUCache(capacity=False)
    with pytest.raises(TypeError):
        LRUCache(capacity=1.5)  # type: ignore
    with pytest.raises(TypeError):
        LRUCache(capacity="10")  # type: ignore
    with pytest.raises(TypeError):
        LRUCache(capacity=None)  # type: ignore
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=-5)

    # TTL validation in constructor
    with pytest.raises(ValueError):
        LRUCache(capacity=5, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=5, ttl=-1.0)
    with pytest.raises(ValueError):
        LRUCache(capacity=5, ttl=float("nan"))
    with pytest.raises(ValueError):
        LRUCache(capacity=5, ttl=float("inf"))
    with pytest.raises(ValueError):
        LRUCache(capacity=5, ttl=True)  # type: ignore
    with pytest.raises(ValueError):
        LRUCache(capacity=5, ttl="10")  # type: ignore

    # time_fn validation
    with pytest.raises(TypeError):
        LRUCache(capacity=5, time_fn="not_callable")  # type: ignore


def test_capacity_eviction_order():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=3, time_fn=clock)

    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.keys() == ["c", "b", "a"]

    # Adding 4th element evicts LRU which is 'a'
    cache.set("d", 4)
    assert cache.keys() == ["d", "c", "b"]
    assert cache.get("a") is None
    assert cache.stats().evictions == 1
    assert cache.stats().misses == 1


def test_lru_refresh_on_get():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=3, time_fn=clock)

    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    # Access 'a', making it MRU
    assert cache.get("a") == 1
    assert cache.keys() == ["a", "c", "b"]

    # Now 'b' is LRU; adding 'd' should evict 'b'
    cache.set("d", 4)
    assert cache.keys() == ["d", "a", "c"]
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.stats().evictions == 1


def test_lru_refresh_on_set_existing():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=3, ttl=10.0, time_fn=clock)

    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    clock.advance(5.0)
    # Re-setting 'a' updates value, resets its TTL, and makes it MRU
    cache.set("a", 100)
    assert cache.keys() == ["a", "c", "b"]

    # Advance clock to 12.0: 'b' and 'c' (set at 0.0 with TTL 10) have expired, but 'a' (re-set at 5.0) expires at 15.0
    clock.set(12.0)
    assert cache.get("a") == 100
    assert cache.get("b") is None
    assert cache.get("c") is None


def test_ttl_expiry_via_get():
    clock = FakeClock(100.0)
    cache = LRUCache(capacity=5, ttl=10.0, time_fn=clock)

    cache.set("x", 42)
    # Right before expiration
    clock.set(109.999)
    assert cache.get("x") == 42
    assert cache.stats().hits == 1

    # Exactly at expiration deadline -> already expired
    clock.set(119.999)
    res = cache.get("x", default="missing")
    assert res == "missing"
    assert cache.stats().expirations == 1
    assert cache.stats().misses == 1

    # Key was removed lazily
    assert len(cache) == 0


def test_per_entry_ttl_overriding_default():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=5, ttl=10.0, time_fn=clock)

    cache.set("default_entry", 1)
    cache.set("short_entry", 2, ttl=2.0)
    cache.set("long_entry", 3, ttl=20.0)

    clock.advance(3.0)
    # short_entry should be expired (t0=0 + 2 <= 3)
    assert cache.get("short_entry") is None
    # default_entry and long_entry should be alive
    assert cache.get("default_entry") == 1
    assert cache.get("long_entry") == 3

    clock.advance(8.0)  # clock now at 11.0
    # default_entry should be expired (10 <= 11)
    assert cache.get("default_entry") is None
    # long_entry should still be alive (expires at 20.0)
    assert cache.get("long_entry") == 3


def test_ttl_none_override():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=2, ttl=5.0, time_fn=clock)

    cache.set("immortal", "alive", ttl=None)
    cache.set("mortal", "alive")  # uses default ttl 5.0

    clock.advance(100.0)
    assert cache.get("immortal") == "alive"
    assert cache.get("mortal") is None
    assert cache.stats().expirations == 1


def test_purge_expired():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=5, ttl=10.0, time_fn=clock)

    cache.set("a", 1, ttl=5.0)
    cache.set("b", 2, ttl=15.0)
    cache.set("c", 3, ttl=5.0)
    cache.set("d", 4, ttl=None)

    clock.advance(6.0)
    # 'a' and 'c' expired at 5.0; 'b' and 'd' are alive
    purged = cache.purge_expired()
    assert purged == 2
    assert cache.stats().expirations == 2
    assert len(cache) == 2
    assert set(cache.keys()) == {"b", "d"}

    # Running purge again when none expired returns 0
    assert cache.purge_expired() == 0
    assert cache.stats().expirations == 2


def test_delete_return_values_and_expiry():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=5, ttl=10.0, time_fn=clock)

    cache.set("live", 1)
    cache.set("expired", 2, ttl=5.0)

    # Delete non-existent
    assert cache.delete("non_existent") is False
    assert cache.stats().hits == 0
    assert cache.stats().misses == 0
    assert cache.stats().expirations == 0

    # Delete live
    assert cache.delete("live") is True
    assert cache.stats().hits == 0
    assert cache.stats().misses == 0
    assert cache.stats().expirations == 0
    assert len(cache) == 1

    # Delete expired
    clock.advance(6.0)
    assert cache.delete("expired") is False
    assert cache.stats().expirations == 1
    assert cache.stats().hits == 0
    assert cache.stats().misses == 0
    assert len(cache) == 0


def test_clear_not_resetting_stats():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=2, ttl=5.0, time_fn=clock)

    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # hit
    cache.get("z")  # miss
    clock.advance(10.0)
    cache.get("b")  # expiration + miss

    initial_stats = cache.stats()
    assert initial_stats.hits == 1
    assert initial_stats.misses == 2
    assert initial_stats.expirations == 1

    cache.clear()
    assert len(cache) == 0
    assert cache.keys() == []
    # Stats remain unchanged after clear
    cleared_stats = cache.stats()
    assert cleared_stats == initial_stats


def test_keys_ordering_and_no_mutation():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=5, ttl=10.0, time_fn=clock)

    cache.set("first", 1)
    cache.set("second", 2)
    cache.set("third", 3)
    cache.get("first")  # first becomes MRU

    assert cache.keys() == ["first", "third", "second"]

    # Mark "second" as expired
    cache.set("temp", 4, ttl=2.0)
    assert cache.keys() == ["temp", "first", "third", "second"]

    clock.advance(3.0)
    # keys() excludes "temp", but does NOT mutate cache or stats
    keys_result = cache.keys()
    assert keys_result == ["first", "third", "second"]
    assert len(cache) == 4  # "temp" still physically present
    assert cache.stats().expirations == 0


def test_contains_behavior():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=5, ttl=10.0, time_fn=clock)

    cache.set("live", 1)
    cache.set("expiring", 2, ttl=5.0)

    # Missing
    assert ("ghost" in cache) is False
    assert cache.stats().hits == 0
    assert cache.stats().misses == 0

    # Live
    assert ("live" in cache) is True
    assert cache.stats().hits == 0
    assert cache.stats().misses == 0

    # Expired
    clock.advance(6.0)
    assert ("expiring" in cache) is False
    assert cache.stats().expirations == 1
    assert cache.stats().hits == 0
    assert cache.stats().misses == 0
    assert len(cache) == 1


def test_len_includes_expired_until_purged():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=2, ttl=5.0, time_fn=clock)

    cache.set("a", 1)
    cache.set("b", 2)
    assert len(cache) == 2

    clock.advance(10.0)
    # Both are expired, but len still reports 2
    assert len(cache) == 2

    # Purging cleans them up
    cache.purge_expired()
    assert len(cache) == 0


def test_expired_preferred_over_live_on_eviction():
    clock = FakeClock(0.0)
    # Capacity 2
    cache = LRUCache(capacity=2, time_fn=clock)

    # 'a' has TTL 10; 'b' has TTL 2
    cache.set("a", 100, ttl=10.0)  # 'a' is LRU
    cache.set("b", 200, ttl=2.0)   # 'b' is MRU

    clock.advance(5.0)
    # At t=5, 'b' is expired, but 'a' is live.
    # Inserting 'c' should drop expired 'b' (counting 1 expiration), freeing room,
    # so live LRU 'a' is NOT evicted!
    cache.set("c", 300, ttl=10.0)

    assert cache.stats().expirations == 1
    assert cache.stats().evictions == 0
    assert cache.get("a") == 100
    assert cache.get("c") == 300
    assert cache.get("b") is None


def test_stats_snapshot_immutability():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=3, time_fn=clock)

    s1 = cache.stats()
    assert s1 == CacheStats(hits=0, misses=0, evictions=0, expirations=0)

    cache.set("a", 1)
    cache.get("a")
    cache.get("missing")

    s2 = cache.stats()
    assert s2 == CacheStats(hits=1, misses=1, evictions=0, expirations=0)
    # s1 remains unchanged
    assert s1 == CacheStats(hits=0, misses=0, evictions=0, expirations=0)

    # Mutating frozen dataclass raises FrozenInstanceError
    with pytest.raises(Exception):
        s2.hits = 99  # type: ignore


def test_set_ttl_validation():
    cache = LRUCache(capacity=3)
    with pytest.raises(ValueError):
        cache.set("k", "v", ttl=0)
    with pytest.raises(ValueError):
        cache.set("k", "v", ttl=-1)
    with pytest.raises(ValueError):
        cache.set("k", "v", ttl="invalid")  # type: ignore
    with pytest.raises(ValueError):
        cache.set("k", "v", ttl=False)  # type: ignore
    with pytest.raises(ValueError):
        cache.set("k", "v", ttl=float("nan"))
    with pytest.raises(ValueError):
        cache.set("k", "v", ttl=float("inf"))


def test_multithreaded_concurrency():
    clock = FakeClock(0.0)
    cache = LRUCache(capacity=10, ttl=50.0, time_fn=clock)

    num_threads = 8
    ops_per_thread = 200

    def worker(tid: int):
        for i in range(ops_per_thread):
            key = f"k_{i % 20}"
            cache.set(key, i, ttl=None if i % 5 == 0 else 10.0)
            cache.get(key)
            if i % 3 == 0:
                _ = key in cache
            if i % 7 == 0:
                cache.delete(key)
            if i % 15 == 0:
                cache.keys()
            if i % 25 == 0:
                cache.purge_expired()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Cache should be in consistent state and stats should be non-negative
    stats = cache.stats()
    assert stats.hits >= 0
    assert stats.misses >= 0
    assert stats.evictions >= 0
    assert stats.expirations >= 0
    assert len(cache) <= 10
