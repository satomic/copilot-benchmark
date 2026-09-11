"""Hidden verification suite for task M1. Not visible to the model under test."""
import importlib
import sys
import threading
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def pkg():
    sys.path.insert(0, ".")
    return importlib.import_module("cache")


@pytest.fixture
def clock():
    return {"t": 0.0}


@pytest.fixture
def make(pkg, clock):
    def _make(capacity=3, ttl=None):
        return pkg.LRUCache(capacity=capacity, ttl=ttl, time_fn=lambda: clock["t"])
    return _make


# ------------------------------------------------------------ package shape ---

def test_package_surface(pkg):
    assert set(pkg.__all__) == {"LRUCache", "CacheStats"}
    assert hasattr(pkg, "LRUCache") and hasattr(pkg, "CacheStats")


def test_expected_files_exist():
    for rel in ("cache/__init__.py", "cache/lru.py", "cache/stats.py", "tests/test_cache.py"):
        assert Path(rel).is_file(), f"missing {rel}"


_IGNORED_DIRS = {"__pycache__", "_verify", ".pytest_cache", ".git", ".ruff_cache", ".mypy_cache"}


def _project_files() -> set[str]:
    """Relative paths of authored files, ignoring tool caches and the verify drop-in."""
    out = set()
    for p in Path(".").rglob("*"):
        if not p.is_file():
            continue
        if any(part in _IGNORED_DIRS for part in p.parts):
            continue
        if p.suffix == ".pyc":
            continue
        out.add(p.as_posix())
    return out


def test_no_forbidden_files():
    forbidden = {"README.md", "requirements.txt", "setup.py", "pyproject.toml", "setup.cfg"}
    present = {Path(p).name for p in _project_files()}
    assert not (forbidden & present), f"forbidden files: {sorted(forbidden & present)}"


def test_only_expected_files():
    expected = {
        "task.md",
        "cache/__init__.py",
        "cache/lru.py",
        "cache/stats.py",
        "tests/test_cache.py",
    }
    extra = _project_files() - expected
    assert not extra, f"unexpected files created: {sorted(extra)}"


def test_stats_is_frozen_dataclass(pkg):
    import dataclasses
    assert dataclasses.is_dataclass(pkg.CacheStats)
    s = pkg.CacheStats()
    assert (s.hits, s.misses, s.evictions, s.expirations) == (0, 0, 0, 0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.hits = 5


def test_injected_clock_is_the_only_time_source(pkg):
    """Behavioural check: with a frozen fake clock, nothing may ever expire."""
    calls = []

    def fake_clock():
        calls.append(1)
        return 0.0

    c = pkg.LRUCache(capacity=4, ttl=0.001, time_fn=fake_clock)
    c.set("a", 1)
    for _ in range(5):
        assert c.get("a") == 1, "entry expired although the injected clock never advanced"
    assert c.purge_expired() == 0
    assert c.stats().expirations == 0
    assert calls, "time_fn was never called — the class uses its own clock"


# ------------------------------------------------------------- construction ---

@pytest.mark.parametrize("capacity", [0, -1, -100])
def test_capacity_must_be_positive(pkg, capacity):
    with pytest.raises(ValueError):
        pkg.LRUCache(capacity=capacity)


@pytest.mark.parametrize("capacity", [True, False, 1.5, "3", None])
def test_capacity_must_be_int(pkg, capacity):
    with pytest.raises(TypeError):
        pkg.LRUCache(capacity=capacity)


@pytest.mark.parametrize("ttl", [0, -1, -0.5])
def test_default_ttl_must_be_positive(pkg, ttl):
    with pytest.raises(ValueError):
        pkg.LRUCache(capacity=2, ttl=ttl)


def test_ttl_none_is_allowed(pkg):
    assert pkg.LRUCache(capacity=2, ttl=None) is not None


# --------------------------------------------------------------- basic ops ----

def test_reference_scenario(pkg, clock):
    c = pkg.LRUCache(capacity=2, ttl=10, time_fn=lambda: clock["t"])
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert c.keys() == ["c", "a"]
    assert c.get("b") is None
    assert c.stats() == pkg.CacheStats(hits=1, misses=1, evictions=1, expirations=0)
    clock["t"] = 10.0
    assert c.get("a") is None
    assert c.stats().expirations == 1


def test_get_default(make):
    c = make()
    assert c.get("nope") is None
    assert c.get("nope", "fallback") == "fallback"
    assert c.stats().misses == 2


def test_set_existing_refreshes_recency_and_value(make):
    c = make(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("a", 99)
    assert c.keys() == ["a", "b"]
    c.set("c", 3)
    assert "b" not in c
    assert c.get("a") == 99


def test_eviction_order_is_lru(make):
    c = make(capacity=3)
    for k in "abc":
        c.set(k, k)
    c.get("a")
    c.get("b")
    c.set("d", "d")          # evicts 'c'
    assert sorted(c.keys()) == ["a", "b", "d"]
    assert c.stats().evictions == 1


def test_len_never_exceeds_capacity(make):
    c = make(capacity=3)
    for i in range(50):
        c.set(i, i)
    assert len(c) == 3


def test_delete(make):
    c = make()
    c.set("a", 1)
    assert c.delete("a") is True
    assert c.delete("a") is False
    st = c.stats()
    assert st.hits == 0 and st.misses == 0


def test_clear_keeps_stats(make):
    c = make()
    c.set("a", 1)
    c.get("a")
    c.get("zz")
    c.clear()
    assert len(c) == 0
    st = c.stats()
    assert st.hits == 1 and st.misses == 1


def test_keys_order_mru_first(make):
    c = make(capacity=4)
    for k in "abcd":
        c.set(k, k)
    assert c.keys() == ["d", "c", "b", "a"]
    c.get("a")
    assert c.keys() == ["a", "d", "c", "b"]


def test_keys_does_not_change_stats(make, clock):
    c = make(capacity=4, ttl=5)
    c.set("a", 1)
    before = c.stats()
    c.keys()
    assert c.stats() == before


def test_stats_snapshot_is_stable(make):
    c = make()
    c.set("a", 1)
    snap = c.stats()
    c.get("a")
    c.get("b")
    assert snap.hits == 0 and snap.misses == 0


# ------------------------------------------------------------------- ttl -----

def test_expiry_is_inclusive_at_deadline(make, clock):
    c = make(capacity=4, ttl=10)
    c.set("a", 1)
    clock["t"] = 9.999
    assert c.get("a") == 1
    clock["t"] = 10.0
    assert c.get("a") is None
    st = c.stats()
    assert st.expirations == 1 and st.misses == 1


def test_per_entry_ttl_overrides_default(make, clock):
    c = make(capacity=4, ttl=100)
    c.set("short", 1, ttl=5)
    c.set("long", 2)
    clock["t"] = 5.0
    assert c.get("short") is None
    assert c.get("long") == 2


def test_ttl_none_entry_never_expires(make, clock):
    c = make(capacity=4, ttl=5)
    c.set("forever", 1, ttl=None)
    clock["t"] = 10_000.0
    assert c.get("forever") == 1
    assert c.stats().expirations == 0


def test_omitting_ttl_uses_default(make, clock):
    c = make(capacity=4, ttl=5)
    c.set("a", 1)
    clock["t"] = 5.0
    assert c.get("a") is None


@pytest.mark.parametrize("bad", [0, -1, "x"])
def test_set_rejects_bad_ttl(make, bad):
    c = make(capacity=4)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=bad)


def test_set_restarts_ttl(make, clock):
    c = make(capacity=4, ttl=10)
    c.set("a", 1)
    clock["t"] = 9.0
    c.set("a", 2)
    clock["t"] = 18.0
    assert c.get("a") == 2
    clock["t"] = 19.0
    assert c.get("a") is None


def test_purge_expired(make, clock):
    c = make(capacity=8, ttl=10)
    c.set("a", 1)
    c.set("b", 2, ttl=100)
    clock["t"] = 10.0
    assert c.purge_expired() == 1
    assert c.purge_expired() == 0
    assert c.keys() == ["b"]
    assert c.stats().expirations == 1


def test_contains_does_not_count_hits_or_misses(make, clock):
    c = make(capacity=4, ttl=10)
    c.set("a", 1)
    assert ("a" in c) is True
    assert ("zz" in c) is False
    st = c.stats()
    assert st.hits == 0 and st.misses == 0
    clock["t"] = 10.0
    assert ("a" in c) is False
    st = c.stats()
    assert st.expirations == 1 and st.hits == 0 and st.misses == 0


def test_delete_of_expired_entry(make, clock):
    c = make(capacity=4, ttl=10)
    c.set("a", 1)
    clock["t"] = 10.0
    assert c.delete("a") is False
    st = c.stats()
    assert st.expirations == 1 and st.hits == 0 and st.misses == 0


def test_expired_entries_are_reclaimed_before_eviction(make, clock):
    c = make(capacity=2, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    clock["t"] = 10.0
    c.set("c", 3)
    st = c.stats()
    assert st.evictions == 0, "expired entries must be reclaimed instead of evicting"
    assert st.expirations >= 1
    assert c.get("c") == 3


def test_keys_excludes_expired(make, clock):
    c = make(capacity=4, ttl=10)
    c.set("a", 1)
    c.set("b", 2, ttl=100)
    clock["t"] = 10.0
    assert c.keys() == ["b"]


# ---------------------------------------------------------------- threading ---

def test_thread_safety_smoke(pkg):
    c = pkg.LRUCache(capacity=64, ttl=None)
    errors = []

    def worker(base):
        try:
            for i in range(2000):
                k = (base + i) % 200
                c.set(k, i)
                c.get(k)
                if i % 50 == 0:
                    c.purge_expired()
                    c.keys()
                    len(c)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i * 37,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, f"exceptions raised under concurrency: {errors[:3]}"
    assert len(c) <= 64


def test_uses_an_rlock(pkg):
    """RLock (not Lock) is required: nested public calls must not deadlock."""
    src = Path("cache/lru.py").read_text(encoding="utf-8")
    assert "RLock" in src, "spec requires threading.RLock"

    # A reentrant lock means purge_expired() can be reached from inside set()
    # without deadlocking. Exercise the reclaim path under a tight capacity.
    clock = {"t": 0.0}
    c = pkg.LRUCache(capacity=2, ttl=1, time_fn=lambda: clock["t"])
    c.set("a", 1)
    c.set("b", 2)
    clock["t"] = 1.0
    c.set("c", 3)          # would hang or raise with a non-reentrant lock
    assert c.get("c") == 3


# --------------------------------------------------- model's own test suite ---

def test_model_test_suite_is_substantial():
    src = Path("tests/test_cache.py").read_text(encoding="utf-8")
    count = len([m for m in src.splitlines() if m.strip().startswith("def test_")])
    assert count >= 12, f"expected >= 12 test functions, found {count}"

    # Look for an actual call, not the word. A docstring that says "never sleeps"
    # is the suite documenting compliance, and must not be flagged.
    import re as _re
    calls = _re.findall(r"\bsleep\s*\(", src)
    assert not calls, (
        f"tests must not sleep; inject a fake clock (found {len(calls)} sleep call(s))"
    )


def test_hot_path_scales(pkg):
    """get/set must be ~O(1): a 20x larger cache must not cost ~20x per operation."""
    import time as _time

    def cost(capacity):
        c = pkg.LRUCache(capacity=capacity, ttl=None)
        for i in range(capacity):
            c.set(i, i)
        n = 20_000
        t0 = _time.perf_counter()
        for i in range(n):
            k = i % capacity
            c.set(k, i)
            c.get(k)
        return (_time.perf_counter() - t0) / n

    small = cost(500)
    large = cost(10_000)
    # generous bound: O(n) behaviour would blow this out by an order of magnitude
    assert large < small * 5 + 5e-6, (
        f"per-op cost grew from {small:.3e}s to {large:.3e}s — hot path looks O(n)"
    )
