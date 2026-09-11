"""Executor: runs a :class:`Plan` against a set of tables."""

from __future__ import annotations

import dataclasses
import functools
from typing import Callable

from .aggregate import compute
from .errors import UnknownColumnError, UnknownTableError
from .expr import Binding, Context, as_logical, evaluate, expr_key
from .parser import ColumnRef, Expr, OrderItem, SelectItem, Star, parse
from .planner import (
    DistinctStage,
    FilterStage,
    GroupStage,
    HavingStage,
    JoinStage,
    Plan,
    ProjectStage,
    ScanStage,
    SliceStage,
    SortStage,
    plan,
)
from .schema import Table
from .value import compare_eq, compare_lt, type_of


@dataclasses.dataclass(frozen=True)
class Result:
    """The outcome of a query: output column names and rows."""

    columns: list[str]
    rows: list[list[object]]


@dataclasses.dataclass
class Unit:
    """One projection unit: a single row, or a whole group with its aggregates."""

    rep_row: list[object]
    rows: list[list[object]]
    aggregates: dict[tuple[object, ...], object] | None


@dataclasses.dataclass
class State:
    """Mutable execution state threaded through the stages."""

    tables: dict[str, Table]
    scope: frozenset[str] = frozenset()
    bindings: list[Binding] = dataclasses.field(default_factory=list)
    rows: list[list[object]] = dataclasses.field(default_factory=list)
    units: list[Unit] | None = None
    columns: list[str] = dataclasses.field(default_factory=list)
    select_keys: list[tuple[object, ...] | None] = dataclasses.field(default_factory=list)
    output: list[tuple[list[object], Unit]] = dataclasses.field(default_factory=list)


def group_token(v: object) -> tuple[object, ...]:
    """Hashable token for grouping, where NULL equals NULL and INT equals FLOAT."""
    kind = type_of(v)
    if kind == "NULL":
        return ("NULL",)
    if kind in ("INT", "FLOAT"):
        return ("NUM", v)
    return (kind, v)


def _ctx(state: State, row: list[object],
         aggs: dict[tuple[object, ...], object] | None = None) -> Context:
    return Context(state.bindings, row, state.scope, None, True, aggs)


def _get_table(state: State, name: str) -> Table:
    if name not in state.tables:
        raise UnknownTableError(f"unknown table {name!r}")
    return state.tables[name]


def _run_scan(state: State, stage: ScanStage) -> None:
    table = _get_table(state, stage.table)
    state.scope = state.scope | {stage.table}
    state.bindings = [Binding(stage.table, c.name) for c in table.columns]
    state.rows = [list(row) for row in table.rows]


def _run_join(state: State, stage: JoinStage) -> None:
    right = _get_table(state, stage.table)
    left_rows = state.rows
    state.scope = state.scope | {stage.table}
    state.bindings = state.bindings + [Binding(stage.table, c.name) for c in right.columns]
    nulls: list[object] = [None] * len(right.columns)
    joined: list[list[object]] = []
    for left_row in left_rows:
        matched = False
        for right_row in right.rows:
            combined = left_row + list(right_row)
            if as_logical(evaluate(stage.on, _ctx(state, combined))) is True:
                joined.append(combined)
                matched = True
        if stage.kind == "LEFT" and not matched:
            joined.append(left_row + nulls)
    state.rows = joined


def _run_filter(state: State, stage: FilterStage) -> None:
    state.rows = [
        row for row in state.rows
        if as_logical(evaluate(stage.predicate, _ctx(state, row))) is True
    ]


def _aggregate_group(state: State, stage: GroupStage,
                     rows: list[list[object]]) -> dict[tuple[object, ...], object]:
    values: dict[tuple[object, ...], object] = {}
    for call in stage.aggregates:
        arg = call.args[0]
        star = isinstance(arg, Star)
        if star:
            inputs: list[object] = [True] * len(rows)
        else:
            inputs = [evaluate(arg, _ctx(state, row)) for row in rows]
        values[expr_key(call)] = compute(call.name, inputs, star)
    return values


def _run_group(state: State, stage: GroupStage) -> None:
    buckets: dict[tuple[tuple[object, ...], ...], list[list[object]]] = {}
    if stage.implicit:
        buckets[()] = list(state.rows)
    else:
        for row in state.rows:
            ctx = _ctx(state, row)
            key = tuple(group_token(evaluate(k, ctx)) for k in stage.keys)
            buckets.setdefault(key, []).append(row)
    empty: list[object] = [None] * len(state.bindings)
    state.units = [
        Unit(rows[0] if rows else empty, rows, _aggregate_group(state, stage, rows))
        for rows in buckets.values()
    ]


def _run_having(state: State, stage: HavingStage) -> None:
    units = state.units or []
    state.units = [
        unit for unit in units
        if as_logical(
            evaluate(stage.predicate, _ctx(state, unit.rep_row, unit.aggregates))
        ) is True
    ]


def _star_bindings(state: State, star: Star) -> list[int]:
    if star.table is not None and star.table not in state.scope:
        raise UnknownTableError(f"unknown table {star.table!r}")
    return [
        index for index, binding in enumerate(state.bindings)
        if star.table is None or binding.table == star.table
    ]


def _projectors(state: State, items: tuple[SelectItem, ...]
                ) -> list[tuple[str, int | None, Expr | None]]:
    """Build (output name, binding index, expression) triples for the projection."""
    out: list[tuple[str, int | None, Expr | None]] = []
    for item in items:
        if isinstance(item.expr, Star):
            for index in _star_bindings(state, item.expr):
                out.append((state.bindings[index].name, index, None))
        elif item.alias is not None:
            out.append((item.alias, None, item.expr))
        elif isinstance(item.expr, ColumnRef):
            out.append((item.expr.name, None, item.expr))
        else:
            out.append((item.expr.text, None, item.expr))
    return out


def _run_project(state: State, stage: ProjectStage) -> None:
    if state.units is None:
        state.units = [Unit(row, [row], None) for row in state.rows]
    projectors = _projectors(state, stage.items)
    state.columns = [name for name, _, _ in projectors]
    state.select_keys = _select_keys(state, stage)
    output: list[tuple[list[object], Unit]] = []
    for unit in state.units:
        ctx = _ctx(state, unit.rep_row, unit.aggregates)
        row = [
            unit.rep_row[index] if expression is None else evaluate(expression, ctx)
            for _, index, expression in projectors
        ]
        output.append((row, unit))
    state.output = output


def _run_distinct(state: State, stage: DistinctStage) -> None:
    seen: set[tuple[tuple[object, ...], ...]] = set()
    kept: list[tuple[list[object], Unit]] = []
    for row, unit in state.output:
        key = tuple(group_token(v) for v in row)
        if key not in seen:
            seen.add(key)
            kept.append((row, unit))
    state.output = kept


def _order_value(state: State, item: OrderItem, row: list[object], unit: Unit,
                 distinct: bool) -> object:
    """Resolve one ORDER BY expression; output names and aliases shadow input columns."""
    expr = item.expr
    if isinstance(expr, ColumnRef) and expr.table is None and expr.name in state.columns:
        return row[state.columns.index(expr.name)]
    key = expr_key(expr)
    for index, projected in enumerate(state.select_keys):
        if projected is not None and projected == key:
            return row[index]
    if distinct:
        raise UnknownColumnError(
            f"ORDER BY {expr.text!r} is not an output column of a DISTINCT query"
        )
    return evaluate(expr, _ctx(state, unit.rep_row, unit.aggregates))


def _key_comparator(descending: bool) -> Callable[[object, object], int]:
    """Build a comparator putting NULL last in both directions."""

    def cmp(a: object, b: object) -> int:
        if a is None and b is None:
            return 0
        if a is None:
            return 1
        if b is None:
            return -1
        if compare_eq(a, b) is True:
            return 0
        forward = -1 if compare_lt(a, b) is True else 1
        return -forward if descending else forward

    return cmp


def _run_sort(state: State, stage: SortStage) -> None:
    for item in reversed(stage.keys):
        cmp = _key_comparator(item.descending)
        decorated = [
            (_order_value(state, item, row, unit, stage.distinct), row, unit)
            for row, unit in state.output
        ]
        decorated.sort(key=functools.cmp_to_key(lambda x, y: cmp(x[0], y[0])))
        state.output = [(row, unit) for _, row, unit in decorated]


def _run_slice(state: State, stage: SliceStage) -> None:
    start = stage.offset or 0
    rows = state.output[start:]
    if stage.limit is not None:
        rows = rows[: stage.limit]
    state.output = rows


_RUNNERS: dict[type, Callable[..., None]] = {
    ScanStage: _run_scan,
    JoinStage: _run_join,
    FilterStage: _run_filter,
    GroupStage: _run_group,
    HavingStage: _run_having,
    ProjectStage: _run_project,
    DistinctStage: _run_distinct,
    SortStage: _run_sort,
    SliceStage: _run_slice,
}


def execute_plan(plan_obj: Plan, tables: dict[str, Table]) -> Result:
    """Run every stage of ``plan_obj`` and return the :class:`Result`."""
    state = State(tables)
    for stage in plan_obj:
        runner = _RUNNERS[type(stage)]
        runner(state, stage)
    return Result(list(state.columns), [row for row, _ in state.output])


def _select_keys(state: State, stage: ProjectStage) -> list[tuple[object, ...] | None]:
    """Structural keys of projected expressions, used to match ORDER BY items."""
    keys: list[tuple[object, ...] | None] = []
    for item in stage.items:
        if isinstance(item.expr, Star):
            keys.extend([None] * len(_star_bindings(state, item.expr)))
        else:
            keys.append(expr_key(item.expr))
    return keys


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Parse, plan and execute ``query`` against ``tables``."""
    return execute_plan(plan(parse(query)), tables)
