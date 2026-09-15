"""Query execution engine."""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
import functools
from microdb.aggregate import evaluate_aggregate
from microdb.errors import (
    AmbiguousColumnError,
    GroupingError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownTableError,
)
from microdb.expr import (
    AggregateCall,
    ColumnRef,
    EvalContext,
    Expr,
    GroupEvalContext,
    RowEvalContext,
    eval_expr,
)
from microdb.parser import OrderItem, Query, SelectItem
from microdb.planner import Plan
from microdb.schema import Table
from microdb.value import compare_eq, compare_lt


@dataclasses.dataclass(frozen=True)
class Result:
    """Query result containing column names and rows."""

    columns: list[str]
    rows: list[list[object]]


def _make_resolver(
    cols: list[tuple[str, str]],
) -> Callable[[str | None, str], int]:
    def resolve(table: str | None, column: str) -> int:
        if table is not None:
            known_tables = {tbl for tbl, _ in cols}
            if table not in known_tables:
                raise UnknownTableError(f"Unknown table '{table}'")
            matches = [
                i for i, (tbl, c) in enumerate(cols) if tbl == table and c == column
            ]
            if not matches:
                raise UnknownColumnError(f"Unknown column '{table}.{column}'")
            return matches[0]
        matches = [i for i, (_, c) in enumerate(cols) if c == column]
        if len(matches) > 1:
            raise AmbiguousColumnError(f"Ambiguous column '{column}'")
        if not matches:
            raise UnknownColumnError(f"Unknown column '{column}'")
        return matches[0]

    return resolve


def _exec_join(
    left_cols: list[tuple[str, str]],
    left_rows: list[list[object]],
    join_type: str,
    t2: Table,
    t2_name: str,
    on_expr: Expr,
) -> tuple[list[tuple[str, str]], list[list[object]]]:
    right_cols = [(t2_name, col.name) for col in t2.columns]
    combined_cols = left_cols + right_cols
    resolver = _make_resolver(combined_cols)
    out_rows: list[list[object]] = []
    right_nulls = [None] * len(t2.columns)
    for l_row in left_rows:
        matched = False
        for r_row in t2.rows:
            cand = l_row + r_row
            pred = eval_expr(on_expr, RowEvalContext(cand, resolver))
            if pred is not None and not isinstance(pred, bool):
                raise TypeMismatchError("ON predicate must be boolean")
            if pred is True:
                out_rows.append(cand)
                matched = True
        if join_type == "LEFT" and not matched:
            out_rows.append(l_row + right_nulls)
    return combined_cols, out_rows


def _exec_from_and_join(
    query: Query, tables: dict[str, Table]
) -> tuple[list[tuple[str, str]], list[list[object]]]:
    t1_name = query.from_table
    if t1_name not in tables:
        raise UnknownTableError(f"Unknown table '{t1_name}'")
    t1 = tables[t1_name]
    cols = [(t1_name, col.name) for col in t1.columns]
    rows = [list(r) for r in t1.rows]
    if query.join is not None:
        t2_name = query.join.table
        if t2_name not in tables:
            raise UnknownTableError(f"Unknown table '{t2_name}'")
        cols, rows = _exec_join(
            cols, rows, query.join.type, tables[t2_name], t2_name, query.join.on
        )
    return cols, rows


def _exec_where(
    where_expr: Expr | None,
    cols: list[tuple[str, str]],
    rows: list[list[object]],
) -> list[list[object]]:
    if where_expr is None:
        return rows
    resolver = _make_resolver(cols)
    filtered: list[list[object]] = []
    for row in rows:
        pred = eval_expr(where_expr, RowEvalContext(row, resolver))
        if pred is not None and not isinstance(pred, bool):
            raise TypeMismatchError("WHERE predicate must be boolean")
        if pred is True:
            filtered.append(row)
    return filtered


def _cell_group_equal(a: object, b: object) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    return compare_eq(a, b) is True


def _key_equal(k1: tuple[object, ...], k2: tuple[object, ...]) -> bool:
    return len(k1) == len(k2) and all(
        _cell_group_equal(a, b) for a, b in zip(k1, k2)
    )


def _eval_group_aggregates(
    aggs: list[AggregateCall],
    g_rows: list[list[object]],
    resolver: Callable[[str | None, str], int],
) -> dict[AggregateCall, object]:
    agg_values: dict[AggregateCall, object] = {}
    row_count = len(g_rows)
    for call in aggs:
        if call.is_star:
            val = evaluate_aggregate(call.name, [], is_star=True, row_count=row_count)
        else:
            evaluated = [
                eval_expr(call.arg, RowEvalContext(r, resolver))  # type: ignore[arg-type]
                for r in g_rows
            ]
            val = evaluate_aggregate(
                call.name, evaluated, is_star=False, row_count=row_count
            )
        agg_values[call] = val
    return agg_values


def _exec_group_by_and_aggregate(
    query: Query,
    cols: list[tuple[str, str]],
    rows: list[list[object]],
    aggs: list[AggregateCall],
) -> list[GroupEvalContext]:
    resolver = _make_resolver(cols)
    groups: list[tuple[tuple[object, ...], list[list[object]]]] = []
    if query.group_by:
        for row in rows:
            key = tuple(
                eval_expr(e, RowEvalContext(row, resolver)) for e in query.group_by
            )
            found = False
            for g_key, g_rows in groups:
                if _key_equal(g_key, key):
                    g_rows.append(row)
                    found = True
                    break
            if not found:
                groups.append((key, [row]))
    else:
        groups.append(((), rows))
    contexts: list[GroupEvalContext] = []
    for g_key, g_rows in groups:
        agg_values = _eval_group_aggregates(aggs, g_rows, resolver)
        group_key_map = dict(zip(query.group_by, g_key))
        contexts.append(GroupEvalContext(group_key_map, agg_values))
    return contexts


def _exec_having(
    having_expr: Expr | None, contexts: list[GroupEvalContext]
) -> list[GroupEvalContext]:
    if having_expr is None:
        return contexts
    surviving: list[GroupEvalContext] = []
    for ctx in contexts:
        pred = eval_expr(having_expr, ctx)
        if pred is not None and not isinstance(pred, bool):
            raise TypeMismatchError("HAVING predicate must be boolean")
        if pred is True:
            surviving.append(ctx)
    return surviving


def _expand_select_items(
    items: list[SelectItem],
    cols: list[tuple[str, str]],
) -> list[tuple[Expr, str, str | None]]:
    expanded: list[tuple[Expr, str, str | None]] = []
    for item in items:
        if item.is_star:
            for tbl, col_name in cols:
                expanded.append((ColumnRef(tbl, col_name), col_name, None))
        elif item.table_star is not None:
            tbl_match = [c for t, c in cols if t == item.table_star]
            if not tbl_match:
                raise UnknownTableError(f"Unknown table '{item.table_star}'")
            for col_name in tbl_match:
                expanded.append(
                    (ColumnRef(item.table_star, col_name), col_name, None)
                )
        else:
            expr = item.expr
            assert expr is not None
            if item.alias is not None:
                name = item.alias
            elif isinstance(expr, ColumnRef) and expr.table is None:
                name = expr.column
            else:
                name = item.source_text
            expanded.append((expr, name, item.alias))
    return expanded


def _project_rows(
    expanded: list[tuple[Expr, str, str | None]],
    contexts: list[EvalContext],
) -> list[tuple[list[object], EvalContext]]:
    projected: list[tuple[list[object], EvalContext]] = []
    for ctx in contexts:
        row_vals = [eval_expr(expr, ctx) for expr, _, _ in expanded]
        projected.append((row_vals, ctx))
    return projected


def _exec_distinct(
    rows: list[tuple[list[object], EvalContext]],
) -> list[tuple[list[object], EvalContext]]:
    unique_rows: list[tuple[list[object], EvalContext]] = []
    for row_vals, ctx in rows:
        key = tuple(row_vals)
        if not any(_key_equal(key, tuple(existing[0])) for existing in unique_rows):
            unique_rows.append((row_vals, ctx))
    return unique_rows


class _OrderByContext(EvalContext):
    def __init__(
        self,
        output_row: list[object],
        alias_map: dict[str, int],
        base_ctx: EvalContext | None,
    ) -> None:
        self._output_row: list[object] = output_row
        self._alias_map: dict[str, int] = alias_map
        self._base_ctx: EvalContext | None = base_ctx

    def get_column(self, table: str | None, column: str) -> object:
        if table is None and column in self._alias_map:
            return self._output_row[self._alias_map[column]]
        if self._base_ctx is not None:
            return self._base_ctx.get_column(table, column)
        raise UnknownColumnError(f"Unknown column: '{column}'")

    def get_aggregate(self, call: AggregateCall) -> object:
        if self._base_ctx is not None:
            return self._base_ctx.get_aggregate(call)
        raise UnknownColumnError(f"Unknown aggregate in ORDER BY: {call.name}")

    def matches_group_key(self, expr: Expr) -> tuple[bool, object]:
        if self._base_ctx is not None:
            return self._base_ctx.matches_group_key(expr)
        return False, None


def _compare_sort_values(v1: object, v2: object, desc: bool) -> int:
    if v1 is None and v2 is None:
        return 0
    if v1 is None:
        return 1
    if v2 is None:
        return -1
    eq = compare_eq(v1, v2)
    if eq is True:
        return 0
    lt = compare_lt(v1, v2)
    if desc:
        return -1 if not lt else 1
    return -1 if lt else 1


def _sort_rows(
    rows: list[tuple[list[object], EvalContext]],
    order_items: list[OrderItem],
    alias_map: dict[str, int],
    is_distinct: bool,
) -> list[tuple[list[object], EvalContext]]:
    evaluated_orders: list[tuple[tuple[object, ...], tuple[list[object], EvalContext]]] = []
    for row_vals, ctx in rows:
        ob_ctx = _OrderByContext(
            row_vals, alias_map, None if is_distinct else ctx
        )
        keys = tuple(eval_expr(item.expr, ob_ctx) for item in order_items)
        evaluated_orders.append((keys, (row_vals, ctx)))

    def _cmp_rows(
        item1: tuple[tuple[object, ...], tuple[list[object], EvalContext]],
        item2: tuple[tuple[object, ...], tuple[list[object], EvalContext]],
    ) -> int:
        for (v1, v2), oi in zip(zip(item1[0], item2[0]), order_items):
            cmp = _compare_sort_values(v1, v2, oi.desc)
            if cmp != 0:
                return cmp
        return 0

    sorted_items = sorted(evaluated_orders, key=functools.cmp_to_key(_cmp_rows))
    return [item[1] for item in sorted_items]


def _exec_order_by(
    rows: list[tuple[list[object], EvalContext]],
    order_items: list[OrderItem],
    output_names: list[str],
    aliases: dict[str, int],
    is_distinct: bool,
) -> list[tuple[list[object], EvalContext]]:
    if not order_items:
        return rows
    alias_map = (
        {name: i for i, name in enumerate(output_names)}
        if is_distinct
        else aliases
    )
    return _sort_rows(rows, order_items, alias_map, is_distinct)


def _exec_slice(
    rows: list[list[object]], offset: int | None, limit: int | None
) -> list[list[object]]:
    if offset is not None:
        rows = rows[offset:]
    if limit is not None:
        rows = rows[:limit]
    return rows


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Convenience function to parse, plan and execute a query."""
    from microdb.parser import parse
    from microdb.planner import plan

    return execute_plan(plan(parse(query)), tables)


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    """Execute a planned query against a dictionary of tables."""
    query = plan.query
    cols, rows = _exec_from_and_join(query, tables)
    rows = _exec_where(query.where, cols, rows)
    expanded = _expand_select_items(query.select_items, cols)
    output_names = [name for _, name, _ in expanded]
    aliases = {alias: i for i, (_, _, alias) in enumerate(expanded) if alias is not None}
    aggs = [stage.aggregates for stage in plan if stage.name == "AGGREGATE"]
    is_grouped = bool(aggs) or bool(query.group_by) or query.having is not None
    if is_grouped:
        flattened_aggs = aggs[0] if aggs else []
        contexts = _exec_group_by_and_aggregate(query, cols, rows, flattened_aggs)
        contexts = _exec_having(query.having, contexts)  # type: ignore[assignment]
        eval_contexts: list[EvalContext] = contexts  # type: ignore[assignment]
    else:
        resolver = _make_resolver(cols)
        eval_contexts = [RowEvalContext(r, resolver) for r in rows]
    proj_rows = _project_rows(expanded, eval_contexts)
    if query.distinct:
        proj_rows = _exec_distinct(proj_rows)
    if query.order_by:
        proj_rows = _exec_order_by(
            proj_rows, query.order_by, output_names, aliases, query.distinct
        )
    raw_rows = [vals for vals, _ in proj_rows]
    raw_rows = _exec_slice(raw_rows, query.offset, query.limit)
    return Result(columns=output_names, rows=raw_rows)
