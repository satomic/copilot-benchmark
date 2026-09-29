"""Aggregate functions: count, sum, avg, min, max."""

from __future__ import annotations

from .errors import TypeMismatchError
from .value import compare_lt, is_numeric, type_of

AGGREGATE_NAMES = frozenset({"count", "sum", "avg", "min", "max"})


def is_aggregate(name: str) -> bool:
    """True when name (any case) is an aggregate function."""
    return name.lower() in AGGREGATE_NAMES


def _non_null(values: list[object]) -> list[object]:
    return [v for v in values if v is not None]


def _require_numeric(name: str, values: list[object]) -> None:
    for v in values:
        if not is_numeric(v):
            raise TypeMismatchError(f"{name}() requires numeric input, got {type_of(v)}")


def agg_count_star(row_count: int) -> int:
    """count(*): the number of rows, NULL or not."""
    return row_count


def agg_count(values: list[object]) -> int:
    """count(expr): the number of non-NULL values."""
    return len(_non_null(values))


def agg_sum(values: list[object]) -> object:
    """Sum of non-NULL values; NULL when there are none; INT only if all INT."""
    present = _non_null(values)
    _require_numeric("sum", present)
    if not present:
        return None
    total: int | float = 0
    for v in present:
        total = total + v  # type: ignore[operator]
    if any(isinstance(v, float) for v in present):
        return float(total)
    return total


def agg_avg(values: list[object]) -> float | None:
    """Mean of non-NULL values as FLOAT; NULL when there are none."""
    present = _non_null(values)
    _require_numeric("avg", present)
    if not present:
        return None
    total: int | float = 0
    for v in present:
        total = total + v  # type: ignore[operator]
    return float(total / len(present))


def _extreme(values: list[object], want_min: bool) -> object:
    best: object = None
    for v in _non_null(values):
        if best is None:
            compare_lt(v, v)  # validates the value is orderable
            best = v
        elif compare_lt(v, best) if want_min else compare_lt(best, v):
            best = v
    return best


def agg_min(values: list[object]) -> object:
    """Smallest non-NULL value, type preserved; NULL when there are none."""
    return _extreme(values, True)


def agg_max(values: list[object]) -> object:
    """Largest non-NULL value, type preserved; NULL when there are none."""
    return _extreme(values, False)


_FUNCTIONS = {
    "count": agg_count,
    "sum": agg_sum,
    "avg": agg_avg,
    "min": agg_min,
    "max": agg_max,
}


def compute_aggregate(name: str, values: list[object]) -> object:
    """Apply the named aggregate to a list of input values."""
    return _FUNCTIONS[name.lower()](values)
