"""Executor: runs a Plan against tables."""

import dataclasses
import functools
from typing import Callable, NamedTuple

from .aggregate import aggregate
from .errors import (AggregateError, AmbiguousColumnError, GroupingError,
                     TypeMismatchError, UnknownColumnError, UnknownTableError)
from .expr import (bind, children, collect_aggregates, contains_aggregate,
                   evaluate, is_aggregate, rewrite)
from .parser import (BoundColumn, Call, ColumnRef, OutColumn, Star, parse)
from .planner import Plan, plan
from .schema import Table
from .value import compare_lt, is_numeric


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


class _Unit(NamedTuple):
    row: list | None
    aggs: dict | None


@dataclasses.dataclass
class _Bound:
    scope: list[tuple[str, str]]
    where: object | None
    on: object | None
    group_by: list
    having: object | None
    items: list[tuple[object, str]]
    order: list[tuple[object, bool]]
    calls: list[Call]


@dataclasses.dataclass
class _State:
    tables: dict[str, Table]
    bound: _Bound
    rows: list = dataclasses.field(default_factory=list)
    groups: list | None = None
    units: list[_Unit] | None = None
    out: list = dataclasses.field(default_factory=list)


def _table(tables: dict[str, Table], name: str) -> Table:
    if name not in tables:
        raise UnknownTableError(f"unknown table {name!r}")
    return tables[name]


def _make_resolver(scope: list[tuple[str, str]]) -> Callable[[ColumnRef], BoundColumn]:
    def resolve(ref: ColumnRef) -> BoundColumn:
        if ref.table is not None and all(t != ref.table for t, _ in scope):
            raise UnknownTableError(f"unknown table {ref.table!r}")
        hits = [i for i, (t, c) in enumerate(scope)
                if c == ref.name and (ref.table is None or t == ref.table)]
        label = ref.name if ref.table is None else f"{ref.table}.{ref.name}"
        if not hits:
            raise UnknownColumnError(f"unknown column {label!r}")
        if len(hits) > 1:
            raise AmbiguousColumnError(f"ambiguous column {label!r}")
        return BoundColumn(hits[0])
    return resolve


def _no_aggregate(node: object, where: str) -> None:
    if node is not None and contains_aggregate(node):
        raise AggregateError(f"aggregates are not allowed in {where}")


def _bind_items(query, scope, resolve) -> list[tuple[object, str]]:
    items: list[tuple[object, str]] = []
    for item in query.items:
        if isinstance(item.expr, Star):
            star = item.expr
            if star.table is not None and all(t != star.table for t, _ in scope):
                raise UnknownTableError(f"unknown table {star.table!r}")
            for i, (t, c) in enumerate(scope):
                if star.table is None or t == star.table:
                    items.append((BoundColumn(i), c))
            continue
        name = item.alias
        if name is None:
            name = item.expr.name if isinstance(item.expr, ColumnRef) else item.text
        items.append((bind(item.expr, resolve), name))
    return items


def _bind_order(query, items, resolve, grouped: bool) -> list[tuple[object, bool]]:
    names = [n for _, n in items]
    nodes = [n for n, _ in items]

    def by_output(n: object) -> object | None:
        if is_aggregate(n):
            return bind(n, resolve)
        if isinstance(n, ColumnRef) and n.table is None and n.name in names:
            return OutColumn(names.index(n.name))  # the alias wins over input columns
        if isinstance(n, ColumnRef):
            return resolve(n)
        return None

    def to_output(n: object) -> object | None:
        return OutColumn(nodes.index(n)) if n in nodes else None

    order = []
    for entry in query.order_by:
        node = rewrite(entry.expr, by_output)
        if not grouped and contains_aggregate(node):
            raise AggregateError("aggregates in ORDER BY need GROUP BY or a SELECT aggregate")
        if query.distinct:
            node = rewrite(node, to_output)
            _require_output_only(node)
        order.append((node, entry.desc))
    return order


def _require_output_only(node: object) -> None:
    if isinstance(node, BoundColumn):
        raise UnknownColumnError("with DISTINCT, ORDER BY may only use output columns")
    for child in children(node):
        _require_output_only(child)


def _check_grouped(node: object, group: list) -> None:
    if node in group or is_aggregate(node) or isinstance(node, OutColumn):
        return
    if isinstance(node, BoundColumn):
        raise GroupingError("column is neither aggregated nor in GROUP BY")
    for child in children(node):
        _check_grouped(child, group)


def _bind_query(plan_: Plan, tables: dict[str, Table]) -> _Bound:
    query = plan_.query
    scope = [(query.table, c.name) for c in _table(tables, query.table).columns]
    if query.join is not None:
        right = _table(tables, query.join.table)
        scope += [(query.join.table, c.name) for c in right.columns]
    resolve = _make_resolver(scope)
    where = bind(query.where, resolve) if query.where is not None else None
    on = bind(query.join.on, resolve) if query.join is not None else None
    group_by = [bind(g, resolve) for g in query.group_by]
    for node, label in ((where, "WHERE"), (on, "JOIN ON")):
        _no_aggregate(node, label)
    for g in group_by:
        _no_aggregate(g, "GROUP BY")
    items = _bind_items(query, scope, resolve)
    having = bind(query.having, resolve) if query.having is not None else None
    grouped = "group" in plan_.names
    order = _bind_order(query, items, resolve, grouped)
    if grouped:
        for node in [n for n, _ in items] + [having] + [n for n, _ in order]:
            if node is not None:
                _check_grouped(node, group_by)
    calls: list[Call] = []
    for node in [n for n, _ in items] + [having] + [n for n, _ in order]:
        if node is not None:
            collect_aggregates(node, calls)
    return _Bound(scope, where, on, group_by, having, items, order, calls)


def _truth(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TypeMismatchError("a predicate must be BOOL")
    return value


def _key(value: object) -> tuple:
    """Grouping/DISTINCT identity: NULL equals NULL, numbers equal numerically."""
    if value is None:
        return ("NULL",)
    if isinstance(value, bool):
        return ("B", value)
    if is_numeric(value):
        return ("N", value)
    return ("T", value)


def _stage_scan(st: _State, stage) -> None:
    st.rows = list(_table(st.tables, stage.payload).rows)


def _stage_join(st: _State, stage) -> None:
    clause = stage.payload
    right = _table(st.tables, clause.table)
    joined: list = []
    for left_row in st.rows:
        matched = False
        for right_row in right.rows:
            combined = left_row + right_row
            if _truth(evaluate(st.bound.on, combined)):
                joined.append(combined)
                matched = True
        if not matched and clause.kind == "LEFT":
            joined.append(left_row + [None] * len(right.columns))
    st.rows = joined


def _stage_filter(st: _State, stage) -> None:
    st.rows = [r for r in st.rows if _truth(evaluate(st.bound.where, r))]


def _stage_group(st: _State, stage) -> None:
    if not st.bound.group_by:
        st.groups = [list(st.rows)]  # one group, even for empty input
        return
    groups: dict[tuple, list] = {}
    for row in st.rows:
        key = tuple(_key(evaluate(g, row)) for g in st.bound.group_by)
        groups.setdefault(key, []).append(row)
    st.groups = list(groups.values())


def _group_aggs(calls: list[Call], rows: list) -> dict:
    aggs: dict = {}
    for call in calls:
        if call.star:
            aggs[call] = aggregate(call.name, rows, star=True)
        else:
            values = [evaluate(call.args[0], r) for r in rows]
            aggs[call] = aggregate(call.name, values)
    return aggs


def _stage_aggregate(st: _State, stage) -> None:
    calls = st.bound.calls
    st.units = [_Unit(rows[0] if rows else None, _group_aggs(calls, rows))
                for rows in st.groups or []]


def _units(st: _State) -> list[_Unit]:
    if st.units is None:
        st.units = [_Unit(r, None) for r in st.rows]
    return st.units


def _stage_having(st: _State, stage) -> None:
    st.units = [u for u in _units(st)
                if _truth(evaluate(st.bound.having, u.row, None, u.aggs))]


def _stage_project(st: _State, stage) -> None:
    items = st.bound.items
    st.out = [([evaluate(n, u.row, None, u.aggs) for n, _ in items], u)
              for u in _units(st)]


def _stage_distinct(st: _State, stage) -> None:
    seen: set[tuple] = set()
    kept = []
    for entry in st.out:
        key = tuple(_key(v) for v in entry[0])
        if key not in seen:
            seen.add(key)
            kept.append(entry)
    st.out = kept


def _cmp(a: object, b: object) -> int:
    if compare_lt(a, b):
        return -1
    return 1 if compare_lt(b, a) else 0


def _stage_sort(st: _State, stage) -> None:
    order = st.bound.order
    keys = [[evaluate(n, u.row, o, u.aggs) for n, _ in order] for o, u in st.out]
    idx = list(range(len(st.out)))
    for k in reversed(range(len(order))):  # stable passes, last key first
        present = [i for i in idx if keys[i][k] is not None]
        nulls = [i for i in idx if keys[i][k] is None]
        present.sort(key=functools.cmp_to_key(lambda a, b: _cmp(keys[a][k], keys[b][k])),
                     reverse=order[k][1])
        idx = present + nulls  # NULL last for both ASC and DESC
    st.out = [st.out[i] for i in idx]


def _stage_offset(st: _State, stage) -> None:
    st.out = st.out[stage.payload:]


def _stage_limit(st: _State, stage) -> None:
    st.out = st.out[:stage.payload]


_HANDLERS: dict[str, Callable[[_State, object], None]] = {
    "scan": _stage_scan,
    "join": _stage_join,
    "filter": _stage_filter,
    "group": _stage_group,
    "aggregate": _stage_aggregate,
    "having": _stage_having,
    "project": _stage_project,
    "distinct": _stage_distinct,
    "sort": _stage_sort,
    "offset": _stage_offset,
    "limit": _stage_limit,
}


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    state = _State(tables, _bind_query(plan, tables))
    for stage in plan:
        _HANDLERS[stage.name](state, stage)
    return Result([n for _, n in state.bound.items], [o for o, _ in state.out])


def execute(query: str, tables: dict[str, Table]) -> Result:
    return execute_plan(plan(parse(query)), tables)
