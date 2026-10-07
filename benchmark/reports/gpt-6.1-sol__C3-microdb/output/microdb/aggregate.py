"""Aggregate reduction; NULL inputs are removed before type checking."""

from collections.abc import Iterable

from .errors import ArityError, TypeMismatchError, UnknownFunctionError
from .value import compare_lt, is_numeric


def check_arity(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise ArityError(f"{name} expects {expected} arguments, got {actual}")


def aggregate(name: str, values: Iterable[object]) -> object:
    name = name.lower()
    if name not in ("count", "sum", "avg", "min", "max"):
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
    best = present[0]
    for value in present[1:]:
        less = compare_lt(value, best) if name == "min" else compare_lt(best, value)
        if less:
            best = value
    return best


def count(values: Iterable[object]) -> int:
    return sum(1 for value in values if value is not None)


def sum_(values: Iterable[object]) -> object:
    return aggregate("sum", values)


def avg(values: Iterable[object]) -> object:
    return aggregate("avg", values)


def min_(values: Iterable[object]) -> object:
    return aggregate("min", values)


def max_(values: Iterable[object]) -> object:
    return aggregate("max", values)
