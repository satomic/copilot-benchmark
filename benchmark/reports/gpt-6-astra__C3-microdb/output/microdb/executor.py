"""Schema binding and execution of the planner's ordered stages."""

from dataclasses import dataclass, replace
from functools import cmp_to_key

from .aggregate import AGGREGATES
from .errors import (AmbiguousColumnError, GroupingError, UnknownColumnError,
                     UnknownTableError)
from .expr import (BoundRef, Call, Context, Expr, Literal, OutputRef, Ref, Star,
                   children, evaluate, expression_key, transform)
from .parser import OrderItem, Query, SelectItem, parse
from .planner import Plan, plan
from .schema import Column, Table
from .value import compare_eq, compare_lt, equality_key, logical


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclass(frozen=True)
class _Source:
    table: str
    column: Column


def _sources(query: Query, tables: dict[str, Table]) -> list[_Source]:
    result = []
    names = [query.table] + ([query.join.table] if query.join else [])
    for name in names:
        if name not in tables:
            raise UnknownTableError(f"Unknown table: {name}")
        result.extend(_Source(name, column) for column in tables[name].columns)
    return result


def _resolve(ref: Ref, sources: list[_Source]) -> BoundRef:
    if ref.table is not None and not any(s.table == ref.table for s in sources):
        raise UnknownTableError(f"Unknown table: {ref.table}")
    indices = [i for i, source in enumerate(sources)
               if source.column.name == ref.name
               and (ref.table is None or source.table == ref.table)]
    label = f"{ref.table}.{ref.name}" if ref.table else ref.name
    if not indices:
        raise UnknownColumnError(f"Unknown column: {label}")
    if len(indices) > 1:
        raise AmbiguousColumnError(f"Ambiguous column: {label}")
    return BoundRef(indices[0])


def _bind(expr: Expr, sources: list[_Source]) -> Expr:
    def visit(node: Expr) -> Expr | None:
        return _resolve(node, sources) if isinstance(node, Ref) else None
    return transform(expr, visit)


def _projection(query: Query, sources: list[_Source]) -> tuple[SelectItem, ...]:
    items = []
    for item in query.select:
        if not isinstance(item.expr, Star):
            name = item.alias or (item.expr.name if isinstance(item.expr, Ref)
                                  else item.text)
            items.append(SelectItem(_bind(item.expr, sources), item.alias, name))
            continue
        table = item.expr.table
        if table is not None and not any(source.table == table for source in sources):
            raise UnknownTableError(f"Unknown table: {table}")
        for index, source in enumerate(sources):
            if table is None or table == source.table:
                items.append(SelectItem(BoundRef(index), None, source.column.name))
    return tuple(items)


def _output_index(name: str, items: tuple[SelectItem, ...]) -> int | None:
    aliases = [i for i, item in enumerate(items) if item.alias == name]
    indices = aliases or [i for i, item in enumerate(items) if item.text == name]
    if len(indices) > 1:
        raise AmbiguousColumnError(f"Ambiguous output column: {name}")
    return indices[0] if indices else None


def _order_expr(expr: Expr, items: tuple[SelectItem, ...],
                sources: list[_Source], distinct: bool) -> Expr:
    def bind(node: Expr) -> Expr | None:
        if isinstance(node, Call) and node.name in AGGREGATES:
            # Aggregate arguments address group input, not projected aliases.
            return _bind(node, sources)
        if not isinstance(node, Ref):
            return None
        index = _output_index(node.name, items) if node.table is None else None
        return OutputRef(index) if index is not None else _resolve(node, sources)

    bound = transform(expr, bind)
    if not distinct:
        return bound
    projected = {}
    for index, item in enumerate(items):
        projected.setdefault(expression_key(item.expr), index)

    def output_only(node: Expr) -> Expr | None:
        key = expression_key(node)
        if key in projected:
            return OutputRef(projected[key])
        if isinstance(node, BoundRef) or (
                isinstance(node, Call) and node.name in AGGREGATES):
            # No source row survives DISTINCT as a uniquely addressable row.
            raise UnknownColumnError("DISTINCT ORDER BY requires output columns")
        return None

    return transform(bound, output_only)


def _group_valid(expr: Expr, keys: set[tuple]) -> bool:
    if expression_key(expr) in keys:
        return True
    if isinstance(expr, (Literal, OutputRef)):
        return True
    if isinstance(expr, Call) and expr.name in AGGREGATES:
        return True
    if isinstance(expr, BoundRef):
        return False
    return all(_group_valid(child, keys) for child in children(expr))


def _validate_grouping(query: Query, grouped: bool) -> None:
    if not grouped:
        return
    keys = {expression_key(expr) for expr in query.group_by}
    expressions = [*(item.expr for item in query.select),
                   *(item.expr for item in query.order_by)]
    if query.having is not None:
        expressions.append(query.having)
    # As in SQL, constants and compositions of grouping keys/aggregates are valid.
    for expr in expressions:
        if not _group_valid(expr, keys):
            raise GroupingError("Expression references a column outside GROUP BY")


def _prepare(pipeline: Plan, tables: dict[str, Table]) -> tuple[Query, int]:
    query = pipeline.query
    sources = _sources(query, tables)
    items = _projection(query, sources)
    join = replace(query.join, on=_bind(query.join.on, sources)) if query.join else None
    bound = replace(
        query, select=items, join=join,
        where=_bind(query.where, sources) if query.where is not None else None,
        group_by=tuple(_bind(expr, sources) for expr in query.group_by),
        having=_bind(query.having, sources) if query.having is not None else None,
        order_by=tuple(OrderItem(_order_expr(item.expr, items, sources, query.distinct),
                                 item.descending) for item in query.order_by))
    _validate_grouping(bound, any(stage.name == "AGGREGATE" for stage in pipeline))
    return bound, len(sources)


def _aggregate_calls(expr: Expr) -> list[Call]:
    if isinstance(expr, Call) and expr.name in AGGREGATES:
        return [expr]
    return [call for child in children(expr) for call in _aggregate_calls(child)]


def _compare_keys(left: list[object], right: list[object],
                  order: tuple[OrderItem, ...]) -> int:
    for a, b, item in zip(left, right, order):
        if a is None or b is None:
            result = 0 if a is b else (1 if a is None else -1)
        elif compare_eq(a, b):
            result = 0
        else:
            result = -1 if compare_lt(a, b) else 1
            if item.descending:
                result = -result
        if result:
            return result
    return 0


class _Execution:
    def __init__(self, pipeline: Plan, tables: dict[str, Table]) -> None:
        self.query, self.width = _prepare(pipeline, tables)
        self.tables = tables
        self.contexts: list[Context] = []

    def from_rows(self) -> None:
        self.contexts = [Context(row) for row in self.tables[self.query.table].rows]

    def join_rows(self) -> None:
        join = self.query.join
        if join is None:
            return
        right = self.tables[join.table]
        rows = right.rows
        result = []
        for left in self.contexts:
            matches = []
            for row in rows:
                context = Context(left.row + row)
                if logical(evaluate(join.on, context)) is True:
                    matches.append(context)
            if not matches and join.kind == "LEFT":
                matches.append(Context(left.row + [None] * len(right.columns)))
            result.extend(matches)
        self.contexts = result

    def filter_rows(self, expr: Expr | None) -> None:
        if expr is not None:
            self.contexts = [context for context in self.contexts
                             if logical(evaluate(expr, context)) is True]

    def group_rows(self) -> None:
        groups: dict[tuple, list[list[object]]] = {}
        for context in self.contexts:
            values = [evaluate(expr, context) for expr in self.query.group_by]
            groups.setdefault(equality_key(values), []).append(context.row)
        self.contexts = [Context(rows[0], rows) for rows in groups.values()]

    def aggregate_rows(self) -> None:
        if not self.query.group_by:
            rows = [context.row for context in self.contexts]
            self.contexts = [Context(rows[0] if rows else [None] * self.width, rows)]
        expressions = [*(item.expr for item in self.query.select),
                       *(item.expr for item in self.query.order_by)]
        if self.query.having is not None:
            expressions.append(self.query.having)
        calls = [call for expr in expressions for call in _aggregate_calls(expr)]
        for context in self.contexts:
            for call in calls:
                evaluate(call, context)

    def select_rows(self) -> None:
        for context in self.contexts:
            context.output = [evaluate(item.expr, context) for item in self.query.select]

    def distinct_rows(self) -> None:
        seen = set()
        result = []
        for context in self.contexts:
            key = equality_key(context.output)
            if key not in seen:
                seen.add(key)
                result.append(context)
        self.contexts = result

    def order_rows(self) -> None:
        decorated = [(context, [evaluate(item.expr, context)
                                for item in self.query.order_by])
                     for context in self.contexts]

        def compare(left: tuple[Context, list[object]],
                    right: tuple[Context, list[object]]) -> int:
            return _compare_keys(left[1], right[1], self.query.order_by)

        decorated.sort(key=cmp_to_key(compare))
        self.contexts = [context for context, _ in decorated]

    def run_stage(self, name: str) -> None:
        actions = {"FROM": self.from_rows, "JOIN": self.join_rows,
                   "GROUP BY": self.group_rows, "AGGREGATE": self.aggregate_rows,
                   "SELECT": self.select_rows, "DISTINCT": self.distinct_rows,
                   "ORDER BY": self.order_rows}
        if name in actions:
            actions[name]()
        elif name == "WHERE":
            self.filter_rows(self.query.where)
        elif name == "HAVING":
            self.filter_rows(self.query.having)
        elif name == "OFFSET":
            self.contexts = self.contexts[self.query.offset:]
        elif name == "LIMIT":
            self.contexts = self.contexts[:self.query.limit]
        else:
            raise ValueError(f"Unknown execution stage: {name}")


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    execution = _Execution(plan, tables)
    for stage in plan:
        execution.run_stage(stage.name)
    return Result([item.text for item in execution.query.select],
                  [context.output for context in execution.contexts])


def execute(query: str, tables: dict[str, Table]) -> Result:
    return execute_plan(plan(parse(query)), tables)
