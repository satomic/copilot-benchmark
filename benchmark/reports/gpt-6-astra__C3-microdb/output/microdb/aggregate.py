"""Aggregate reducers over a single group's input values."""

from collections.abc import Iterable

from .errors import ArityError, TypeMismatchError, UnknownFunctionError
from .value import compare_lt, is_numeric


AGGREGATES = frozenset(("count", "sum", "avg", "min", "max"))


def check_arity(name: str, actual: int, star: bool = False) -> None:
    if name.lower() not in AGGREGATES:
        raise UnknownFunctionError(f"Unknown aggregate: {name}")
    if actual != 1 or (star and name.lower() != "count"):
        raise ArityError(f"{name} expects 1 argument; got {actual}")


def aggregate(name: str, values: Iterable[object]) -> object:
    name = name.lower()
    if name not in AGGREGATES:
        raise UnknownFunctionError(f"Unknown aggregate: {name}")
    present = [value for value in values if value is not None]
    if name == "count":
        return len(present)
    if not present:
        return None
    if name in ("sum", "avg"):
        if not all(is_numeric(value) for value in present):
            raise TypeMismatchError(f"{name} requires numeric input")
        total = sum(present)
        return total / len(present) if name == "avg" else total
    result = present[0]
    for value in present[1:]:
        smaller = compare_lt(value, result)
        if (name == "min" and smaller) or (
                name == "max" and compare_lt(result, value)):
            result = value
    return result
