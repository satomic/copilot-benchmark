"""Executor: runs a Plan against a set of tables, stage by stage.

Pipeline: FROM/JOIN -> WHERE -> GROUP BY -> AGGREGATE -> HAVING -> SELECT ->
DISTINCT -> ORDER BY -> OFFSET -> LIMIT.
"""

from __future__ import annotations

import dataclasses
import functools

from .aggregate import compute, find_aggregates, is_aggregate_name
from .errors import (
    AggregateError,
    GroupingError,
    UnknownTableError,
)
from .expr import Row, Scope, eval_expr, require_logic
from .parser import ColumnRef, FuncCall, Node, Query, SelectItem, Star
from .planner import Plan, Stage, query_aggregates
from .schema import Table
from .value import compare_lt


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclasses.dataclass
class _Ctx:
    query: Query
    tables: dict[str, Table]
    scope: Scope = Scope(())
    rows: list[Row] = dataclasses.field(default_factory=list)
    grouped: bool = False
    groups: list[list[Row]] = dataclasses.field(default_factory=list)
    out: list[tuple[Row, tuple[object, ...]]] = dataclasses.field(
        default_factory=list)
    columns: list[str] = dataclasses.field(default_factory=list)
    items: list[SelectItem] = dataclasses.field(default_factory=list)
    alias_pos: dict[str, int] = dataclasses.field(default_factory=dict)
    distinct_done: bool = False


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    """Execute every stage of a plan in order and return the Result."""
    ctx = _Ctx(query=plan.query, tables=tables)
    for stage in plan:
        _HANDLERS[stage.name](ctx, stage)
    return Result(columns=ctx.columns,
                  rows=[list(values) for _, values in ctx.out])


# ---------------------------------------------------------------------------
# Key normalization: NULL is equal to NULL, INT/FLOAT compare numerically,
# and BOOL never collides with INT (Python's True == 1 must not group/sort
# together).
# ---------------------------------------------------------------------------

def _key_of(v: object) -> tuple[str, object]:
    if v is None:
        return ("null", None)
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("num", v)
    return ("text", v)


# ---------------------------------------------------------------------------
# Stage handlers
# ---------------------------------------------------------------------------

def _table(ctx: _Ctx, name: str) -> Table:
    try:
        return ctx.tables[name]
    except KeyError:
        raise UnknownTableError(f"unknown table {name!r}")


def _from(ctx: _Ctx, stage: Stage) -> None:
    table = _table(ctx, ctx.query.from_table)
    entries = tuple((table.name, c.name) for c in table.columns)
    ctx.scope = Scope(entries)
    ctx.rows = [Row(values=tuple(r), scope=ctx.scope) for r in table.rows]
    if ctx.query.join is not None:
        _join(ctx, entries)


def _join(ctx: _Ctx, left_entries: tuple[tuple[str | None, str], ...]) -> None:
    join = ctx.query.join
    assert join is not None
    right = _table(ctx, join.table)
    right_entries = tuple((right.name, c.name) for c in right.columns)
    ctx.scope = Scope(left_entries + right_entries)
    nulls = tuple(None for _ in right.columns)
    out: list[Row] = []
    for lrow in ctx.rows:
        matched = False
        for rvals in right.rows:
            row = Row(values=lrow.values + tuple(rvals), scope=ctx.scope)
            if require_logic(eval_expr(join.on, row)) is True:
                matched = True
                out.append(row)
        if not matched and join.kind == "LEFT":
            out.append(Row(values=lrow.values + nulls, scope=ctx.scope))
    ctx.rows = out


def _where(ctx: _Ctx, stage: Stage) -> None:
    where = ctx.query.where
    assert where is not None
    if find_aggregates(where):
        raise AggregateError("WHERE cannot contain an aggregate function")
    ctx.rows = [
        row for row in ctx.rows
        if require_logic(eval_expr(where, row)) is True
    ]


def _group_by(ctx: _Ctx, stage: Stage) -> None:
    ctx.grouped = True
    groups: dict[tuple[tuple[str, object], ...], list[Row]] = {}
    for row in ctx.rows:
        key = tuple(_key_of(eval_expr(e, row)) for e in ctx.query.group_by)
        groups.setdefault(key, []).append(row)
    ctx.groups = list(groups.values())  # first-appearance order


def _aggregate(ctx: _Ctx, stage: Stage) -> None:
    if not ctx.grouped:
        # No GROUP BY but aggregates exist: the whole input is one group,
        # and exactly one row is produced even when the input is empty.
        ctx.groups = [list(ctx.rows)]
    _check_grouping(ctx)
    aggs = query_aggregates(ctx.query)
    reps: list[Row] = []
    for group in ctx.groups:
        agg_values = {id(call): compute(call, group) for call in aggs}
        if group:
            rep = group[0]
        else:
            rep = Row(values=tuple(None for _ in ctx.scope.entries),
                      scope=ctx.scope)
        reps.append(dataclasses.replace(rep, agg_values=agg_values))
    ctx.rows = reps


def _having(ctx: _Ctx, stage: Stage) -> None:
    having = ctx.query.having
    assert having is not None
    ctx.rows = [
        row for row in ctx.rows
        if require_logic(eval_expr(having, row)) is True
    ]


def _select(ctx: _Ctx, stage: Stage) -> None:
    items = _expanded_items(ctx)
    ctx.columns = [_output_name(ctx.query, it) for it in items]
    ctx.alias_pos = {it.alias: i for i, it in enumerate(items) if it.alias}
    ctx.out = [
        (row, tuple(eval_expr(it.expr, row) for it in items))
        for row in ctx.rows
    ]


def _distinct(ctx: _Ctx, stage: Stage) -> None:
    seen: set[tuple[tuple[str, object], ...]] = set()
    out: list[tuple[Row, tuple[object, ...]]] = []
    for row, values in ctx.out:
        key = tuple(_key_of(v) for v in values)
        if key not in seen:
            seen.add(key)
            out.append((row, values))
    ctx.out = out
    ctx.distinct_done = True


def _order_by(ctx: _Ctx, stage: Stage) -> None:
    items = ctx.query.order_by
    keyed = [
        (tuple(eval_expr(oi.expr, _order_row(ctx, row, vals)) for oi in items),
         row, vals)
        for row, vals in ctx.out
    ]
    descs = [oi.desc for oi in items]

    def cmp(a: tuple, b: tuple) -> int:
        for ka, kb, desc in zip(a[0], b[0], descs):
            if ka is None and kb is None:
                continue
            if ka is None:
                return 1  # NULLs last in both ASC and DESC
            if kb is None:
                return -1
            r = _cmp_key(ka, kb)
            if r:
                return -r if desc else r  # DESC reverses non-NULLs only
        return 0

    keyed.sort(key=functools.cmp_to_key(cmp))  # sort is stable
    ctx.out = [(row, vals) for _, row, vals in keyed]


def _offset(ctx: _Ctx, stage: Stage) -> None:
    ctx.out = ctx.out[int(stage.detail):]  # type: ignore[arg-type]


def _limit(ctx: _Ctx, stage: Stage) -> None:
    ctx.out = ctx.out[: int(stage.detail)]  # type: ignore[arg-type]


_HANDLERS = {
    "FROM": _from,
    "WHERE": _where,
    "GROUP BY": _group_by,
    "AGGREGATE": _aggregate,
    "HAVING": _having,
    "SELECT": _select,
    "DISTINCT": _distinct,
    "ORDER BY": _order_by,
    "OFFSET": _offset,
    "LIMIT": _limit,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmp_key(a: object, b: object) -> int:
    """Compare two non-NULL sort-key values (caller handles NULLs)."""
    if compare_lt(a, b):
        return -1
    if compare_lt(b, a):
        return 1
    return 0


def _order_row(ctx: _Ctx, row: Row, values: tuple[object, ...]) -> Row:
    """Build the evaluation context for ORDER BY expressions.

    Aliases are visible (and win over input columns).  With DISTINCT, only
    output columns may be referenced, so the scope is the output column list.
    """
    aliases = {name: values[i] for name, i in ctx.alias_pos.items()}
    if ctx.distinct_done:
        scope = Scope(tuple((None, c) for c in ctx.columns))
        return Row(values=values, scope=scope,
                   agg_values=row.agg_values, aliases=aliases)
    return dataclasses.replace(row, aliases=aliases)


def _expanded_items(ctx: _Ctx) -> list[SelectItem]:
    """Expand '*' and 't.*' select items into plain column references."""
    if ctx.items:
        return ctx.items
    items: list[SelectItem] = []
    for item in ctx.query.select:
        if not isinstance(item.expr, Star):
            items.append(item)
            continue
        star = item.expr
        matched = False
        for tbl, col in ctx.scope.entries:
            if star.table is None or star.table == tbl:
                matched = True
                ref = ColumnRef(name=col, table=tbl,
                                start=star.start, end=star.end)
                items.append(SelectItem(expr=ref, alias=None))
        if not matched and star.table is not None:
            raise UnknownTableError(f"unknown table {star.table!r}")
    ctx.items = items
    return items


def _output_name(query: Query, item: SelectItem) -> str:
    """Alias, else column name for a bare reference, else collapsed source."""
    if item.alias is not None:
        return item.alias
    if isinstance(item.expr, ColumnRef):
        return item.expr.name
    raw = query.source[item.expr.start:item.expr.end]
    return " ".join(raw.split())


def _same_expr(a: Node, b: Node) -> bool:
    """Structural equality, lenient about table qualification of columns."""
    if isinstance(a, ColumnRef) and isinstance(b, ColumnRef):
        return a.name == b.name and (
            a.table == b.table or a.table is None or b.table is None)
    return a == b


def _group_valid(node: Node, gexprs: tuple[Node, ...], aliases: set[str]) -> bool:
    """A SELECT/HAVING/ORDER BY expression is valid in a grouped query when
    every column reference sits inside an aggregate, an alias reference, or a
    subexpression that is one of the grouping expressions."""
    if any(_same_expr(node, g) for g in gexprs):
        return True
    if isinstance(node, FuncCall) and is_aggregate_name(node.name):
        return True
    if isinstance(node, ColumnRef):
        return node.table is None and node.name in aliases
    if isinstance(node, Star):
        return False
    children: tuple[Node, ...] = ()
    if isinstance(node, FuncCall):
        children = node.args
    elif hasattr(node, "operand"):
        children = (node.operand,)  # type: ignore[attr-defined]
    elif hasattr(node, "left"):
        children = (node.left, node.right)  # type: ignore[attr-defined]
    return all(_group_valid(c, gexprs, aliases) for c in children)


def _check_grouping(ctx: _Ctx) -> None:
    gexprs = ctx.query.group_by
    alias_names = {it.alias for it in ctx.query.select if it.alias}
    targets = [it.expr for it in _expanded_items(ctx)]
    if ctx.query.having is not None:
        targets.append(ctx.query.having)
    for t in targets:
        if not _group_valid(t, gexprs, set()):
            raise GroupingError(
                "SELECT/HAVING item must be an aggregate or a grouping "
                "expression")
    for oi in ctx.query.order_by:
        if not _group_valid(oi.expr, gexprs, alias_names):
            raise GroupingError(
                "ORDER BY item must be an aggregate, an alias or a grouping "
                "expression")
