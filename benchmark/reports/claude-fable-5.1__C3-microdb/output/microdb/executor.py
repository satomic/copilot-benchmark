"""Execute a Plan against a set of tables."""

from __future__ import annotations

import dataclasses
import functools
from typing import Callable, Optional

from .aggregate import Aggregator, make_aggregator
from .errors import UnknownTableError
from .expr import Context, Scope, eval_predicate, evaluate, expr_key
from .parser import ColumnRef, Expr, parse
from .planner import (
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
    check_grouped,
    plan,
)
from .schema import Table
from .value import compare, hash_key


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclasses.dataclass
class _State:
    """Mutable pipeline state threaded through the stages."""

    tables: dict[str, Table]
    scope: Scope = dataclasses.field(default_factory=lambda: Scope([]))
    frames: list[Context] = dataclasses.field(default_factory=list)
    grouped: bool = False
    group_keys: set[tuple] = dataclasses.field(default_factory=set)
    out_names: list[str] = dataclasses.field(default_factory=list)
    out_rows: list[list[object]] = dataclasses.field(default_factory=list)
    out_scope: Scope = dataclasses.field(default_factory=lambda: Scope([]))
    select_keys: list[tuple] = dataclasses.field(default_factory=list)
    distinct: bool = False


def _lookup_table(state: _State, name: str) -> Table:
    try:
        return state.tables[name]
    except KeyError:
        raise UnknownTableError(f"unknown table {name!r}") from None


def _run_scan(state: _State, stage: ScanStage) -> None:
    table = _lookup_table(state, stage.table)
    state.scope = Scope([(table.name, c.name) for c in table.columns])
    state.frames = [Context(state.scope, list(row)) for row in table.rows]


def _run_join(state: _State, stage: JoinStage) -> None:
    right = _lookup_table(state, stage.table)
    if stage.table in state.scope.tables:
        raise UnknownTableError(f"table {stage.table!r} appears twice in FROM")
    scope = Scope(state.scope.columns + [(right.name, c.name) for c in right.columns])
    nulls: list[object] = [None] * len(right.columns)
    frames: list[Context] = []
    for left in state.frames:
        matched = False
        for rrow in right.rows:
            ctx = Context(scope, left.row + list(rrow))
            if eval_predicate(stage.on, ctx, "ON"):
                frames.append(ctx)
                matched = True
        if not matched and stage.kind == "LEFT":
            frames.append(Context(scope, left.row + nulls))
    state.scope = scope
    state.frames = frames


def _run_filter(state: _State, stage: FilterStage) -> None:
    state.frames = [f for f in state.frames if eval_predicate(stage.predicate, f, "WHERE")]


def _run_group(state: _State, stage: GroupStage) -> None:
    groups: dict[tuple, tuple[list[object], list[Aggregator]]] = {}

    def new_group(first: list[object]) -> tuple[list[object], list[Aggregator]]:
        return (first, [make_aggregator(a.name, a.star) for a in stage.aggregates])

    for frame in state.frames:
        key = tuple(hash_key(evaluate(k, frame)) for k in stage.keys)
        if key not in groups:
            groups[key] = new_group(frame.row)
        for agg_node, agg in zip(stage.aggregates, groups[key][1]):
            agg.add(None if agg_node.star else evaluate(agg_node.args[0], frame))
    if not stage.keys and not groups:
        # No GROUP BY: the whole (empty) input is still exactly one group.
        groups[()] = new_group([None] * len(state.scope))
    agg_keys = [expr_key(a) for a in stage.aggregates]
    state.frames = [
        Context(state.scope, first, dict(zip(agg_keys, (a.result() for a in aggs))))
        for first, aggs in groups.values()
    ]
    state.grouped = True
    state.group_keys = {expr_key(k) for k in stage.keys}


def _run_having(state: _State, stage: HavingStage) -> None:
    state.frames = [f for f in state.frames if eval_predicate(stage.predicate, f, "HAVING")]


def _project_names(state: _State, stage: ProjectStage) -> tuple[list[str], list[tuple]]:
    names: list[str] = []
    keys: list[tuple] = []
    for item in stage.items:
        if item.star:
            table = item.star_table
            if table is not None and table not in state.scope.tables:
                raise UnknownTableError(f"unknown table {table!r}")
            for t, n in state.scope.columns:
                if table is None or t == table:
                    names.append(n)
                    keys.append(("star", t, n))
            continue
        assert item.expr is not None
        if item.alias is not None:
            names.append(item.alias)
        elif isinstance(item.expr, ColumnRef):
            # A qualified reference t.c is also reported as c, as SQL engines do.
            names.append(item.expr.name)
        else:
            names.append(item.source)
        keys.append(expr_key(item.expr))
    return names, keys


def _project_row(frame: Context, stage: ProjectStage) -> list[object]:
    out: list[object] = []
    for item in stage.items:
        if item.star:
            table = item.star_table
            for i, (t, _) in enumerate(frame.scope.columns):
                if table is None or t == table:
                    out.append(frame.row[i])
        else:
            assert item.expr is not None
            out.append(evaluate(item.expr, frame))
    return out


def _run_project(state: _State, stage: ProjectStage) -> None:
    state.out_names, state.select_keys = _project_names(state, stage)
    state.out_rows = [_project_row(f, stage) for f in state.frames]
    state.out_scope = Scope([(None, n) for n in state.out_names])


def _run_distinct(state: _State, stage: DistinctStage) -> None:
    seen: set[tuple] = set()
    rows: list[list[object]] = []
    frames: list[Context] = []
    for row, frame in zip(state.out_rows, state.frames):
        key = tuple(hash_key(v) for v in row)
        if key not in seen:
            seen.add(key)
            rows.append(row)
            frames.append(frame)
    state.out_rows = rows
    state.frames = frames
    state.distinct = True


def _order_getter(state: _State, expr: Expr) -> Callable[[int], object]:
    """Build a function mapping an output row index to the sort key value."""
    if isinstance(expr, ColumnRef) and expr.table is None and expr.name in state.out_names:
        col = state.out_names.index(expr.name)  # alias wins over input columns
        return lambda i: state.out_rows[i][col]
    key = expr_key(expr)
    if key in state.select_keys:
        col = state.select_keys.index(key)
        return lambda i: state.out_rows[i][col]
    if state.distinct:
        # After DISTINCT only output columns are visible.
        return lambda i: evaluate(expr, Context(state.out_scope, state.out_rows[i]))
    if state.grouped:
        aliases = {n for n in state.out_names}
        check_grouped(expr, state.group_keys, aliases)
    scope = state.out_scope.extend(state.scope)
    return lambda i: evaluate(
        expr, Context(scope, state.out_rows[i] + state.frames[i].row, state.frames[i].aggregates)
    )


def _compare_keys(a: list[object], b: list[object], descs: list[bool]) -> int:
    for x, y, desc in zip(a, b, descs):
        if x is None and y is None:
            continue
        if x is None:
            return 1  # NULL sorts last regardless of direction
        if y is None:
            return -1
        c = compare(x, y)
        if c:
            return -c if desc else c
    return 0


def _run_sort(state: _State, stage: SortStage) -> None:
    getters = [_order_getter(state, k.expr) for k in stage.keys]
    descs = [k.desc for k in stage.keys]
    indices = list(range(len(state.out_rows)))
    keys = [[g(i) for g in getters] for i in indices]
    cmp = functools.cmp_to_key(lambda i, j: _compare_keys(keys[i], keys[j], descs))
    indices.sort(key=cmp)
    state.out_rows = [state.out_rows[i] for i in indices]
    state.frames = [state.frames[i] for i in indices]


def _run_offset(state: _State, stage: OffsetStage) -> None:
    state.out_rows = state.out_rows[stage.count :]
    state.frames = state.frames[stage.count :]


def _run_limit(state: _State, stage: LimitStage) -> None:
    state.out_rows = state.out_rows[: stage.count]
    state.frames = state.frames[: stage.count]


_RUNNERS: dict[type, Callable[[_State, Stage], None]] = {
    ScanStage: _run_scan,  # type: ignore[dict-item]
    JoinStage: _run_join,  # type: ignore[dict-item]
    FilterStage: _run_filter,  # type: ignore[dict-item]
    GroupStage: _run_group,  # type: ignore[dict-item]
    HavingStage: _run_having,  # type: ignore[dict-item]
    ProjectStage: _run_project,  # type: ignore[dict-item]
    DistinctStage: _run_distinct,  # type: ignore[dict-item]
    SortStage: _run_sort,  # type: ignore[dict-item]
    OffsetStage: _run_offset,  # type: ignore[dict-item]
    LimitStage: _run_limit,  # type: ignore[dict-item]
}


def execute_plan(plan_: Plan, tables: dict[str, Table]) -> Result:
    state = _State(tables=tables)
    for stage in plan_:
        runner: Optional[Callable[[_State, Stage], None]] = _RUNNERS.get(type(stage))
        if runner is None:
            raise TypeError(f"unknown stage {stage!r}")
        runner(state, stage)
    return Result(columns=list(state.out_names), rows=[list(r) for r in state.out_rows])


def execute(query: str, tables: dict[str, Table]) -> Result:
    return execute_plan(plan(parse(query)), tables)
