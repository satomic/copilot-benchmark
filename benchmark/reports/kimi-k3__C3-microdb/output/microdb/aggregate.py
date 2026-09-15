"""Aggregate functions: count, sum, avg, min, max.

Aggregates ignore NULL inputs entirely, except ``count(*)`` which counts rows.
Over a group with no non-NULL input, ``count`` is 0 and ``sum``/``avg``/``min``/
``max`` are all NULL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import ArityError, TypeMismatchError
from .value import INT, arith, compare_lt, is_numeric, type_of

if TYPE_CHECKING:
    from .expr import Row
    from .parser import FuncCall, Node

AGGREGATE_NAMES = frozenset({"count", "sum", "avg", "min", "max"})


def is_aggregate_name(name: str) -> bool:
    """True when ``name`` (any case) is an aggregate function name."""
    return name.lower() in AGGREGATE_NAMES


def find_aggregates(node: Node) -> list[FuncCall]:
    """Collect all aggregate call nodes in an expression tree."""
    from . import parser as _p

    found: list[FuncCall] = []

    def walk(n: Node) -> None:
        if isinstance(n, _p.FuncCall):
            if is_aggregate_name(n.name):
                found.append(n)
                return  # aggregates may not nest; args hold no aggregates
            for a in n.args:
                walk(a)
        elif isinstance(n, (_p.UnaryOp, _p.NotOp, _p.IsNull)):
            walk(n.operand)
        elif isinstance(n, _p.BinaryOp):
            walk(n.left)
            walk(n.right)

    walk(node)
    return found


def contains_aggregate(node: Node) -> bool:
    """True when the expression tree contains an aggregate call."""
    return bool(find_aggregates(node))


def compute(call: FuncCall, rows: list[Row]) -> object:
    """Evaluate one aggregate call over a group's rows."""
    from .expr import eval_expr

    name = call.name.lower()
    if call.star:
        return len(rows)  # count(*): counts rows, NULLs included
    if len(call.args) != 1:
        raise ArityError(f"{call.name} expects 1 argument, got {len(call.args)}")
    values: list[object] = []
    for row in rows:
        v = eval_expr(call.args[0], row)
        if v is not None:
            values.append(v)
    if name == "count":
        return len(values)
    if not values:
        return None  # sum/avg/min/max of no non-NULL input are NULL
    if name == "sum":
        return _sum(values)
    if name == "avg":
        total = _sum(values)
        return float(total) / len(values)  # avg always yields FLOAT
    best = values[0]
    for v in values[1:]:
        if name == "min" and compare_lt(v, best):
            best = v
        elif name == "max" and compare_lt(best, v):
            best = v
    return best


def _sum(values: list[object]) -> object:
    """Sum numeric values; INT when every value is INT, otherwise FLOAT."""
    total: object = 0
    all_int = True
    for v in values:
        if not is_numeric(v):
            raise TypeMismatchError(
                f"sum/avg require numeric input, got {type_of(v)}")
        if type_of(v) != INT:
            all_int = False
        total = arith("+", total, v)
    return total if all_int else float(total)  # type: ignore[arg-type]
