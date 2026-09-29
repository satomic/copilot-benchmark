"""Expression binding (name resolution) and evaluation."""

from __future__ import annotations

import dataclasses
from typing import Callable

from .errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    MicroDBError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from .parser import (
    AggCall,
    BinaryOp,
    ColumnRef,
    Expr,
    FuncCall,
    IsNull,
    Literal,
    Not,
    UnaryMinus,
)
from .value import and_, arith, compare, is_numeric, negate, not_, or_, type_of

# ---------------------------------------------------------------- bound nodes


@dataclasses.dataclass(frozen=True)
class BoundColumn(Expr):
    """A resolved reference to a position in the working row."""

    index: int
    name: str = dataclasses.field(default="", compare=False)


@dataclasses.dataclass(frozen=True)
class OutputColumn(Expr):
    """A reference to a position in the projected output row (ORDER BY)."""

    index: int


@dataclasses.dataclass(frozen=True)
class GroupKey(Expr):
    """A reference to a component of the current group's key."""

    index: int


@dataclasses.dataclass(frozen=True)
class AggRef(Expr):
    """A reference to a precomputed aggregate value of the current group."""

    index: int


@dataclasses.dataclass
class Context:
    """Evaluation context; each field is only needed by some node kinds."""

    row: list | None = None
    out: list | None = None
    keys: list | None = None
    aggs: list | None = None


# ---------------------------------------------------------------- scope


class Scope:
    """The columns visible to an expression: (table name, column name) pairs."""

    def __init__(self, entries: list[tuple[str, str]], tables: list[str]) -> None:
        self.entries = list(entries)
        self.tables = list(tables)

    def resolve(self, table: str | None, name: str) -> int:
        """Return the working-row index of a column reference."""
        if table is not None and table not in self.tables:
            raise UnknownTableError(f"unknown table {table!r}")
        matches = [
            i for i, (t, c) in enumerate(self.entries)
            if c == name and (table is None or t == table)
        ]
        label = name if table is None else f"{table}.{name}"
        if not matches:
            raise UnknownColumnError(f"unknown column {label!r}")
        if len(matches) > 1:
            raise AmbiguousColumnError(f"column reference {label!r} is ambiguous")
        return matches[0]


# ---------------------------------------------------------------- tree helpers


def map_children(node: Expr, fn: Callable[[Expr], Expr]) -> Expr:
    """Return node with fn applied to each direct child expression."""
    if isinstance(node, (UnaryMinus, Not, IsNull)):
        return dataclasses.replace(node, operand=fn(node.operand))
    if isinstance(node, BinaryOp):
        return dataclasses.replace(node, left=fn(node.left), right=fn(node.right))
    if isinstance(node, (FuncCall, AggCall)):
        return dataclasses.replace(node, args=tuple(fn(a) for a in node.args))
    return node


def contains_aggregate(node: Expr | None) -> bool:
    """True when an aggregate call appears anywhere inside node."""
    if node is None:
        return False
    if isinstance(node, AggCall):
        return True
    found = []

    def visit(child: Expr) -> Expr:
        found.append(contains_aggregate(child))
        return child

    map_children(node, visit)
    return any(found)


# ---------------------------------------------------------------- functions


def _text_args(name: str, args: list[object]) -> None:
    for a in args:
        if a is not None and not isinstance(a, str):
            raise TypeMismatchError(f"{name}() requires TEXT, got {type_of(a)}")


def _fn_concat(args: list[object]) -> object:
    _text_args("concat", args)
    if any(a is None for a in args):
        return None
    return "".join(args)  # type: ignore[arg-type]


def _fn_upper(args: list[object]) -> object:
    _text_args("upper", args)
    return None if args[0] is None else args[0].upper()  # type: ignore[union-attr]


def _fn_lower(args: list[object]) -> object:
    _text_args("lower", args)
    return None if args[0] is None else args[0].lower()  # type: ignore[union-attr]


def _fn_length(args: list[object]) -> object:
    _text_args("length", args)
    return None if args[0] is None else len(args[0])  # type: ignore[arg-type]


def _fn_abs(args: list[object]) -> object:
    v = args[0]
    if v is None:
        return None
    if not is_numeric(v):
        raise TypeMismatchError(f"abs() requires a number, got {type_of(v)}")
    return abs(v)  # type: ignore[arg-type]


def _fn_coalesce(args: list[object]) -> object:
    for a in args:
        if a is not None:
            return a
    return None


# name -> (minimum arity, maximum arity or None, implementation)
FUNCTIONS: dict[str, tuple[int, int | None, Callable[[list[object]], object]]] = {
    "concat": (2, None, _fn_concat),
    "upper": (1, 1, _fn_upper),
    "lower": (1, 1, _fn_lower),
    "length": (1, 1, _fn_length),
    "abs": (1, 1, _fn_abs),
    "coalesce": (1, None, _fn_coalesce),
}


def _arity_message(name: str, low: int, high: int | None, got: int) -> str:
    if high is None:
        expected = f"at least {low}"
    elif low == high:
        expected = f"exactly {low}"
    else:
        expected = f"{low} to {high}"
    return f"function {name}() expects {expected} argument(s), got {got}"


def check_function(name: str, argc: int) -> None:
    """Validate that a scalar function exists and accepts argc arguments."""
    spec = FUNCTIONS.get(name.lower())
    if spec is None:
        raise UnknownFunctionError(f"unknown function {name!r}")
    low, high, _ = spec
    if argc < low or (high is not None and argc > high):
        raise ArityError(_arity_message(name, low, high, argc))


def check_aggregate(node: AggCall) -> None:
    """Validate the arity of an aggregate call."""
    if node.star:
        return
    if len(node.args) != 1:
        raise ArityError(_arity_message(node.name, 1, 1, len(node.args)))


def call_function(name: str, args: list[object]) -> object:
    """Invoke a scalar function on already-evaluated arguments."""
    check_function(name, len(args))
    return FUNCTIONS[name.lower()][2](args)


# ---------------------------------------------------------------- binding


def bind(node: Expr, scope: Scope, allow_aggregates: bool = False, clause: str = "") -> Expr:
    """Resolve column references to positions and validate calls.

    Aggregates are rejected with AggregateError unless allow_aggregates is set.
    """
    if isinstance(node, ColumnRef):
        return BoundColumn(scope.resolve(node.table, node.name), node.name)
    if isinstance(node, FuncCall):
        check_function(node.name, len(node.args))
    if isinstance(node, AggCall):
        if not allow_aggregates:
            where = f" in {clause}" if clause else " here"
            raise AggregateError(f"aggregate {node.name}() is not allowed{where}")
        check_aggregate(node)
        return map_children(node, lambda c: bind(c, scope, False, "an aggregate argument"))
    return map_children(node, lambda c: bind(c, scope, allow_aggregates, clause))


# ---------------------------------------------------------------- evaluation


def _eval_binary(node: BinaryOp, ctx: Context) -> object:
    left = evaluate(node.left, ctx)
    right = evaluate(node.right, ctx)
    op = node.op
    if op == "AND":
        return and_(left, right)  # type: ignore[arg-type]
    if op == "OR":
        return or_(left, right)  # type: ignore[arg-type]
    if op in ("+", "-", "*", "/", "%"):
        return arith(op, left, right)
    return compare(op, left, right)


def evaluate(node: Expr, ctx: Context) -> object:
    """Evaluate a bound expression in the given context."""
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, BoundColumn):
        return ctx.row[node.index]  # type: ignore[index]
    if isinstance(node, OutputColumn):
        return ctx.out[node.index]  # type: ignore[index]
    if isinstance(node, GroupKey):
        return ctx.keys[node.index]  # type: ignore[index]
    if isinstance(node, AggRef):
        return ctx.aggs[node.index]  # type: ignore[index]
    if isinstance(node, BinaryOp):
        return _eval_binary(node, ctx)
    if isinstance(node, UnaryMinus):
        return negate(evaluate(node.operand, ctx))
    if isinstance(node, Not):
        return not_(evaluate(node.operand, ctx))  # type: ignore[arg-type]
    if isinstance(node, IsNull):
        return (evaluate(node.operand, ctx) is None) != node.negated
    if isinstance(node, FuncCall):
        return call_function(node.name, [evaluate(a, ctx) for a in node.args])
    if isinstance(node, AggCall):
        raise MicroDBError(f"aggregate {node.name}() evaluated outside a group")
    raise MicroDBError(f"cannot evaluate unbound expression {node!r}")
