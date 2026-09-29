"""Test suite for LRUCache.

Uses an injected fake clock (a list-wrapped float) so no test calls
time.sleep.
"""

from __future__ import annotations

import gc
import threading
import pytest
from cache import LRUCache, CacheStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clock(seq: list[float]) -> float:
    """Return the current value of *seq*."""
    return seq[0]


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_capacity_below_one_raises(self) -> None:
        with pytest.raises(ValueError):
            LRUCache(capacity=0)

    def test_capacity_not_int_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            LRUCache(capacity=True)

    def test_capacity_float_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            LRUCache(capacity=1.5)

    def test_ttl_non_positive_raises(self) -> None:
        with pytest.raises(ValueError):
            LRUCache(capacity=1, ttl=0)
        with pytest.raises(ValueError):
            LRUCache(capacity=1, ttl=-1)

    def test_ttl_str_raises(self) -> None:
        with pytest.raises(ValueError):
            LRUCache(capacity=1, ttl="10")


# ---------------------------------------------------------------------------
# Capacity eviction order (LRU)
# ---------------------------------------------------------------------------

class TestEviction:
    def test_evicts_lru_on_full(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=None, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)  # evicts 'a' (inserted first, not touched since)

        assert "a" not in c
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_eviction_prefers_expired_over_live(self) -> None:
        """Expired entries are dropped before an LRU eviction occurs."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10.0, time_fn=lambda: clock[0])

        c.set("a", 1)
        clock[0] = 5.0
        c.set("b", 2)     # 'b' has 10s TTL → expires at 15
        # Now both entries are live.
        clock[0] = 11.0   # 'a' expired at 10, 'b' still live
        c.set("c", 3)     # should evict 'a' (expired), not 'b'

        assert c.get("a") is None
        assert c.get("b") == 2  # 'b' still live
        assert c.get("c") == 3
        assert c.stats().evictions == 0
        assert c.stats().expirations == 1


# ---------------------------------------------------------------------------
# LRU refresh on get
# ---------------------------------------------------------------------------

class TestLruOrder:
    def test_get_promotes_mru(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=None, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        # 'a' is LRU now
        c.get("a")           # promotes 'a' to MRU
        c.set("c", 3)        # evicts 'b'

        assert c.get("b") is None
        assert c.keys() == ["c", "a"]


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------

class TestTtlExpiry:
    def test_expired_entry_returns_none_on_get(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10.0, time_fn=lambda: clock[0])

        c.set("a", 1)
        clock[0] = 10.0       # exactly at deadline → already expired
        assert c.get("a") is None
        assert c.stats().expirations == 1
        assert c.stats().misses == 1

    def test_expired_entry_counts_miss_and_expiration(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10.0, time_fn=lambda: clock[0])

        c.set("a", 1)
        clock[0] = 20.0
        result = c.get("a", "DEFAULT")
        assert result == "DEFAULT"
        s = c.stats()
        assert s.misses == 1
        assert s.expirations == 1

    def test_never_expire_default_ttl_none(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=8, ttl=None, time_fn=lambda: clock[0])

        c.set("a", 1)
        clock[0] += 9999
        assert c.get("a") == 1


# ---------------------------------------------------------------------------
# Per-entry TTL
# ---------------------------------------------------------------------------

class TestPerEntryTtl:
    def test_per_entry_ttl_overrides_default(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=8, ttl=5.0, time_fn=lambda: clock[0])

        c.set("a", 1, ttl=20.0)
        clock[0] = 10.0    # past default (5), but per-entry (20) still live
        assert c.get("a") == 1

    def test_per_entry_ttl_none_never_expires(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=8, ttl=5.0, time_fn=lambda: clock[0])

        c.set("forever", 1, ttl=None)
        clock[0] += 1000
        assert c.get("forever") == 1

    def test_per_entry_ttl_negative_raises(self) -> None:
        c = LRUCache(capacity=2, ttl=None)
        with pytest.raises(ValueError):
            c.set("x", 1, ttl=-1)
        with pytest.raises(ValueError):
            c.set("x", 1, ttl=0)

    def test_per_entry_ttl_none_with_default_none(self) -> None:
        """Both default and per-entry ttl=None should be fine."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=None, time_fn=lambda: clock[0])
        c.set("a", 1, ttl=None)
        clock[0] += 9999
        assert c.get("a") == 1


# ---------------------------------------------------------------------------
# purge_expired
# ---------------------------------------------------------------------------

class TestPurgeExpired:
    def test_purge_expired_removes_entries(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=5, ttl=10.0, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        clock[0] = 5.0
        c.set("c", 3)   # expires at 15
        clock[0] = 12.0  # a and b expired, c still live

        n = c.purge_expired()
        assert n == 2
        assert "a" not in c
        assert "b" not in c
        assert "c" in c
        assert c.stats().expirations == 2


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_live_returns_true(self) -> None:
        c = LRUCache(capacity=2, ttl=None)
        c.set("a", 1)
        assert c.delete("a") is True
        assert c.get("a") is None

    def test_delete_missing_returns_false(self) -> None:
        c = LRUCache(capacity=2, ttl=None)
        assert c.delete("nonexistent") is False

    def test_delete_expired_returns_false_counts_expiration(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10.0, time_fn=lambda: clock[0])
        c.set("a", 1)
        clock[0] = 15.0
        assert c.delete("a") is False
        assert c.stats().expirations == 1


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_empties_cache(self) -> None:
        c = LRUCache(capacity=2, ttl=None)
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert len(c) == 0

    def test_clear_does_not_reset_stats(self) -> None:
        c = LRUCache(capacity=2, ttl=None)
        c.set("a", 1)
        c.get("b")  # miss
        c.clear()
        s = c.stats()
        assert s.hits == 0
        assert s.misses == 1


# ---------------------------------------------------------------------------
# keys ordering
# ---------------------------------------------------------------------------

class TestKeys:
    def test_keys_mru_first(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=3, ttl=None, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        # order: c (MRU), b, a (LRU)
        assert c.keys() == ["c", "b", "a"]

        c.get("a")  # promotes a
        assert c.keys() == ["a", "c", "b"]

    def test_keys_excludes_expired(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=3, ttl=10.0, time_fn=lambda: clock[0])

        c.set("a", 1)  # expires at 10
        c.set("b", 2)  # expires at 10
        clock[0] = 15.0
        assert c.keys() == []
        assert len(c) == 2  # __len__ counts even expired entries


# ---------------------------------------------------------------------------
# __contains__
# ---------------------------------------------------------------------------

class TestContains:
    def test_contains_live_entry(self) -> None:
        c = LRUCache(capacity=2, ttl=None)
        c.set("a", 1)
        assert ("a" in c) is True

    def test_contains_missing_entry(self) -> None:
        c = LRUCache(capacity=2, ttl=None)
        assert ("x" in c) is False

    def test_contains_expired_removes_entry(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10.0, time_fn=lambda: clock[0])
        c.set("a", 1)
        clock[0] = 15.0
        assert ("a" in c) is False  # expired → removed
        assert c.stats().expirations == 1
        # hits and misses should NOT be affected
        assert c.stats().hits == 0
        assert c.stats().misses == 0


# ---------------------------------------------------------------------------
# stats isolation
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_snapshot_is_independent(self) -> None:
        c = LRUCache(capacity=2, ttl=None)
        c.set("a", 1)
        c.get("a")  # hit
        s1 = c.stats()
        c.get("a")  # another hit
        s2 = c.stats()
        assert s1.hits == 1
        assert s2.hits == 2


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_access(self) -> None:
        """Basic smoke test: hammer the cache from multiple threads."""
        clock = [0.0]
        lock = threading.Lock()

        def tick() -> float:
            with lock:
                clock[0] += 0.001
                return clock[0]

        c = LRUCache(capacity=50, ttl=1.0, time_fn=tick)

        errors = []

        def worker() -> None:
            try:
                for i in range(100):
                    c.set(i, i * 2)
                    c.get(i - 1)
                    c.delete(i - 2)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread safety errors: {errors}"


# ---------------------------------------------------------------------------
# Acceptance criteria smoke test (from spec)
# ---------------------------------------------------------------------------

class TestAcceptance:
    def test_smoke(self) -> None:
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10.0, time_fn=lambda: clock[0])

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

        c2 = LRUCache(capacity=8, ttl=5.0, time_fn=lambda: clock[0])
        c2.set("forever", 1, ttl=None)
        clock[0] += 1000
        assert c2.get("forever") == 1

        with pytest.raises(ValueError):
            LRUCache(capacity=0)
        with pytest.raises(TypeError):
            LRUCache(capacity=True)