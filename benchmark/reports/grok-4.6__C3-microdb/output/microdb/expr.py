"""Expression evaluation, binding, and tree walks."""

from __future__ import annotations

from dataclasses import dataclass

from microdb.errors import (
    AmbiguousColumnError,
    ArityError,
    AggregateError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from microdb.parser import Binary, Call, ColumnRef, IsNull, Literal, Unary
from microdb.value import (
    and_,
    arith,
    as_logical,
    compare_eq,
    compare_ge,
    compare_gt,
    compare_le,
    compare_lt,
    compare_ne,
    is_numeric,
    negate,
    not_,
    or_,
    type_of,
)

AGGS = frozenset({"count", "sum", "avg", "min", "max"})
_CMP = {
    "=": compare_eq,
    "<>": compare_ne,
    "<": compare_lt,
    "<=": compare_le,
    ">": compare_gt,
    ">=": compare_ge,
}
_ARITY: dict[str, tuple[int, int | None]] = {
    "upper": (1, 1),
    "lower": (1, 1),
    "length": (1, 1),
    "abs": (1, 1),
    "concat": (2, None),
    "coalesce": (1, None),
    "count": (1, 1),
    "sum": (1, 1),
    "avg": (1, 1),
    "min": (1, 1),
    "max": (1, 1),
}


@dataclass
class EvalCtx:
    col_tables: list[str]
    col_names: list[str]
    row: list[object]
    aliases: dict[str, object] | None = None
    aggs: dict[int, object] | None = None
    allow_input: bool = True


def eval_expr(node: object, ctx: EvalCtx) -> object:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, ColumnRef):
        return _eval_column(node, ctx)
    if isinstance(node, Unary):
        return _eval_unary(node, ctx)
    if isinstance(node, Binary):
        return _eval_binary(node, ctx)
    if isinstance(node, IsNull):
        v = eval_expr(node.expr, ctx)
        isn = v is None
        return (not isn) if node.negated else isn
    if isinstance(node, Call):
        return _eval_call(node, ctx)
    raise TypeMismatchError("invalid expression node")


def has_aggregate(node: object) -> bool:
    found: list[Call] = []
    collect_aggregates(node, found)
    return bool(found)


def collect_aggregates(node: object, out: list[Call]) -> None:
    if isinstance(node, Call) and node.name in AGGS:
        out.append(node)
        return
    if isinstance(node, Unary):
        collect_aggregates(node.expr, out)
    elif isinstance(node, Binary):
        collect_aggregates(node.left, out)
        collect_aggregates(node.right, out)
    elif isinstance(node, IsNull):
        collect_aggregates(node.expr, out)
    elif isinstance(node, Call):
        for arg in node.args:
            collect_aggregates(arg, out)


def walk_children(node: object) -> list[object]:
    if isinstance(node, Unary):
        return [node.expr]
    if isinstance(node, Binary):
        return [node.left, node.right]
    if isinstance(node, IsNull):
        return [node.expr]
    if isinstance(node, Call):
        return list(node.args)
    return []


def bind_expr(node: object, col_tables: list[str], col_names: list[str]) -> object:
    if isinstance(node, ColumnRef):
        idx = resolve_column(col_tables, col_names, node.table, node.name)
        table = col_tables[idx]
        name = col_names[idx]
        return ColumnRef(name, table, node.offset, node.source)
    if isinstance(node, Unary):
        return Unary(node.op, bind_expr(node.expr, col_tables, col_names), node.offset, node.source)
    if isinstance(node, Binary):
        return Binary(
            node.op,
            bind_expr(node.left, col_tables, col_names),
            bind_expr(node.right, col_tables, col_names),
            node.offset,
            node.source,
        )
    if isinstance(node, IsNull):
        return IsNull(
            bind_expr(node.expr, col_tables, col_names), node.negated, node.offset, node.source
        )
    if isinstance(node, Call):
        args = tuple(bind_expr(a, col_tables, col_names) for a in node.args)
        return Call(node.name, args, node.star, node.offset, node.source)
    return node


def expr_equal(a: object, b: object) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, Literal) and isinstance(b, Literal):
        return type_of(a.value) == type_of(b.value) and a.value == b.value
    if isinstance(a, ColumnRef) and isinstance(b, ColumnRef):
        return a.name == b.name and a.table == b.table
    if isinstance(a, Unary) and isinstance(b, Unary):
        return a.op == b.op and expr_equal(a.expr, b.expr)
    if isinstance(a, Binary) and isinstance(b, Binary):
        return a.op == b.op and expr_equal(a.left, b.left) and expr_equal(a.right, b.right)
    if isinstance(a, IsNull) and isinstance(b, IsNull):
        return a.negated == b.negated and expr_equal(a.expr, b.expr)
    if isinstance(a, Call) and isinstance(b, Call):
        if a.name != b.name or a.star != b.star or len(a.args) != len(b.args):
            return False
        return all(expr_equal(x, y) for x, y in zip(a.args, b.args))
    return False


def resolve_column(
    col_tables: list[str], col_names: list[str], table: str | None, name: str
) -> int:
    tables = {t for t in col_tables}
    if table is not None:
        if table not in tables:
            raise UnknownTableError(table)
        hits = [i for i, (t, n) in enumerate(zip(col_tables, col_names)) if t == table and n == name]
        if not hits:
            raise UnknownColumnError(f"{table}.{name}")
        if len(hits) > 1:
            raise AmbiguousColumnError(f"{table}.{name}")
        return hits[0]
    hits = [i for i, n in enumerate(col_names) if n == name]
    if not hits:
        raise UnknownColumnError(name)
    owners = {col_tables[i] for i in hits}
    if len(owners) > 1 or len(hits) > 1:
        raise AmbiguousColumnError(name)
    return hits[0]


def eval_predicate(node: object, ctx: EvalCtx) -> bool | None:
    return as_logical(eval_expr(node, ctx))


def item_source(node: object) -> str:
    if isinstance(node, (Literal, ColumnRef, Binary, Unary, IsNull, Call)):
        return node.source
    return ""


def _eval_column(node: ColumnRef, ctx: EvalCtx) -> object:
    if node.table is None and ctx.aliases is not None and node.name in ctx.aliases:
        return ctx.aliases[node.name]
    if not ctx.allow_input:
        if node.table is not None:
            raise UnknownTableError(node.table)
        raise UnknownColumnError(node.name)
    idx = resolve_column(ctx.col_tables, ctx.col_names, node.table, node.name)
    return ctx.row[idx]


def _eval_unary(node: Unary, ctx: EvalCtx) -> object:
    inner = eval_expr(node.expr, ctx)
    if node.op == "NOT":
        return not_(as_logical(inner))
    return negate(inner)


def _eval_binary(node: Binary, ctx: EvalCtx) -> object:
    if node.op == "AND":
        return and_(as_logical(eval_expr(node.left, ctx)), as_logical(eval_expr(node.right, ctx)))
    if node.op == "OR":
        return or_(as_logical(eval_expr(node.left, ctx)), as_logical(eval_expr(node.right, ctx)))
    if node.op in _CMP:
        return _CMP[node.op](eval_expr(node.left, ctx), eval_expr(node.right, ctx))
    return arith(node.op, eval_expr(node.left, ctx), eval_expr(node.right, ctx))


def _eval_call(node: Call, ctx: EvalCtx) -> object:
    if node.name in AGGS:
        if ctx.aggs is not None and id(node) in ctx.aggs:
            return ctx.aggs[id(node)]
        raise AggregateError(f"aggregate {node.name} not allowed here")
    if node.name not in _ARITY:
        raise UnknownFunctionError(node.name)
    _check_arity(node.name, len(node.args), star=False)
    args = [eval_expr(a, ctx) for a in node.args]
    return _scalar(node.name, args)


def _check_arity(name: str, got: int, star: bool) -> None:
    if name == "count" and star:
        return
    lo, hi = _ARITY[name]
    if got < lo or (hi is not None and got > hi):
        raise ArityError(name, lo if hi is None or got < lo else hi, got)


def _scalar(name: str, args: list[object]) -> object:
    if name == "coalesce":
        for v in args:
            if v is not None:
                return v
        return None
    if name == "concat":
        return _concat(args)
    if any(v is None for v in args):
        return None
    if name == "upper":
        return _need_text(args[0]).upper()
    if name == "lower":
        return _need_text(args[0]).lower()
    if name == "length":
        return len(_need_text(args[0]))
    if name == "abs":
        if not is_numeric(args[0]):
            raise TypeMismatchError("abs requires numeric")
        return abs(args[0])  # type: ignore[arg-type]
    raise UnknownFunctionError(name)


def _concat(args: list[object]) -> object:
    texts: list[str] = []
    for v in args:
        if v is None:
            return None
        texts.append(_need_text(v))
    return "".join(texts)


def _need_text(v: object) -> str:
    if type_of(v) != "TEXT":
        raise TypeMismatchError(f"expected TEXT, got {type_of(v)}")
    return str(v)
