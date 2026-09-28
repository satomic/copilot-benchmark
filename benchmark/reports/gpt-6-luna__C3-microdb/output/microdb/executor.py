from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cmp_to_key

from .errors import (AggregateError, AmbiguousColumnError, ArityError, GroupingError,
                     TypeMismatchError, UnknownColumnError, UnknownFunctionError,
                     UnknownTableError)
from .expr import contains_aggregate, evaluate, infer_type
from .parser import Expr, Query
from .planner import Plan
from .schema import Column, Table
from .value import compare_eq, compare_lt, type_of


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


@dataclass
class _Output:
    values: list[object]
    source_row: list[object]
    group: list[list[object]] | None


def execute(query: str, tables: dict[str, Table]) -> Result:
    from .parser import parse
    from .planner import plan
    return execute_plan(plan(parse(query)), tables)


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    query = plan.query
    descriptors, rows = _from_rows(query, tables)
    resolver = _resolver(descriptors, query, tables)
    _validate_query_calls(query)
    if query.where is not None and contains_aggregate(query.where):
        raise AggregateError("aggregate functions are not allowed in WHERE")
    if query.where is not None:
        _validate_expression_columns(query.where, _type_resolver(descriptors, query))
        _check_predicate_type(query.where, _type_resolver(descriptors, query))
    if query.where is not None:
        rows = [row for row in rows if _predicate(query.where, row, resolver)]
    if any(contains_aggregate(expr) for expr in query.group_by):
        raise AggregateError("aggregate functions are not allowed in GROUP BY")
    projections = _projections(query, descriptors)
    _validate_types(query, projections, descriptors)
    aggregate_query = _has_aggregation(query)
    _validate_grouping(query, projections, aggregate_query)
    grouped = _groups(query, rows, resolver, aggregate_query)
    outputs = _project(query, projections, grouped, rows, resolver, aggregate_query)
    if query.distinct:
        outputs = _distinct(outputs)
    outputs = _order(query, outputs, resolver, projections)
    start = query.offset
    end = None if query.limit is None else start + query.limit
    outputs = outputs[start:end]
    return Result([label for _, label in projections],
                  [output.values for output in outputs])


def _validate_query_calls(query: Query) -> None:
    expressions = [item.expr for item in query.items if item.expr is not None]
    expressions.extend(expr for expr in (
        query.where, query.having, *(item.expr for item in query.order_by),
        *(query.group_by), query.join.on if query.join else None,
    ) if expr is not None)
    for expr in expressions:
        _validate_calls(expr)


def _validate_calls(expr: Expr) -> None:
    if expr.kind == "CALL":
        name = str(expr.value).lower()
        aggregates = {"count", "sum", "avg", "min", "max"}
        scalars = {"concat", "upper", "lower", "length", "abs", "coalesce"}
        if name not in aggregates | scalars:
            raise UnknownFunctionError(f"unknown function: {name}")
        count = len(expr.children)
        if name in aggregates and count != 1:
            raise ArityError(f"{name} expects 1 argument, got {count}")
        if name in scalars:
            minimum = 2 if name == "concat" else 1
            maximum = None if name in {"concat", "coalesce"} else 1
            if count < minimum or (maximum is not None and count > maximum):
                upper = "unbounded" if maximum is None else str(maximum)
                raise ArityError(f"{name} expects {minimum}..{upper} arguments, got {count}")
        stars = [child for child in expr.children if child.kind == "STAR"]
        if stars and not (name == "count" and count == 1):
            raise TypeMismatchError("* is only valid in count(*)")
    elif expr.kind == "STAR":
        raise TypeMismatchError("* is only valid in count(*)")
    for child in expr.children:
        if child.kind != "STAR":
            _validate_calls(child)


def _from_rows(query: Query, tables: dict[str, Table]) -> tuple[list[tuple[str, Column]], list[list[object]]]:
    if query.table not in tables:
        raise UnknownTableError(f"unknown table: {query.table}")
    left = tables[query.table]
    descriptors = [(query.table, column) for column in left.columns]
    rows = left.rows
    if query.join is None:
        return descriptors, rows
    if contains_aggregate(query.join.on):
        raise AggregateError("aggregate functions are not allowed in JOIN ON")
    if query.join.table not in tables:
        raise UnknownTableError(f"unknown table: {query.join.table}")
    right = tables[query.join.table]
    right_desc = [(query.join.table, column) for column in right.columns]
    combined = descriptors + right_desc
    join_types = _type_resolver(combined, query)
    _validate_expression_columns(query.join.on, join_types)
    _check_predicate_type(query.join.on, join_types)
    resolver = _resolver(combined, query, tables)
    joined: list[list[object]] = []
    for left_row in rows:
        matches = 0
        for right_row in right.rows:
            candidate = left_row + right_row
            if _predicate(query.join.on, candidate, resolver):
                joined.append(candidate)
                matches += 1
        if query.join.kind == "LEFT" and matches == 0:
            joined.append(left_row + [None] * len(right_desc))
    return combined, joined


def _resolver(descriptors: list[tuple[str, Column]], query: Query,
              tables: dict[str, Table]) -> Callable[[tuple[str | None, str]], object]:
    names = [query.table]
    if query.join is not None:
        names.append(query.join.table)

    def resolve(reference: tuple[str | None, str], row: object = None) -> object:
        index = _column_index(reference, descriptors, names)
        if not isinstance(row, list):
            raise UnknownColumnError(f"column {reference[1]} has no input row")
        return row[index]

    return resolve


def _column_index(reference: tuple[str | None, str],
                  descriptors: list[tuple[str, Column]], names: list[str]) -> int:
    qualifier, column_name = reference
    if qualifier is not None:
        if qualifier not in names:
            raise UnknownTableError(f"unknown table: {qualifier}")
        matches = [index for index, (table_name, column) in enumerate(descriptors)
                   if table_name == qualifier and column.name == column_name]
    else:
        matches = [index for index, (_, column) in enumerate(descriptors)
                   if column.name == column_name]
    if not matches:
        raise UnknownColumnError(f"unknown column: {column_name}")
    if len(matches) > 1:
        raise AmbiguousColumnError(f"ambiguous column: {column_name}")
    return matches[0]


def _type_resolver(descriptors: list[tuple[str, Column]], query: Query) -> Callable[[tuple[str | None, str]], str]:
    names = [query.table]
    if query.join is not None:
        names.append(query.join.table)
    return lambda reference: descriptors[_column_index(reference, descriptors, names)][1].type


def _bind(resolver: Callable[..., object], row: object) -> Callable[[tuple[str | None, str]], object]:
    return lambda reference: resolver(reference, row)


def _check_predicate_type(expr: Expr,
                          resolver: Callable[[tuple[str | None, str]], str]) -> None:
    kind = _infer_safe(expr, resolver)
    if kind not in {"BOOL", "NULL", "ANY"} and not _has_any_column(expr):
        raise TypeMismatchError(f"predicate must be BOOL, got {kind}")


def _infer_safe(expr: Expr, resolver: Callable[[tuple[str | None, str]], str]) -> str:
    try:
        return infer_type(expr, resolver)
    except TypeMismatchError:
        if _has_any_column(expr):
            return "ANY"
        raise


def _validate_expression_columns(expr: Expr,
                                 resolver: Callable[[tuple[str | None, str]], str]) -> None:
    if expr.kind == "COLUMN":
        resolver(expr.value)  # type: ignore[arg-type]
    for child in expr.children:
        _validate_expression_columns(child, resolver)


def _validate_types(query: Query, projections: list[tuple[Expr, str]],
                    descriptors: list[tuple[str, Column]]) -> None:
    resolver = _type_resolver(descriptors, query)
    expressions = [expr for expr, _ in projections] + list(query.group_by)
    if query.having is not None:
        expressions.append(query.having)
    for expr in expressions:
        _validate_expression_columns(expr, resolver)
    projected_types = [_infer_safe(expr, resolver) for expr, _ in projections]
    for expr in query.group_by:
        _infer_safe(expr, resolver)
    if query.having is not None:
        _check_predicate_type(query.having, resolver)
    labels = [label for _, label in projections]

    def order_type(reference: tuple[str | None, str]) -> str:
        qualifier, name = reference
        if qualifier is None and name in labels:
            return projected_types[labels.index(name)]
        return resolver(reference)

    for item in query.order_by:
        _validate_expression_columns(item.expr, order_type)
        _infer_safe(item.expr, order_type)


def _predicate(expr: Expr, row: list[object],
               resolver: Callable[..., object]) -> bool:
    value = evaluate(expr, row, _bind(resolver, row), row_resolver=resolver)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TypeMismatchError(f"predicate must be BOOL, got {type_of(value)}")
    return value


def _projections(query: Query, descriptors: list[tuple[str, Column]]) -> list[tuple[Expr, str]]:
    result: list[tuple[Expr, str]] = []
    for item in query.items:
        if item.expr is not None:
            expr = item.expr
            name = item.alias or _output_name(expr)
            result.append((expr, name))
            continue
        matches = descriptors if item.star_table is None else [
            pair for pair in descriptors if pair[0] == item.star_table
        ]
        if item.star_table is not None and not any(n == item.star_table for n, _ in descriptors):
            raise UnknownTableError(f"unknown table: {item.star_table}")
        result.extend((_column_expr(table, column), column.name) for table, column in matches)
    return result


def _column_expr(table: str, column: Column) -> Expr:
    return Expr("COLUMN", (table, column.name), (), f"{table}.{column.name}")


def _output_name(expr: Expr) -> str:
    if expr.kind == "COLUMN":
        return str(expr.value[1])  # type: ignore[index]
    return " ".join(expr.source.split())


def _has_aggregation(query: Query) -> bool:
    expressions = [item.expr for item in query.items if item.expr is not None]
    if query.having is not None:
        expressions.append(query.having)
    expressions.extend(item.expr for item in query.order_by)
    return any(contains_aggregate(expr) for expr in expressions)


def _groups(query: Query, rows: list[list[object]], resolver: Callable[..., object],
            aggregate_query: bool) -> list[tuple[list[list[object]], list[object]]]:
    if query.group_by:
        groups: list[tuple[list[list[object]], list[object]]] = []
        keysets: list[list[object]] = []
        for row in rows:
            bound = _bind(resolver, row)
            keys = [evaluate(expr, row, bound, row_resolver=resolver) for expr in query.group_by]
            match = next((i for i, existing in enumerate(keysets)
                          if _keys_equal(existing, keys)), None)
            if match is None:
                keysets.append(keys)
                groups.append(([row], row))
            else:
                groups[match][0].append(row)
        return groups
    if aggregate_query:
        return [(rows, rows[0] if rows else [])]
    return [([row], row) for row in rows]


def _keys_equal(left: list[object], right: list[object]) -> bool:
    return len(left) == len(right) and all(
        (a is None and b is None) or (a is not None and b is not None and compare_eq(a, b) is True)
        for a, b in zip(left, right)
    )


def _project(query: Query, projections: list[tuple[Expr, str]],
             groups: list[tuple[list[list[object]], list[object]]],
             rows: list[list[object]], resolver: Callable[..., object],
             aggregate_query: bool) -> list[_Output]:
    output: list[_Output] = []
    for members, representative in groups:
        if query.having is not None:
            if not _predicate_group(query.having, representative, members, resolver):
                continue
        bound = _bind(resolver, representative)
        values = [evaluate(expr, representative, bound, members if aggregate_query else None,
                           resolver)
                  for expr, _ in projections]
        output.append(_Output(values, representative, members if aggregate_query else None))
    return output


def _predicate_group(expr: Expr, row: list[object], group: list[list[object]],
                     resolver: Callable[..., object]) -> bool:
    value = evaluate(expr, row, _bind(resolver, row), group, resolver)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TypeMismatchError(f"predicate must be BOOL, got {type_of(value)}")
    return value


def _validate_grouping(query: Query, projections: list[tuple[Expr, str]],
                       aggregate_query: bool) -> None:
    if query.group_by:
        for expr, _ in projections:
            if not _valid_group_expression(expr, query.group_by, allow_constant=False):
                raise GroupingError(f"{expr.source} is not a GROUP BY expression")
        if query.having is not None and not _valid_group_expression(
                query.having, query.group_by, allow_constant=True):
            raise GroupingError(f"{query.having.source} is not grouped")
        labels = [label for _, label in projections]
        for item in query.order_by:
            is_alias = (item.expr.kind == "COLUMN" and item.expr.value[0] is None
                        and item.expr.value[1] in labels)
            if not is_alias and not _valid_group_expression(
                    item.expr, query.group_by, allow_constant=True):
                raise GroupingError(f"{item.expr.source} is not grouped")
    elif aggregate_query:
        for expr, _ in projections:
            if _has_column_outside_aggregate(expr):
                raise GroupingError(f"{expr.source} is not grouped")
        if query.having is not None and _has_column_outside_aggregate(query.having):
            raise GroupingError(f"{query.having.source} is not grouped")


def _valid_group_expression(expr: Expr, groups: tuple[Expr, ...],
                           allow_constant: bool) -> bool:
    if expr in groups or _is_aggregate_call(expr):
        return True
    if not contains_aggregate(expr):
        if not _has_any_column(expr):
            return allow_constant
        if not allow_constant:
            return False
        return _valid_group_component(expr, groups)
    return all(_valid_group_component(child, groups) for child in expr.children)


def _valid_group_component(expr: Expr, groups: tuple[Expr, ...]) -> bool:
    if expr in groups or _is_aggregate_call(expr):
        return True
    if not _has_any_column(expr):
        return True
    return bool(expr.children) and all(
        _valid_group_component(child, groups) for child in expr.children
    )


def _is_aggregate_call(expr: Expr) -> bool:
    return expr.kind == "CALL" and str(expr.value).lower() in {
        "count", "sum", "avg", "min", "max"
    }


def _has_any_column(expr: Expr) -> bool:
    return expr.kind == "COLUMN" or any(_has_any_column(child) for child in expr.children)


def _has_column_outside_aggregate(expr: Expr, inside: bool = False) -> bool:
    if expr.kind == "CALL" and str(expr.value).lower() in {"count", "sum", "avg", "min", "max"}:
        return False
    if expr.kind == "COLUMN" and not inside:
        return True
    return any(_has_column_outside_aggregate(child, inside) for child in expr.children)


def _distinct(outputs: list[_Output]) -> list[_Output]:
    result: list[_Output] = []
    for candidate in outputs:
        if not any(_rows_equal(candidate.values, existing.values) for existing in result):
            result.append(candidate)
    return result


def _rows_equal(left: list[object], right: list[object]) -> bool:
    return len(left) == len(right) and all(
        (a is None and b is None) or (a is not None and b is not None and compare_eq(a, b) is True)
        for a, b in zip(left, right)
    )


def _order(query: Query, outputs: list[_Output], resolver: Callable[..., object],
           projections: list[tuple[Expr, str]]) -> list[_Output]:
    if not query.order_by:
        return outputs
    labels = [label for _, label in projections]
    if query.distinct:
        for item in query.order_by:
            _validate_distinct_order(item.expr, labels)
    for output in outputs:
        for item in query.order_by:
            _order_value(item.expr, output, labels, query.distinct, resolver)

    def compare(left: _Output, right: _Output) -> int:
        for item in query.order_by:
            a = _order_value(item.expr, left, labels, query.distinct, resolver)
            b = _order_value(item.expr, right, labels, query.distinct, resolver)
            result = _compare_sort(a, b, item.descending)
            if result:
                return result
        return 0

    return sorted(outputs, key=cmp_to_key(compare))


def _validate_distinct_order(expr: Expr, labels: list[str]) -> None:
    if expr.kind == "COLUMN":
        qualifier, name = expr.value
        if qualifier is not None or name not in labels:
            raise UnknownColumnError(f"ORDER BY column is not in DISTINCT output: {name}")
    for child in expr.children:
        _validate_distinct_order(child, labels)


def _order_value(expr: Expr, output: _Output, labels: list[str], distinct: bool,
                 resolver: Callable[..., object]) -> object:
    if expr.kind == "COLUMN" and expr.value[0] is None and expr.value[1] in labels:
        return output.values[labels.index(expr.value[1])]
    if distinct:
        def output_resolve(reference: tuple[str | None, str]) -> object:
            qualifier, name = reference
            if qualifier is not None or name not in labels:
                raise UnknownColumnError(f"ORDER BY column is not in DISTINCT output: {name}")
            return output.values[labels.index(name)]
        return evaluate(expr, output.values, output_resolve, output.group)
    def alias_resolve(reference: tuple[str | None, str], row: object) -> object:
        qualifier, name = reference
        if qualifier is None and name in labels:
            return output.values[labels.index(name)]
        return resolver(reference, row)
    return evaluate(expr, output.source_row, _bind(alias_resolve, output.source_row),
                    output.group, alias_resolve)


def _compare_sort(a: object, b: object, descending: bool) -> int:
    if a is None or b is None:
        return 0 if a is None and b is None else (1 if a is None else -1)
    if compare_eq(a, b) is True:
        return 0
    less = compare_lt(a, b)
    if less is None:
        return 0
    result = -1 if less else 1
    return -result if descending else result
