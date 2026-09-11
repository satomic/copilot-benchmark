"""Expression evaluation: column resolution, scalar functions and operators."""

from __future__ import annotations

import dataclasses
from typing import Callable

from .errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from .parser import (
    AGGREGATE_NAMES,
    Binary,
    ColumnRef,
    Compare,
    Expr,
    FuncCall,
    IsNull,
    Literal,
    Logical,
    Not,
    Star,
    Unary,
)
from .value import (
    and_,
    arith,
    compare_op,
    is_numeric,
    is_text,
    negate,
    not_,
    or_,
    type_of,
)


@dataclasses.dataclass(frozen=True)
class Binding:
    """One resolvable column of the working row."""

    table: str | None
    name: str


@dataclasses.dataclass
class Context:
    """Everything an expression may consult while it is evaluated."""

    bindings: list[Binding]
    row: list[object]
    tables: frozenset[str] = frozenset()
    aliases: dict[str, object] | None = None
    columns_visible: bool = True
    aggregates: dict[tuple[object, ...], object] | None = None


def expr_key(expr: Expr) -> tuple[object, ...]:
    """Return a structural key ignoring source text, used to match expressions."""
    if isinstance(expr, Literal):
        return ("lit", type_of(expr.value), expr.value)
    if isinstance(expr, ColumnRef):
        return ("col", expr.table, expr.name)
    if isinstance(expr, Star):
        return ("star", expr.table)
    if isinstance(expr, FuncCall):
        return ("func", expr.name.lower(), tuple(expr_key(a) for a in expr.args))
    if isinstance(expr, Unary):
        return ("unary", expr.op, expr_key(expr.operand))
    if isinstance(expr, Binary):
        return ("bin", expr.op, expr_key(expr.left), expr_key(expr.right))
    if isinstance(expr, Compare):
        return ("cmp", expr.op, expr_key(expr.left), expr_key(expr.right))
    if isinstance(expr, IsNull):
        return ("isnull", expr.negated, expr_key(expr.operand))
    if isinstance(expr, Not):
        return ("not", expr_key(expr.operand))
    if isinstance(expr, Logical):
        return ("logic", expr.op, expr_key(expr.left), expr_key(expr.right))
    raise TypeMismatchError(f"unsupported expression node {type(expr).__name__}")


def resolve_column(ctx: Context, table: str | None, name: str) -> object:
    """Look up a column reference in ``ctx``, honouring alias shadowing."""
    if table is None and ctx.aliases is not None and name in ctx.aliases:
        return ctx.aliases[name]
    if not ctx.columns_visible:
        raise UnknownColumnError(f"unknown output column {name!r}")
    if table is not None and table not in ctx.tables:
        raise UnknownTableError(f"unknown table {table!r}")
    matches = [
        index
        for index, binding in enumerate(ctx.bindings)
        if binding.name == name and (table is None or binding.table == table)
    ]
    if not matches:
        qualified = f"{table}.{name}" if table else name
        raise UnknownColumnError(f"unknown column {qualified!r}")
    if len(matches) > 1:
        raise AmbiguousColumnError(f"column {name!r} is ambiguous")
    return ctx.row[matches[0]]


def evaluate(expr: Expr, ctx: Context) -> object:
    """Evaluate ``expr`` against ``ctx`` and return a microdb value."""
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        return resolve_column(ctx, expr.table, expr.name)
    if isinstance(expr, FuncCall):
        return _eval_call(expr, ctx)
    if isinstance(expr, Unary):
        return negate(evaluate(expr.operand, ctx))
    if isinstance(expr, Binary):
        return arith(expr.op, evaluate(expr.left, ctx), evaluate(expr.right, ctx))
    if isinstance(expr, Compare):
        return compare_op(expr.op, evaluate(expr.left, ctx), evaluate(expr.right, ctx))
    if isinstance(expr, IsNull):
        result = evaluate(expr.operand, ctx) is None
        return (not result) if expr.negated else result
    if isinstance(expr, Not):
        return not_(as_logical(evaluate(expr.operand, ctx)))
    if isinstance(expr, Logical):
        return _eval_logical(expr, ctx)
    if isinstance(expr, Star):
        raise TypeMismatchError("'*' is not a value")
    raise TypeMismatchError(f"unsupported expression node {type(expr).__name__}")


def _eval_logical(expr: Logical, ctx: Context) -> bool | None:
    left = as_logical(evaluate(expr.left, ctx))
    right = as_logical(evaluate(expr.right, ctx))
    return and_(left, right) if expr.op == "AND" else or_(left, right)


def as_logical(v: object) -> bool | None:
    """Require a logical value; anything else is a type error."""
    if v is None or isinstance(v, bool):
        return v
    raise TypeMismatchError(f"expected a BOOL value, got {type_of(v)}")


def _eval_call(expr: FuncCall, ctx: Context) -> object:
    name = expr.name.lower()
    if name in AGGREGATE_NAMES:
        if ctx.aggregates is None:
            raise AggregateError(f"aggregate {expr.name!r} is not allowed here")
        key = expr_key(expr)
        if key not in ctx.aggregates:
            raise AggregateError(f"aggregate {expr.text!r} was not computed")
        return ctx.aggregates[key]
    if name not in SCALAR_ARITY:
        raise UnknownFunctionError(f"unknown function {expr.name!r}")
    args = [evaluate(arg, ctx) for arg in expr.args]
    _check_arity(name, len(args))
    return SCALAR_FUNCTIONS[name](args)


SCALAR_ARITY: dict[str, tuple[int, int | None]] = {
    "concat": (2, None),
    "upper": (1, 1),
    "lower": (1, 1),
    "length": (1, 1),
    "abs": (1, 1),
    "coalesce": (1, None),
}


def _check_arity(name: str, count: int) -> None:
    low, high = SCALAR_ARITY[name]
    if count < low or (high is not None and count > high):
        want = str(low) if high == low else f"at least {low}"
        raise ArityError(f"function {name!r} expects {want} arguments, got {count}")


def _require_text(name: str, v: object) -> None:
    if not is_text(v):
        raise TypeMismatchError(f"function {name!r} requires TEXT, got {type_of(v)}")


def _fn_concat(args: list[object]) -> object:
    for arg in args:
        if arg is not None:
            _require_text("concat", arg)
    if any(arg is None for arg in args):
        return None
    return "".join(str(arg) for arg in args)


def _fn_upper(args: list[object]) -> object:
    if args[0] is None:
        return None
    _require_text("upper", args[0])
    return str(args[0]).upper()


def _fn_lower(args: list[object]) -> object:
    if args[0] is None:
        return None
    _require_text("lower", args[0])
    return str(args[0]).lower()


def _fn_length(args: list[object]) -> object:
    if args[0] is None:
        return None
    _require_text("length", args[0])
    return len(str(args[0]))


def _fn_abs(args: list[object]) -> object:
    if args[0] is None:
        return None
    if not is_numeric(args[0]):
        raise TypeMismatchError(f"function 'abs' requires a number, got {type_of(args[0])}")
    return abs(args[0])  # type: ignore[arg-type]


def _fn_coalesce(args: list[object]) -> object:
    for arg in args:
        if arg is not None:
            return arg
    return None


SCALAR_FUNCTIONS: dict[str, Callable[[list[object]], object]] = {
    "concat": _fn_concat,
    "upper": _fn_upper,
    "lower": _fn_lower,
    "length": _fn_length,
    "abs": _fn_abs,
    "coalesce": _fn_coalesce,
}
