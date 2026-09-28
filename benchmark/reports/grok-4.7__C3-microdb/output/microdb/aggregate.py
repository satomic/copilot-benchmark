"""Aggregate functions. NULL inputs are ignored. An empty sum is NULL."""

from __future__ import annotations

from microdb.errors import ArityError, TypeMismatchError
from microdb.value import compare_lt, is_numeric, type_of

_AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})


def is_aggregate_name(name: str) -> bool:
    """Return True if *name* is an aggregate, case-insensitively."""
    return name.lower() in _AGGREGATES


def eval_aggregate(name: str, star: bool, values: list[object], row_count: int) -> object:
    """Evaluate one aggregate over already-computed per-row values."""
    key = name.lower()
    if key == "count":
        return _count(star, values, row_count)
    if key == "sum":
        return _sum(values)
    if key == "avg":
        return _avg(values)
    if key == "min":
        return _minmax(values, True)
    if key == "max":
        return _minmax(values, False)
    raise TypeMismatchError(f"unknown aggregate {name}")


def _count(star: bool, values: list[object], row_count: int) -> int:
    if star:
        return row_count
    return sum(1 for value in values if value is not None)


def _sum(values: list[object]) -> object:
    total: int | float | None = None
    saw_float = False
    for value in values:
        if value is None:
            continue
        number = _numeric(value, "sum")
        if type(number) is float:
            saw_float = True
        total = number if total is None else total + number
    if total is None:
        return None
    if saw_float:
        return float(total)
    return total


def _avg(values: list[object]) -> object:
    total: int | float = 0
    count = 0
    for value in values:
        if value is None:
            continue
        total += _numeric(value, "avg")
        count += 1
    if count == 0:
        return None
    return total / count


def _minmax(values: list[object], want_min: bool) -> object:
    best: object = None
    started = False
    for value in values:
        if value is None:
            continue
        if not started:
            best = value
            started = True
            continue
        best = _prefer(best, value, want_min)
    return best if started else None


def _prefer(best: object, value: object, want_min: bool) -> object:
    lesser = compare_lt(value, best)
    if want_min and lesser:
        return value
    if not want_min and compare_lt(best, value):
        return value
    return best


def _numeric(value: object, name: str) -> int | float:
    if type(value) is bool or not is_numeric(value):
        raise TypeMismatchError(f"{name} requires numeric input, got {type_of(value)}")
    return value  # type: ignore[return-value]


def check_arity(name: str, actual: int, expected: int, at_least: bool = False) -> None:
    """Raise ArityError naming the function and both counts."""
    if at_least and actual < expected:
        raise ArityError(name.lower(), expected, actual, at_least=True)
    if not at_least and actual != expected:
        raise ArityError(name.lower(), expected, actual)
