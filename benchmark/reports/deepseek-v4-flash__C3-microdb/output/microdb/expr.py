"""Expression evaluation engine.

Evaluates expression AST nodes in the context of a data row.
"""

from microdb.parser import (
    Literal,
    ColumnRef,
    QualifiedColumnRef,
    FunctionCall,
    BinaryOp,
    UnaryOp,
    IsNull,
    Star,
)
from microdb.value import (
    type_of,
    and_,
    or_,
    not_,
    compare_eq,
    compare_lt,
    arith,
    negate,
)
from microdb.errors import (
    TypeMismatchError,
    UnknownColumnError,
    AmbiguousColumnError,
    UnknownTableError,
    UnknownFunctionError,
    ArityError,
    AggregateError,
    MicroDBError,
)


class EvalContext:
    """Evaluation context holding row data and metadata."""

    __slots__ = (
        "row",
        "col_names",
        "table_col_map",
        "table_names",
        "tables",
    )

    def __init__(
        self,
        row: list[object] | None = None,
        col_names: list[str] | None = None,
        table_col_map: dict[str, dict[str, int]] | None = None,
        tables: dict[str, object] | None = None,
    ) -> None:
        self.row = row if row is not None else []
        self.col_names = col_names if col_names is not None else []
        # table -> {column_name -> index}
        self.table_col_map = (
            table_col_map if table_col_map is not None else {}
        )
        self.table_names = set(self.table_col_map.keys())
        self.tables = tables if tables is not None else {}

    def with_row(self, row: list[object]) -> "EvalContext":
        """Return a new context with a different row but same schema."""
        return EvalContext(
            row=row,
            col_names=self.col_names,
            table_col_map=self.table_col_map,
            tables=self.tables,
        )


def evaluate(expr: object, ctx: EvalContext) -> object:
    """Evaluate an expression AST in the given context."""
    if isinstance(expr, Literal):
        return expr.value

    if isinstance(expr, ColumnRef):
        return _resolve_column(expr.name, ctx)

    if isinstance(expr, QualifiedColumnRef):
        return _resolve_qualified(expr.table, expr.name, ctx)

    if isinstance(expr, FunctionCall):
        return _eval_function(expr, ctx)

    if isinstance(expr, BinaryOp):
        return _eval_binary(expr.op, expr.left, expr.right, ctx)

    if isinstance(expr, UnaryOp):
        val = evaluate(expr.operand, ctx)
        if expr.op == "NOT":
            if not isinstance(val, (bool, type(None))):
                raise TypeMismatchError(
                    f"NOT requires boolean, got {type_of(val)}"
                )
            return not_(val)
        if expr.op == "-":
            return negate(val)
        raise ValueError(f"unknown unary op: {expr.op}")

    if isinstance(expr, IsNull):
        val = evaluate(expr.operand, ctx)
        if expr.negated:
            return val is not None
        return val is None

    if isinstance(expr, Star):
        # count(*) - represented as Star
        return expr

    raise ValueError(f"unknown expression type: {type(expr).__name__}")


def _resolve_column(name: str, ctx: EvalContext) -> object:
    """Resolve an unqualified column reference."""
    candidates: list[int] = []
    for tbl, cmap in ctx.table_col_map.items():
        if name in cmap:
            candidates.append(cmap[name])

    # If no table context, fall back to direct column name lookup
    # (needed for post-SELECT stages like ORDER BY)
    if not candidates and ctx.col_names:
        for i, cn in enumerate(ctx.col_names):
            if cn == name:
                candidates.append(i)
                break

    if len(candidates) == 0:
        raise UnknownColumnError(f"unknown column: {name}")
    if len(candidates) > 1:
        raise AmbiguousColumnError(
            f"column {name!r} is ambiguous"
        )
    return ctx.row[candidates[0]]


def _resolve_qualified(table: str, name: str, ctx: EvalContext) -> object:
    """Resolve a qualified column reference (table.column)."""
    if table not in ctx.table_col_map:
        raise UnknownTableError(f"unknown table: {table}")
    cmap = ctx.table_col_map[table]
    if name not in cmap:
        raise UnknownColumnError(
            f"column {name!r} not in table {table!r}"
        )
    return ctx.row[cmap[name]]


def _eval_concat(args: list[object], ctx: EvalContext) -> object:
    """Evaluate concat(...)."""
    if len(args) < 2:
        raise ArityError(f"concat requires at least 2 arguments, got {len(args)}")
    evaled = [evaluate(a, ctx) for a in args]
    for v in evaled:
        if v is None:
            return None
        if type_of(v) != "TEXT":
            raise TypeMismatchError(f"concat requires TEXT, got {type_of(v)}")
    return "".join(evaled)


def _eval_unary_text(
    fname: str, args: list[object], ctx: EvalContext, func: object
) -> object:
    """Evaluate a unary TEXT function (upper, lower, length)."""
    if len(args) != 1:
        raise ArityError(f"{fname} requires 1 argument, got {len(args)}")
    val = evaluate(args[0], ctx)
    if val is None:
        return None
    if type_of(val) != "TEXT":
        raise TypeMismatchError(f"{fname} requires TEXT, got {type_of(val)}")
    return func(val)


def _eval_abs(args: list[object], ctx: EvalContext) -> object:
    """Evaluate abs(n)."""
    if len(args) != 1:
        raise ArityError(f"abs requires 1 argument, got {len(args)}")
    val = evaluate(args[0], ctx)
    if val is None:
        return None
    if type_of(val) not in ("INT", "FLOAT"):
        raise TypeMismatchError(f"abs requires numeric, got {type_of(val)}")
    return abs(val)


def _eval_coalesce(args: list[object], ctx: EvalContext) -> object:
    """Evaluate coalesce(a, b, ...)."""
    if len(args) < 1:
        raise ArityError(f"coalesce requires at least 1 argument, got {len(args)}")
    for a in args:
        v = evaluate(a, ctx)
        if v is not None:
            return v
    return None


_SCALAR_FUNCTIONS: dict[str, object] = {
    "CONCAT": _eval_concat,
    "UPPER": lambda args, ctx: _eval_unary_text("upper", args, ctx, str.upper),
    "LOWER": lambda args, ctx: _eval_unary_text("lower", args, ctx, str.lower),
    "LENGTH": lambda args, ctx: _eval_unary_text("length", args, ctx, len),
    "ABS": _eval_abs,
    "COALESCE": _eval_coalesce,
}


def _eval_function(call: FunctionCall, ctx: EvalContext) -> object:
    """Evaluate a scalar function call."""
    fname = call.name.upper()
    handler = _SCALAR_FUNCTIONS.get(fname)
    if handler is None:
        raise UnknownFunctionError(f"unknown function: {call.name}")
    return handler(call.args, ctx)


def _eval_binary(
    op: str, left: object, right: object, ctx: EvalContext
) -> object:
    """Evaluate a binary operation."""
    # Logical operators short-circuit for three-valued logic
    if op == "AND":
        lv = evaluate(left, ctx)
        if not isinstance(lv, (bool, type(None))):
            raise TypeMismatchError(
                f"AND requires boolean, got {type_of(lv)}"
            )
        if lv is False:
            return False
        rv = evaluate(right, ctx)
        if not isinstance(rv, (bool, type(None))):
            raise TypeMismatchError(
                f"AND requires boolean, got {type_of(rv)}"
            )
        return and_(lv, rv)

    if op == "OR":
        lv = evaluate(left, ctx)
        if not isinstance(lv, (bool, type(None))):
            raise TypeMismatchError(
                f"OR requires boolean, got {type_of(lv)}"
            )
        if lv is True:
            return True
        rv = evaluate(right, ctx)
        if not isinstance(rv, (bool, type(None))):
            raise TypeMismatchError(
                f"OR requires boolean, got {type_of(rv)}"
            )
        return or_(lv, rv)

    # Comparison operators
    if op in ("=", "<>", "<", "<=", ">", ">="):
        lv = evaluate(left, ctx)
        rv = evaluate(right, ctx)
        result = _compare(op, lv, rv)
        return result

    # Arithmetic operators
    if op in ("+", "-", "*", "/", "%"):
        lv = evaluate(left, ctx)
        rv = evaluate(right, ctx)
        return arith(op, lv, rv)

    raise ValueError(f"unknown binary op: {op}")


def _compare(op: str, a: object, b: object) -> bool | None:
    """Compare two values with the given operator."""
    if op == "=":
        return compare_eq(a, b)
    if op == "<>":
        eq = compare_eq(a, b)
        if eq is None:
            return None
        return not eq
    if op == "<":
        return compare_lt(a, b)
    if op == "<=":
        lt = compare_lt(a, b)
        if lt is True:
            return True
        eq = compare_eq(a, b)
        if eq is True:
            return True
        if lt is None or eq is None:
            return None
        return False
    if op == ">":
        lt = compare_lt(a, b)
        if lt is None:
            return None
        return not (lt or compare_eq(a, b))
    if op == ">=":
        lt = compare_lt(a, b)
        if lt is None:
            return None
        return not lt
    raise ValueError(f"unknown comparison: {op}")


def has_aggregate(expr: object) -> bool:
    """Return True if the expression contains any aggregate function call."""
    if isinstance(expr, FunctionCall):
        if expr.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            return True
        # Check args for nested aggregates (which should raise error)
        return any(has_aggregate(a) for a in expr.args)
    if isinstance(expr, BinaryOp):
        return has_aggregate(expr.left) or has_aggregate(expr.right)
    if isinstance(expr, UnaryOp):
        return has_aggregate(expr.operand)
    if isinstance(expr, IsNull):
        return has_aggregate(expr.operand)
    return False


def contains_aggregate(expr: object) -> bool:
    """Return True and also detect nested aggregates (error case)."""
    found = [False]

    def _walk(node: object) -> None:
        if isinstance(node, FunctionCall):
            if node.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
                if found[0]:
                    # Nested aggregate
                    raise AggregateError(
                        "aggregates may not be nested"
                    )
                found[0] = True
            for a in node.args:
                _walk(a)
        elif isinstance(node, BinaryOp):
            _walk(node.left)
            _walk(node.right)
        elif isinstance(node, UnaryOp):
            _walk(node.operand)
        elif isinstance(node, IsNull):
            _walk(node.operand)

    _walk(expr)
    return found[0]


def collect_aggregates(expr: object) -> list[FunctionCall]:
    """Return a list of aggregate function calls found in the expression."""
    aggrs: list[FunctionCall] = []

    def _walk(node: object) -> None:
        if isinstance(node, FunctionCall):
            if node.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
                aggrs.append(node)
            for a in node.args:
                _walk(a)
        elif isinstance(node, BinaryOp):
            _walk(node.left)
            _walk(node.right)
        elif isinstance(node, UnaryOp):
            _walk(node.operand)
        elif isinstance(node, IsNull):
            _walk(node.operand)

    _walk(expr)
    return aggrs