"""Aggregate functions."""

from .errors import TypeMismatchError
from .value import compare_lt, is_numeric, type_of

AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})


def _numeric_values(name: str, values: list[object]) -> None:
    for v in values:
        if not is_numeric(v):
            raise TypeMismatchError(f"{name}() needs numeric input, got {type_of(v)}")


def _extreme(name: str, values: list[object]) -> object:
    best = values[0]
    for v in values[1:]:
        if name == "min":
            if compare_lt(v, best):
                best = v
        elif compare_lt(best, v):
            best = v
    return best


def aggregate(name: str, values: list[object], star: bool = False) -> object:
    """Fold `values`; with star=True (count(*)) every element is one row."""
    name = name.lower()
    if name == "count" and star:
        return len(values)
    present = [v for v in values if v is not None]
    if name == "count":
        return len(present)
    if name in ("sum", "avg"):
        _numeric_values(name, present)
        if not present:
            return None
        if name == "avg":
            return float(sum(present)) / len(present)  # type: ignore[arg-type]
        total = sum(present)  # type: ignore[arg-type]
        all_int = all(isinstance(v, int) for v in present)
        return total if all_int else float(total)
    if name in ("min", "max"):
        return _extreme(name, present) if present else None
    raise ValueError(f"unknown aggregate {name!r}")
