from dataclasses import dataclass
from functools import cmp_to_key

from .aggregate import evaluate_aggregate
from .errors import (
    AggregateError,
    AmbiguousColumnError,
    GroupingError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownTableError,
)
from .expr import (
    Call,
    ColumnRef,
    Expr,
    IsNull,
    Binary,
    Literal,
    Star,
    Unary,
    contains_aggregate,
    evaluate,
)
from .parser import Query, SelectItem, parse
from .planner import Plan, plan
from .schema import Table
from .value import compare_eq, compare_lt


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclass(frozen=True)
class Field:
    table: str
    name: str


@dataclass
class Record:
    values: list[object]
    source: list[object]
    group: list[list[object]] | None


def _table(tables: dict[str, Table], name: str) -> Table:
    if name not in tables:
        raise UnknownTableError(f"unknown table: {name}")
    return tables[name]


def _fields(name: str, table: Table) -> list[Field]:
    return [Field(name, column.name) for column in table.columns]


def _resolver(fields: list[Field], row: list[object]):
    def resolve(reference: ColumnRef) -> object:
        if reference.table is not None:
            if reference.table not in {field.table for field in fields}:
                raise UnknownTableError(f"unknown table: {reference.table}")
            matches = [
                index for index, field in enumerate(fields)
                if field.table == reference.table and field.name == reference.name
            ]
        else:
            matches = [
                index for index, field in enumerate(fields) if field.name == reference.name
            ]
        if not matches:
            raise UnknownColumnError(f"unknown column: {reference.name}")
        if len(matches) > 1:
            raise AmbiguousColumnError(f"ambiguous column: {reference.name}")
        return row[matches[0]]
    return resolve


def _predicate(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TypeMismatchError("predicate requires BOOL")
    return value


def _from_join(query: Query, tables: dict[str, Table]) -> tuple[list[Field], list[list[object]]]:
    left = _table(tables, query.table)
    fields = _fields(query.table, left)
    rows = left.rows
    if query.join is None:
        return fields, rows
    if contains_aggregate(query.join.condition):
        raise AggregateError("JOIN condition cannot contain an aggregate")
    right = _table(tables, query.join.table)
    right_fields = _fields(query.join.table, right)
    joined: list[list[object]] = []
    for left_row in rows:
        matches = _join_matches(
            left_row, right.rows, fields + right_fields, query.join.condition
        )
        joined.extend(matches)
        if query.join.kind == "LEFT" and not matches:
            joined.append(left_row + [None] * len(right_fields))
    return fields + right_fields, joined


def _join_matches(
    left: list[object],
    right_rows: list[list[object]],
    fields: list[Field],
    condition: Expr,
) -> list[list[object]]:
    matches: list[list[object]] = []
    for right in right_rows:
        combined = left + right
        if _predicate(evaluate(condition, _resolver(fields, combined))):
            matches.append(combined)
    return matches


def _same_value(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    result = compare_eq(left, right)
    return result is True


def _same_row(left: list[object], right: list[object]) -> bool:
    return len(left) == len(right) and all(
        _same_value(a, b) for a, b in zip(left, right)
    )


def _group_rows(
    rows: list[list[object]], fields: list[Field], expressions: tuple[Expr, ...]
) -> list[list[list[object]]]:
    groups: list[tuple[list[object], list[list[object]]]] = []
    for row in rows:
        key = [evaluate(expr, _resolver(fields, row)) for expr in expressions]
        for old_key, members in groups:
            if _same_row(key, old_key):
                members.append(row)
                break
        else:
            groups.append((key, [row]))
    return [members for _, members in groups]


def _children(expression: Expr) -> tuple[Expr, ...]:
    if isinstance(expression, (Unary, IsNull)):
        return (expression.operand,)
    if isinstance(expression, Binary):
        return (expression.left, expression.right)
    if isinstance(expression, Call):
        return expression.args
    return ()


def _valid_group_expression(expression: Expr, keys: tuple[Expr, ...]) -> bool:
    if expression in keys or isinstance(expression, Literal):
        return True
    if isinstance(expression, Call) and expression.name.lower() in {
        "count", "sum", "avg", "min", "max"
    }:
        return True
    if isinstance(expression, (ColumnRef, Star)):
        return False
    return all(_valid_group_expression(child, keys) for child in _children(expression))


def _validate_grouping(query: Query, grouped: bool) -> None:
    expressions = [item.expression for item in query.select]
    if query.having:
        expressions.append(query.having)
    if not grouped:
        return
    keys = query.group_by
    for expression in expressions:
        if not _valid_group_expression(expression, keys):
            raise GroupingError(f"expression is not grouped: {expression.source}")


def _aggregate_resolver(
    fields: list[Field], group: list[list[object]], cache: dict[Call, object]
):
    def resolve(call: Call) -> object:
        if call not in cache:
            def item_eval(expression: object, row: object) -> object:
                assert isinstance(expression, Expr) and isinstance(row, list)
                return evaluate(expression, _resolver(fields, row))
            cache[call] = evaluate_aggregate(call, group, item_eval)
        return cache[call]
    return resolve


def _eval_group(expression: Expr, fields: list[Field], group: list[list[object]]) -> object:
    representative = group[0] if group else [None] * len(fields)
    cache: dict[Call, object] = {}
    return evaluate(
        expression,
        _resolver(fields, representative),
        _aggregate_resolver(fields, group, cache),
    )


def _select_name(item: SelectItem) -> str:
    if item.alias is not None:
        return item.alias
    if isinstance(item.expression, ColumnRef):
        return item.expression.name
    return item.expression.source


def _expand_select(
    query: Query, fields: list[Field]
) -> tuple[list[str], list[tuple[Expr | None, int | None]]]:
    names: list[str] = []
    specs: list[tuple[Expr | None, int | None]] = []
    for item in query.select:
        if not isinstance(item.expression, Star):
            names.append(_select_name(item))
            specs.append((item.expression, None))
            continue
        indexes = [
            index for index, field in enumerate(fields)
            if item.expression.table is None or field.table == item.expression.table
        ]
        if item.expression.table is not None and not indexes:
            raise UnknownTableError(f"unknown table: {item.expression.table}")
        for index in indexes:
            names.append(fields[index].name)
            specs.append((None, index))
    return names, specs


def _project(
    query: Query,
    fields: list[Field],
    contexts: list[tuple[list[object], list[list[object]] | None]],
) -> tuple[list[str], list[Record]]:
    names, specs = _expand_select(query, fields)
    records: list[Record] = []
    for source, group in contexts:
        values: list[object] = []
        for expression, index in specs:
            if index is not None:
                values.append(source[index])
            elif group is not None:
                values.append(_eval_group(expression, fields, group))  # type: ignore[arg-type]
            else:
                values.append(evaluate(expression, _resolver(fields, source)))  # type: ignore[arg-type]
        records.append(Record(values, source, group))
    return names, records


def _distinct(records: list[Record]) -> list[Record]:
    unique: list[Record] = []
    for record in records:
        if not any(_same_row(record.values, old.values) for old in unique):
            unique.append(record)
    return unique


def _order_value(
    expression: Expr,
    record: Record,
    names: list[str],
    fields: list[Field],
    query: Query,
) -> object:
    if (
        isinstance(expression, ColumnRef)
        and expression.table is None
        and expression.name in names
    ):
        return record.values[names.index(expression.name)]
    direct = _output_expression_index(expression, query, fields)
    if direct is not None:
        return record.values[direct]

    def resolve(reference: ColumnRef) -> object:
        if reference.table is None and reference.name in names:
            return record.values[names.index(reference.name)]
        if query.distinct:
            raise UnknownColumnError(f"ORDER BY column is not in output: {reference.name}")
        return _resolver(fields, record.source)(reference)
    if record.group is not None:
        cache: dict[Call, object] = {}
        return evaluate(
            expression, resolve,
            _aggregate_resolver(fields, record.group, cache),
        )
    return evaluate(expression, resolve)


def _output_expression_index(
    expression: Expr, query: Query, fields: list[Field]
) -> int | None:
    index = 0
    for item in query.select:
        if not isinstance(item.expression, Star):
            if item.expression == expression:
                return index
            index += 1
            continue
        index += sum(
            1 for field in fields
            if item.expression.table is None or field.table == item.expression.table
        )
    return None


def _compare_order(left: object, right: object, descending: bool) -> int:
    if left is None or right is None:
        if left is None and right is None:
            return 0
        return 1 if left is None else -1
    if compare_eq(left, right):
        return 0
    result = -1 if compare_lt(left, right) else 1
    return -result if descending else result


def _order(
    records: list[Record], query: Query, names: list[str], fields: list[Field]
) -> list[Record]:
    ordered = records
    for item in reversed(query.order_by):
        def compare(left: Record, right: Record) -> int:
            a = _order_value(item.expression, left, names, fields, query)
            b = _order_value(item.expression, right, names, fields, query)
            return _compare_order(a, b, item.descending)
        ordered = sorted(ordered, key=cmp_to_key(compare))
    return ordered


def _contexts(
    query: Query, fields: list[Field], rows: list[list[object]]
) -> list[tuple[list[object], list[list[object]] | None]]:
    aggregate_query = any(
        contains_aggregate(item.expression) for item in query.select
    ) or (query.having is not None and contains_aggregate(query.having))
    grouped = bool(query.group_by) or aggregate_query
    _validate_grouping(query, grouped)
    if query.group_by:
        groups = _group_rows(rows, fields, query.group_by)
        return [(group[0], group) for group in groups]
    if aggregate_query:
        source = rows[0] if rows else [None] * len(fields)
        return [(source, rows)]
    return [(row, None) for row in rows]


def execute_plan(query_plan: Plan, tables: dict[str, Table]) -> Result:
    query = query_plan.query
    fields, rows = _from_join(query, tables)
    if query.where:
        if contains_aggregate(query.where):
            raise AggregateError("WHERE cannot contain an aggregate")
        rows = [
            row for row in rows
            if _predicate(evaluate(query.where, _resolver(fields, row)))
        ]
    if any(contains_aggregate(expression) for expression in query.group_by):
        raise AggregateError("GROUP BY cannot contain an aggregate")
    contexts = _contexts(query, fields, rows)
    if query.having:
        contexts = [
            (source, group) for source, group in contexts
            if _predicate(
                _eval_group(query.having, fields, group)
                if group is not None
                else evaluate(query.having, _resolver(fields, source))
            )
        ]
    names, records = _project(query, fields, contexts)
    if query.distinct:
        records = _distinct(records)
    if query.order_by:
        records = _order(records, query, names, fields)
    records = records[query.offset:]
    if query.limit is not None:
        records = records[:query.limit]
    return Result(names, [record.values for record in records])


def execute(query: str, tables: dict[str, Table]) -> Result:
    return execute_plan(plan(parse(query)), tables)
