from collections.abc import Callable

from .errors import ArityError, TypeMismatchError
from .expr import Call, Star
from .value import compare_lt, is_numeric


def _check_arity(call: Call, expected: int = 1) -> None:
    if len(call.args) != expected:
        raise ArityError(
            f"{call.name} expects {expected} arguments, got {len(call.args)}"
        )


def _extreme(values: list[object], maximum: bool) -> object:
    if not values:
        return None
    result = values[0]
    for value in values[1:]:
        less = compare_lt(result, value) if maximum else compare_lt(value, result)
        if less is True:
            result = value
    return result


def aggregate(call: Call, values: list[object], row_count: int) -> object:
    name = call.name.lower()
    _check_arity(call)
    if name == "count":
        return row_count if isinstance(call.args[0], Star) else len(values)
    if isinstance(call.args[0], Star):
        raise TypeMismatchError(f"{name}(*) is not allowed")
    if name in {"sum", "avg"}:
        if any(not is_numeric(value) for value in values):
            raise TypeMismatchError(f"{name} requires numeric input")
        if not values:
            return None
        total = sum(values)  # type: ignore[arg-type]
        return float(total) / len(values) if name == "avg" else total
    if name == "min":
        return _extreme(values, False)
    if name == "max":
        return _extreme(values, True)
    raise TypeMismatchError(f"unknown aggregate: {name}")


def evaluate_aggregate(
    call: Call, rows: list[object], evaluator: Callable[[object, object], object]
) -> object:
    _check_arity(call)
    if isinstance(call.args[0], Star):
        values: list[object] = []
    else:
        values = [
            value
            for row in rows
            if (value := evaluator(call.args[0], row)) is not None
        ]
    return aggregate(call, values, len(rows))
