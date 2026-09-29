"""Query executor: runs a Plan against tables and produces a Result."""

import dataclasses
from typing import Any

from microdb.errors import (
    TypeMismatchError,
    AggregateError,
    GroupingError,
    UnknownColumnError,
    AmbiguousColumnError,
    UnknownTableError,
    MicroDBError,
)
from microdb.schema import Table
from microdb.expr import (
    EvalContext,
    evaluate,
    contains_aggregate,
    collect_aggregates,
)
from microdb.aggregate import eval_aggregate
from microdb.planner import (
    ScanStage,
    JoinStage,
    FilterStage,
    GroupByStage,
    SelectStage,
    DistinctStage,
    SortStage,
    OffsetStage,
    LimitStage,
)
from microdb.parser import (
    SelectExpr,
    Star,
    StarTable,
    ColumnRef,
    FunctionCall,
    BinaryOp,
    UnaryOp,
    IsNull,
    Literal,
    QualifiedColumnRef,
)
from microdb.value import compare_lt, type_of, compare_eq, is_numeric


@dataclasses.dataclass(frozen=True)
class Result:
    """Query execution result."""
    columns: list[str]
    rows: list[list[object]]


def execute_plan(plan: list[Any], tables: dict[str, Table]) -> Result:
    """Execute a plan against the given tables."""
    rows: list[list[object]] = []
    col_names: list[str] = []
    table_col_map: dict[str, dict[str, int]] = {}
    pre_col_names: list[str] = []
    pre_tcm: dict[str, dict[str, int]] = {}
    group_mode = False
    group_key_exprs: list[Any] = []
    groups: list[tuple[list[object], list[list[object]]]] = []
    for stage in plan:
        if isinstance(stage, ScanStage):
            rows, col_names, table_col_map = _exec_scan(stage, tables)
            pre_col_names, pre_tcm = list(col_names), _deep_copy_tcm(table_col_map)
        elif isinstance(stage, JoinStage):
            rows, col_names, table_col_map = _exec_join(
                stage, rows, col_names, table_col_map, tables)
            pre_col_names, pre_tcm = list(col_names), _deep_copy_tcm(table_col_map)
        elif isinstance(stage, FilterStage):
            if group_mode and groups:
                groups = _exec_having(stage, groups, col_names, table_col_map, tables)
            else:
                rows = _exec_where(stage, rows, col_names, table_col_map, tables)
        elif isinstance(stage, GroupByStage):
            group_key_exprs = stage.keys
            groups = _exec_group_by(stage, rows, col_names, table_col_map, tables)
            group_mode, rows = True, []
        elif isinstance(stage, SelectStage):
            pre_col_names, pre_tcm = list(col_names), _deep_copy_tcm(table_col_map)
            rows, col_names, table_col_map = _exec_select_dispatch(
                stage, rows, col_names, table_col_map, tables,
                group_mode, group_key_exprs, groups)
        elif isinstance(stage, DistinctStage):
            rows = _exec_distinct(rows)
        elif isinstance(stage, SortStage):
            rows = _exec_sort(stage, rows, col_names, pre_col_names, pre_tcm, tables)
        elif isinstance(stage, OffsetStage):
            rows = rows[stage.n:]
        elif isinstance(stage, LimitStage):
            rows = rows[:stage.n]
    return Result(columns=col_names, rows=rows)


def _deep_copy_tcm(
    tcm: dict[str, dict[str, int]]
) -> dict[str, dict[str, int]]:
    return {t: dict(cmap) for t, cmap in tcm.items()}


def _check_grouping(
    items: list[Any],
    group_key_exprs: list[Any],
    col_names: list[str],
    table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
) -> None:
    """Verify that non-aggregate SELECT items are in GROUP BY keys."""
    for item in items:
        if isinstance(item, (Star, StarTable)):
            continue
        if not isinstance(item, SelectExpr):
            continue
        expr = item.expr
        if _has_agg(expr):
            continue
        if not _is_group_key_expr(expr, group_key_exprs):
            raise GroupingError(
                f"not a GROUP BY expression and not an aggregate"
            )


def _is_group_key_expr(
    expr: object, keys: list[Any],
) -> bool:
    """Check if an expression matches one of the group key expressions."""
    for key in keys:
        if _expr_equal(expr, key):
            return True
    return False


def _expr_equal(a: object, b: object) -> bool:
    """Structural equality check for expression ASTs."""
    if type(a) is not type(b):
        return False
    if isinstance(a, Literal):
        return a.value == b.value
    if isinstance(a, ColumnRef):
        return a.name == b.name
    if isinstance(a, QualifiedColumnRef):
        return a.table == b.table and a.name == b.name
    if isinstance(a, FunctionCall):
        if a.name.upper() != b.name.upper():
            return False
        if len(a.args) != len(b.args):
            return False
        return all(_expr_equal(av, bv) for av, bv in zip(a.args, b.args))
    if isinstance(a, BinaryOp):
        return a.op == b.op and _expr_equal(a.left, b.left) and _expr_equal(a.right, b.right)
    if isinstance(a, UnaryOp):
        return a.op == b.op and _expr_equal(a.operand, b.operand)
    if isinstance(a, IsNull):
        return a.negated == b.negated and _expr_equal(a.operand, b.operand)
    return a == b


# ── Scan ───────────────────────────────────────────────────────────────

def _exec_scan(
    stage: ScanStage, tables: dict[str, Table]
) -> tuple[list[list[object]], list[str], dict[str, dict[str, int]]]:
    table = tables[stage.table]
    rows = [list(r) for r in table.rows]
    col_names = [c.name for c in table.columns]
    table_col_map = {
        stage.table: {c.name: i for i, c in enumerate(table.columns)}
    }
    return rows, col_names, table_col_map


# ── Join ───────────────────────────────────────────────────────────────

def _exec_join(
    stage: JoinStage,
    left_rows: list[list[object]],
    left_col_names: list[str],
    left_table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
) -> tuple[list[list[object]], list[str], dict[str, dict[str, int]]]:
    if stage.table not in tables:
        raise UnknownTableError(f"unknown table: {stage.table}")
    right_table = tables[stage.table]
    right_rows = [list(r) for r in right_table.rows]
    right_col_names = [c.name for c in right_table.columns]
    right_col_map = {c.name: i for i, c in enumerate(right_table.columns)}

    combined_names = left_col_names + right_col_names
    combined_tcm: dict[str, dict[str, int]] = {}
    for tbl, cmap in left_table_col_map.items():
        combined_tcm[tbl] = dict(cmap)
    combined_tcm[stage.table] = {
        c: i + len(left_col_names) for c, i in right_col_map.items()
    }

    base_col_names = combined_names
    base_tcm = combined_tcm
    ctx = EvalContext(
        col_names=base_col_names,
        table_col_map=base_tcm,
        tables=tables,
    )

    result_rows: list[list[object]] = []
    for li, lrow in enumerate(left_rows):
        matched = False
        for ri, rrow in enumerate(right_rows):
            combined = list(lrow) + list(rrow)
            ctx_row = ctx.with_row(combined)
            val = evaluate(stage.on, ctx_row)
            if val is True:
                result_rows.append(combined)
                matched = True
        if stage.join_type == "LEFT" and not matched:
            null_right = [None] * len(right_col_names)
            result_rows.append(list(lrow) + null_right)

    return result_rows, base_col_names, base_tcm


# ── WHERE ──────────────────────────────────────────────────────────────

def _exec_where(
    stage: FilterStage,
    rows: list[list[object]],
    col_names: list[str],
    table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
) -> list[list[object]]:
    if contains_aggregate(stage.predicate):
        raise AggregateError("WHERE cannot contain aggregate")

    ctx = EvalContext(
        col_names=col_names,
        table_col_map=table_col_map,
        tables=tables,
    )

    result: list[list[object]] = []
    for row in rows:
        ctx_row = ctx.with_row(row)
        val = evaluate(stage.predicate, ctx_row)
        if not isinstance(val, (bool, type(None))):
            raise TypeMismatchError(
                f"WHERE predicate must be boolean, got {type_of(val)}"
            )
        if val is True:
            result.append(row)
    return result


# ── GROUP BY ───────────────────────────────────────────────────────────

def _exec_group_by(
    stage: GroupByStage,
    rows: list[list[object]],
    col_names: list[str],
    table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
) -> list[tuple[list[object], list[list[object]]]]:
    ctx = EvalContext(
        col_names=col_names,
        table_col_map=table_col_map,
        tables=tables,
    )

    groups: list[tuple[list[object], list[list[object]]]] = []
    key_map: dict[tuple, int] = {}

    for row in rows:
        ctx_row = ctx.with_row(row)
        key_vals: list[object] = []
        for ke in stage.keys:
            v = evaluate(ke, ctx_row)
            key_vals.append(v)

        key_tuple = _null_key_tuple(key_vals)
        if key_tuple in key_map:
            gi = key_map[key_tuple]
            groups[gi][1].append(row)
        else:
            gi = len(groups)
            key_map[key_tuple] = gi
            groups.append((key_vals, [row]))

    return groups


def _null_key_tuple(key_vals: list[object]) -> tuple:
    return tuple(_null_sentinel(v) for v in key_vals)


def _null_sentinel(v: object) -> object:
    if v is None:
        return _NULL_SENTINEL
    return v


_NULL_SENTINEL = object()


# ── HAVING ─────────────────────────────────────────────────────────────

def _exec_having(
    stage: FilterStage,
    groups: list[tuple[list[object], list[list[object]]]],
    col_names: list[str],
    table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
) -> list[tuple[list[object], list[list[object]]]]:
    ctx = EvalContext(
        col_names=col_names,
        table_col_map=table_col_map,
        tables=tables,
    )

    result: list[tuple[list[object], list[list[object]]]] = []
    for key_vals, group_rows in groups:
        val = _eval_group_predicate(stage.predicate, group_rows, ctx)
        if val is True:
            result.append((key_vals, group_rows))
    return result


def _eval_group_predicate(
    expr: object, group_rows: list[list[object]], ctx: EvalContext
) -> object:
    """Evaluate an expression over a group, handling aggregates."""
    if isinstance(expr, FunctionCall) and expr.name.upper() in (
        "COUNT", "SUM", "AVG", "MIN", "MAX"
    ):
        return eval_aggregate(
            expr, group_rows,
            lambda e, r: evaluate(e, ctx.with_row(r)),
        )

    if isinstance(expr, BinaryOp):
        if expr.op == "AND":
            lv = _eval_group_predicate(expr.left, group_rows, ctx)
            if lv is False:
                return False
            rv = _eval_group_predicate(expr.right, group_rows, ctx)
            if lv is None or rv is None:
                return None if lv is not False and rv is not False else False
            return lv and rv
        if expr.op == "OR":
            lv = _eval_group_predicate(expr.left, group_rows, ctx)
            if lv is True:
                return True
            rv = _eval_group_predicate(expr.right, group_rows, ctx)
            if lv is None or rv is None:
                return None if lv is not True and rv is not True else True
            return lv or rv
        lv = _eval_group_predicate(expr.left, group_rows, ctx)
        rv = _eval_group_predicate(expr.right, group_rows, ctx)
        if expr.op in ("=", "<>", "<", "<=", ">", ">="):
            from microdb.expr import _compare
            return _compare(expr.op, lv, rv)
        from microdb.value import arith
        return arith(expr.op, lv, rv)

    if isinstance(expr, UnaryOp):
        val = _eval_group_predicate(expr.operand, group_rows, ctx)
        if expr.op == "NOT":
            from microdb.value import not_
            return not_(val)
        from microdb.value import negate
        return negate(val)

    if isinstance(expr, IsNull):
        val = _eval_group_predicate(expr.operand, group_rows, ctx)
        if expr.negated:
            return val is not None
        return val is None

    if group_rows:
        return evaluate(expr, ctx.with_row(group_rows[0]))
    return None


# ── SELECT (grouped) ───────────────────────────────────────────────────

def _exec_select_grouped(
    stage: SelectStage,
    groups: list[tuple[list[object], list[list[object]]]],
    group_key_exprs: list[Any],
    input_col_names: list[str],
    table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
) -> tuple[list[list[object]], list[str], dict[str, dict[str, int]]]:
    ctx = EvalContext(
        col_names=input_col_names,
        table_col_map=table_col_map,
        tables=tables,
    )

    out_col_names: list[str] = []
    for si_idx, item in enumerate(stage.items):
        out_col_names.append(_get_output_col_name(item, si_idx))

    result_rows: list[list[object]] = []
    for _key_vals, group_rows in groups:
        out_row = _eval_group_items(
            stage.items, group_rows, input_col_names,
            table_col_map, ctx,
        )
        result_rows.append(out_row)

    return result_rows, out_col_names, {}


def _eval_group_items(
    items: list[Any],
    group_rows: list[list[object]],
    input_col_names: list[str],
    table_col_map: dict[str, dict[str, int]],
    ctx: EvalContext,
) -> list[object]:
    """Evaluate SELECT items for one group."""
    dummy_row = [None] * len(input_col_names)
    out_row: list[object] = []
    for item in items:
        if isinstance(item, Star):
            first = group_rows[0] if group_rows else dummy_row
            ctx_row = ctx.with_row(first)
            for cn in input_col_names:
                out_row.append(evaluate(ColumnRef(cn), ctx_row))
            continue

        if isinstance(item, StarTable):
            tbl = item.table
            if tbl in table_col_map:
                first = group_rows[0] if group_rows else dummy_row
                ctx_row = ctx.with_row(first)
                for cn in table_col_map[tbl]:
                    out_row.append(evaluate(QualifiedColumnRef(tbl, cn), ctx_row))
            continue

        expr = item.expr
        if _has_agg(expr):
            val = _eval_group_expression(expr, group_rows, ctx)
            out_row.append(val)
        else:
            if group_rows:
                out_row.append(evaluate(expr, ctx.with_row(group_rows[0])))
            else:
                evaluate(expr, ctx.with_row(dummy_row))  # validate column refs
                out_row.append(None)

    return out_row


def _has_agg(expr: object) -> bool:
    if isinstance(expr, FunctionCall):
        if expr.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            return True
        return any(_has_agg(a) for a in expr.args)
    if isinstance(expr, BinaryOp):
        return _has_agg(expr.left) or _has_agg(expr.right)
    if isinstance(expr, UnaryOp):
        return _has_agg(expr.operand)
    if isinstance(expr, IsNull):
        return _has_agg(expr.operand)
    return False


def _eval_group_expression(
    expr: object,
    group_rows: list[list[object]],
    ctx: EvalContext,
) -> object:
    if isinstance(expr, FunctionCall) and expr.name.upper() in (
        "COUNT", "SUM", "AVG", "MIN", "MAX"
    ):
        return eval_aggregate(
            expr, group_rows,
            lambda e, r: evaluate(e, ctx.with_row(r)),
        )

    if isinstance(expr, FunctionCall):
        evaled_args = [
            _eval_group_expression(a, group_rows, ctx)
            for a in expr.args
        ]
        from microdb.expr import _eval_function
        fc = FunctionCall(expr.name, evaled_args)
        return _eval_function(fc, ctx)

    if isinstance(expr, BinaryOp):
        lv = _eval_group_expression(expr.left, group_rows, ctx)
        rv = _eval_group_expression(expr.right, group_rows, ctx)
        if expr.op == "AND":
            from microdb.value import and_
            return and_(lv, rv)
        if expr.op == "OR":
            from microdb.value import or_
            return or_(lv, rv)
        if expr.op in ("=", "<>", "<", "<=", ">", ">="):
            from microdb.expr import _compare
            return _compare(expr.op, lv, rv)
        from microdb.value import arith
        return arith(expr.op, lv, rv)

    if isinstance(expr, UnaryOp):
        val = _eval_group_expression(expr.operand, group_rows, ctx)
        if expr.op == "NOT":
            from microdb.value import not_
            return not_(val)
        from microdb.value import negate
        return negate(val)

    if isinstance(expr, IsNull):
        val = _eval_group_expression(expr.operand, group_rows, ctx)
        if expr.negated:
            return val is not None
        return val is None

    if group_rows:
        return evaluate(expr, ctx.with_row(group_rows[0]))
    return None


# ── SELECT (per row, no aggregates) ────────────────────────────────────

def _exec_select_per_row(
    stage: SelectStage,
    rows: list[list[object]],
    col_names: list[str],
    table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
) -> tuple[list[list[object]], list[str], dict[str, dict[str, int]]]:
    ctx = EvalContext(
        col_names=col_names,
        table_col_map=table_col_map,
        tables=tables,
    )

    out_col_names: list[str] = []
    for si_idx, item in enumerate(stage.items):
        out_col_names.append(_get_output_col_name(item, si_idx))

    result_rows: list[list[object]] = []
    # Validate column references even when no rows (e.g. empty join result)
    # by evaluating against a dummy row.
    dummy_row = [None] * len(col_names)
    for row in rows or [dummy_row]:
        is_dummy = row is dummy_row
        ctx_row = ctx.with_row(row)
        out_row: list[object] = []
        for item in stage.items:
            if isinstance(item, Star):
                for cn in col_names:
                    out_row.append(evaluate(ColumnRef(cn), ctx_row))
                continue
            if isinstance(item, StarTable):
                tbl = item.table
                if tbl in table_col_map:
                    for cn in table_col_map[tbl]:
                        out_row.append(
                            evaluate(QualifiedColumnRef(tbl, cn), ctx_row)
                        )
                continue
            out_row.append(evaluate(item.expr, ctx_row))
        if not is_dummy:
            result_rows.append(out_row)

    return result_rows, out_col_names, {}


def _exec_select_dispatch(
    stage: SelectStage,
    rows: list[list[object]],
    col_names: list[str],
    table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
    group_mode: bool,
    group_key_exprs: list[Any],
    groups: list[tuple[list[object], list[list[object]]]],
) -> tuple[list[list[object]], list[str], dict[str, dict[str, int]]]:
    """Dispatch to the appropriate SELECT execution path."""
    if group_mode:
        _check_grouping(stage.items, group_key_exprs,
                        col_names, table_col_map, tables)
    if group_mode and groups:
        return _exec_select_grouped(
            stage, groups, group_key_exprs,
            col_names, table_col_map, tables,
        )
    if group_mode or contains_aggregate_in_items(stage.items):
        agg_groups = [([], list(rows))]
        return _exec_select_grouped(
            stage, agg_groups, [],
            col_names, table_col_map, tables,
        )
    return _exec_select_per_row(
        stage, rows, col_names, table_col_map, tables,
    )


def _get_output_col_name(item: Any, idx: int) -> str:
    if isinstance(item, Star):
        return "*"
    if isinstance(item, StarTable):
        return f"{item.table}.*"
    if item.alias:
        return item.alias
    return _expr_to_str(item.expr)


def _expr_to_str(expr: object) -> str:
    if isinstance(expr, Literal):
        v = expr.value
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, str):
            return f"'{v}'"
        return str(v)

    if isinstance(expr, ColumnRef):
        return expr.name

    if isinstance(expr, QualifiedColumnRef):
        return f"{expr.table}.{expr.name}"

    if isinstance(expr, FunctionCall):
        args = ", ".join(_expr_to_str(a) for a in expr.args)
        return f"{expr.name}({args})"

    if isinstance(expr, Star):
        return "*"

    if isinstance(expr, BinaryOp):
        left = _expr_to_str(expr.left)
        right = _expr_to_str(expr.right)
        return f"{left} {expr.op} {right}"

    if isinstance(expr, UnaryOp):
        if expr.op == "NOT":
            return f"NOT {_expr_to_str(expr.operand)}"
        return f"-{_expr_to_str(expr.operand)}"

    if isinstance(expr, IsNull):
        base = _expr_to_str(expr.operand)
        if expr.negated:
            return f"{base} IS NOT NULL"
        return f"{base} IS NULL"

    return str(expr)


# ── DISTINCT ───────────────────────────────────────────────────────────

def _exec_distinct(rows: list[list[object]]) -> list[list[object]]:
    seen: set[tuple] = set()
    result: list[list[object]] = []
    for row in rows:
        key = tuple(_null_sentinel(v) for v in row)
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


# ── SORT ───────────────────────────────────────────────────────────────

def _exec_sort(
    stage: SortStage,
    rows: list[list[object]],
    col_names: list[str],
    pre_select_col_names: list[str],
    pre_select_table_col_map: dict[str, dict[str, int]],
    tables: dict[str, Table],
) -> list[list[object]]:
    if not rows:
        return rows

    indices = list(range(len(rows)))
    # Try output columns first; fall back to input columns
    ctx = EvalContext(
        col_names=col_names,
        table_col_map={},
        tables=tables,
    )
    input_ctx = EvalContext(
        col_names=pre_select_col_names,
        table_col_map=pre_select_table_col_map,
        tables=tables,
    )

    def _sort_key(idx: int) -> tuple:
        row = rows[idx]
        key_vals: list[object] = []
        for expr, asc in stage.keys:
            v = _sort_eval(expr, row, ctx, input_ctx)
            key_vals.append((v, asc))
        return _make_sort_tuple(key_vals)

    indices.sort(key=_sort_key)
    return [rows[i] for i in indices]


def _sort_eval(
    expr: object,
    row: list[object],
    out_ctx: EvalContext,
    in_ctx: EvalContext,
) -> object:
    """Evaluate a sort key expression, trying output then input context."""
    from microdb.expr import _resolve_column
    # Try output columns first
    if isinstance(expr, ColumnRef):
        try:
            return evaluate(expr, out_ctx.with_row(row))
        except UnknownColumnError:
            pass
        # Fall back to input columns
        return evaluate(expr, in_ctx.with_row(row))
    return evaluate(expr, out_ctx.with_row(row))


def _make_sort_tuple(values: list[tuple[object, bool]]) -> tuple:
    """Create a sort key tuple from values.

    NULL sorts after every non-NULL value, in both ASC and DESC.
    """
    result: list[object] = []
    for v, asc in values:
        if v is None:
            result.append((1,))
        elif isinstance(v, bool):
            result.append((0, int(not v)) if not asc else (0, int(v)))
        elif isinstance(v, (int, float)):
            result.append((0, -v)) if not asc else result.append((0, v))
        elif isinstance(v, str):
            if asc:
                result.append((0, v))
            else:
                result.append((0, _reverse_str(v)))
        else:
            result.append((0, v))
    return tuple(result)


def _reverse_str(s: str) -> str:
    """Produce a string that reverses str comparison via character inversion."""
    return "".join(chr(0x10FFFF - ord(c)) for c in s)


def contains_aggregate_in_items(items: list[Any]) -> bool:
    for item in items:
        if isinstance(item, (Star, StarTable)):
            continue
        if _has_agg(item.expr):
            return True
    return False