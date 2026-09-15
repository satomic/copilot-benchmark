"""Aggregate function evaluation."""

from __future__ import annotations

from microdb.errors import TypeMismatchError, UnknownFunctionError
from microdb.value import compare_lt, is_numeric, type_of

AGGREGATE_NAMES = frozenset({"count", "sum", "avg", "min", "max"})


def is_aggregate_name(name: str) -> bool:
    """Return True if name is a known aggregate function."""
    return name.lower() in AGGREGATE_NAMES


def _eval_sum(non_nulls: list[object]) -> object:
    if not non_nulls:
        return None
    has_float = False
    for v in non_nulls:
        if not is_numeric(v):
            raise TypeMismatchError(f"sum requires numeric input, got {type_of(v)}")
        if isinstance(v, float):
            has_float = True
    total = sum(v for v in non_nulls)  # type: ignore[arg-type]
    return float(total) if has_float else int(total)


def _eval_avg(non_nulls: list[object]) -> object:
    if not non_nulls:
        return None
    for v in non_nulls:
        if not is_numeric(v):
            raise TypeMismatchError(f"avg requires numeric input, got {type_of(v)}")
    total = sum(v for v in non_nulls)  # type: ignore[arg-type]
    return float(total) / len(non_nulls)


def _eval_min_max(non_nulls: list[object], find_min: bool) -> object:
    if not non_nulls:
        return None
    best = non_nulls[0]
    for v in non_nulls[1:]:
        if find_min:
            if compare_lt(v, best) is True:
                best = v
        else:
            if compare_lt(best, v) is True:
                best = v
    return best


def evaluate_aggregate(
    name: str, values: list[object], is_star: bool = False, row_count: int = 0
) -> object:
    """Evaluate an aggregate function over a collection of values."""
    lower_name = name.lower()
    if lower_name == "count":
        if is_star:
            return row_count
        return sum(1 for v in values if v is not None)
    non_nulls = [v for v in values if v is not None]
    if lower_name == "sum":
        return _eval_sum(non_nulls)
    if lower_name == "avg":
        return _eval_avg(non_nulls)
    if lower_name == "min":
        return _eval_min_max(non_nulls, find_min=True)
    if lower_name == "max":
        return _eval_min_max(non_nulls, find_min=False)
    raise UnknownFunctionError(f"Unknown aggregate: '{name}'")
