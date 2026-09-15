from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key

from .aggregate import AGGREGATE_NAMES, aggregate_value
from .errors import AggregateError, AmbiguousColumnError, GroupingError, TypeMismatchError, UnknownColumnError, UnknownFunctionError
from .expr import contains_aggregate, evaluate, expr_label
from .parser import BinaryOp, ColumnRef, FunctionCall, Query, SelectItem, Star, parse
from .planner import DistinctStage, FromStage, GroupStage, JoinStage, LimitStage, OrderStage, SelectStage, WhereStage, plan
from .value import compare_eq, compare_lt


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


def execute(query: str, tables: dict[str, object]) -> Result:
    ast = parse(query)
    pipeline = plan(ast)
    return execute_plan(pipeline, tables)


def execute_plan(plan_data: object, tables: dict[str, object]) -> Result:
    rows: list[dict[str, object]] = []
    columns: list[str] = []
    for stage in plan_data:
        if isinstance(stage, FromStage):
            rows = _from_stage(stage, tables)
        elif isinstance(stage, JoinStage):
            rows = _join_stage(rows, stage, tables)
        elif isinstance(stage, WhereStage):
            rows = _where_stage(rows, stage.predicate)
        elif isinstance(stage, GroupStage):
            rows = _group_stage(rows, stage)
        elif isinstance(stage, SelectStage):
            rows, columns = _select_stage(rows, stage.items)
        elif isinstance(stage, DistinctStage):
            rows = _distinct_stage(rows)
        elif isinstance(stage, OrderStage):
            rows = _order_stage(rows, stage.items)
        elif isinstance(stage, LimitStage):
            rows = _limit_stage(rows, stage.offset, stage.limit)
    if not columns:
        columns = _result_columns(rows)
    output: list[list[object]] = []
    for row in rows:
        output.append([row[name] for name in columns])
    return Result(columns, output)


def _from_stage(stage: FromStage, tables: dict[str, object]) -> list[dict[str, object]]:
    table = tables[stage.table]
    rows: list[dict[str, object]] = []
    for raw in table.rows:
        row: dict[str, object] = {"__tables__": {stage.table}, "__ambig__": set()}
        for i, col in enumerate(table.columns):
            value = raw[i]
            row[col.name] = value
            row[f"{stage.table}.{col.name}"] = value
        rows.append(row)
    return rows


def _join_stage(rows: list[dict[str, object]], stage: JoinStage, tables: dict[str, object]) -> list[dict[str, object]]:
    right_table = tables[stage.table]
    out: list[dict[str, object]] = []
    for left in rows:
        matches = 0
        for raw in right_table.rows:
            right = _row_for_table(stage.table, right_table, raw)
            combined = dict(left)
            combined.update(right)
            combined["__tables__"] = set(left.get("__tables__", set())) | {stage.table}
            combined["__ambig__"] = set(left.get("__ambig__", set())) | set(right.get("__ambig__", set()))
            if stage.kind == "INNER":
                if _predicate_true(evaluate(stage.on, combined)):
                    out.append(combined)
                    matches += 1
            else:
                if _predicate_true(evaluate(stage.on, combined)):
                    out.append(combined)
                    matches += 1
        if stage.kind == "LEFT" and matches == 0:
            right_null = _row_for_table(stage.table, right_table, [None for _ in right_table.columns])
            combined = dict(left)
            combined.update(right_null)
            combined["__tables__"] = set(left.get("__tables__", set())) | {stage.table}
            combined["__ambig__"] = set(left.get("__ambig__", set()))
            out.append(combined)
    return out


def _row_for_table(name: str, table: object, raw: list[object]) -> dict[str, object]:
    row: dict[str, object] = {"__tables__": {name}, "__ambig__": set()}
    for i, col in enumerate(table.columns):
        value = raw[i]
        row[col.name] = value
        row[f"{name}.{col.name}"] = value
    return row


def _where_stage(rows: list[dict[str, object]], predicate: object) -> list[dict[str, object]]:
    if contains_aggregate(predicate):
        raise AggregateError("aggregate not allowed in WHERE")
    return [row for row in rows if _predicate_true(evaluate(predicate, row))]


def _group_stage(rows: list[dict[str, object]], stage: GroupStage) -> list[dict[str, object]]:
    if stage.keys:
        key_set = {expr_signature(expr) for expr in stage.keys}
        for item in stage.select_items:
            if not contains_aggregate(item.expr) and expr_signature(item.expr) not in key_set:
                raise GroupingError("non-grouped select expression")
    if not stage.keys and not stage.aggregate_needed:
        return rows
    if not rows and not stage.keys:
        return [_aggregate_context(stage.select_items, [])]
    if not stage.keys:
        ctx = _aggregate_context(stage.select_items, rows)
        if stage.having is not None and not _having_ok(stage.having, ctx):
            return []
        return [ctx]
    groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in rows:
        key = tuple(_key_value(expr, row) for expr in stage.keys)
        groups.setdefault(key, []).append(row)
    out: list[dict[str, object]] = []
    for items in groups.values():
        ctx = _aggregate_context(stage.select_items, items)
        if stage.having is not None and not _predicate_true(evaluate(stage.having, ctx)):
            continue
        out.append(ctx)
    return out


def _aggregate_context(items: list[SelectItem], rows: list[dict[str, object]]) -> dict[str, object]:
    ctx: dict[str, object] = {"__source__": rows[0] if rows else {}}
    for item in items:
        name = _item_label(item)
        ctx[name] = _value_for_group(item.expr, rows)
    return ctx


def _value_for_group(expr: object, rows: list[dict[str, object]]) -> object:
    if isinstance(expr, FunctionCall) and expr.name.lower() in AGGREGATE_NAMES:
        return _aggregate_expr(expr, rows)
    if not rows:
        return None
    return evaluate(expr, rows[0])


def _aggregate_expr(expr: FunctionCall, rows: list[dict[str, object]]) -> object:
    name = expr.name.lower()
    if name == "count":
        if len(expr.args) == 1 and isinstance(expr.args[0], Star):
            return aggregate_value("count", [], star_count=len(rows))
        vals = []
        for row in rows:
            for arg in expr.args:
                value = evaluate(arg, row)
                if value is not None:
                    vals.append(value)
        return aggregate_value("count", vals)
    vals: list[object] = []
    for row in rows:
        for arg in expr.args:
            value = evaluate(arg, row)
            if value is not None:
                vals.append(value)
    return aggregate_value(name, vals)


def _select_stage(rows: list[dict[str, object]], items: list[SelectItem]) -> tuple[list[dict[str, object]], list[str]]:
    out: list[dict[str, object]] = []
    columns: list[str] = []
    for row in rows:
        proj: dict[str, object] = {"__source__": row}
        for item in items:
            if isinstance(item.expr, Star):
                for key in _visible_keys(row):
                    if key.startswith("__"):
                        continue
                    proj[key] = row[key]
                    columns.append(key)
            else:
                key = _item_label(item)
                if key in row and isinstance(item.expr, FunctionCall) and item.expr.name.lower() in AGGREGATE_NAMES:
                    proj[key] = row[key]
                else:
                    proj[key] = evaluate(item.expr, row)
                columns.append(key)
        out.append(proj)
    if not columns:
        columns = _result_columns(rows)
    return out, _unique_columns(columns)


def _distinct_stage(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[object, ...]] = set()
    out: list[dict[str, object]] = []
    for row in rows:
        key = tuple(row[name] for name in _visible_keys(row))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _order_stage(rows: list[dict[str, object]], items: list[tuple[object, str]]) -> list[dict[str, object]]:
    def cmp(a: dict[str, object], b: dict[str, object]) -> int:
        for expr, direction in items:
            av = _order_value(expr, a)
            bv = _order_value(expr, b)
            if av is None and bv is None:
                continue
            if av is None:
                return 1
            if bv is None:
                return -1
            if av == bv:
                continue
            lt = compare_lt(av, bv)
            if lt is None:
                raise TypeMismatchError("incompatible ORDER BY type")
            if lt:
                return -1 if direction == "ASC" else 1
            return 1 if direction == "ASC" else -1
        return 0

    return sorted(rows, key=cmp_to_key(cmp))


def _limit_stage(rows: list[dict[str, object]], offset: int | None, limit: int | None) -> list[dict[str, object]]:
    start = 0 if offset is None else offset
    end = len(rows) if limit is None else start + limit
    return rows[start:end]


def _predicate_true(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise TypeMismatchError("predicate must be logical")


def _order_value(expr: object, row: dict[str, object]) -> object:
    return evaluate(expr, row)


def _key_value(expr: object, row: dict[str, object]) -> object:
    return evaluate(expr, row)


def _visible_keys(row: dict[str, object]) -> list[str]:
    return [k for k in row.keys() if not k.startswith("__")]


def _result_columns(rows: list[dict[str, object]]) -> list[str]:
    if not rows:
        return []
    return _visible_keys(rows[0])


def _unique_columns(columns: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for name in columns:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _item_label(item: SelectItem) -> str:
    if item.alias is not None:
        return item.alias
    if isinstance(item.expr, ColumnRef) and item.expr.table is None:
        return item.expr.name
    if isinstance(item.expr, Star):
        return item.expr.table + ".*" if item.expr.table else "*"
    return expr_label(item.expr)


def _having_ok(expr: object | None, row: dict[str, object]) -> bool:
    if expr is None:
        return True
    return _predicate_true(evaluate(expr, row))


def expr_signature(expr: object) -> str:
    if isinstance(expr, ColumnRef):
        return f"{expr.table}.{expr.name}" if expr.table else expr.name
    if isinstance(expr, FunctionCall):
        return f"{expr.name}({','.join(expr_signature(a) for a in expr.args)})"
    if isinstance(expr, BinaryOp):
        return f"{expr_signature(expr.left)}{expr.op}{expr_signature(expr.right)}"
    if isinstance(expr, Star):
        return "*"
    return str(expr)
