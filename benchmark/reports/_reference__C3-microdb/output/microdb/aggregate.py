"""Aggregate functions.

Every aggregate here ignores NULL inputs except ``count(*)``, and every one of
them returns NULL for an empty set of non-NULL inputs except ``count``, which
returns 0. Keeping the rule in one place is what stops ``sum`` of nothing from
drifting to 0.
"""

from __future__ import annotations

from .errors import ArityError, TypeMismatchError
from .value import INT, TEXT, is_numeric, sort_key_lt, type_of

__all__ = ["AGGREGATE_ARITY", "aggregate", "check_arity"]

#: name -> exact argument count
AGGREGATE_ARITY: dict[str, int] = {"count": 1, "sum": 1, "avg": 1, "min": 1, "max": 1}


def _require_numeric(name: str, values: list[object]) -> None:
    for value in values:
        if not is_numeric(value):
            raise TypeMismatchError(f"{name}() requires numbers, got {type_of(value)}")


def _require_uniform(name: str, values: list[object]) -> None:
    """min and max may mix INT with FLOAT but not TEXT with numbers."""
    kinds = {type_of(v) for v in values}
    if TEXT in kinds and kinds - {TEXT}:
        raise TypeMismatchError(f"{name}() cannot mix TEXT with numbers")


def aggregate(name: str, values: list[object], *, star_rows: int | None = None) -> object:
    """Apply an aggregate.

    ``values`` are the per-row results of the argument expression, still holding
    NULLs. ``star_rows`` is the row count and is only set for ``count(*)``.
    """
    lowered = name.lower()
    if lowered not in AGGREGATE_ARITY:
        raise TypeMismatchError(f"unknown aggregate {name}")
    if lowered == "count":
        return star_rows if star_rows is not None else sum(1 for v in values if v is not None)
    live = [v for v in values if v is not None]
    if not live:
        return None
    if lowered in ("sum", "avg"):
        _require_numeric(lowered, live)
        total = sum(live)  # type: ignore[arg-type]
        if lowered == "avg":
            return float(total) / len(live)
        return total if all(type_of(v) == INT for v in live) else float(total)
    _require_uniform(lowered, live)
    best = live[0]
    for value in live[1:]:
        if lowered == "min":
            if sort_key_lt(value, best):
                best = value
        elif sort_key_lt(best, value):
            best = value
    return best


def check_arity(name: str, count: int) -> None:
    """Aggregates all take exactly one argument."""
    expected = AGGREGATE_ARITY[name.lower()]
    if count != expected:
        raise ArityError(name, str(expected), count)

