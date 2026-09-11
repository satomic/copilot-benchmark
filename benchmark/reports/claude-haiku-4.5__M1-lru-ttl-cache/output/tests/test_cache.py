import pytest
from cache import LRUCache, CacheStats


class TestConstructorValidation:
    def test_capacity_must_be_int(self):
        """Test that non-int capacity raises TypeError."""
        with pytest.raises(TypeError):
            LRUCache(capacity=True)
        with pytest.raises(TypeError):
            LRUCache(capacity="5")
        with pytest.raises(TypeError):
            LRUCache(capacity=5.0)

    def test_capacity_must_be_at_least_one(self):
        """Test that capacity < 1 raises ValueError."""
        with pytest.raises(ValueError):
            LRUCache(capacity=0)
        with pytest.raises(ValueError):
            LRUCache(capacity=-1)

    def test_ttl_must_be_positive_or_none(self):
        """Test that invalid ttl raises ValueError."""
        with pytest.raises(ValueError):
            LRUCache(capacity=5, ttl=0)
        with pytest.raises(ValueError):
            LRUCache(capacity=5, ttl=-1)
        with pytest.raises(ValueError):
            LRUCache(capacity=5, ttl="invalid")

    def test_valid_construction(self):
        """Test valid cache construction."""
        clock = [0.0]
        c = LRUCache(capacity=5, ttl=10, time_fn=lambda: clock[0])
        assert len(c) == 0
        assert c.stats() == CacheStats(0, 0, 0, 0)


class TestSetAndGet:
    def test_set_and_get_simple(self):
        """Test basic set and get operations."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        assert c.get("a") == 1
        assert c.stats().hits == 1

    def test_get_nonexistent_key(self):
        """Test get on missing key returns default."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        assert c.get("missing") is None
        assert c.get("missing", "default") == "default"
        assert c.stats().misses == 2

    def test_set_updates_existing_key(self):
        """Test that set on existing key updates the value."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("a", 2)
        assert c.get("a") == 2
        assert len(c) == 1

    def test_set_makes_updated_key_mru(self):
        """Test that updating an existing key makes it MRU."""
        clock = [0.0]
        c = LRUCache(capacity=3, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        c.set("a", 10)  # Update 'a', should make it MRU

        # Fill to capacity and add new, should evict 'b' (the LRU)
        c.set("c", 3)
        c.set("d", 4)

        assert c.get("a") == 10
        assert c.get("b") is None
        assert c.stats().evictions == 1


class TestLRUEviction:
    def test_lru_eviction_on_capacity(self):
        """Test that LRU entry is evicted when capacity is reached."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        assert len(c) == 2

        # This should evict 'a' (LRU)
        c.set("c", 3)

        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3
        assert c.stats().evictions == 1

    def test_get_updates_lru_order(self):
        """Test that get makes entry MRU."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)

        # Access 'a' to make it MRU
        assert c.get("a") == 1

        # This should evict 'b' (now LRU)
        c.set("c", 3)

        assert c.get("a") == 1
        assert c.get("b") is None
        assert c.get("c") == 3

    def test_keys_order_mru_first(self):
        """Test that keys() returns entries in MRU-first order."""
        clock = [0.0]
        c = LRUCache(capacity=3, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)

        # keys() returns MRU-first, which means access order: a, b, c -> [c, b, a]
        assert c.keys() == ["c", "b", "a"]

        # Access 'a' to make it MRU
        c.get("a")
        assert c.keys() == ["a", "c", "b"]


class TestTTLAndExpiry:
    def test_ttl_expiry_on_get(self):
        """Test that expired entries are returned as misses."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        clock[0] = 10.0  # Exactly at expiry time

        assert c.get("a") is None
        assert c.stats().expirations == 1
        assert c.stats().misses == 1

    def test_per_entry_ttl_override(self):
        """Test that per-entry TTL overrides default."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2, ttl=5)

        clock[0] = 7.0
        assert c.get("a") == 1  # Still alive (default TTL is 10)
        assert c.get("b") is None  # Expired (per-entry TTL is 5)

    def test_ttl_none_entry_never_expires(self):
        """Test that ttl=None entry never expires."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=5, time_fn=lambda: clock[0])

        c.set("forever", 1, ttl=None)
        clock[0] = 1000.0

        assert c.get("forever") == 1

    def test_default_ttl_none_entries_never_expire(self):
        """Test that entries with default ttl=None never expire."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=None, time_fn=lambda: clock[0])

        c.set("a", 1)
        clock[0] = 1000.0

        assert c.get("a") == 1

    def test_purge_expired(self):
        """Test purge_expired removes all expired entries."""
        clock = [0.0]
        c = LRUCache(capacity=5, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)

        clock[0] = 10.0
        count = c.purge_expired()

        assert count == 3
        assert c.stats().expirations == 3
        assert len(c) == 0

    def test_expired_entries_preferred_over_lru_on_eviction(self):
        """Test that expired entries are evicted before LRU."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2, ttl=5)

        clock[0] = 7.0  # 'b' is now expired

        # Adding a new entry should expire 'b' and free space without evicting 'a'
        c.set("c", 3)

        assert c.get("a") == 1
        assert c.get("b") is None
        assert c.get("c") == 3
        assert c.stats().evictions == 0
        assert c.stats().expirations == 1


class TestDelete:
    def test_delete_existing_entry(self):
        """Test delete on existing entry returns True."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        assert c.delete("a") is True
        assert c.get("a") is None

    def test_delete_nonexistent_entry(self):
        """Test delete on missing key returns False."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        assert c.delete("missing") is False

    def test_delete_expired_entry(self):
        """Test delete on expired entry counts as expiration and returns False."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        clock[0] = 10.0

        assert c.delete("a") is False
        assert c.stats().expirations == 1

    def test_delete_no_hit_miss_count(self):
        """Test that delete doesn't count as hit or miss."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.delete("a")

        assert c.stats().hits == 0
        assert c.stats().misses == 0


class TestClear:
    def test_clear_removes_entries(self):
        """Test clear removes all entries."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.set("b", 2)
        c.clear()

        assert len(c) == 0
        assert c.get("a") is None

    def test_clear_does_not_reset_stats(self):
        """Test that clear doesn't reset statistics."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.get("a")  # 1 hit
        c.clear()

        stats = c.stats()
        assert stats.hits == 1
        assert stats.misses == 0


class TestContains:
    def test_contains_live_entry(self):
        """Test __contains__ for live entry."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        assert "a" in c

    def test_contains_missing_entry(self):
        """Test __contains__ for missing entry."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        assert "missing" not in c

    def test_contains_expired_entry(self):
        """Test __contains__ for expired entry."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        clock[0] = 10.0

        assert "a" not in c
        assert c.stats().expirations == 1

    def test_contains_no_hit_miss_count(self):
        """Test that __contains__ doesn't count as hit or miss."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        "a" in c

        assert c.stats().hits == 0
        assert c.stats().misses == 0


class TestStats:
    def test_stats_immutability(self):
        """Test that stats snapshot is immutable."""
        clock = [0.0]
        c = LRUCache(capacity=2, ttl=10, time_fn=lambda: clock[0])

        c.set("a", 1)
        c.get("a")
        stats1 = c.stats()

        c.set("b", 2)
        c.get("b")

        # Original stats should be unchanged
        assert stats1.hits == 1
        assert c.stats().hits == 2


class TestAcceptanceCriteria:
    def test_acceptance_example(self):
        """Test the example from acceptance criteria."""
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
