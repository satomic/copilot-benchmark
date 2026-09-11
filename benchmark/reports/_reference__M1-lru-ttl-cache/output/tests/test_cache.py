"""Reference test suite (12 tests) using an injected fake clock."""
import pytest

from cache import CacheStats, LRUCache


@pytest.fixture
def clock():
    return {"t": 0.0}


@pytest.fixture
def make(clock):
    def _make(capacity=3, ttl=None):
        return LRUCache(capacity=capacity, ttl=ttl, time_fn=lambda: clock["t"])
    return _make


def test_eviction_order(make):
    c = make(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["c", "b"]
    assert c.stats().evictions == 1


def test_get_refreshes_recency(make):
    c = make(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")
    c.set("c", 3)
    assert sorted(c.keys()) == ["a", "c"]


def test_ttl_expiry_via_get(make, clock):
    c = make(capacity=2, ttl=5)
    c.set("a", 1)
    clock["t"] = 5.0
    assert c.get("a") is None
    assert c.stats().expirations == 1


def test_per_entry_ttl(make, clock):
    c = make(capacity=2, ttl=100)
    c.set("a", 1, ttl=1)
    clock["t"] = 1.0
    assert c.get("a") is None


def test_ttl_none_override(make, clock):
    c = make(capacity=2, ttl=1)
    c.set("a", 1, ttl=None)
    clock["t"] = 999.0
    assert c.get("a") == 1


def test_purge_expired(make, clock):
    c = make(capacity=4, ttl=1)
    c.set("a", 1)
    c.set("b", 2, ttl=100)
    clock["t"] = 1.0
    assert c.purge_expired() == 1
    assert c.keys() == ["b"]


def test_delete_returns(make):
    c = make()
    c.set("a", 1)
    assert c.delete("a") is True
    assert c.delete("a") is False


def test_clear_keeps_stats(make):
    c = make()
    c.set("a", 1)
    c.get("a")
    c.clear()
    assert c.stats().hits == 1
    assert len(c) == 0


def test_keys_ordering(make):
    c = make(capacity=3)
    for k in "abc":
        c.set(k, k)
    assert c.keys() == ["c", "b", "a"]


def test_contains_no_hit_accounting(make):
    c = make()
    c.set("a", 1)
    assert "a" in c
    assert "b" not in c
    assert c.stats() == CacheStats()


def test_constructor_validation():
    with pytest.raises(ValueError):
        LRUCache(capacity=0)
    with pytest.raises(TypeError):
        LRUCache(capacity=True)
    with pytest.raises(ValueError):
        LRUCache(capacity=2, ttl=0)


def test_set_restarts_ttl(make, clock):
    c = make(capacity=2, ttl=10)
    c.set("a", 1)
    clock["t"] = 9.0
    c.set("a", 2)
    clock["t"] = 18.0
    assert c.get("a") == 2
