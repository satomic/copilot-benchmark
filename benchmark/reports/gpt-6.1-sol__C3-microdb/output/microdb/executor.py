"""Relational stages operating on bound row and group contexts."""

from dataclasses import dataclass, field, replace
from functools import cmp_to_key

from .errors import (
    AggregateError, AmbiguousColumnError, GroupingError, UnknownColumnError, UnknownTableError,
)
from .expr import Binding, Context, Output, evaluate, resolve, signature, validate
from .parser import (
    AGGREGATES, Binary, Call, Expr, Literal, Query, Reference, SelectItem, Unary,
    children, has_aggregate, parse,
)
from .planner import Plan, plan
from .schema import Table
from .value import compare_eq, compare_lt, key, logical


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclass
class Execution:
    query: Query
    tables: dict[str, Table]
    bindings: list[Binding]
    items: list[SelectItem]
    columns: list[str]
    orders: list[Expr]
    grouped: bool
    records: list[Context] = field(default_factory=list)


def _table(name: str, tables: dict[str, Table]) -> Table:
    if name not in tables:
        raise UnknownTableError(f"Unknown table: {name}")
    return tables[name]


def _bindings(query: Query, tables: dict[str, Table]) -> list[Binding]:
    names = [query.table] + ([query.join.table] if query.join else [])
    return [Binding(name, column) for name in names
            for column in _table(name, tables).columns]


def _projection(query: Query, bindings: list[Binding]) -> tuple[list[SelectItem], list[str]]:
    items = []
    names = []
    for item in query.select:
        if item.expr is None:
            if (item.wildcard_table is not None
                    and not any(b.table == item.wildcard_table for b in bindings)):
                raise UnknownTableError(f"Unknown table: {item.wildcard_table}")
            for binding in bindings:
                if item.wildcard_table is None or binding.table == item.wildcard_table:
                    ref = Reference(0, 0, binding.column.name, binding.table)
                    items.append(SelectItem(ref))
                    names.append(binding.column.name)
        else:
            items.append(item)
            names.append(item.alias if item.alias is not None else
                         item.expr.name if isinstance(item.expr, Reference) else
                         " ".join(query.source[item.expr.start:item.expr.end].split()))
    return items, names


def _contains_output_name(expr: Expr, names: list[str]) -> bool:
    return (isinstance(expr, Reference) and expr.table is None and expr.name in names
            or any(_contains_output_name(child, names) for child in children(expr)))


def _selected_index(expr: Expr, state: Execution) -> int | None:
    wanted = signature(expr, state.bindings)
    for index, item in enumerate(state.items):
        if signature(item.expr, state.bindings) == wanted:
            return index
    return None


def _order_expression(expr: Expr, state: Execution) -> Expr:
    if isinstance(expr, Reference) and expr.table is None and expr.name in state.columns:
        matches = [i for i, name in enumerate(state.columns) if name == expr.name]
        if len(matches) > 1:
            raise AmbiguousColumnError(f"Ambiguous output column: {expr.name}")
        return Output(expr.start, expr.end, matches[0])
    if isinstance(expr, Call) and expr.name in AGGREGATES:
        # Aggregate arguments bind to input columns, never to projection aliases.
        selected = _selected_index(expr, state)
        if selected is not None:
            return Output(expr.start, expr.end, selected)
        if state.query.distinct:
            raise AggregateError("ORDER BY with DISTINCT cannot compute an unselected aggregate")
        return expr
    if not _contains_output_name(expr, state.columns):
        selected = _selected_index(expr, state)
        if selected is not None:
            return Output(expr.start, expr.end, selected)
    if isinstance(expr, Reference):
        resolve(expr, state.bindings)
        if state.query.distinct:
            raise UnknownColumnError("ORDER BY with DISTINCT may reference only output columns")
    if isinstance(expr, Call):
        return replace(expr, args=tuple(_order_expression(arg, state) for arg in expr.args))
    if isinstance(expr, Binary):
        return replace(expr, left=_order_expression(expr.left, state),
                       right=_order_expression(expr.right, state))
    if isinstance(expr, Unary):
        return replace(expr, operand=_order_expression(expr.operand, state))
    return expr


def _group_check(expr: Expr, groups: set[object], bindings: list[Binding]) -> None:
    if isinstance(expr, (Literal, Output)):
        return
    if signature(expr, bindings) in groups:
        return
    if isinstance(expr, Call) and expr.name in AGGREGATES:
        return
    if isinstance(expr, Reference):
        raise GroupingError(f"Column {expr.name} is not a grouping expression")
    for child in children(expr):
        _group_check(child, groups, bindings)


def _prepare(query: Query, tables: dict[str, Table]) -> Execution:
    bindings = _bindings(query, tables)
    items, columns = _projection(query, bindings)
    grouped = bool(query.group_by) or any(has_aggregate(item.expr) for item in items)
    grouped = grouped or (query.having is not None and has_aggregate(query.having))
    state = Execution(query, tables, bindings, items, columns, [], grouped)
    for expr in ([query.where] if query.where is not None else []) + list(query.group_by):
        validate(expr, bindings, allow_aggregate=False)
    if query.join:
        validate(query.join.on, bindings, allow_aggregate=False)
    for item in items:
        validate(item.expr, bindings)
    if query.having is not None:
        validate(query.having, bindings)
    for order in query.order_by:
        rewritten = _order_expression(order.expr, state)
        validate(rewritten, bindings, allow_aggregate=grouped)
        state.orders.append(rewritten)
    if grouped:
        groups = {signature(expr, bindings) for expr in query.group_by}
        for item in items:
            if (query.group_by and not has_aggregate(item.expr)
                    and signature(item.expr, bindings) not in groups):
                raise GroupingError("SELECT expression is not a GROUP BY expression")
        checked = [item.expr for item in items] + state.orders
        if query.having is not None:
            checked.append(query.having)
        for expr in checked:
            _group_check(expr, groups, bindings)
    return state


def _from(state: Execution) -> None:
    state.records = [Context(state.bindings, row)
                     for row in _table(state.query.table, state.tables).rows]


def _join(state: Execution) -> None:
    join = state.query.join
    right = _table(join.table, state.tables)
    right_rows = right.rows
    records = []
    for left in state.records:
        matched = False
        for row in right_rows:
            context = Context(state.bindings, left.row + row)
            if logical(evaluate(join.on, context)) is True:
                records.append(context)
                matched = True
        if not matched and join.kind == "LEFT":
            records.append(Context(state.bindings, left.row + [None] * len(right.columns)))
    state.records = records


def _filter(state: Execution, expr: Expr | None) -> None:
    if expr is not None:
        state.records = [record for record in state.records
                         if logical(evaluate(expr, record)) is True]


def _group(state: Execution) -> None:
    if not state.query.group_by:
        return
    groups: dict[tuple[object, ...], list[list[object]]] = {}
    for record in state.records:
        group_key = tuple(key(evaluate(expr, record)) for expr in state.query.group_by)
        groups.setdefault(group_key, []).append(record.row)
    state.records = [Context(state.bindings, rows[0], rows) for rows in groups.values()]


def _aggregate_calls(expr: Expr) -> list[Call]:
    if isinstance(expr, Call) and expr.name in AGGREGATES:
        return [expr]
    return [call for child in children(expr) for call in _aggregate_calls(child)]


def _aggregates(state: Execution) -> None:
    if not state.grouped:
        return
    if not state.query.group_by:
        rows = [record.row for record in state.records]
        first = rows[0] if rows else [None] * len(state.bindings)
        state.records = [Context(state.bindings, first, rows)]
    expressions = [item.expr for item in state.items] + state.orders
    if state.query.having is not None:
        expressions.append(state.query.having)
    calls = [call for expr in expressions for call in _aggregate_calls(expr)]
    for record in state.records:
        for call in calls:
            evaluate(call, record)


def _select(state: Execution) -> None:
    for record in state.records:
        record.output = [evaluate(item.expr, record) for item in state.items]


def _distinct(state: Execution) -> None:
    if not state.query.distinct:
        return
    seen = set()
    records = []
    for record in state.records:
        row_key = tuple(key(value) for value in record.output)
        if row_key not in seen:
            seen.add(row_key)
            records.append(record)
    state.records = records


def _compare_keys(left: list[object], right: list[object], query: Query) -> int:
    for a, b, order in zip(left, right, query.order_by):
        if a is None or b is None:
            result = 0 if a is None and b is None else 1 if a is None else -1
        elif compare_eq(a, b):
            result = 0
        else:
            result = -1 if compare_lt(a, b) else 1
            if order.descending:
                result = -result
        if result:
            return result
    return 0


def _order(state: Execution) -> None:
    if not state.orders:
        return
    keyed = [(record, [evaluate(expr, record) for expr in state.orders])
             for record in state.records]
    keyed.sort(key=cmp_to_key(lambda a, b: _compare_keys(a[1], b[1], state.query)))
    state.records = [record for record, keys in keyed]


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    state = _prepare(plan.query, tables)
    for stage in plan:
        if stage.name == "FROM":
            _from(state)
        elif stage.name == "JOIN":
            _join(state)
        elif stage.name == "WHERE":
            _filter(state, state.query.where)
        elif stage.name == "GROUP BY":
            _group(state)
        elif stage.name == "AGGREGATE":
            _aggregates(state)
        elif stage.name == "HAVING":
            # Without grouping or aggregates, HAVING is a row-wise post-WHERE filter.
            _filter(state, state.query.having)
        elif stage.name == "SELECT":
            _select(state)
        elif stage.name == "DISTINCT":
            _distinct(state)
        elif stage.name == "ORDER BY":
            _order(state)
        elif stage.name == "OFFSET":
            state.records = state.records[state.query.offset:]
        elif stage.name == "LIMIT" and state.query.limit is not None:
            state.records = state.records[:state.query.limit]
    return Result(state.columns, [record.output for record in state.records])


def execute(query: str, tables: dict[str, Table]) -> Result:
    return execute_plan(plan(parse(query)), tables)
