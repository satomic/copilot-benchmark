"""Aggregate functions: count, sum, avg, min, max."""

from __future__ import annotations

from .errors import TypeMismatchError, UnknownFunctionError
from .value import compare_lt, is_numeric, type_of

AGGREGATE_NAMES = frozenset({"count", "sum", "avg", "min", "max"})


class Aggregator:
    """Accumulates values for one group. NULL inputs are ignored except by count(*)."""

    name = ""

    def add(self, value: object) -> None:
        raise NotImplementedError

    def result(self) -> object:
        raise NotImplementedError


class CountStar(Aggregator):
    name = "count"

    def __init__(self) -> None:
        self.n = 0

    def add(self, value: object) -> None:
        self.n += 1

    def result(self) -> object:
        return self.n


class Count(Aggregator):
    name = "count"

    def __init__(self) -> None:
        self.n = 0

    def add(self, value: object) -> None:
        if value is not None:
            self.n += 1

    def result(self) -> object:
        return self.n


class Sum(Aggregator):
    name = "sum"

    def __init__(self) -> None:
        self.total: object = None
        self.n = 0

    def add(self, value: object) -> None:
        if value is None:
            return
        if not is_numeric(value):
            raise TypeMismatchError(f"{self.name} requires numeric input, got {type_of(value)}")
        self.total = value if self.total is None else self.total + value  # type: ignore[operator]
        self.n += 1

    def result(self) -> object:
        return self.total


class Avg(Sum):
    name = "avg"

    def result(self) -> object:
        if self.n == 0:
            return None
        return float(self.total) / self.n  # type: ignore[arg-type]


class Extreme(Aggregator):
    """Shared implementation of min and max."""

    want_less = True

    def __init__(self) -> None:
        self.best: object = None

    def add(self, value: object) -> None:
        if value is None:
            return
        if self.best is None:
            self.best = value
            return
        better = compare_lt(value, self.best) if self.want_less else compare_lt(self.best, value)
        if better:
            self.best = value

    def result(self) -> object:
        return self.best


class Min(Extreme):
    name = "min"
    want_less = True


class Max(Extreme):
    name = "max"
    want_less = False


def make_aggregator(name: str, star: bool) -> Aggregator:
    lname = name.lower()
    if lname not in AGGREGATE_NAMES:
        raise UnknownFunctionError(f"unknown aggregate {name!r}")
    if star:
        return CountStar()
    factories: dict[str, type[Aggregator]] = {
        "count": Count,
        "sum": Sum,
        "avg": Avg,
        "min": Min,
        "max": Max,
    }
    return factories[lname]()
