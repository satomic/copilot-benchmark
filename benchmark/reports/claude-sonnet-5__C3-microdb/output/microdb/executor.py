"""Executor: run a validated Plan against concrete tables, producing a Result."""

from __future__ import annotations

import dataclasses
import functools

from microdb import value as V
from microdb.aggregate import evaluate_with_aggregates
from microdb.errors import UnknownColumnError, UnknownTableError
from microdb.expr import as_bool_or_null, contains_column_ref, eval_expr, eval_predicate, substitute_aliases
from microdb.parser import ColumnRef, Query, Star
from microdb.planner import Plan
from microdb.schema import Table


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list
    rows: list


def _get_table(tables: dict, name: str) -> Table:
    if name not in tables:
        raise UnknownTableError(f"unknown table: {name!r}")
    return tables[name]


def _build_from(query: Query, tables: dict) -> tuple:
    left = _get_table(tables, query.from_table)
    schema = [(query.from_table, c.name) for c in left.columns]
    rows = [list(r) for r in left.rows]
    if query.join is not None:
        schema, rows = _do_join(query.join, tables, schema, rows)
    return schema, rows


def _do_join(join: object, tables: dict, left_schema: list, left_rows: list) -> tuple:
    right = _get_table(tables, join.table)
    right_schema = [(join.table, c.name) for c in right.columns]
    right_rows = [list(r) for r in right.rows]
    combined_schema = left_schema + right_schema
    out_rows = []
    for lrow in left_rows:
        matched = False
        for rrow in right_rows:
            combo = lrow + rrow
            if eval_predicate(join.on, combined_schema, combo) is True:
                out_rows.append(combo)
                matched = True
        if join.kind == "LEFT" and not matched:
            out_rows.append(lrow + [None] * len(right_schema))
    return combined_schema, out_rows


def _apply_where(where: object, schema: list, rows: list) -> list:
    return [r for r in rows if eval_predicate(where, schema, r) is True]


def _build_groups(group_by_exprs: list, schema: list, rows: list) -> list:
    if not group_by_exprs:
        return [rows]
    groups: dict = {}
    order: list = []
    for row in rows:
        key = tuple(eval_expr(g, schema, row) for g in group_by_exprs)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    return [groups[k] for k in order]


def _filter_having(having: object, schema: list, groups: list, group_by: list) -> list:
    if having is None:
        return groups
    kept = []
    for g in groups:
        val = as_bool_or_null(evaluate_with_aggregates(having, schema, g, group_by))
        if val is True:
            kept.append(g)
    return kept


def _expand_star_items(select_items: list, schema: list) -> list:
    expanded = []
    valid_tables = {t for t, _ in schema if t is not None}
    for item in select_items:
        if isinstance(item.expr, Star):
            if item.expr.table is None:
                indices = list(range(len(schema)))
            else:
                if item.expr.table not in valid_tables:
                    raise UnknownTableError(f"unknown table: {item.expr.table!r}")
                indices = [i for i, (t, _) in enumerate(schema) if t == item.expr.table]
            for i in indices:
                name = schema[i][1]
                expanded.append((name, ColumnRef(schema[i][0], name, 0, 0)))
        else:
            expanded.append((item.default_name, item.expr))
    return expanded


def _select_rows(query: Query, schema: list, rows: list) -> tuple:
    expanded = _expand_star_items(query.select_items, schema)
    out_cols = [name for name, _ in expanded]
    entries = []
    for row in rows:
        out_row = [eval_expr(expr, schema, row) for _, expr in expanded]
        fallback = (lambda e, schema=schema, row=row: eval_expr(e, schema, row))
        entries.append((out_row, fallback))
    return out_cols, entries


def _select_grouped(query: Query, schema: list, groups: list) -> tuple:
    out_cols = [item.default_name for item in query.select_items]
    entries = []
    for g in groups:
        out_row = [evaluate_with_aggregates(item.expr, schema, g, query.group_by) for item in query.select_items]
        fallback = (lambda e, schema=schema, g=g, gb=query.group_by: evaluate_with_aggregates(e, schema, g, gb))
        entries.append((out_row, fallback))
    return out_cols, entries


def _dedupe(entries: list) -> list:
    seen: set = set()
    out = []
    for row, _ in entries:
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            out.append((row, None))
    return out


def _build_alias_map(out_cols: list, row: list) -> dict:
    alias_map: dict = {}
    for name, val in zip(out_cols, row):
        if name not in alias_map:
            alias_map[name] = val
    return alias_map


def _eval_order_value(expr: object, alias_map: dict, fallback: object) -> object:
    substituted = substitute_aliases(expr, alias_map)
    if fallback is not None:
        return fallback(substituted)
    if contains_column_ref(substituted):
        raise UnknownColumnError("ORDER BY may only reference output columns when DISTINCT is present")
    return eval_expr(substituted, [], [])


def _cmp_single(a: object, b: object, desc: bool) -> int:
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    if V.compare_eq(a, b):
        return 0
    base = -1 if V.compare_lt(a, b) else 1
    return -base if desc else base


def _sort_entries(order_by: list, out_cols: list, entries: list) -> list:
    keyed = []
    for entry in entries:
        row, fallback = entry
        alias_map = _build_alias_map(out_cols, row)
        vals = [_eval_order_value(item.expr, alias_map, fallback) for item in order_by]
        keyed.append((vals, entry))

    def cmp(a: tuple, b: tuple) -> int:
        for i, item in enumerate(order_by):
            c = _cmp_single(a[0][i], b[0][i], item.desc)
            if c != 0:
                return c
        return 0

    keyed.sort(key=functools.cmp_to_key(cmp))
    return [e for _, e in keyed]


def _apply_offset_limit(entries: list, offset: object, limit: object) -> list:
    if offset is not None:
        entries = entries[offset:]
    if limit is not None:
        entries = entries[:limit]
    return entries


def execute_plan(plan: Plan, tables: dict) -> Result:
    """Execute a validated Plan against concrete tables, producing a Result."""
    query = plan.query
    schema, rows = _build_from(query, tables)
    if query.where is not None:
        rows = _apply_where(query.where, schema, rows)
    grouping_active = any(s.name == "group_by" for s in plan.stages)
    if grouping_active:
        groups = _build_groups(query.group_by, schema, rows)
        groups = _filter_having(query.having, schema, groups, query.group_by)
        out_cols, entries = _select_grouped(query, schema, groups)
    else:
        out_cols, entries = _select_rows(query, schema, rows)
    if query.distinct:
        entries = _dedupe(entries)
    if query.order_by:
        entries = _sort_entries(query.order_by, out_cols, entries)
    entries = _apply_offset_limit(entries, query.offset, query.limit)
    return Result(out_cols, [row for row, _ in entries])
