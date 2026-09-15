"""Aggregate functions: count, sum, avg, min, max."""

from __future__ import annotations

from microdb.errors import TypeMismatchError
from microdb.expr import _check_arity
from microdb.parser import Call
from microdb.value import compare_lt, is_numeric, type_of


def eval_aggregate(call: Call, values: list[object]) -> object:
    if call.star:
        if call.name != "count":
            raise TypeMismatchError("* is only valid in count(*)")
        return len(values)
    _check_arity(call.name, len(call.args), star=False)
    if call.name == "count":
        return sum(1 for v in values if v is not None)
    nonempty = [v for v in values if v is not None]
    if not nonempty:
        return None
    if call.name == "sum":
        return _sum(nonempty)
    if call.name == "avg":
        return _avg(nonempty)
    if call.name == "min":
        return _minmax(nonempty, take_lt=True)
    if call.name == "max":
        return _minmax(nonempty, take_lt=False)
    raise TypeMismatchError(f"unknown aggregate {call.name}")


def _sum(vals: list[object]) -> object:
    total: object = 0
    all_int = True
    for v in vals:
        if not is_numeric(v):
            raise TypeMismatchError("sum requires numeric input")
        if type_of(v) != "INT":
            all_int = False
        total = total + v  # type: ignore[operator]
    if all_int:
        return int(total)  # type: ignore[arg-type]
    return float(total)  # type: ignore[arg-type]


def _avg(vals: list[object]) -> object:
    total = 0.0
    for v in vals:
        if not is_numeric(v):
            raise TypeMismatchError("avg requires numeric input")
        total += float(v)  # type: ignore[arg-type]
    return total / len(vals)


def _minmax(vals: list[object], take_lt: bool) -> object:
    best = vals[0]
    for v in vals[1:]:
        less = compare_lt(v, best)
        if take_lt and less is True:
            best = v
        elif (not take_lt) and less is False and compare_lt(best, v) is True:
            best = v
    return best
