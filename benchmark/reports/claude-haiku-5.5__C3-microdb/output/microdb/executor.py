"""Executor: runs a Plan over in-memory tables."""

from __future__ import annotations

import dataclasses
import functools
from dataclasses import dataclass, field

from .aggregate import compute
from .errors import UnknownTableError
from .expr import Env, Scope, evaluate, iter_nodes
from .parser import Call, Col, Expr, Join, OrderItem, SelectItem, Star, parse
from .planner import (
    AggregateStage,
    DistinctStage,
    FilterStage,
    GroupStage,
    HavingStage,
    Plan,
    ProjectStage,
    ScanStage,
    SliceStage,
    SortStage,
    plan as build_plan,
)
from .schema import Table
from .value import as_logical, compare_lt, group_key


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclass
class _State:
    tables: dict[str, Table]
    stages: tuple = ()
    scope: Scope | None = None
    units: list[Env] = field(default_factory=list)
    rows: list[tuple[Env, list[object]]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    distinct: bool = False


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Parse, plan and run a query string against the given tables."""
    return execute_plan(build_plan(parse(query)), tables)


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    state = _State(tables=tables, stages=tuple(plan))
    for stage in plan:
        _HANDLERS[type(stage)](state, stage)
    return Result(columns=state.names, rows=[row for _, row in state.rows])


def _table(tables: dict[str, Table], name: str) -> Table:
    if name not in tables:
        raise UnknownTableError(f"unknown table {name!r}")
    return tables[name]


def _scan(state: _State, stage: ScanStage) -> None:
    base = _table(state.tables, stage.table)
    entries = [(stage.table, c.name) for c in base.columns]
    rows = [list(r) for r in base.rows]
    if stage.join is not None:
        right = _table(state.tables, stage.join.table)
        entries += [(stage.join.table, c.name) for c in right.columns]
        rows = _join(rows, right.rows, stage.join, Scope(tuple(entries)), len(right.columns))
    state.scope = Scope(tuple(entries))
    _check_columns(state)
    state.units = [Env(row=r, scope=state.scope) for r in rows]


def _join(left: list[list[object]], right: list[list[object]], join: Join,
          scope: Scope, width: int) -> list[list[object]]:
    """Left-major nested-loop join; LEFT joins pad unmatched rows with NULLs."""
    out: list[list[object]] = []
    for lrow in left:
        matches = []
        for rrow in right:
            combined = lrow + rrow
            if as_logical(evaluate(join.on, Env(row=combined, scope=scope))) is True:
                matches.append(combined)
        if not matches and join.kind == "LEFT":
            matches.append(lrow + [None] * width)
        out.extend(matches)
    return out


def _check_columns(state: _State) -> None:
    """Resolve every column reference up front so errors surface even on empty input.

    ORDER BY is excluded because it may legitimately name output aliases.
    """
    assert state.scope is not None
    for expr in _stage_exprs(state.stages):
        for node in iter_nodes(expr):
            if isinstance(node, Col):
                state.scope.resolve(node.qualifier, node.name)


def _stage_exprs(stages: tuple) -> list[Expr]:
    exprs: list[Expr] = []
    for stage in stages:
        if isinstance(stage, ScanStage) and stage.join is not None:
            exprs.append(stage.join.on)
        elif isinstance(stage, FilterStage | HavingStage):
            exprs.append(stage.predicate)
        elif isinstance(stage, GroupStage):
            exprs.extend(stage.keys)
        elif isinstance(stage, AggregateStage):
            exprs.extend(stage.calls)
        elif isinstance(stage, ProjectStage):
            exprs.extend(i.expr for i in stage.items if isinstance(i, SelectItem))
    return exprs


def _keep(state: _State, predicate: Expr) -> None:
    state.units = [u for u in state.units if as_logical(evaluate(predicate, u)) is True]


def _filter(state: _State, stage: FilterStage) -> None:
    _keep(state, stage.predicate)


def _group(state: _State, stage: GroupStage) -> None:
    buckets: dict[tuple, tuple[list[object], list[Env]]] = {}
    for unit in state.units:
        values = [evaluate(key, unit) for key in stage.keys]
        gkey = tuple(group_key(v) for v in values)
        buckets.setdefault(gkey, (values, []))[1].append(unit)
    if not stage.keys and not buckets:
        buckets[()] = ([], [])
    empty_row = [None] * len(state.scope.entries) if state.scope else []
    state.units = [
        Env(row=members[0].row if members else empty_row, scope=state.scope,
            keys=dict(zip(stage.keys, values)), members=tuple(members))
        for values, members in buckets.values()
    ]


def _aggregate_value(call: Call, members: tuple) -> object:
    if call.star:
        return compute(call.name, [1] * len(members))
    arg = call.args[0]
    return compute(call.name, [evaluate(arg, m) for m in members])


def _aggregate(state: _State, stage: AggregateStage) -> None:
    updated = []
    for unit in state.units:
        values = {call: _aggregate_value(call, unit.members) for call in stage.calls}
        updated.append(dataclasses.replace(unit, keys={**(unit.keys or {}), **values}))
    state.units = updated


def _having(state: _State, stage: HavingStage) -> None:
    _keep(state, stage.predicate)


def _output_name(item: SelectItem) -> str:
    if item.alias is not None:
        return item.alias
    if isinstance(item.expr, Col):
        return item.expr.name
    return item.text


def _expand_items(items: tuple, scope: Scope) -> list[tuple[str, Expr]]:
    expanded: list[tuple[str, Expr]] = []
    for item in items:
        if isinstance(item, Star):
            if item.table is not None and item.table not in {t for t, _ in scope.entries}:
                raise UnknownTableError(f"unknown table {item.table!r}")
            for table, col in scope.entries:
                if item.table is None or item.table == table:
                    expanded.append((col, Col(table, col)))
        else:
            expanded.append((_output_name(item), item.expr))
    return expanded


def _project(state: _State, stage: ProjectStage) -> None:
    assert state.scope is not None
    expanded = _expand_items(stage.items, state.scope)
    state.names = [name for name, _ in expanded]
    state.rows = [(u, [evaluate(e, u) for _, e in expanded]) for u in state.units]


def _distinct(state: _State, stage: DistinctStage) -> None:
    seen: set[tuple] = set()
    kept = []
    for unit, row in state.rows:
        key = tuple(group_key(v) for v in row)
        if key not in seen:
            seen.add(key)
            kept.append((unit, row))
    state.rows = kept
    state.distinct = True


def _cmp_one(x: object, y: object, desc: bool) -> int:
    """NULL sorts after every value in both directions; DESC flips non-NULL order only."""
    if x is None and y is None:
        return 0
    if x is None:
        return 1
    if y is None:
        return -1
    if compare_lt(x, y):
        result = -1
    elif compare_lt(y, x):
        result = 1
    else:
        result = 0
    return -result if desc else result


def _cmp_keys(a: list[object], b: list[object], items: tuple[OrderItem, ...]) -> int:
    for x, y, item in zip(a, b, items):
        result = _cmp_one(x, y, item.desc)
        if result:
            return result
    return 0


def _sort(state: _State, stage: SortStage) -> None:
    decorated = []
    for unit, row in state.rows:
        env = dataclasses.replace(
            unit,
            scope=None if state.distinct else unit.scope,
            aliases=dict(zip(state.names, row)),
        )
        decorated.append(([evaluate(o.expr, env) for o in stage.keys], (unit, row)))
    decorated.sort(key=functools.cmp_to_key(lambda a, b: _cmp_keys(a[0], b[0], stage.keys)))
    state.rows = [pair for _, pair in decorated]


def _slice(state: _State, stage: SliceStage) -> None:
    start = stage.offset or 0
    end = None if stage.limit is None else start + stage.limit
    state.rows = state.rows[start:end]


_HANDLERS = {
    ScanStage: _scan,
    FilterStage: _filter,
    GroupStage: _group,
    AggregateStage: _aggregate,
    HavingStage: _having,
    ProjectStage: _project,
    DistinctStage: _distinct,
    SortStage: _sort,
    SliceStage: _slice,
}
