from __future__ import annotations

from collections.abc import Callable, Sequence
import dataclasses

from microdb.aggregate import validate_aggregate_call
from microdb.errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from microdb.parser import (
     COMPARE_OPS,
    AggregateCall,
    BinaryExpr,
    ColumnRef,
    Expr,
    FuncCall,
    IsNullExpr,
    LiteralExpr,
    UnaryExpr,
)
from microdb.value import and_, arith, compare, is_numeric, negate, not_, or_, type_of

SCALAR_FUNCTIONS: frozenset[str] = frozenset(
    {"concat", "upper", "lower", "length", "abs", "coalesce"}
)


@dataclasses.dataclass(frozen=True)
class SourceColumn:
    table: str | None
    name: str
    col_type: str


class RowSchema:
    def __init__(
        self, columns: Sequence[SourceColumn], valid_tables: frozenset[str]
    ) -> None:
        self.columns: tuple[SourceColumn, ...] = tuple(columns)
        self.valid_tables: frozenset[str] = valid_tables

    def resolve(self, table: str | None, name: str) -> int:
        if table is not None:
            if table not in self.valid_tables:
                raise UnknownTableError(f"Unknown table {table!r}")
            matches = [
                i
                for i, c in enumerate(self.columns)
                if c.table == table and c.name == name
            ]
            if not matches:
                raise UnknownColumnError(f"Unknown column '{table}.{name}'")
            if len(matches) > 1:
                raise AmbiguousColumnError(f"Ambiguous column '{table}.{name}'")
            return matches[0]
        matches = [i for i, c in enumerate(self.columns) if c.name == name]
        if not matches:
            raise UnknownColumnError(f"Unknown column {name!r}")
        if len(matches) > 1:
            raise AmbiguousColumnError(f"Ambiguous column {name!r}")
        return matches[0]


def validate_scalar_call(name: str, arity: int) -> None:
    lower = name.lower()
    if lower not in SCALAR_FUNCTIONS:
        raise UnknownFunctionError(f"Unknown function {name!r}")
    if lower == "concat" and arity < 2:
        raise ArityError(f"concat expects at least 2 arguments, got {arity}")
    if lower == "coalesce" and arity < 1:
        raise ArityError(f"coalesce expects at least 1 argument, got {arity}")
    if lower in ("upper", "lower", "length", "abs") and arity != 1:
        raise ArityError(f"{lower} expects 1 argument, got {arity}")


def eval_scalar_function(name: str, args: Sequence[object]) -> object:
    lower = name.lower()
    validate_scalar_call(lower, len(args))
    if lower == "concat":
        for arg in args:
            if arg is not None and not isinstance(arg, str):
                raise TypeMismatchError(f"concat expects TEXT, got {type_of(arg)}")
        if any(arg is None for arg in args):
            return None
        return "".join(str(a) for a in args)
    if lower == "coalesce":
        for arg in args:
            if arg is not None:
                return arg
        return None
    arg0 = args[0]
    if arg0 is None:
        return None
    if lower in ("upper", "lower", "length"):
        if not isinstance(arg0, str):
            raise TypeMismatchError(f"{lower} expects TEXT, got {type_of(arg0)}")
        if lower == "upper":
            return arg0.upper()
        if lower == "lower":
            return arg0.lower()
        return len(arg0)
    if not is_numeric(arg0):
        raise TypeMismatchError(f"abs expects numeric, got {type_of(arg0)}")
    assert isinstance(arg0, (int, float))
    return abs(arg0)


def validate_expr_functions(expr: Expr) -> None:
    if isinstance(expr, FuncCall):
        validate_scalar_call(expr.name, len(expr.args))
        for arg in expr.args:
            validate_expr_functions(arg)
    elif isinstance(expr, AggregateCall):
        validate_aggregate_call(expr.name, len(expr.args), expr.is_star)
        for arg in expr.args:
            validate_expr_functions(arg)
    elif isinstance(expr, UnaryExpr):
        validate_expr_functions(expr.operand)
    elif isinstance(expr, BinaryExpr):
        validate_expr_functions(expr.left)
        validate_expr_functions(expr.right)
    elif isinstance(expr, IsNullExpr):
        validate_expr_functions(expr.operand)


def eval_expr(
    expr: Expr,
    schema: RowSchema,
    row: Sequence[object],
    col_resolver: Callable[[ColumnRef], object] | None = None,
) -> object:
    if isinstance(expr, LiteralExpr):
        return expr.value
    if isinstance(expr, ColumnRef):
        if col_resolver is not None:
            return col_resolver(expr)
        idx = schema.resolve(expr.table, expr.name)
        return row[idx]
    if isinstance(expr, AggregateCall):
        raise AggregateError(f"Aggregate {expr.name!r} is not allowed in this clause")
    if isinstance(expr, UnaryExpr):
        val = eval_expr(expr.operand, schema, row, col_resolver)
        return not_(val) if expr.op == "NOT" else negate(val)  # type: ignore[arg-type]
    if isinstance(expr, IsNullExpr):
        val = eval_expr(expr.operand, schema, row, col_resolver)
        return (val is not None) if expr.negated else (val is None)
    if isinstance(expr, BinaryExpr):
        return _eval_binary(expr, schema, row, col_resolver)
    if isinstance(expr, FuncCall):
        validate_scalar_call(expr.name, len(expr.args))
        vals = [eval_expr(a, schema, row, col_resolver) for a in expr.args]
        return eval_scalar_function(expr.name, vals)
    raise TypeError(f"Unsupported expression node: {expr!r}")


def _eval_binary(
    expr: BinaryExpr,
    schema: RowSchema,
    row: Sequence[object],
    col_resolver: Callable[[ColumnRef], object] | None,
) -> object:
    left = eval_expr(expr.left, schema, row, col_resolver)
    right = eval_expr(expr.right, schema, row, col_resolver)
    if expr.op == "AND":
        return and_(left, right)  # type: ignore[arg-type]
    if expr.op == "OR":
        return or_(left, right)  # type: ignore[arg-type]
    if expr.op in COMPARE_OPS:
        return compare(expr.op, left, right)
    return arith(expr.op, left, right)


def eval_predicate(
    expr: Expr,
    schema: RowSchema,
    row: Sequence[object],
    col_resolver: Callable[[ColumnRef], object] | None = None,
) -> bool:
    val = eval_expr(expr, schema, row, col_resolver)
    if val is not None and not isinstance(val, bool):
        raise TypeMismatchError(f"Predicate must evaluate to BOOL, got {type_of(val)}")
    return val is True
