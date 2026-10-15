import threading
import pytest

from cache import CacheStats, LRUCache


class FakeClock:
    def __init__(self, initial: float = 0.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_constructor_validation() -> None:
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=-5)
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(TypeError):
        LRUCache(capacity=False)
    with pytest.raises(TypeError):
        LRUCache(capacity=2.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        LRUCache(capacity="2")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=0)
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=-1.0)
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl="10")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=float("nan"))


def test_set_ttl_validation() -> None:
    clock = FakeClock()
    c = LRUCache(capacity=2, time_fn=clock)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=0)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=-5)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=False)  # type: ignore[arg-type]
    assert len(c) == 0


def test_capacity_eviction_order() -> None:
    clock = FakeClock()
    c = LRUCache(capacity=3, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    c.set("d", 4)  # evicts 'a'

    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3
    assert c.get("d") == 4
    assert c.stats() == CacheStats(hits=3, misses=1, evictions=1, expirations=0)


def test_lru_refresh_on_get_and_set() -> None:
    clock = FakeClock()
    c = LRUCache(capacity=2, ttl=10, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # 'a' is now MRU, 'b' is LRU

    c.set("c", 3)  # evicts 'b'
    assert c.keys() == ["c", "a"]
    assert c.get("b", "missing") == "missing"

    # Updating 'a' via set makes 'a' MRU again and updates value
    c.set("a", 10)
    assert c.keys() == ["a", "c"]
    c.set("d", 4)  # evicts 'c'
    assert c.keys() == ["d", "a"]
    assert c.get("a") == 10


def test_ttl_expiry_via_get_and_exact_deadline() -> None:
    clock = FakeClock(100.0)
    c = LRUCache(capacity=2, ttl=10.0, time_fn=clock)
    c.set("a", 1)

    clock.advance(9.999)
    assert c.get("a") == 1

    # Exactly at t0 + t -> already expired
    clock.now = 110.0
    assert c.get("a", "expired") == "expired"
    assert len(c) == 0
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=0, expirations=1)


def test_per_entry_ttl_overrides_default() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=4, ttl=10.0, time_fn=clock)
    c.set("short", "s", ttl=3.0)
    c.set("default", "d")
    c.set("long", "l", ttl=20.0)

    clock.advance(3.0)
    assert c.get("short") is None
    assert c.get("default") == "d"
    assert c.get("long") == "l"

    clock.advance(7.0)  # t = 10.0
    assert c.get("default") is None
    assert c.get("long") == "l"

    clock.advance(10.0)  # t = 20.0
    assert c.get("long") is None
    assert c.stats().expirations == 3


def test_ttl_none_override_never_expires() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=4, ttl=5.0, time_fn=clock)
    c.set("forever", 42, ttl=None)
    c.set("ephemeral", 99)

    clock.advance(1000.0)
    assert c.get("forever") == 42
    assert c.get("ephemeral") is None
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=0, expirations=1)


def test_set_existing_key_restarts_ttl() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=2, ttl=10.0, time_fn=clock)
    c.set("a", 1)

    clock.advance(8.0)
    c.set("a", 2)  # restarts TTL: now expires at 18.0

    clock.advance(5.0)  # t = 13.0
    assert c.get("a") == 2

    clock.advance(5.0)  # t = 18.0
    assert c.get("a") is None


def test_expired_entries_preferred_over_live_when_making_room() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=3, ttl=10.0, time_fn=clock)
    c.set("lru_live", 1, ttl=20.0)
    c.set("mid_expiring", 2, ttl=5.0)
    c.set("mru_live", 3, ttl=20.0)

    clock.advance(6.0)  # 'mid_expiring' is expired, 'lru_live' is still live
    c.set("new_key", 4)

    assert c.keys() == ["new_key", "mru_live", "lru_live"]
    assert len(c) == 3
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=1)


def test_purge_expired() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=5, ttl=10.0, time_fn=clock)
    c.set("a", 1, ttl=5.0)
    c.set("b", 2, ttl=5.0)
    c.set("c", 3, ttl=15.0)
    c.set("d", 4, ttl=None)

    clock.advance(5.0)
    assert len(c) == 4  # lazy: still 4 before purge
    removed = c.purge_expired()
    assert removed == 2
    assert len(c) == 2
    assert c.keys() == ["d", "c"]
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=2)


def test_delete_semantics() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=3, ttl=10.0, time_fn=clock)
    c.set("live", 1)
    c.set("expiring", 2, ttl=4.0)

    assert c.delete("missing") is False
    assert c.delete("live") is True
    assert c.delete("live") is False

    clock.advance(4.0)
    assert c.delete("expiring") is False
    assert len(c) == 0
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=1)


def test_clear_preserves_stats() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=2, ttl=10.0, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    assert c.get("missing") is None
    c.set("c", 3)  # evicts 'b'

    c.clear()
    assert len(c) == 0
    assert c.keys() == []
    assert c.stats() == CacheStats(hits=1, misses=1, evictions=1, expirations=0)


def test_keys_ordering_and_non_mutation() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=4, ttl=10.0, time_fn=clock)
    c.set("a", 1, ttl=5.0)
    c.set("b", 2, ttl=20.0)
    c.set("c", 3, ttl=20.0)
    c.get("b")  # order: b (MRU), c, a (LRU)

    assert c.keys() == ["b", "c", "a"]

    clock.advance(6.0)  # 'a' is now expired
    assert c.keys() == ["b", "c"]
    # keys() must not mutate cache or stats
    assert len(c) == 3
    assert c.stats() == CacheStats(hits=1, misses=0, evictions=0, expirations=0)


def test_contains_semantics_and_len() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=3, ttl=5.0, time_fn=clock)
    c.set("a", 1)
    c.set("b", 2, ttl=10.0)

    assert "a" in c
    assert "missing" not in c
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=0)

    clock.advance(5.0)
    assert len(c) == 2  # includes expired but unpurged 'a'
    assert "a" not in c  # lazily removes 'a' and counts expiration
    assert len(c) == 1
    assert "b" in c
    assert c.stats() == CacheStats(hits=0, misses=0, evictions=0, expirations=1)


def test_stats_returns_immutable_snapshot() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=2, time_fn=clock)
    snap1 = c.stats()
    c.set("a", 1)
    c.get("a")
    c.get("b")
    snap2 = c.stats()

    assert snap1 == CacheStats(hits=0, misses=0, evictions=0, expirations=0)
    assert snap2 == CacheStats(hits=1, misses=1, evictions=0, expirations=0)
    with pytest.raises(Exception):
        snap1.hits = 5  # type: ignore[misc]


def test_thread_safety() -> None:
    clock = FakeClock(0.0)
    c = LRUCache(capacity=32, ttl=10.0, time_fn=clock)
    errors: list[BaseException] = []

    def worker(tid: int) -> None:
        try:
            for i in range(100):
                key = f"k-{tid}-{i % 20}"
                c.set(key, i)
                _ = c.get(key)
                _ = key in c
                if i % 25 == 0:
                    _ = c.keys()
                    _ = c.purge_expired()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(c) <= 32
