from __future__ import annotations

from collections.abc import Sequence

from microdb.errors import ArityError, TypeMismatchError, UnknownFunctionError
from microdb.value import compare_lt, is_numeric, type_of

AGGREGATES: frozenset[str] = frozenset({"count", "sum", "avg", "min", "max"})


def validate_aggregate_call(name: str, arity: int, is_star: bool) -> None:
    lower = name.lower()
    if lower not in AGGREGATES:
        raise UnknownFunctionError(f"Unknown aggregate function {name!r}")
    if not is_star and arity != 1:
        raise ArityError(f"{lower} expects 1 argument, got {arity}")


def compute_aggregate(
    name: str,
    values: Sequence[object],
    is_star: bool = False,
    row_count: int | None = None,
) -> object:
    lower = name.lower()
    if lower == "count":
        if is_star:
            return row_count if row_count is not None else len(values)
        return sum(1 for v in values if v is not None)

    non_null = [v for v in values if v is not None]
    if lower in ("sum", "avg"):
        for v in non_null:
            if not is_numeric(v):
                raise TypeMismatchError(f"{lower} requires numeric input, got {type_of(v)}")
        if not non_null:
            return None
        total = sum(non_null)  # type: ignore[arg-type]
        if lower == "avg":
            return float(total) / float(len(non_null))
        if any(isinstance(v, float) for v in non_null):
            return float(total)
        return int(total)

    if lower in ("min", "max"):
        if not non_null:
            return None
        best = non_null[0]
        compare_lt(best, best)
        for v in non_null[1:]:
            if lower == "min":
                if compare_lt(v, best) is True:
                    best = v
            else:
                if compare_lt(best, v) is True:
                    best = v
        return best

    raise UnknownFunctionError(f"Unknown aggregate function {name!r}")
