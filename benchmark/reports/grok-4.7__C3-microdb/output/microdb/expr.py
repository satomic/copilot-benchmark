"""Expression evaluation and grouping equivalence."""

from __future__ import annotations

from collections.abc import Callable

from microdb.aggregate import check_arity, is_aggregate_name
from microdb.errors import (
    AggregateError,
    AmbiguousColumnError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from microdb.parser import (
    BinaryOp,
    ColumnRef,
    Expr,
    FuncCall,
    IsNull,
    Literal,
    SelectItem,
    UnaryOp,
)
from microdb.value import arith, compare, negate, not_, type_of

Resolver = Callable[[str | None, str], object]
_SCALARS = frozenset({"concat", "upper", "lower", "length", "abs", "coalesce"})


def evaluate(
    expr: Expr,
    resolve: Resolver,
    aggregates: dict[int, object] | None = None,
    allow_aggregates: bool = False,
) -> object:
    """Evaluate *expr*. Aggregates return precomputed values when allowed."""
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        return resolve(expr.table, expr.name)
    if isinstance(expr, UnaryOp):
        return _unary(expr, resolve, aggregates, allow_aggregates)
    if isinstance(expr, IsNull):
        return _is_null(expr, resolve, aggregates, allow_aggregates)
    if isinstance(expr, BinaryOp):
        return _binary(expr, resolve, aggregates, allow_aggregates)
    if isinstance(expr, FuncCall):
        return _call(expr, resolve, aggregates, allow_aggregates)
    raise TypeMismatchError("unknown expression")


def contains_aggregate(expr: Expr) -> bool:
    """Return True if *expr* contains an aggregate call."""
    found: list[FuncCall] = []
    collect_aggregates(expr, found)
    return bool(found)


def is_aggregate_call(expr: Expr) -> bool:
    """Return True if *expr* itself is an aggregate call."""
    return isinstance(expr, FuncCall) and is_aggregate_name(expr.name)


def collect_aggregates(expr: Expr, found: list[FuncCall]) -> None:
    """Append aggregate calls in *expr* to *found*, including nested scalars."""
    if isinstance(expr, FuncCall):
        if is_aggregate_name(expr.name):
            found.append(expr)
        for arg in expr.args:
            collect_aggregates(arg, found)
        return
    if isinstance(expr, BinaryOp):
        collect_aggregates(expr.left, found)
        collect_aggregates(expr.right, found)
        return
    if isinstance(expr, UnaryOp):
        collect_aggregates(expr.operand, found)
        return
    if isinstance(expr, IsNull):
        collect_aggregates(expr.operand, found)


def equivalent(left: Expr, right: Expr, columns: list[tuple[str | None, str]]) -> bool:
    """Structural equality. Column refs match when they resolve to the same column."""
    if type(left) is not type(right):
        return False
    if isinstance(left, Literal) and isinstance(right, Literal):
        return _same_value(left.value, right.value)
    if isinstance(left, ColumnRef) and isinstance(right, ColumnRef):
        return resolve_binding(columns, left.table, left.name) == resolve_binding(
            columns, right.table, right.name
        )
    if isinstance(left, BinaryOp) and isinstance(right, BinaryOp):
        return _same_binary(left, right, columns)
    if isinstance(left, UnaryOp) and isinstance(right, UnaryOp):
        return left.op == right.op and equivalent(left.operand, right.operand, columns)
    if isinstance(left, IsNull) and isinstance(right, IsNull):
        return left.negated == right.negated and equivalent(left.operand, right.operand, columns)
    if isinstance(left, FuncCall) and isinstance(right, FuncCall):
        return _same_call(left, right, columns)
    return False


def having_valid(
    expr: Expr,
    keys: tuple[Expr, ...],
    columns: list[tuple[str | None, str]],
    explicit: bool,
) -> bool:
    """True when every non-aggregated column is covered by a grouping expression."""
    if explicit and any(equivalent(expr, key, columns) for key in keys):
        return True
    if isinstance(expr, FuncCall) and is_aggregate_name(expr.name):
        return True
    if isinstance(expr, Literal):
        return True
    if isinstance(expr, ColumnRef):
        return False
    return _having_parts(expr, keys, columns, explicit)


def output_name(item: SelectItem) -> str:
    """Alias, else bare column name, else collapsed source text."""
    if item.alias:
        return item.alias
    if isinstance(item.expr, ColumnRef):
        return item.expr.name
    return item.source


def resolve_binding(
    columns: list[tuple[str | None, str]],
    table: str | None,
    name: str,
) -> tuple[str | None, str]:
    """Resolve a column reference to its (qualifier, name) binding."""
    index = _match_index(columns, table, name)
    return columns[index]


def resolve_value(
    columns: list[tuple[str | None, str]],
    row: list[object],
    table: str | None,
    name: str,
) -> object:
    """Resolve a column reference to the value in *row*."""
    return row[_match_index(columns, table, name)]


def require_logic(value: object) -> bool | None:
    """Accept only TRUE, FALSE, or UNKNOWN."""
    if value is None or type(value) is bool:
        return value
    raise TypeMismatchError(f"predicate must be boolean, got {type_of(value)}")


def _unary(expr: UnaryOp, resolve: Resolver, aggs: dict[int, object] | None, allow: bool) -> object:
    value = evaluate(expr.operand, resolve, aggs, allow)
    if expr.op == "NOT":
        return not_(require_logic(value))
    if expr.op == "-":
        return negate(value)
    raise TypeMismatchError(f"unknown unary operator {expr.op}")


def _is_null(expr: IsNull, resolve: Resolver, aggs: dict[int, object] | None, allow: bool) -> bool:
    value = evaluate(expr.operand, resolve, aggs, allow)
    found = value is None
    return not found if expr.negated else found


def _binary(expr: BinaryOp, resolve: Resolver, aggs: dict[int, object] | None, allow: bool) -> object:
    left = evaluate(expr.left, resolve, aggs, allow)
    right = evaluate(expr.right, resolve, aggs, allow)
    if expr.op in {"AND", "OR"}:
        return _logic(expr.op, left, right)
    if expr.op in {"=", "<>", "<", "<=", ">", ">="}:
        return compare(expr.op, left, right)
    return arith(expr.op, left, right)


def _logic(op: str, left: object, right: object) -> bool | None:
    from microdb.value import and_, or_

    a = require_logic(left)
    b = require_logic(right)
    return and_(a, b) if op == "AND" else or_(a, b)


def _call(expr: FuncCall, resolve: Resolver, aggs: dict[int, object] | None, allow: bool) -> object:
    if is_aggregate_name(expr.name):
        return _aggregate_ref(expr, aggs, allow)
    args = [evaluate(arg, resolve, aggs, allow) for arg in expr.args]
    return eval_scalar(expr.name, args)


def _aggregate_ref(expr: FuncCall, aggs: dict[int, object] | None, allow: bool) -> object:
    if not allow:
        raise AggregateError(f"aggregate {expr.name} is not allowed in this clause")
    if aggs is None or id(expr) not in aggs:
        raise AggregateError(f"aggregate {expr.name} was not computed")
    return aggs[id(expr)]


def eval_scalar(name: str, args: list[object]) -> object:
    """Evaluate a scalar function. NULL propagates except in coalesce."""
    key = name.lower()
    if key not in _SCALARS:
        raise UnknownFunctionError(name)
    if key == "concat":
        return _concat(args)
    if key == "coalesce":
        return _coalesce(args)
    if key == "abs":
        return _abs(args)
    if key == "length":
        return _length(args)
    return _case_fold(key, args)


def _concat(args: list[object]) -> object:
    check_arity("concat", len(args), 2, at_least=True)
    parts: list[str] = []
    saw_null = False
    for arg in args:
        if arg is None:
            saw_null = True
            continue
        if type(arg) is not str:
            raise TypeMismatchError(f"concat requires TEXT, got {type_of(arg)}")
        parts.append(arg)
    if saw_null:
        return None
    return "".join(parts)


def _coalesce(args: list[object]) -> object:
    check_arity("coalesce", len(args), 1, at_least=True)
    for arg in args:
        if arg is not None:
            return arg
    return None


def _abs(args: list[object]) -> object:
    check_arity("abs", len(args), 1)
    value = args[0]
    if value is None:
        return None
    if type(value) is int:
        return abs(value)
    if type(value) is float:
        return abs(value)
    raise TypeMismatchError(f"abs requires a numeric value, got {type_of(value)}")


def _length(args: list[object]) -> object:
    check_arity("length", len(args), 1)
    value = args[0]
    if value is None:
        return None
    if type(value) is not str:
        raise TypeMismatchError(f"length requires TEXT, got {type_of(value)}")
    return len(value)


def _case_fold(name: str, args: list[object]) -> object:
    check_arity(name, len(args), 1)
    value = args[0]
    if value is None:
        return None
    if type(value) is not str:
        raise TypeMismatchError(f"{name} requires TEXT, got {type_of(value)}")
    return value.upper() if name == "upper" else value.lower()


def _same_value(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    return left == right


def _same_binary(left: BinaryOp, right: BinaryOp, columns: list[tuple[str | None, str]]) -> bool:
    return left.op == right.op and equivalent(left.left, right.left, columns) and equivalent(
        left.right, right.right, columns
    )


def _same_call(left: FuncCall, right: FuncCall, columns: list[tuple[str | None, str]]) -> bool:
    if left.name.lower() != right.name.lower() or left.star != right.star:
        return False
    if len(left.args) != len(right.args):
        return False
    return all(equivalent(a, b, columns) for a, b in zip(left.args, right.args))


def _having_parts(
    expr: Expr,
    keys: tuple[Expr, ...],
    columns: list[tuple[str | None, str]],
    explicit: bool,
) -> bool:
    parts = _children(expr)
    if not parts:
        return False
    return all(having_valid(part, keys, columns, explicit) for part in parts)


def _children(expr: Expr) -> tuple[Expr, ...]:
    if isinstance(expr, BinaryOp):
        return (expr.left, expr.right)
    if isinstance(expr, UnaryOp):
        return (expr.operand,)
    if isinstance(expr, IsNull):
        return (expr.operand,)
    if isinstance(expr, FuncCall):
        return expr.args
    return ()


def _match_index(columns: list[tuple[str | None, str]], table: str | None, name: str) -> int:
    if table is not None:
        return _qualified(columns, table, name)
    hits = [i for i, col in enumerate(columns) if col[1] == name]
    if not hits:
        raise UnknownColumnError(name)
    if len(hits) > 1:
        raise AmbiguousColumnError(name)
    return hits[0]


def _qualified(columns: list[tuple[str | None, str]], table: str, name: str) -> int:
    known = {col[0] for col in columns if col[0] is not None}
    if table not in known:
        raise UnknownTableError(table)
    hits = [i for i, col in enumerate(columns) if col[0] == table and col[1] == name]
    if not hits:
        raise UnknownColumnError(f"{table}.{name}")
    if len(hits) > 1:
        raise AmbiguousColumnError(f"{table}.{name}")
    return hits[0]
