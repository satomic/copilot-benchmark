"""Plan execution and the public execute() entry point."""

from __future__ import annotations

import dataclasses
import functools

from microdb.aggregate import eval_aggregate
from microdb.errors import GroupingError, UnknownTableError
from microdb.expr import (
    EvalCtx,
    _check_arity,
    bind_expr,
    collect_aggregates,
    eval_expr,
    eval_predicate,
    expr_equal,
    has_aggregate,
    item_source,
    walk_children,
)
from microdb.parser import Call, ColumnRef, Literal, SelectItem, Star
from microdb.planner import (
    DistinctStage,
    FromStage,
    GroupStage,
    HavingStage,
    JoinStage,
    LimitStage,
    OffsetStage,
    OrderStage,
    Plan,
    SelectStage,
    WhereStage,
)
from microdb.schema import Table
from microdb.value import distinct_canon, group_canon


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclasses.dataclass
class _Group:
    key: tuple[object, ...]
    rows: list[list[object]]


@dataclasses.dataclass
class _Frame:
    col_tables: list[str]
    col_names: list[str]
    rows: list[list[object]]
    groups: list[_Group] | None = None
    out_names: list[str] | None = None
    out_rows: list[list[object]] | None = None
    in_rows: list[list[object]] | None = None
    group_aggs: list[dict[int, object]] | None = None
    group_rowsets: list[list[list[object]]] | None = None
    group_exprs: tuple[object, ...] = ()
    distinct: bool = False


def execute(query: str, tables: dict[str, Table]) -> Result:
    from microdb.parser import parse
    from microdb.planner import plan as make_plan

    return execute_plan(make_plan(parse(query)), tables)


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    frame = _Frame([], [], [])
    for stage in plan.stages:
        _run_stage(stage, tables, frame)
    names = frame.out_names if frame.out_names is not None else list(frame.col_names)
    rows = frame.out_rows if frame.out_rows is not None else frame.rows
    return Result(list(names), [list(r) for r in rows])


def _run_stage(stage: object, tables: dict[str, Table], frame: _Frame) -> None:
    if isinstance(stage, FromStage):
        _exec_from(stage, tables, frame)
    elif isinstance(stage, JoinStage):
        _exec_join(stage, tables, frame)
    elif isinstance(stage, WhereStage):
        _exec_where(stage.pred, frame)
    elif isinstance(stage, GroupStage):
        _exec_group(stage.keys, frame)
    elif isinstance(stage, HavingStage):
        _exec_having(stage.pred, frame)
    elif isinstance(stage, SelectStage):
        _exec_select(stage.items, frame)
    elif isinstance(stage, DistinctStage):
        _exec_distinct(frame)
    elif isinstance(stage, OrderStage):
        _exec_order(stage.items, frame)
    elif isinstance(stage, OffsetStage):
        _slice_rows(frame, stage.count, None)
    elif isinstance(stage, LimitStage):
        _slice_rows(frame, 0, stage.count)


def _exec_from(stage: FromStage, tables: dict[str, Table], frame: _Frame) -> None:
    table = _load(tables, stage.table)
    frame.col_tables = [stage.table] * len(table.columns)
    frame.col_names = [c.name for c in table.columns]
    frame.rows = [list(r) for r in table.rows]


def _load(tables: dict[str, Table], name: str) -> Table:
    if name not in tables:
        raise UnknownTableError(name)
    return tables[name]


def _exec_join(stage: JoinStage, tables: dict[str, Table], frame: _Frame) -> None:
    right = _load(tables, stage.table)
    r_tables = [stage.table] * len(right.columns)
    r_names = [c.name for c in right.columns]
    r_rows = [list(r) for r in right.rows]
    r_width = len(right.columns)
    left_rows = frame.rows
    combined_t = frame.col_tables + r_tables
    combined_n = frame.col_names + r_names
    out: list[list[object]] = []
    for lrow in left_rows:
        matched = _join_matches(stage, lrow, r_rows, combined_t, combined_n, out)
        if not matched and stage.kind == "LEFT":
            out.append(list(lrow) + [None] * r_width)
    frame.col_tables = combined_t
    frame.col_names = combined_n
    frame.rows = out


def _join_matches(
    stage: JoinStage,
    lrow: list[object],
    r_rows: list[list[object]],
    tables: list[str],
    names: list[str],
    out: list[list[object]],
) -> bool:
    matched = False
    for rrow in r_rows:
        row = list(lrow) + list(rrow)
        ctx = EvalCtx(tables, names, row)
        if eval_predicate(stage.on, ctx) is True:
            out.append(row)
            matched = True
    return matched


def _exec_where(pred: object, frame: _Frame) -> None:
    kept: list[list[object]] = []
    for row in frame.rows:
        ctx = EvalCtx(frame.col_tables, frame.col_names, row)
        if eval_predicate(pred, ctx) is True:
            kept.append(row)
    frame.rows = kept


def _exec_group(keys: tuple[object, ...], frame: _Frame) -> None:
    frame.group_exprs = keys
    if not keys:
        frame.groups = [_Group((), list(frame.rows))]
        return
    order: list[tuple[object, ...]] = []
    groups: dict[tuple[object, ...], _Group] = {}
    for row in frame.rows:
        ctx = EvalCtx(frame.col_tables, frame.col_names, row)
        kv = tuple(eval_expr(k, ctx) for k in keys)
        ck = tuple(group_canon(v) for v in kv)
        if ck not in groups:
            groups[ck] = _Group(kv, [row])
            order.append(ck)
        else:
            groups[ck].rows.append(row)
    frame.groups = [groups[k] for k in order]


def _exec_having(pred: object, frame: _Frame) -> None:
    if frame.groups is None:
        _exec_where(pred, frame)
        return
    kept: list[_Group] = []
    for g in frame.groups:
        aggs = _aggs_for([pred], g, frame)
        ctx = _group_ctx(g, frame, aggs)
        if eval_predicate(pred, ctx) is True:
            kept.append(g)
    frame.groups = kept


def _exec_select(items: tuple[SelectItem, ...], frame: _Frame) -> None:
    expanded = _expand_stars(items, frame)
    if frame.groups is not None:
        _select_groups(expanded, frame)
    else:
        _select_rows(expanded, frame)


def _expand_stars(items: tuple[SelectItem, ...], frame: _Frame) -> list[SelectItem]:
    out: list[SelectItem] = []
    for item in items:
        val = item.value
        if not isinstance(val, Star):
            out.append(item)
            continue
        any_col = False
        for t, n in zip(frame.col_tables, frame.col_names):
            if val.table is not None and t != val.table:
                continue
            any_col = True
            out.append(SelectItem(ColumnRef(n, t, val.offset, n), None))
        if val.table is not None and not any_col:
            raise UnknownTableError(val.table)
    return out


def _select_rows(items: list[SelectItem], frame: _Frame) -> None:
    for item in items:
        if has_aggregate(item.value):
            raise GroupingError("aggregate without grouping")
    names = [_out_name(it) for it in items]
    out_rows: list[list[object]] = []
    in_rows: list[list[object]] = []
    for row in frame.rows:
        ctx = EvalCtx(frame.col_tables, frame.col_names, row)
        out_rows.append([eval_expr(it.value, ctx) for it in items])
        in_rows.append(row)
    frame.out_names = names
    frame.out_rows = out_rows
    frame.in_rows = in_rows
    frame.group_aggs = [{} for _ in out_rows]
    frame.group_rowsets = None


def _select_groups(items: list[SelectItem], frame: _Frame) -> None:
    keys = _group_keys(frame)
    for item in items:
        _check_grouped(item.value, keys, frame)
    names = [_out_name(it) for it in items]
    out_rows: list[list[object]] = []
    in_rows: list[list[object]] = []
    all_aggs: list[dict[int, object]] = []
    assert frame.groups is not None
    for g in frame.groups:
        aggs = _aggs_for([it.value for it in items], g, frame)
        ctx = _group_ctx(g, frame, aggs)
        out_rows.append([eval_expr(it.value, ctx) for it in items])
        in_rows.append(_rep_row(g, frame))
        all_aggs.append(aggs)
    frame.out_names = names
    frame.out_rows = out_rows
    frame.in_rows = in_rows
    frame.group_aggs = all_aggs
    frame.group_rowsets = [g.rows for g in frame.groups]


def _group_keys(frame: _Frame) -> list[object]:
    return list(frame.group_exprs)


def _check_grouped(expr: object, keys: list[object], frame: _Frame) -> None:
    if has_aggregate(expr) or _constant_expr(expr):
        return
    bound = bind_expr(expr, frame.col_tables, frame.col_names)
    for key in keys:
        if expr_equal(bound, bind_expr(key, frame.col_tables, frame.col_names)):
            return
    raise GroupingError("select item is not a grouping expression or aggregate")


def _constant_expr(node: object) -> bool:
    if isinstance(node, Literal):
        return True
    if isinstance(node, ColumnRef):
        return False
    if isinstance(node, Call) and node.name in {"count", "sum", "avg", "min", "max"}:
        return False
    kids = walk_children(node)
    return all(_constant_expr(c) for c in kids)


def _has_column(node: object) -> bool:
    if isinstance(node, ColumnRef):
        return True
    return any(_has_column(c) for c in walk_children(node))


def _out_name(item: SelectItem) -> str:
    if item.alias is not None:
        return item.alias
    val = item.value
    if isinstance(val, ColumnRef) and val.table is None:
        return val.name
    if isinstance(val, ColumnRef) and val.source == val.name:
        return val.name
    src = item_source(val)
    return src if src else "?"


def _rep_row(group: _Group, frame: _Frame) -> list[object]:
    if group.rows:
        return group.rows[0]
    return [None] * len(frame.col_names)


def _group_ctx(group: _Group, frame: _Frame, aggs: dict[int, object]) -> EvalCtx:
    return EvalCtx(frame.col_tables, frame.col_names, _rep_row(group, frame), aggs=aggs)


def _aggs_for(nodes: list[object], group: _Group, frame: _Frame) -> dict[int, object]:
    calls: list[Call] = []
    for node in nodes:
        collect_aggregates(node, calls)
    result: dict[int, object] = {}
    for call in calls:
        result[id(call)] = _run_agg(call, group, frame)
    return result


def _run_agg(call: Call, group: _Group, frame: _Frame) -> object:
    if call.star:
        return eval_aggregate(call, group.rows)
    _check_arity(call.name, len(call.args), star=False)
    values: list[object] = []
    for row in group.rows:
        ctx = EvalCtx(frame.col_tables, frame.col_names, row)
        values.append(eval_expr(call.args[0], ctx))
    return eval_aggregate(call, values)


def _exec_distinct(frame: _Frame) -> None:
    assert frame.out_rows is not None
    seen: set[tuple[object, ...]] = set()
    new_out: list[list[object]] = []
    for row in frame.out_rows:
        key = tuple(distinct_canon(v) for v in row)
        if key in seen:
            continue
        seen.add(key)
        new_out.append(row)
    frame.out_rows = new_out
    frame.in_rows = None
    frame.group_aggs = None
    frame.group_rowsets = None
    frame.distinct = True


def _exec_order(items: tuple[object, ...], frame: _Frame) -> None:
    assert frame.out_rows is not None
    keys: list[list[object]] = []
    descs: list[bool] = []
    for item in items:
        descs.append(item.desc)  # type: ignore[attr-defined]
    for i, row in enumerate(frame.out_rows):
        keys.append(_order_keys(items, frame, i, row))
    idx = list(range(len(frame.out_rows)))

    def cmp(i: int, j: int) -> int:
        return _row_cmp(keys[i], keys[j], descs)

    idx.sort(key=functools.cmp_to_key(cmp))
    frame.out_rows = [frame.out_rows[i] for i in idx]
    if frame.in_rows is not None:
        frame.in_rows = [frame.in_rows[i] for i in idx]
    if frame.group_aggs is not None:
        frame.group_aggs = [frame.group_aggs[i] for i in idx]
    if frame.group_rowsets is not None:
        frame.group_rowsets = [frame.group_rowsets[i] for i in idx]


def _order_keys(
    items: tuple[object, ...], frame: _Frame, i: int, row: list[object]
) -> list[object]:
    names = frame.out_names or []
    aliases: dict[str, object] = {}
    for name, val in zip(names, row):
        if name not in aliases:
            aliases[name] = val
    in_row = frame.in_rows[i] if frame.in_rows is not None else row
    aggs = _order_aggs(frame, i, items)
    ctx = EvalCtx(
        frame.col_tables,
        frame.col_names,
        in_row,
        aliases=aliases,
        aggs=aggs,
        allow_input=not frame.distinct,
    )
    return [eval_expr(it.expr, ctx) for it in items]  # type: ignore[attr-defined]


def _order_aggs(frame: _Frame, i: int, items: tuple[object, ...]) -> dict[int, object] | None:
    if frame.distinct:
        return None
    aggs: dict[int, object] = dict(frame.group_aggs[i]) if frame.group_aggs else {}
    if frame.group_rowsets is not None:
        extra = _aggs_for(
            [it.expr for it in items],  # type: ignore[attr-defined]
            _Group((), frame.group_rowsets[i]),
            frame,
        )
        aggs.update(extra)
    return aggs


def _row_cmp(a: list[object], b: list[object], descs: list[bool]) -> int:
    for x, y, desc in zip(a, b, descs):
        c = _nulls_last(x, y, desc)
        if c != 0:
            return c
    return 0


def _nulls_last(a: object, b: object, desc: bool) -> int:
    from microdb.value import compare_lt

    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    if compare_lt(a, b) is True:
        return 1 if desc else -1
    if compare_lt(b, a) is True:
        return -1 if desc else 1
    return 0


def _slice_rows(frame: _Frame, offset: int, limit: int | None) -> None:
    rows = frame.out_rows if frame.out_rows is not None else frame.rows
    rows = _cut(rows, offset, limit)
    frame.in_rows = _cut(frame.in_rows, offset, limit)
    frame.group_aggs = _cut(frame.group_aggs, offset, limit)
    frame.group_rowsets = _cut(frame.group_rowsets, offset, limit)
    if frame.out_rows is not None:
        frame.out_rows = rows
    else:
        frame.rows = rows


def _cut(seq: list[object] | None, offset: int, limit: int | None) -> list[object] | None:
    if seq is None:
        return None
    if offset:
        seq = seq[offset:]
    if limit is not None:
        seq = seq[:limit]
    return seq

