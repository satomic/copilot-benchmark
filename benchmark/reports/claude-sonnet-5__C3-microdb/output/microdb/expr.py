"""Expression evaluation: resolving columns and evaluating expr trees against rows."""

from __future__ import annotations

from microdb import value as V
from microdb.errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from microdb.parser import AGGREGATE_NAMES, BinOp, ColumnRef, FuncCall, IsNull, Literal, UnaryOp

Schema = list  # list[tuple[Optional[str], str]]

SCALAR_FUNCS = {"CONCAT", "UPPER", "LOWER", "LENGTH", "ABS", "COALESCE"}


def resolve_column(schema: Schema, table: object, name: str) -> int:
    """Resolve a (possibly qualified) column reference to an index in schema."""
    if table is not None:
        valid_tables = {t for t, _ in schema if t is not None}
        if table not in valid_tables:
            raise UnknownTableError(f"unknown table: {table!r}")
        for i, (t, n) in enumerate(schema):
            if t == table and n == name:
                return i
        raise UnknownColumnError(f"unknown column: {table}.{name}")
    matches = [i for i, (_, n) in enumerate(schema) if n == name]
    if not matches:
        raise UnknownColumnError(f"unknown column: {name!r}")
    if len(matches) > 1:
        raise AmbiguousColumnError(f"ambiguous column: {name!r}")
    return matches[0]


def as_bool_or_null(v: object) -> bool | None:
    """Ensure v is a BOOL or NULL; raise TypeMismatchError otherwise."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    raise TypeMismatchError(f"expected BOOL, got {V.type_of(v)}")


def apply_binop(op: str, left: object, right: object) -> object:
    """Apply a binary operator (arithmetic, comparison or boolean) to evaluated operands."""
    if op in ("+", "-", "*", "/", "%"):
        return V.arith(op, left, right)
    if op == "=":
        return V.compare_eq(left, right)
    if op == "<>":
        return V.not_(V.compare_eq(left, right))
    if op == "<":
        return V.compare_lt(left, right)
    if op == ">":
        return V.compare_lt(right, left)
    if op == "<=":
        return V.not_(V.compare_lt(right, left))
    if op == ">=":
        return V.not_(V.compare_lt(left, right))
    if op == "AND":
        return V.and_(as_bool_or_null(left), as_bool_or_null(right))
    if op == "OR":
        return V.or_(as_bool_or_null(left), as_bool_or_null(right))
    raise TypeMismatchError(f"unknown operator: {op}")


def apply_unary(op: str, val: object) -> object:
    if op == "-":
        return V.negate(val)
    if op == "NOT":
        return V.not_(as_bool_or_null(val))
    raise TypeMismatchError(f"unknown unary operator: {op}")


def call_scalar_function(name: str, args: list) -> object:
    """Dispatch a scalar (non-aggregate) function call given already-evaluated args."""
    upper = name.upper()
    if upper in AGGREGATE_NAMES:
        raise AggregateError(f"aggregate {name} used where not permitted")
    if upper not in SCALAR_FUNCS:
        raise UnknownFunctionError(f"unknown function: {name}")
    if upper == "CONCAT":
        return _concat(name, args)
    if upper == "UPPER":
        return _text_fn(name, args, str.upper)
    if upper == "LOWER":
        return _text_fn(name, args, str.lower)
    if upper == "LENGTH":
        return _length_fn(name, args)
    if upper == "ABS":
        return _abs_fn(name, args)
    return _coalesce_fn(name, args)


def _concat(name: str, args: list) -> object:
    if len(args) < 2:
        raise ArityError(f"{name} expects at least 2 arguments, got {len(args)}")
    if any(a is None for a in args):
        return None
    for a in args:
        if not isinstance(a, str):
            raise TypeMismatchError(f"{name} requires TEXT arguments")
    return "".join(args)


def _text_fn(name: str, args: list, fn) -> object:
    if len(args) != 1:
        raise ArityError(f"{name} expects 1 argument, got {len(args)}")
    a = args[0]
    if a is None:
        return None
    if not isinstance(a, str):
        raise TypeMismatchError(f"{name} requires a TEXT argument")
    return fn(a)


def _length_fn(name: str, args: list) -> object:
    if len(args) != 1:
        raise ArityError(f"{name} expects 1 argument, got {len(args)}")
    a = args[0]
    if a is None:
        return None
    if not isinstance(a, str):
        raise TypeMismatchError(f"{name} requires a TEXT argument")
    return len(a)


def _abs_fn(name: str, args: list) -> object:
    if len(args) != 1:
        raise ArityError(f"{name} expects 1 argument, got {len(args)}")
    a = args[0]
    if a is None:
        return None
    if not V.is_numeric(a):
        raise TypeMismatchError(f"{name} requires a numeric argument")
    return abs(a)


def _coalesce_fn(name: str, args: list) -> object:
    if len(args) < 1:
        raise ArityError(f"{name} expects at least 1 argument, got {len(args)}")
    for a in args:
        if a is not None:
            return a
    return None


def eval_expr(expr: object, schema: Schema, row: list) -> object:
    """Evaluate an expression against a single row (no aggregates allowed)."""
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        idx = resolve_column(schema, expr.table, expr.name)
        return row[idx]
    if isinstance(expr, UnaryOp):
        return apply_unary(expr.op, eval_expr(expr.operand, schema, row))
    if isinstance(expr, BinOp):
        left = eval_expr(expr.left, schema, row)
        right = eval_expr(expr.right, schema, row)
        return apply_binop(expr.op, left, right)
    if isinstance(expr, IsNull):
        result = eval_expr(expr.expr, schema, row) is None
        return (not result) if expr.negated else result
    if isinstance(expr, FuncCall):
        args = [eval_expr(a, schema, row) for a in expr.args]
        return call_scalar_function(expr.name, args)
    raise TypeMismatchError(f"cannot evaluate expression node: {expr!r}")


def eval_predicate(expr: object, schema: Schema, row: list) -> bool | None:
    """Evaluate expr as a predicate; ensures the result is BOOL-or-NULL."""
    return as_bool_or_null(eval_expr(expr, schema, row))


def expr_equal(a: object, b: object) -> bool:
    """Structural equality of two expression trees, ignoring source position."""
    if type(a) is not type(b):
        return False
    if isinstance(a, Literal):
        return type(a.value) is type(b.value) and a.value == b.value
    if isinstance(a, ColumnRef):
        return a.table == b.table and a.name == b.name
    if isinstance(a, UnaryOp):
        return a.op == b.op and expr_equal(a.operand, b.operand)
    if isinstance(a, BinOp):
        return a.op == b.op and expr_equal(a.left, b.left) and expr_equal(a.right, b.right)
    if isinstance(a, IsNull):
        return a.negated == b.negated and expr_equal(a.expr, b.expr)
    if isinstance(a, FuncCall):
        return (
            a.name.upper() == b.name.upper()
            and a.star == b.star
            and len(a.args) == len(b.args)
            and all(expr_equal(x, y) for x, y in zip(a.args, b.args))
        )
    return False


def contains_aggregate(expr: object) -> bool:
    """True if expr contains an aggregate function call anywhere in its tree."""
    if isinstance(expr, FuncCall):
        if expr.name.upper() in AGGREGATE_NAMES:
            return True
        return any(contains_aggregate(a) for a in expr.args)
    if isinstance(expr, UnaryOp):
        return contains_aggregate(expr.operand)
    if isinstance(expr, BinOp):
        return contains_aggregate(expr.left) or contains_aggregate(expr.right)
    if isinstance(expr, IsNull):
        return contains_aggregate(expr.expr)
    return False


def substitute_aliases(expr: object, alias_map: dict) -> object:
    """Replace bare unqualified ColumnRefs matching an alias with a Literal of its value."""
    if isinstance(expr, ColumnRef) and expr.table is None and expr.name in alias_map:
        return Literal(alias_map[expr.name], expr.start, expr.end)
    if isinstance(expr, UnaryOp):
        return UnaryOp(expr.op, substitute_aliases(expr.operand, alias_map), expr.start, expr.end)
    if isinstance(expr, BinOp):
        return BinOp(
            expr.op,
            substitute_aliases(expr.left, alias_map),
            substitute_aliases(expr.right, alias_map),
            expr.start,
            expr.end,
        )
    if isinstance(expr, IsNull):
        return IsNull(substitute_aliases(expr.expr, alias_map), expr.negated, expr.start, expr.end)
    if isinstance(expr, FuncCall):
        return FuncCall(
            expr.name,
            [substitute_aliases(a, alias_map) for a in expr.args],
            expr.star,
            expr.start,
            expr.end,
        )
    return expr


def contains_column_ref(expr: object) -> bool:
    """True if expr still references any column (used post-substitution/post-DISTINCT)."""
    if isinstance(expr, ColumnRef):
        return True
    if isinstance(expr, UnaryOp):
        return contains_column_ref(expr.operand)
    if isinstance(expr, BinOp):
        return contains_column_ref(expr.left) or contains_column_ref(expr.right)
    if isinstance(expr, IsNull):
        return contains_column_ref(expr.expr)
    if isinstance(expr, FuncCall):
        return any(contains_column_ref(a) for a in expr.args)
    return False
