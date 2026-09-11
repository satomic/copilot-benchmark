"""Run a plan. Each helper corresponds to exactly one stage name."""

from __future__ import annotations

import dataclasses
import functools

from .aggregate import aggregate, check_arity
from .errors import UnknownColumnError, UnknownTableError
from .expr import Scope, as_condition, evaluate
from .parser import Call, ColumnRef, Expr, JoinClause, SelectItem, SortKey, Star
from .planner import Plan, plan
from .schema import Table
from .value import sort_key_lt

__all__ = ["Result", "execute_plan", "execute"]


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclasses.dataclass
class _Frame:
    """Rows, the scope that resolves names against them, and optional groups."""

    rows: list[list[object]]
    scope: Scope
    width: int
    groups: list[tuple[list[list[object]], dict[str, object]]] | None = None


def _scope_for(tables: list[Table]) -> tuple[Scope, int]:
    qualified: dict[tuple[str, str], int] = {}
    unqualified: dict[str, list[int]] = {}
    index = 0
    for table in tables:
        for col in table.columns:
            qualified[(table.name, col.name)] = index
            unqualified.setdefault(col.name, []).append(index)
            index += 1
    return Scope(qualified, unqualified, frozenset(t.name for t in tables)), index


def _lookup(tables: dict[str, Table], name: str) -> Table:
    if name not in tables:
        raise UnknownTableError(f"unknown table {name}")
    return tables[name]


def _marker(values: list[object] | tuple[object, ...]) -> tuple[object, ...]:
    """A hashable identity where NULL equals NULL and 1 does not equal True."""
    return tuple(("N",) if v is None else (type(v).__name__, v) for v in values)


def _do_join(
    frame: _Frame, clause: JoinClause, tables: dict[str, Table], left: Table
) -> _Frame:
    right = _lookup(tables, clause.table)
    scope, width = _scope_for([left, right])
    pad = len(right.columns)
    out: list[list[object]] = []
    for lrow in frame.rows:
        matched = False
        for rrow in right.rows:
            combined = lrow + rrow
            if as_condition(clause.on, combined, scope) is True:
                out.append(combined)
                matched = True
        if not matched and clause.kind == "LEFT":
            out.append(lrow + [None] * pad)
    return _Frame(out, scope, width)


def _do_group(frame: _Frame, keys: tuple[Expr, ...]) -> _Frame:
    """Group rows, preserving first-appearance order and treating NULL as equal."""
    if not keys:
        return _Frame(frame.rows, frame.scope, frame.width, [(list(frame.rows), {})])
    order: list[tuple[object, ...]] = []
    buckets: dict[tuple[object, ...], list[list[object]]] = {}
    for row in frame.rows:
        key = _marker([evaluate(k, row, frame.scope) for k in keys])
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    return _Frame(
        frame.rows, frame.scope, frame.width, [(buckets[k], {}) for k in order]
    )


def _do_aggregate(frame: _Frame, calls: dict[str, Call]) -> _Frame:
    groups = []
    for rows, _values in frame.groups or []:
        computed: dict[str, object] = {}
        for source, call in calls.items():
            check_arity(call.name, len(call.args))
            arg = call.args[0]
            if isinstance(arg, Star):
                computed[source] = aggregate(call.name, [], star_rows=len(rows))
            else:
                column = [evaluate(arg, row, frame.scope) for row in rows]
                computed[source] = aggregate(call.name, column)
        groups.append((rows, computed))
    return _Frame(frame.rows, frame.scope, frame.width, groups)


def _representative(rows: list[list[object]], width: int) -> list[object]:
    """A row for evaluating group keys. An empty group gets an all-NULL row."""
    return rows[0] if rows else [None] * width


def _expand_star(item: SelectItem, tables: list[Table]) -> list[tuple[str, Expr]]:
    out: list[tuple[str, Expr]] = []
    for table in tables:
        if item.star_table is not None and table.name != item.star_table:
            continue
        for col in table.columns:
            ref = ColumnRef(table.name, col.name, f"{table.name}.{col.name}")
            out.append((col.name, ref))
    if item.star_table is not None and not out:
        raise UnknownTableError(f"unknown table {item.star_table}")
    return out


def _output_name(item: SelectItem, expr: Expr) -> str:
    if item.alias is not None:
        return item.alias
    return expr.name if isinstance(expr, ColumnRef) else expr.source


def _projection_plan(
    items: tuple[SelectItem, ...], tables: list[Table]
) -> list[tuple[str, Expr]]:
    pairs: list[tuple[str, Expr]] = []
    for item in items:
        if item.expr is None:
            pairs.extend(_expand_star(item, tables))
        else:
            pairs.append((_output_name(item, item.expr), item.expr))
    return pairs


def _do_project(
    frame: _Frame, pairs: list[tuple[str, Expr]]
) -> list[list[object]]:
    rows: list[list[object]] = []
    if frame.groups is not None:
        for group_rows, values in frame.groups:
            base = _representative(group_rows, frame.width)
            rows.append([evaluate(e, base, frame.scope, values) for _, e in pairs])
    else:
        for row in frame.rows:
            rows.append([evaluate(e, row, frame.scope) for _, e in pairs])
    return rows


def _row_cmp(a: list[object], b: list[object], keys: list[tuple[int, bool]]) -> int:
    """Compare two rows across every sort key. NULL is last in both directions."""
    for index, descending in keys:
        av, bv = a[index], b[index]
        if av is None and bv is None:
            continue
        if av is None:
            return 1
        if bv is None:
            return -1
        if sort_key_lt(av, bv):
            return 1 if descending else -1
        if sort_key_lt(bv, av):
            return -1 if descending else 1
    return 0


def _do_sort(rows: list[list[object]], keys: list[tuple[int, bool]]) -> list[list[object]]:
    """One stable pass over all keys, so ties keep their incoming order."""
    ordered = list(rows)
    ordered.sort(key=functools.cmp_to_key(lambda a, b: _row_cmp(a, b, keys)))
    return ordered


def _distinct(rows: list[list[object]]) -> list[list[object]]:
    seen: set[tuple[object, ...]] = set()
    out: list[list[object]] = []
    for row in rows:
        key = _marker(row)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _sort_keys(
    order_by: tuple[SortKey, ...], names: list[str], distinct: bool
) -> tuple[list[tuple[int, bool]], list[tuple[str, Expr]]]:
    """Resolve sort keys to column indices, adding hidden columns when needed.

    An output alias wins over an input column of the same name, because ``names``
    is searched before anything is computed from the input rows.
    """
    keys: list[tuple[int, bool]] = []
    extra: list[tuple[str, Expr]] = []
    for key in order_by:
        expr = key.expr
        target = expr.name if isinstance(expr, ColumnRef) and expr.table is None else expr.source
        if target in names:
            keys.append((names.index(target), key.descending))
            continue
        if expr.source in names:
            keys.append((names.index(expr.source), key.descending))
            continue
        if distinct:
            raise UnknownColumnError(
                f"ORDER BY {expr.source} is not an output column of a DISTINCT query"
            )
        keys.append((len(names) + len(extra), key.descending))
        extra.append((expr.source, expr))
    return keys, extra


def execute_plan(plan_obj: Plan, tables: dict[str, Table]) -> Result:
    """Run every stage of ``plan_obj`` in the order the planner fixed."""
    query = plan_obj.query
    base = _lookup(tables, query.from_table)
    scope_tables = [base]
    scope, width = _scope_for(scope_tables)
    frame = _Frame(base.rows, scope, width)
    names: list[str] = []
    rows: list[list[object]] = []

    for stage in plan_obj.stages:
        payload = stage.payload
        if stage.name == "scan":
            continue
        if stage.name == "join":
            assert isinstance(payload, JoinClause)
            frame = _do_join(frame, payload, tables, base)
            scope_tables = [base, _lookup(tables, payload.table)]
        elif stage.name == "filter":
            kept = [r for r in frame.rows if as_condition(payload, r, frame.scope) is True]
            frame = _Frame(kept, frame.scope, frame.width)
        elif stage.name == "group":
            frame = _do_group(frame, payload or ())
        elif stage.name == "aggregate":
            frame = _do_aggregate(frame, payload or {})
        elif stage.name == "having":
            kept_groups = [
                (grows, values)
                for grows, values in frame.groups or []
                if as_condition(
                    payload, _representative(grows, frame.width), frame.scope, values
                )
                is True
            ]
            frame = _Frame(frame.rows, frame.scope, frame.width, kept_groups)
        elif stage.name == "project":
            pairs = _projection_plan(payload, scope_tables)
            names = [name for name, _ in pairs]
            keys, extra = _sort_keys(query.order_by, names, query.distinct)
            rows = _do_project(frame, pairs + extra)
            frame = _Frame(
                frame.rows,
                dataclasses.replace(
                    frame.scope, aliases={n: i for i, n in enumerate(names)}
                ),
                frame.width,
                frame.groups,
            )
            stage_keys = keys
        elif stage.name == "distinct":
            rows = _distinct(rows)
        elif stage.name == "sort":
            rows = _do_sort(rows, stage_keys)
        elif stage.name == "offset":
            rows = rows[payload:]
        elif stage.name == "limit":
            rows = rows[:payload]
    visible = len(names)
    return Result(names, [row[:visible] for row in rows])


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Parse, plan and run ``query``."""
    from .parser import parse

    return execute_plan(plan(parse(query)), tables)
