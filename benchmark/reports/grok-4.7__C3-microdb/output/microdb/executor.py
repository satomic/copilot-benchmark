"""Execute a plan. NULL, grouping and ordering follow section 8."""

from __future__ import annotations

import dataclasses
from functools import cmp_to_key

from microdb.aggregate import check_arity, eval_aggregate
from microdb.errors import (
    AggregateError,
    AmbiguousColumnError,
    GroupingError,
    MicroDBError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownTableError,
)
from microdb.expr import (
    contains_aggregate,
    equivalent,
    evaluate,
    having_valid,
    is_aggregate_call,
    output_name,
    require_logic,
    resolve_value,
)
from microdb.parser import BinaryOp, ColumnRef, Expr, FuncCall, IsNull, OrderItem, SelectItem, UnaryOp
from microdb.planner import (
    Aggregate,
    Distinct,
    GroupBy,
    Having,
    Join,
    Limit,
    Offset,
    OrderBy,
    Plan,
    Project,
    Scan,
    Where,
)
from microdb.schema import Table
from microdb.value import compare_eq, compare_lt

# Choice: with GROUP BY, a SELECT item must itself be an aggregate call or
# equivalent to a grouping expression. `count(*) + 1` is therefore rejected.
# Choice: grouping uses section 3.1 equality, except NULL equals NULL.
# Choice: 1 and 1.0 form one group because they compare equal.
# Choice: ORDER BY matches an output column by name or select-item source
# before it re-evaluates, so an alias wins over an input column.


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclasses.dataclass
class _Work:
    columns: list[tuple[str | None, str]]
    rows: list[list[object]]


@dataclasses.dataclass
class _Group:
    key: tuple[object, ...]
    rows: list[list[object]]


class _Engine:
    def __init__(self, tables: dict[str, Table]) -> None:
        self.tables = tables
        self.work = _Work([], [])
        self.groups: list[_Group] = []
        self.agg_maps: list[dict[int, object]] | None = None
        self.grouped = False
        self.explicit_group = False
        self.group_keys: tuple[Expr, ...] = ()
        self.distinct = False
        self.output_names: list[str] = []
        self.output_sources: list[str | None] = []
        self.output_rows: list[list[object]] = []
        self.row_aggs: list[dict[int, object] | None] = []
        self.saved_columns: list[tuple[str | None, str]] = []
        self.saved_rows: list[list[object]] = []

    def apply(self, stage: object) -> None:
        name = "_stage_" + type(stage).__name__
        method = getattr(self, name, None)
        if method is None:
            raise MicroDBError(f"unknown stage {type(stage).__name__}")
        method(stage)

    def result(self) -> Result:
        rows = [list(row) for row in self.output_rows]
        return Result(list(self.output_names), rows)

    def _stage_Scan(self, stage: Scan) -> None:
        self.work = _scan(stage.table, self._table(stage.table))

    def _stage_Join(self, stage: Join) -> None:
        _reject_aggregate(stage.on, "JOIN")
        right = self._table(stage.table)
        self.work = _join(self.work, stage.kind, stage.table, right, stage.on)

    def _stage_Where(self, stage: Where) -> None:
        _reject_aggregate(stage.predicate, "WHERE")
        self.work = _filter_rows(self.work, stage.predicate)

    def _stage_GroupBy(self, stage: GroupBy) -> None:
        self.grouped = True
        self.explicit_group = not stage.implicit
        self.group_keys = stage.keys
        for key in stage.keys:
            _reject_aggregate(key, "GROUP BY")
        self.groups = _form_groups(self.work, stage.keys, stage.implicit)

    def _stage_Aggregate(self, stage: Aggregate) -> None:
        rows: list[list[object]] = []
        maps: list[dict[int, object]] = []
        width = len(self.work.columns)
        for group in self.groups:
            maps.append(_agg_map(self.work.columns, group.rows, stage.calls))
            rows.append(group.rows[0] if group.rows else [None] * width)
        self.work = _Work(self.work.columns, rows)
        self.agg_maps = maps

    def _stage_Having(self, stage: Having) -> None:
        if not self.grouped:
            _reject_aggregate(stage.predicate, "HAVING")
            self.work = _filter_rows(self.work, stage.predicate)
            return
        self._check_having(stage.predicate)
        self._filter_groups(stage.predicate)

    def _stage_Project(self, stage: Project) -> None:
        self._check_select(stage.items)
        self.saved_columns = list(self.work.columns)
        self.saved_rows = self.work.rows
        names, sources = _project_names(self.work.columns, stage.items)
        self.output_names = names
        self.output_sources = sources
        self._project_rows(stage.items)

    def _stage_Distinct(self, stage: Distinct) -> None:
        del stage
        self.distinct = True
        kept_rows: list[list[object]] = []
        kept_aggs: list[dict[int, object] | None] = []
        for row, amap in zip(self.output_rows, self.row_aggs):
            if any(_distinct_eq(row, prev) for prev in kept_rows):
                continue
            kept_rows.append(row)
            kept_aggs.append(amap)
        self.output_rows = kept_rows
        self.row_aggs = kept_aggs

    def _stage_OrderBy(self, stage: OrderBy) -> None:
        self._check_order_items(stage.items)
        keys = [_order_key(self, stage.items, index) for index in range(len(self.output_rows))]
        indexes = sorted(range(len(keys)), key=cmp_to_key(lambda i, j: _cmp_keys(keys[i], keys[j], stage.items)))
        self.output_rows = [self.output_rows[i] for i in indexes]
        self.row_aggs = [self.row_aggs[i] for i in indexes]

    def _check_order_items(self, items: tuple[OrderItem, ...]) -> None:
        if not self.distinct:
            return
        for item in items:
            if _output_match(self.output_names, self.output_sources, item.expr.source) is None:
                raise UnknownColumnError(item.expr.source or "ORDER BY")

    def _stage_Offset(self, stage: Offset) -> None:
        self.output_rows = self.output_rows[stage.count:]

    def _stage_Limit(self, stage: Limit) -> None:
        self.output_rows = self.output_rows[:stage.count]

    def _table(self, name: str) -> Table:
        try:
            return self.tables[name]
        except KeyError as exc:
            raise UnknownTableError(name) from exc

    def _check_having(self, predicate: Expr) -> None:
        if having_valid(predicate, self.group_keys, self.work.columns, self.explicit_group):
            return
        raise GroupingError("HAVING references a column that is not grouped or aggregated")

    def _filter_groups(self, predicate: Expr) -> None:
        rows: list[list[object]] = []
        maps: list[dict[int, object]] = []
        assert self.agg_maps is not None
        for row, amap in zip(self.work.rows, self.agg_maps):
            if _is_true(predicate, self.work.columns, row, amap, True):
                rows.append(row)
                maps.append(amap)
        self.work = _Work(self.work.columns, rows)
        self.agg_maps = maps

    def _check_select(self, items: tuple[SelectItem, ...]) -> None:
        if not self.grouped:
            return
        for item in items:
            _check_select_item(item, self.group_keys, self.work.columns, self.explicit_group)

    def _project_rows(self, items: tuple[SelectItem, ...]) -> None:
        maps = self.agg_maps if self.agg_maps is not None else [None] * len(self.work.rows)
        self.output_rows = []
        self.row_aggs = []
        for row, amap in zip(self.work.rows, maps):
            self.output_rows.append(_project_row(self.work.columns, row, items, amap, self.grouped))
            self.row_aggs.append(amap)

    def order_value(self, expr: Expr, index: int) -> object:
        matched = _output_match(self.output_names, self.output_sources, expr.source)
        if matched is not None:
            return self.output_rows[index][matched]
        if self.distinct:
            raise UnknownColumnError(expr.source or "ORDER BY")
        return evaluate(expr, lambda table, name: self._order_resolve(table, name, index), self.row_aggs[index], self.grouped)

    def _order_resolve(self, table: str | None, name: str, index: int) -> object:
        if table is None:
            hits = [i for i, col in enumerate(self.output_names) if col == name]
            if len(hits) > 1:
                raise AmbiguousColumnError(name)
            if len(hits) == 1:
                return self.output_rows[index][hits[0]]
            return resolve_value(self.saved_columns, self.saved_rows[index], None, name)
        return resolve_value(self.saved_columns, self.saved_rows[index], table, name)


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Parse, plan and execute *query* against *tables*."""
    from microdb.parser import parse
    from microdb.planner import plan as build_plan

    return execute_plan(build_plan(parse(query)), tables)


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    """Execute an already-built plan."""
    engine = _Engine(tables)
    for stage in plan:
        engine.apply(stage)
    return engine.result()


def _scan(name: str, table: Table) -> _Work:
    # Qualifiers follow the query name, not Table.name, so the dict key wins.
    columns = [(name, column.name) for column in table.columns]
    rows = [list(row) for row in table.rows]
    return _Work(columns, rows)


def _join(left: _Work, kind: str, name: str, right: Table, on: Expr) -> _Work:
    right_cols = [(name, column.name) for column in right.columns]
    right_rows = [list(row) for row in right.rows]
    out_cols = left.columns + right_cols
    out_rows: list[list[object]] = []
    for left_row in left.rows:
        out_rows.extend(_join_left(left_row, right_rows, out_cols, right_cols, on, kind))
    return _Work(out_cols, out_rows)


def _join_left(
    left_row: list[object],
    right_rows: list[list[object]],
    out_cols: list[tuple[str | None, str]],
    right_cols: list[tuple[str | None, str]],
    on: Expr,
    kind: str,
) -> list[list[object]]:
    matched: list[list[object]] = []
    for right_row in right_rows:
        combined = left_row + right_row
        if _is_true(on, out_cols, combined, None, False):
            matched.append(combined)
    if matched:
        return matched
    if kind == "LEFT":
        return [left_row + [None] * len(right_cols)]
    return []


def _filter_rows(work: _Work, predicate: Expr) -> _Work:
    kept = [row for row in work.rows if _is_true(predicate, work.columns, row, None, False)]
    return _Work(work.columns, kept)


def _is_true(
    expr: Expr,
    columns: list[tuple[str | None, str]],
    row: list[object],
    aggs: dict[int, object] | None,
    allow: bool,
) -> bool:
    value = evaluate(expr, lambda table, name: resolve_value(columns, row, table, name), aggs, allow)
    return require_logic(value) is True


def _form_groups(work: _Work, keys: tuple[Expr, ...], implicit: bool) -> list[_Group]:
    if implicit:
        return [_Group((), list(work.rows))]
    groups: list[_Group] = []
    for row in work.rows:
        key = tuple(_eval_row(key_expr, work.columns, row) for key_expr in keys)
        found = _find_group(groups, key)
        if found is None:
            groups.append(_Group(key, [row]))
        else:
            found.rows.append(row)
    return groups


def _find_group(groups: list[_Group], key: tuple[object, ...]) -> _Group | None:
    for group in groups:
        if all(_group_eq(left, right) for left, right in zip(group.key, key)):
            return group
    return None


def _group_eq(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return compare_eq(left, right) is True


def _eval_row(expr: Expr, columns: list[tuple[str | None, str]], row: list[object]) -> object:
    return evaluate(expr, lambda table, name: resolve_value(columns, row, table, name), None, False)


def _agg_map(
    columns: list[tuple[str | None, str]],
    rows: list[list[object]],
    calls: tuple[FuncCall, ...],
) -> dict[int, object]:
    return {id(call): _one_agg(columns, rows, call) for call in calls}


def _one_agg(columns: list[tuple[str | None, str]], rows: list[list[object]], call: FuncCall) -> object:
    if call.star:
        check_arity(call.name, 0, 0)
        return eval_aggregate(call.name, True, [], len(rows))
    if len(call.args) != 1:
        check_arity(call.name, len(call.args), 1)
    values = [_eval_row(call.args[0], columns, row) for row in rows]
    return eval_aggregate(call.name, False, values, len(rows))


def _project_names(
    columns: list[tuple[str | None, str]],
    items: tuple[SelectItem, ...],
) -> tuple[list[str], list[str | None]]:
    names: list[str] = []
    sources: list[str | None] = []
    for item in items:
        item_names, item_sources = _item_names(columns, item)
        names.extend(item_names)
        sources.extend(item_sources)
    return names, sources


def _item_names(
    columns: list[tuple[str | None, str]],
    item: SelectItem,
) -> tuple[list[str], list[str | None]]:
    if item.kind == "star":
        return [col[1] for col in columns], [None] * len(columns)
    if item.kind == "table_star":
        return _table_star_names(columns, item.table or "")
    source = item.expr.source if item.expr is not None else item.source
    return [output_name(item)], [source]


def _table_star_names(
    columns: list[tuple[str | None, str]],
    table: str,
) -> tuple[list[str], list[str | None]]:
    known = {col[0] for col in columns if col[0] is not None}
    if table not in known:
        raise UnknownTableError(table)
    names = [col[1] for col in columns if col[0] == table]
    return names, [None] * len(names)


def _project_row(
    columns: list[tuple[str | None, str]],
    row: list[object],
    items: tuple[SelectItem, ...],
    aggs: dict[int, object] | None,
    allow: bool,
) -> list[object]:
    values: list[object] = []
    for item in items:
        values.extend(_item_values(columns, row, item, aggs, allow))
    return values


def _item_values(
    columns: list[tuple[str | None, str]],
    row: list[object],
    item: SelectItem,
    aggs: dict[int, object] | None,
    allow: bool,
) -> list[object]:
    if item.kind == "star":
        return list(row)
    if item.kind == "table_star":
        return [row[i] for i, col in enumerate(columns) if col[0] == item.table]
    assert item.expr is not None
    return [evaluate(item.expr, lambda table, name: resolve_value(columns, row, table, name), aggs, allow)]


def _check_select_item(
    item: SelectItem,
    keys: tuple[Expr, ...],
    columns: list[tuple[str | None, str]],
    explicit: bool,
) -> None:
    if item.kind != "expr" or item.expr is None:
        raise GroupingError("star is not valid when grouping")
    if not explicit:
        if _bare_outside_aggregate(item.expr):
            raise GroupingError("column must appear in an aggregate")
        return
    if is_aggregate_call(item.expr):
        return
    if any(equivalent(item.expr, key, columns) for key in keys):
        return
    raise GroupingError("select item must be an aggregate or a grouping expression")


def _bare_outside_aggregate(expr: Expr) -> bool:
    if isinstance(expr, FuncCall) and is_aggregate_call(expr):
        return False
    if isinstance(expr, ColumnRef):
        return True
    if isinstance(expr, BinaryOp):
        return _bare_outside_aggregate(expr.left) or _bare_outside_aggregate(expr.right)
    if isinstance(expr, UnaryOp):
        return _bare_outside_aggregate(expr.operand)
    if isinstance(expr, IsNull):
        return _bare_outside_aggregate(expr.operand)
    if isinstance(expr, FuncCall):
        return any(_bare_outside_aggregate(arg) for arg in expr.args)
    return False


def _reject_aggregate(expr: Expr, clause: str) -> None:
    if contains_aggregate(expr):
        raise AggregateError(f"aggregate function not allowed in {clause}")


def _output_match(names: list[str], sources: list[str | None], source: str) -> int | None:
    hits = [i for i, name in enumerate(names) if name == source]
    for i, item_source in enumerate(sources):
        if item_source is not None and item_source == source and i not in hits:
            hits.append(i)
    if not hits:
        return None
    if len(hits) > 1:
        raise AmbiguousColumnError(source)
    return hits[0]


def _order_key(engine: _Engine, items: tuple[OrderItem, ...], index: int) -> tuple[object, ...]:
    return tuple(engine.order_value(item.expr, index) for item in items)


def _cmp_keys(left: tuple[object, ...], right: tuple[object, ...], items: tuple[OrderItem, ...]) -> int:
    for index, item in enumerate(items):
        compared = _cmp_sort(left[index], right[index], item.direction == "DESC")
        if compared != 0:
            return compared
    return 0


def _cmp_sort(left: object, right: object, desc: bool) -> int:
    # NULL stays last in both ASC and DESC. DESC reverses non-NULL values only.
    if left is None and right is None:
        return 0
    if left is None:
        return 1
    if right is None:
        return -1
    compared = _cmp_values(left, right)
    return -compared if desc else compared


def _cmp_values(left: object, right: object) -> int:
    if compare_eq(left, right):
        return 0
    if compare_lt(left, right):
        return -1
    return 1


def _distinct_eq(left: list[object], right: list[object]) -> bool:
    return all(_distinct_value_eq(a, b) for a, b in zip(left, right))


def _distinct_value_eq(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return compare_eq(left, right) is True
    except TypeMismatchError:
        return False
