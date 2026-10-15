from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import functools

from microdb.aggregate import compute_aggregate, validate_aggregate_call
from microdb.errors import (
    AmbiguousColumnError,
    GroupingError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownTableError,
)
from microdb.expr import (
    RowSchema,
    SourceColumn,
    eval_expr,
    eval_predicate,
    eval_scalar_function,
    validate_scalar_call,
)
from microdb.parser import (
     COMPARE_OPS,
    AggregateCall,
    BinaryExpr,
    ColumnRef,
    Expr,
    ExprSelectItem,
    FuncCall,
    IsNullExpr,
    JoinClause,
    LiteralExpr,
    OrderItem,
    Query,
    SelectItem,
    StarSelectItem,
    UnaryExpr,
    parse,
)
from microdb.planner import Plan, plan
from microdb.schema import Table
from microdb.value import (
    and_,
    arith,
    compare,
    compare_eq,
    compare_lt,
    negate,
    not_,
    or_,
    type_of,
)


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclasses.dataclass(frozen=True)
class _ProjectedCol:
    output_name: str
    expr: Expr
    alias: str | None


def _key_part(val: object) -> tuple[str, object]:
    if val is None:
        return ("NULL", None)
    if isinstance(val, bool):
        return ("BOOL", val)
    if isinstance(val, (int, float)):
        return ("NUM", val)
    return ("TEXT", val)


def _row_key(values: Sequence[object]) -> tuple[tuple[str, object], ...]:
    return tuple(_key_part(v) for v in values)


def _expr_matches(e1: Expr, e2: Expr, schema: RowSchema) -> bool:
    if isinstance(e1, LiteralExpr) and isinstance(e2, LiteralExpr):
        return type_of(e1.value) == type_of(e2.value) and e1.value == e2.value
    if isinstance(e1, ColumnRef) and isinstance(e2, ColumnRef):
        return schema.resolve(e1.table, e1.name) == schema.resolve(e2.table, e2.name)
    if isinstance(e1, UnaryExpr) and isinstance(e2, UnaryExpr):
        return e1.op == e2.op and _expr_matches(e1.operand, e2.operand, schema)
    if isinstance(e1, BinaryExpr) and isinstance(e2, BinaryExpr):
        return (
            e1.op == e2.op
            and _expr_matches(e1.left, e2.left, schema)
            and _expr_matches(e1.right, e2.right, schema)
        )
    if isinstance(e1, IsNullExpr) and isinstance(e2, IsNullExpr):
        return e1.negated == e2.negated and _expr_matches(e1.operand, e2.operand, schema)
    if isinstance(e1, FuncCall) and isinstance(e2, FuncCall):
        return (
            e1.name.lower() == e2.name.lower()
            and len(e1.args) == len(e2.args)
            and all(_expr_matches(a, b, schema) for a, b in zip(e1.args, e2.args))
        )
    if isinstance(e1, AggregateCall) and isinstance(e2, AggregateCall):
        return (
            e1.name.lower() == e2.name.lower()
            and e1.is_star == e2.is_star
            and len(e1.args) == len(e2.args)
            and all(_expr_matches(a, b, schema) for a, b in zip(e1.args, e2.args))
        )
    return False


def _validate_row_expr(expr: Expr, schema: RowSchema) -> None:
    if isinstance(expr, ColumnRef):
        schema.resolve(expr.table, expr.name)
    elif isinstance(expr, UnaryExpr):
        _validate_row_expr(expr.operand, schema)
    elif isinstance(expr, BinaryExpr):
        _validate_row_expr(expr.left, schema)
        _validate_row_expr(expr.right, schema)
    elif isinstance(expr, IsNullExpr):
        _validate_row_expr(expr.operand, schema)
    elif isinstance(expr, FuncCall):
        for arg in expr.args:
            _validate_row_expr(arg, schema)


def _validate_group_expr(
    expr: Expr,
    group_by: Sequence[Expr],
    schema: RowSchema,
    projected: Sequence[_ProjectedCol] = (),
) -> None:
    if isinstance(expr, ColumnRef) and expr.table is None and projected:
        if _resolve_alias_index(expr.name, projected) is not None:
            return
    for g in group_by:
        if _expr_matches(expr, g, schema):
            return
    if isinstance(expr, AggregateCall):
        validate_aggregate_call(expr.name, len(expr.args), expr.is_star)
        for arg in expr.args:
            _validate_row_expr(arg, schema)
        return
    if isinstance(expr, LiteralExpr):
        return
    if isinstance(expr, ColumnRef):
        schema.resolve(expr.table, expr.name)
        raise GroupingError(
            f"Column {expr.source_text!r} must appear in GROUP BY or be aggregated"
        )
    if isinstance(expr, UnaryExpr):
        _validate_group_expr(expr.operand, group_by, schema, projected)
    elif isinstance(expr, BinaryExpr):
        _validate_group_expr(expr.left, group_by, schema, projected)
        _validate_group_expr(expr.right, group_by, schema, projected)
    elif isinstance(expr, IsNullExpr):
        _validate_group_expr(expr.operand, group_by, schema, projected)
    elif isinstance(expr, FuncCall):
        for arg in expr.args:
            _validate_group_expr(arg, group_by, schema, projected)


def _exec_from_join(
    from_name: str, join: JoinClause | None, tables: dict[str, Table]
) -> tuple[RowSchema, list[list[object]]]:
    if from_name not in tables:
        raise UnknownTableError(f"Unknown table {from_name!r}")
    left_tbl = tables[from_name]
    left_cols = [SourceColumn(from_name, c.name, c.type) for c in left_tbl.columns]
    if join is None:
        schema = RowSchema(left_cols, frozenset({from_name}))
        return schema, [list(r) for r in left_tbl.rows]

    if join.table not in tables:
        raise UnknownTableError(f"Unknown table {join.table!r}")
    right_tbl = tables[join.table]
    right_cols = [SourceColumn(join.table, c.name, c.type) for c in right_tbl.columns]
    schema = RowSchema(left_cols + right_cols, frozenset({from_name, join.table}))
    _validate_row_expr(join.on, schema)

    rows: list[list[object]] = []
    null_right: list[object] = [None] * len(right_tbl.columns)
    for l_row in left_tbl.rows:
        matched = False
        for r_row in right_tbl.rows:
            combined = list(l_row) + list(r_row)
            if eval_predicate(join.on, schema, combined):
                rows.append(combined)
                matched = True
        if join.join_type == "LEFT" and not matched:
            rows.append(list(l_row) + list(null_right))
    return schema, rows


def _expand_select_items(
    items: Sequence[SelectItem], schema: RowSchema
) -> list[_ProjectedCol]:
    expanded: list[_ProjectedCol] = []
    for item in items:
        if isinstance(item, StarSelectItem):
            if item.table is not None and item.table not in schema.valid_tables:
                raise UnknownTableError(f"Unknown table {item.table!r}")
            for col in schema.columns:
                if item.table is None or col.table == item.table:
                    ref = ColumnRef(table=col.table, name=col.name, source_text=col.name, bare=True)
                    expanded.append(_ProjectedCol(col.name, ref, None))
        else:
            expr = item.expr
            if item.alias is not None:
                out_name = item.alias
            elif isinstance(expr, ColumnRef) and expr.bare:
                out_name = expr.name
            else:
                out_name = expr.source_text
            expanded.append(_ProjectedCol(out_name, expr, item.alias))
    return expanded


def _eval_group_binary(
    expr: BinaryExpr,
    group_by: Sequence[Expr],
    group_keys: Sequence[object],
    group_rows: Sequence[Sequence[object]],
    schema: RowSchema,
    alias_lookup: dict[str, object] | None,
) -> object:
    left = _eval_group_expr(expr.left, group_by, group_keys, group_rows, schema, alias_lookup)
    right = _eval_group_expr(expr.right, group_by, group_keys, group_rows, schema, alias_lookup)
    if expr.op == "AND":
        return and_(left, right)  # type: ignore[arg-type]
    if expr.op == "OR":
        return or_(left, right)  # type: ignore[arg-type]
    if expr.op in COMPARE_OPS:
        return compare(expr.op, left, right)
    return arith(expr.op, left, right)


def _eval_group_expr(
    expr: Expr,
    group_by: Sequence[Expr],
    group_keys: Sequence[object],
    group_rows: Sequence[Sequence[object]],
    schema: RowSchema,
    alias_lookup: dict[str, object] | None = None,
) -> object:
    if isinstance(expr, ColumnRef) and expr.table is None and alias_lookup is not None:
        if expr.name in alias_lookup:
            return alias_lookup[expr.name]
    for idx, g_expr in enumerate(group_by):
        if _expr_matches(expr, g_expr, schema):
            return group_keys[idx]
    if isinstance(expr, AggregateCall):
        if expr.is_star:
            return compute_aggregate(expr.name, (), is_star=True, row_count=len(group_rows))
        vals = [eval_expr(expr.args[0], schema, r) for r in group_rows]
        return compute_aggregate(expr.name, vals, is_star=False, row_count=len(group_rows))
    if isinstance(expr, LiteralExpr):
        return expr.value
    if isinstance(expr, ColumnRef):
        schema.resolve(expr.table, expr.name)
        raise GroupingError(
            f"Column {expr.source_text!r} must appear in GROUP BY or be aggregated"
        )
    if isinstance(expr, UnaryExpr):
        val = _eval_group_expr(expr.operand, group_by, group_keys, group_rows, schema, alias_lookup)
        return not_(val) if expr.op == "NOT" else negate(val)  # type: ignore[arg-type]
    if isinstance(expr, IsNullExpr):
        val = _eval_group_expr(expr.operand, group_by, group_keys, group_rows, schema, alias_lookup)
        return (val is not None) if expr.negated else (val is None)
    if isinstance(expr, BinaryExpr):
        return _eval_group_binary(expr, group_by, group_keys, group_rows, schema, alias_lookup)
    if isinstance(expr, FuncCall):
        validate_scalar_call(expr.name, len(expr.args))
        args = [
            _eval_group_expr(a, group_by, group_keys, group_rows, schema, alias_lookup)
            for a in expr.args
        ]
        return eval_scalar_function(expr.name, args)
    raise TypeError(f"Unsupported expression: {expr!r}")


def _form_groups(
    rows: Sequence[list[object]], group_by: Sequence[Expr], schema: RowSchema
) -> list[tuple[tuple[object, ...], list[list[object]]]]:
    for g in group_by:
        _validate_row_expr(g, schema)
    if not group_by:
        return [((), list(rows))]
    groups_map: dict[tuple[tuple[str, object], ...], tuple[tuple[object, ...], list[list[object]]]] = {}
    for row in rows:
        raw_vals = tuple(eval_expr(g, schema, row) for g in group_by)
        k = _row_key(raw_vals)
        if k not in groups_map:
            groups_map[k] = (raw_vals, [row])
        else:
            groups_map[k][1].append(row)
    return list(groups_map.values())


def _resolve_alias_index(name: str, projected: Sequence[_ProjectedCol]) -> int | None:
    matches = [i for i, p in enumerate(projected) if p.alias == name]
    if len(matches) > 1:
        raise AmbiguousColumnError(f"Ambiguous alias {name!r}")
    return matches[0] if matches else None


def _resolve_distinct_col(
    ref: ColumnRef, projected: Sequence[_ProjectedCol], schema: RowSchema
) -> int:
    if ref.table is None:
        alias_idx = _resolve_alias_index(ref.name, projected)
        if alias_idx is not None:
            return alias_idx
        matches = [i for i, p in enumerate(projected) if p.output_name == ref.name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AmbiguousColumnError(f"Ambiguous output column {ref.name!r}")
        raise UnknownColumnError(f"Column {ref.name!r} not in SELECT DISTINCT list")
    target = schema.resolve(ref.table, ref.name)
    col_matches = [
        i
        for i, p in enumerate(projected)
        if isinstance(p.expr, ColumnRef)
        and schema.resolve(p.expr.table, p.expr.name) == target
    ]
    if len(col_matches) == 1:
        return col_matches[0]
    if len(col_matches) > 1:
        raise AmbiguousColumnError(f"Ambiguous column '{ref.table}.{ref.name}'")
    raise UnknownColumnError(f"Column '{ref.table}.{ref.name}' not in SELECT DISTINCT list")


def _validate_distinct_order_expr(
    expr: Expr, projected: Sequence[_ProjectedCol], schema: RowSchema
) -> None:
    if not isinstance(expr, ColumnRef):
        for p in projected:
            if _expr_matches(expr, p.expr, schema):
                return
    if isinstance(expr, LiteralExpr):
        return
    if isinstance(expr, ColumnRef):
        _resolve_distinct_col(expr, projected, schema)
        return
    if isinstance(expr, AggregateCall):
        raise UnknownColumnError(f"Expression {expr.source_text!r} not in SELECT DISTINCT list")
    if isinstance(expr, UnaryExpr):
        _validate_distinct_order_expr(expr.operand, projected, schema)
    elif isinstance(expr, BinaryExpr):
        _validate_distinct_order_expr(expr.left, projected, schema)
        _validate_distinct_order_expr(expr.right, projected, schema)
    elif isinstance(expr, IsNullExpr):
        _validate_distinct_order_expr(expr.operand, projected, schema)
    elif isinstance(expr, FuncCall):
        for arg in expr.args:
            _validate_distinct_order_expr(arg, projected, schema)


def _eval_distinct_order_expr(
    expr: Expr,
    out_row: Sequence[object],
    projected: Sequence[_ProjectedCol],
    schema: RowSchema,
) -> object:
    if not isinstance(expr, ColumnRef):
        for i, p in enumerate(projected):
            if _expr_matches(expr, p.expr, schema):
                return out_row[i]
    dummy_schema = RowSchema((), schema.valid_tables)

    def resolver(ref: ColumnRef) -> object:
        idx = _resolve_distinct_col(ref, projected, schema)
        return out_row[idx]

    return eval_expr(expr, dummy_schema, (), col_resolver=resolver)


def _apply_distinct_and_sort(
    out_rows: list[list[object]],
    order_by: Sequence[OrderItem],
    projected: Sequence[_ProjectedCol],
    schema: RowSchema,
) -> list[list[object]]:
    deduped = _deduplicate_rows(out_rows)
    if not order_by:
        return deduped
    for item in order_by:
        _validate_distinct_order_expr(item.expr, projected, schema)
    s_keys = [
        tuple(_eval_distinct_order_expr(o.expr, r, projected, schema) for o in order_by)
        for r in deduped
    ]
    return _sort_rows(deduped, s_keys, order_by)


def _compare_sort_keys(
    keys_a: Sequence[object],
    keys_b: Sequence[object],
    order_by: Sequence[OrderItem],
) -> int:
    for (va, vb), item in zip(zip(keys_a, keys_b), order_by):
        if va is None and vb is None:
            continue
        if va is None:
            return 1
        if vb is None:
            return -1
        if compare_eq(va, vb) is True:
            continue
        lt = compare_lt(va, vb)
        if item.ascending:
            return -1 if lt is True else 1
        return 1 if lt is True else -1
    return 0


def _sort_rows(
    out_rows: list[list[object]],
    sort_keys: list[tuple[object, ...]],
    order_by: Sequence[OrderItem],
) -> list[list[object]]:
    for col_idx in range(len(order_by)):
        non_null = [sk[col_idx] for sk in sort_keys if sk[col_idx] is not None]
        if non_null:
            first = non_null[0]
            compare_lt(first, first)
            for other in non_null[1:]:
                compare_lt(first, other)

    paired = list(zip(out_rows, sort_keys))
    paired.sort(
        key=functools.cmp_to_key(
            lambda a, b: _compare_sort_keys(a[1], b[1], order_by)
        )
    )
    return [p[0] for p in paired]


def _deduplicate_rows(rows: Sequence[list[object]]) -> list[list[object]]:
    seen: set[tuple[tuple[str, object], ...]] = set()
    result: list[list[object]] = []
    for row in rows:
        k = _row_key(row)
        if k not in seen:
            seen.add(k)
            result.append(row)
    return result


def _execute_grouped(
    query: Query,
    schema: RowSchema,
    working_rows: list[list[object]],
    projected: list[_ProjectedCol],
) -> list[list[object]]:
    groups = _form_groups(working_rows, query.group_by, schema)
    if query.having is not None:
        _validate_group_expr(query.having, query.group_by, schema)
    for p in projected:
        _validate_group_expr(p.expr, query.group_by, schema)

    kept_groups: list[tuple[tuple[object, ...], list[list[object]]]] = []
    for g_keys, g_rows in groups:
        if query.having is not None:
            pred = _eval_group_expr(query.having, query.group_by, g_keys, g_rows, schema)
            if pred is not None and not isinstance(pred, bool):
                raise TypeMismatchError(f"HAVING requires BOOL, got {type_of(pred)}")
            if pred is not True:
                continue
        kept_groups.append((g_keys, g_rows))

    out_rows: list[list[object]] = [
        [_eval_group_expr(p.expr, query.group_by, gk, gr, schema) for p in projected]
        for gk, gr in kept_groups
    ]
    if query.distinct:
        return _apply_distinct_and_sort(out_rows, query.order_by, projected, schema)

    if query.order_by:
        for item in query.order_by:
            _validate_group_expr(item.expr, query.group_by, schema, projected)
        s_keys = []
        for out_r, (gk, gr) in zip(out_rows, kept_groups):
            alias_map = {p.alias: out_r[i] for i, p in enumerate(projected) if p.alias is not None}
            s_keys.append(
                tuple(
                    _eval_group_expr(o.expr, query.group_by, gk, gr, schema, alias_map)
                    for o in query.order_by
                )
            )
        out_rows = _sort_rows(out_rows, s_keys, query.order_by)
    return out_rows


def _execute_ungrouped(
    query: Query,
    schema: RowSchema,
    working_rows: list[list[object]],
    projected: list[_ProjectedCol],
) -> list[list[object]]:
    for p in projected:
        _validate_row_expr(p.expr, schema)
    out_rows = [
        [eval_expr(p.expr, schema, r) for p in projected] for r in working_rows
    ]
    if query.distinct:
        return _apply_distinct_and_sort(out_rows, query.order_by, projected, schema)

    if query.order_by:
        for item in query.order_by:
            _validate_ungrouped_order_expr(item.expr, projected, schema)
        s_keys = []
        for out_r, in_r in zip(out_rows, working_rows):
            def resolver(ref: ColumnRef, _out: list[object] = out_r, _in: list[object] = in_r) -> object:
                if ref.table is None:
                    a_idx = _resolve_alias_index(ref.name, projected)
                    if a_idx is not None:
                        return _out[a_idx]
                return _in[schema.resolve(ref.table, ref.name)]

            s_keys.append(
                tuple(eval_expr(o.expr, schema, in_r, col_resolver=resolver) for o in query.order_by)
            )
        out_rows = _sort_rows(out_rows, s_keys, query.order_by)
    return out_rows


def _validate_ungrouped_order_expr(
    expr: Expr, projected: Sequence[_ProjectedCol], schema: RowSchema
) -> None:
    if isinstance(expr, ColumnRef):
        if expr.table is None:
            a_idx = _resolve_alias_index(expr.name, projected)
            if a_idx is not None:
                return
        schema.resolve(expr.table, expr.name)
    elif isinstance(expr, UnaryExpr):
        _validate_ungrouped_order_expr(expr.operand, projected, schema)
    elif isinstance(expr, BinaryExpr):
        _validate_ungrouped_order_expr(expr.left, projected, schema)
        _validate_ungrouped_order_expr(expr.right, projected, schema)
    elif isinstance(expr, IsNullExpr):
        _validate_ungrouped_order_expr(expr.operand, projected, schema)
    elif isinstance(expr, FuncCall):
        for arg in expr.args:
            _validate_ungrouped_order_expr(arg, projected, schema)


def execute_plan(query_plan: Plan, tables: dict[str, Table]) -> Result:
    query = query_plan.query
    schema, working_rows = _exec_from_join(query.from_table, query.join, tables)
    if query.where is not None:
        _validate_row_expr(query.where, schema)
        working_rows = [
            r for r in working_rows if eval_predicate(query.where, schema, r)
        ]
    projected = _expand_select_items(query.select_items, schema)
    if query_plan.is_grouped:
        out_rows = _execute_grouped(query, schema, working_rows, projected)
    else:
        out_rows = _execute_ungrouped(query, schema, working_rows, projected)
    if query.offset is not None:
        out_rows = out_rows[query.offset :]
    if query.limit is not None:
        out_rows = out_rows[: query.limit]
    return Result(columns=[p.output_name for p in projected], rows=out_rows)


def execute(query: str, tables: dict[str, Table]) -> Result:
    parsed = parse(query)
    query_plan = plan(parsed)
    return execute_plan(query_plan, tables)
