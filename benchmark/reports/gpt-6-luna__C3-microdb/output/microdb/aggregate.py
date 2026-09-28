from __future__ import annotations

from collections.abc import Callable, Sequence

from .errors import ArityError, TypeMismatchError
from .parser import Expr
from .value import compare_eq, compare_lt, is_numeric, type_of


def evaluate_aggregate(expr: Expr, rows: Sequence[object],
                       evaluate_argument: Callable[[Expr, object], object]) -> object:
    name = str(expr.value).lower()
    if len(expr.children) != 1:
        raise ArityError(f"{name} expects 1 argument, got {len(expr.children)}")
    argument = expr.children[0]
    if name == "count" and argument.kind == "STAR":
        return len(rows)
    if argument.kind == "STAR":
        raise TypeMismatchError("* is only valid in count(*)")
    values = [evaluate_argument(argument, row) for row in rows]
    present = [value for value in values if value is not None]
    if name == "count":
        return len(present)
    if not present:
        return None
    if name in {"sum", "avg"}:
        if any(not is_numeric(value) for value in present):
            raise TypeMismatchError(f"{name} requires numeric input")
        total = sum(present)
        if name == "avg":
            return float(total) / len(present)
        return float(total) if any(type_of(value) == "FLOAT" for value in present) else total
    result = present[0]
    for value in present[1:]:
        if compare_eq(result, value) is None:
            continue
        less = compare_lt(value, result)
        if name == "min" and less is True:
            result = value
        elif name == "max" and compare_lt(result, value) is True:
            result = value
    return result
