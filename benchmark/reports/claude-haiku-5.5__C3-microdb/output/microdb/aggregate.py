"""Aggregate functions: count, sum, avg, min, max with SQL NULL rules."""

from __future__ import annotations

from .errors import TypeMismatchError
from .value import compare_lt, is_numeric, type_of

AGGREGATE_NAMES = frozenset({"count", "sum", "avg", "min", "max"})


def is_aggregate(name: str) -> bool:
    return name.lower() in AGGREGATE_NAMES


def compute(name: str, values: list[object]) -> object:
    """Aggregate a list of already-evaluated inputs; NULLs are skipped except by count(*)."""
    if name == "count":
        return sum(1 for v in values if v is not None)
    present = [v for v in values if v is not None]
    if name == "sum":
        return _sum(present)
    if name == "avg":
        return _avg(present)
    return _extreme(name, present)


def _numbers(present: list[object], name: str) -> None:
    for v in present:
        if not is_numeric(v):
            raise TypeMismatchError(f"{name}() requires numeric input, got {type_of(v)}")


def _sum(present: list[object]) -> object:
    if not present:
        return None
    _numbers(present, "sum")
    total = sum(present)  # type: ignore[arg-type]
    if all(type_of(v) == "INT" for v in present):
        return total
    return float(total)


def _avg(present: list[object]) -> object:
    if not present:
        return None
    _numbers(present, "avg")
    return float(sum(present)) / len(present)  # type: ignore[arg-type]


def _extreme(name: str, present: list[object]) -> object:
    if not present:
        return None
    best = present[0]
    for v in present[1:]:
        if name == "min" and compare_lt(v, best):
            best = v
        elif name == "max" and compare_lt(best, v):
            best = v
    return best
