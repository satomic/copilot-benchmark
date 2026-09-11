"""Aggregate functions: count, sum, avg, min, max, plus group-aware expression evaluation."""

from __future__ import annotations

from microdb import value as V
from microdb.errors import TypeMismatchError
from microdb.expr import apply_binop, apply_unary, call_scalar_function, eval_expr, expr_equal
from microdb.parser import AGGREGATE_NAMES, BinOp, ColumnRef, FuncCall, IsNull, Literal, UnaryOp


def _collect_values(func: object, schema: list, group_rows: list) -> list:
    arg = func.args[0]
    return [eval_expr(arg, schema, row) for row in group_rows]


def _sum(non_null: list) -> object:
    if not non_null:
        return None
    for v in non_null:
        if not V.is_numeric(v):
            raise TypeMismatchError("sum requires numeric input")
    total = sum(non_null)
    if all(isinstance(v, int) for v in non_null):
        return int(total)
    return float(total)


def _avg(non_null: list) -> object:
    if not non_null:
        return None
    for v in non_null:
        if not V.is_numeric(v):
            raise TypeMismatchError("avg requires numeric input")
    return float(sum(non_null)) / len(non_null)


def _min_max(non_null: list, is_max: bool) -> object:
    if not non_null:
        return None
    kinds = {V.type_of(v) for v in non_null}
    if "TEXT" in kinds and kinds - {"TEXT"}:
        raise TypeMismatchError("cannot mix TEXT with other types")
    if "BOOL" in kinds and kinds - {"BOOL"}:
        raise TypeMismatchError("cannot mix BOOL with other types")
    return max(non_null) if is_max else min(non_null)


def evaluate_aggregate(func: object, schema: list, group_rows: list) -> object:
    """Evaluate a single aggregate FuncCall over the rows belonging to one group."""
    name = func.name.upper()
    if name == "COUNT":
        if func.star:
            return len(group_rows)
        values = _collect_values(func, schema, group_rows)
        return sum(1 for v in values if v is not None)
    values = _collect_values(func, schema, group_rows)
    non_null = [v for v in values if v is not None]
    if name == "SUM":
        return _sum(non_null)
    if name == "AVG":
        return _avg(non_null)
    if name == "MIN":
        return _min_max(non_null, is_max=False)
    if name == "MAX":
        return _min_max(non_null, is_max=True)
    raise TypeMismatchError(f"unknown aggregate: {func.name}")


def evaluate_with_aggregates(expr: object, schema: list, group_rows: list, group_by_exprs: list) -> object:
    """Evaluate expr against a group: aggregate calls run over the whole group,
    grouping-key subexpressions use a representative row, everything else recurses."""
    if any(expr_equal(expr, g) for g in group_by_exprs):
        rep_row = group_rows[0] if group_rows else []
        return eval_expr(expr, schema, rep_row)
    if isinstance(expr, FuncCall) and expr.name.upper() in AGGREGATE_NAMES:
        return evaluate_aggregate(expr, schema, group_rows)
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        rep_row = group_rows[0] if group_rows else []
        return eval_expr(expr, schema, rep_row)
    if isinstance(expr, UnaryOp):
        operand = evaluate_with_aggregates(expr.operand, schema, group_rows, group_by_exprs)
        return apply_unary(expr.op, operand)
    if isinstance(expr, BinOp):
        left = evaluate_with_aggregates(expr.left, schema, group_rows, group_by_exprs)
        right = evaluate_with_aggregates(expr.right, schema, group_rows, group_by_exprs)
        return apply_binop(expr.op, left, right)
    if isinstance(expr, IsNull):
        result = evaluate_with_aggregates(expr.expr, schema, group_rows, group_by_exprs) is None
        return (not result) if expr.negated else result
    if isinstance(expr, FuncCall):
        args = [evaluate_with_aggregates(a, schema, group_rows, group_by_exprs) for a in expr.args]
        return call_scalar_function(expr.name, args)
    raise TypeMismatchError(f"cannot evaluate expression node: {expr!r}")
