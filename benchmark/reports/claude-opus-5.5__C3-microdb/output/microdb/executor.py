"""Executor: runs a Plan against a set of tables."""

from __future__ import annotations

import dataclasses
import functools
from typing import Callable

from .aggregate import agg_count_star, compute_aggregate
from .errors import GroupingError, UnknownTableError
from .expr import (
    AggRef,
    BoundColumn,
    Context,
    GroupKey,
    OutputColumn,
    Scope,
    bind,
    evaluate,
    map_children,
)
from .parser import AggCall, ColumnRef, Expr, SelectItem, parse
from .planner import (
    AggregateStage,
    DistinctStage,
    FilterStage,
    GroupStage,
    HavingStage,
    JoinStage,
    LimitStage,
    OffsetStage,
    Plan,
    ProjectStage,
    ScanStage,
    SortStage,
    Stage,
    plan,
)
from .schema import Table
from .value import compare_eq, compare_lt, require_logical, row_key


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclasses.dataclass
class _Group:
    keys: list
    rows: list
    aggs: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class _State:
    plan: Plan
    tables: dict[str, Table]
    scope: Scope = dataclasses.field(default_factory=lambda: Scope([], []))
    rows: list = dataclasses.field(default_factory=list)
    prepared: bool = False
    grouped: bool = False
    where: Expr | None = None
    keys: list = dataclasses.field(default_factory=list)
    aggs: list = dataclasses.field(default_factory=list)
    items: list = dataclasses.field(default_factory=list)
    sources: list = dataclasses.field(default_factory=list)
    columns: list = dataclasses.field(default_factory=list)
    having: Expr | None = None
    order: list = dataclasses.field(default_factory=list)
    groups: list = dataclasses.field(default_factory=list)
    outputs: list = dataclasses.field(default_factory=list)


def _is_true(value: object) -> bool:
    return require_logical(value) is True


def _lookup_table(state: _State, name: str) -> Table:
    table = state.tables.get(name)
    if table is None:
        raise UnknownTableError(f"unknown table {name!r}")
    return table


# ---------------------------------------------------------------- preparation


def output_name(item: SelectItem) -> str:
    """Alias, else the column name of a column reference, else the source text."""
    if item.alias is not None:
        return item.alias
    # A qualified reference t.c is also named after its column, c.
    if isinstance(item.expr, ColumnRef):
        return item.expr.name
    return item.text


def _group_compile(node: Expr, state: _State) -> Expr:
    """Rewrite a bound expression so that it evaluates against a group."""
    for i, key in enumerate(state.keys):
        if node == key:
            return GroupKey(i)
    if isinstance(node, AggCall):
        if node not in state.aggs:
            state.aggs.append(node)
        return AggRef(state.aggs.index(node))
    if isinstance(node, BoundColumn):
        raise GroupingError(
            f"column {node.name!r} must appear in GROUP BY or be used in an aggregate"
        )
    return map_children(node, lambda c: _group_compile(c, state))


def _finish(node: Expr, state: _State, scope: Scope, clause: str, aggs: bool) -> Expr:
    bound = bind(node, scope, aggs and state.grouped, clause)
    return _group_compile(bound, state) if state.grouped else bound


def _expand_star(item: SelectItem, state: _State) -> None:
    scope = state.scope
    if item.star_table is not None and item.star_table not in scope.tables:
        raise UnknownTableError(f"unknown table {item.star_table!r}")
    for i, (table, column) in enumerate(scope.entries):
        if item.star_table is None or table == item.star_table:
            state.items.append(_finish(BoundColumn(i, column), state, scope, "SELECT", False))
            state.columns.append(column)
            state.sources.append(ColumnRef(table, column))


def _prepare_items(state: _State, items: tuple) -> None:
    for item in items:
        if item.star:
            _expand_star(item, state)
            continue
        state.items.append(_finish(item.expr, state, state.scope, "SELECT", True))
        state.columns.append(output_name(item))
        state.sources.append(item.expr)


def _resolve_outputs(node: Expr, state: _State) -> Expr:
    """Replace ORDER BY references to output columns; an alias beats an input column."""
    if isinstance(node, ColumnRef) and node.table is None and node.name in state.columns:
        return OutputColumn(state.columns.index(node.name))
    for i, source in enumerate(state.sources):
        if node == source:
            return OutputColumn(i)
    if isinstance(node, AggCall):
        return node  # aggregate arguments always refer to input columns
    return map_children(node, lambda c: _resolve_outputs(c, state))


def _prepare_order(state: _State, stage: SortStage) -> None:
    distinct = state.plan.find(DistinctStage) is not None
    # After DISTINCT only output columns exist; any other column reference is
    # reported as UnknownColumnError (and aggregates as AggregateError).
    scope = Scope([], state.scope.tables) if distinct else state.scope
    for item in stage.keys:
        node = _resolve_outputs(item.expr, state)
        state.order.append((_finish(node, state, scope, "ORDER BY", not distinct),
                            item.descending))


def _prepare(state: _State) -> None:
    """Bind every expression of the plan once the working scope is known."""
    p = state.plan
    filt = p.find(FilterStage)
    if isinstance(filt, FilterStage):
        state.where = bind(filt.predicate, state.scope, False, "WHERE")
    group = p.find(GroupStage)
    if isinstance(group, GroupStage):
        state.grouped = True
        state.keys = [bind(k, state.scope, False, "GROUP BY") for k in group.keys]
    project = p.find(ProjectStage)
    if isinstance(project, ProjectStage):
        _prepare_items(state, project.items)
    having = p.find(HavingStage)
    if isinstance(having, HavingStage):
        state.having = _finish(having.predicate, state, state.scope, "HAVING", True)
    sort = p.find(SortStage)
    if isinstance(sort, SortStage):
        _prepare_order(state, sort)
    state.prepared = True


# ---------------------------------------------------------------- stages


def _run_scan(stage: ScanStage, state: _State) -> None:
    table = _lookup_table(state, stage.table)
    state.scope = Scope([(stage.table, c.name) for c in table.columns], [stage.table])
    state.rows = table.rows


def _run_join(stage: JoinStage, state: _State) -> None:
    right = _lookup_table(state, stage.table)
    entries = state.scope.entries + [(stage.table, c.name) for c in right.columns]
    state.scope = Scope(entries, state.scope.tables + [stage.table])
    on = bind(stage.on, state.scope, False, "JOIN ... ON")
    right_rows = right.rows
    padding = [None] * len(right.columns)
    joined = []
    for left in state.rows:
        matched = False
        for row in right_rows:
            combined = left + row
            if _is_true(evaluate(on, Context(row=combined))):
                joined.append(combined)
                matched = True
        if not matched and stage.kind == "LEFT":
            joined.append(left + padding)
    state.rows = joined


def _run_filter(stage: FilterStage, state: _State) -> None:
    where = state.where
    assert where is not None
    state.rows = [r for r in state.rows if _is_true(evaluate(where, Context(row=r)))]


def _run_group(stage: GroupStage, state: _State) -> None:
    if not state.keys:
        # No GROUP BY: the whole input is one group, even when it is empty.
        state.groups = [_Group([], state.rows)]
        return
    groups: dict[tuple, _Group] = {}
    for row in state.rows:
        ctx = Context(row=row)
        values = [evaluate(k, ctx) for k in state.keys]
        key = row_key(values)
        if key in groups:
            groups[key].rows.append(row)
        else:
            groups[key] = _Group(values, [row])
    state.groups = list(groups.values())


def _compute(agg: AggCall, rows: list) -> object:
    if agg.star:
        return agg_count_star(len(rows))
    arg = agg.args[0]
    return compute_aggregate(agg.name, [evaluate(arg, Context(row=r)) for r in rows])


def _run_aggregate(stage: AggregateStage, state: _State) -> None:
    for group in state.groups:
        group.aggs = [_compute(agg, group.rows) for agg in state.aggs]


def _group_context(group: _Group) -> Context:
    return Context(keys=group.keys, aggs=group.aggs)


def _run_having(stage: HavingStage, state: _State) -> None:
    having = state.having
    assert having is not None
    state.groups = [
        g for g in state.groups if _is_true(evaluate(having, _group_context(g)))
    ]


def _run_project(stage: ProjectStage, state: _State) -> None:
    if state.grouped:
        contexts = [_group_context(g) for g in state.groups]
    else:
        contexts = [Context(row=r) for r in state.rows]
    state.outputs = [([evaluate(e, ctx) for e in state.items], ctx) for ctx in contexts]


def _run_distinct(stage: DistinctStage, state: _State) -> None:
    seen: set[tuple] = set()
    kept = []
    for out, ctx in state.outputs:
        key = row_key(out)
        if key not in seen:
            seen.add(key)
            kept.append((out, ctx))
    state.outputs = kept


def _compare_keys(a: list, b: list, descending: list[bool]) -> int:
    for x, y, desc in zip(a, b, descending):
        if x is None or y is None:
            if x is None and y is None:
                continue
            return 1 if x is None else -1  # NULL last in both directions
        if compare_eq(x, y):
            continue
        result = -1 if compare_lt(x, y) else 1
        return -result if desc else result
    return 0


def _run_sort(stage: SortStage, state: _State) -> None:
    descending = [desc for _, desc in state.order]
    decorated = []
    for out, ctx in state.outputs:
        full = Context(row=ctx.row, out=out, keys=ctx.keys, aggs=ctx.aggs)
        decorated.append(([evaluate(e, full) for e, _ in state.order], (out, ctx)))
    cmp = functools.cmp_to_key(lambda a, b: _compare_keys(a[0], b[0], descending))
    decorated.sort(key=cmp)  # list.sort is stable
    state.outputs = [pair for _, pair in decorated]


def _run_offset(stage: OffsetStage, state: _State) -> None:
    state.outputs = state.outputs[stage.count :]


def _run_limit(stage: LimitStage, state: _State) -> None:
    state.outputs = state.outputs[: stage.count]


_HANDLERS: dict[type, Callable] = {
    ScanStage: _run_scan,
    JoinStage: _run_join,
    FilterStage: _run_filter,
    GroupStage: _run_group,
    AggregateStage: _run_aggregate,
    HavingStage: _run_having,
    ProjectStage: _run_project,
    DistinctStage: _run_distinct,
    SortStage: _run_sort,
    OffsetStage: _run_offset,
    LimitStage: _run_limit,
}


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    """Run every stage of a plan and return the result."""
    state = _State(plan, tables)
    for stage in plan:
        if not state.prepared and not isinstance(stage, (ScanStage, JoinStage)):
            _prepare(state)
        handler: Callable[[Stage, _State], None] = _HANDLERS[type(stage)]
        handler(stage, state)
    return Result(list(state.columns), [list(out) for out, _ in state.outputs])


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Parse, plan and execute a query."""
    return execute_plan(plan(parse(query)), tables)
