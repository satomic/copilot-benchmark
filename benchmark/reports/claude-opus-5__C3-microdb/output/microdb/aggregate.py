"""Aggregate functions evaluated over the values of one group."""

from __future__ import annotations

from .errors import ArityError, TypeMismatchError
from .value import is_numeric, order_lt, type_of

AGGREGATES: frozenset[str] = frozenset({"count", "sum", "avg", "min", "max"})


def check_arity(name: str, count: int) -> None:
    """Every aggregate takes exactly one argument."""
    if count != 1:
        raise ArityError(f"aggregate {name!r} expects 1 argument, got {count}")


def _non_null(values: list[object]) -> list[object]:
    return [v for v in values if v is not None]


def _require_numeric(name: str, values: list[object]) -> None:
    for v in values:
        if not is_numeric(v):
            raise TypeMismatchError(
                f"aggregate {name!r} requires numeric input, got {type_of(v)}"
            )


def agg_count(values: list[object], star: bool = False) -> int:
    """``count(*)`` counts rows; ``count(expr)`` counts non-NULL values."""
    if star:
        return len(values)
    return len(_non_null(values))


def agg_sum(values: list[object]) -> object:
    """Sum of non-NULL values; NULL when there are none, INT when all inputs are INT."""
    kept = _non_null(values)
    _require_numeric("sum", kept)
    if not kept:
        return None
    total = sum(kept)  # type: ignore[arg-type]
    if all(type_of(v) == "INT" for v in kept):
        return int(total)
    return float(total)


def agg_avg(values: list[object]) -> object:
    """Mean of non-NULL values, always FLOAT; NULL when there are none."""
    kept = _non_null(values)
    _require_numeric("avg", kept)
    if not kept:
        return None
    return float(sum(kept)) / len(kept)  # type: ignore[arg-type]


def _extreme(name: str, values: list[object], want_min: bool) -> object:
    kept = _non_null(values)
    if not kept:
        return None
    best = kept[0]
    for candidate in kept[1:]:
        replace = order_lt(candidate, best) if want_min else order_lt(best, candidate)
        if replace:
            best = candidate
    return best


def agg_min(values: list[object]) -> object:
    """Smallest non-NULL value, or NULL when the group has none."""
    return _extreme("min", values, True)


def agg_max(values: list[object]) -> object:
    """Largest non-NULL value, or NULL when the group has none."""
    return _extreme("max", values, False)


def compute(name: str, values: list[object], star: bool = False) -> object:
    """Dispatch to the aggregate called ``name`` (case insensitive)."""
    key = name.lower()
    if key == "count":
        return agg_count(values, star)
    if star:
        raise TypeMismatchError(f"aggregate {name!r} does not accept '*'")
    if key == "sum":
        return agg_sum(values)
    if key == "avg":
        return agg_avg(values)
    if key == "min":
        return agg_min(values)
    if key == "max":
        return agg_max(values)
    raise TypeMismatchError(f"unknown aggregate {name!r}")
