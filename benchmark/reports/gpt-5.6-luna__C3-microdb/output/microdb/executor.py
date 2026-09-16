from dataclasses import dataclass
from functools import cmp_to_key
from .aggregate import eval_group
from .errors import (AggregateError, AmbiguousColumnError, GroupingError, TypeMismatchError,
                     UnknownTableError, UnknownColumnError)
from .expr import Binary, Call, ColumnRef, Expr, IsNull, Unary
from .parser import Query, SelectItem, parse
from .planner import Plan, plan
from .schema import Table
from .value import compare_eq, compare_lt


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


def execute(query: str, tables: dict[str, Table]) -> Result:
    return execute_plan(plan(parse(query)), tables)


def execute_plan(pl: Plan, tables: dict[str, Table]) -> Result:
    q = pl.query
    if q.table not in tables:
        raise UnknownTableError(q.table)
    if q.join_table and q.join_table not in tables:
        raise UnknownTableError(q.join_table)
    output_names = _output_names(q, tables)
    _validate_tables(q, tables, set(output_names))
    rows, names = _from(q, tables)
    if q.where:
        if q.where.aggregate:
            raise AggregateError("aggregate in WHERE")
        rows = [r for r in rows if _predicate(q.where.eval(r))]
    has_agg = any(i.expr and i.expr.aggregate for i in q.items) or bool(q.having and q.having.aggregate)
    groups = _groups(rows, q.group_by, has_agg)
    if q.group_by:
        _check_grouping(q)
    _validate_order(q, output_names)
    projected: list[tuple[list[object], dict[str, object], dict[str, object], list[dict[str, object]]]] = []
    for group in groups:
        if q.having and not _predicate(eval_group(q.having, group)):
            continue
        vals = _project(q.items, group, q, tables, q.group_by or has_agg)
        projected.append((vals, dict(zip(output_names, vals)), group[0] if group else {}, group))
    if q.distinct:
        projected = _distinct(projected)
    projected.sort(key=cmp_to_key(lambda a, b: _compare_rows(a, b, q.order_by)))
    start, end = q.offset, None if q.limit is None else q.offset + q.limit
    return Result(output_names, [r[0] for r in projected[start:end]])


def _predicate(value: object) -> bool:
    if value is not True and value is not False and value is not None:
        raise TypeMismatchError("predicate must be BOOL")
    return value is True


def _from(q: Query, tables: dict[str, Table]) -> tuple[list[dict[str, object]], list[str]]:
    if q.table not in tables:
        raise UnknownTableError(q.table)
    left = _table_rows(tables[q.table])
    names = [c.name for c in tables[q.table].columns]
    if not q.join_table:
        return left, names
    if q.join_table not in tables:
        raise UnknownTableError(q.join_table)
    right = _table_rows(tables[q.join_table])
    names += [c.name for c in tables[q.join_table].columns]
    out: list[dict[str, object]] = []
    for lrow in left:
        matches = []
        for rrow in right:
            joined = _joined(lrow, rrow, q.table, q.join_table)
            if q.join_on and _predicate(q.join_on.eval(joined)):
                matches.append(joined)
        if q.join_kind == "LEFT" and not matches:
            nulls = {f"{q.join_table}.{c.name}": None for c in tables[q.join_table].columns}
            matches = [_joined(lrow, nulls, q.table, q.join_table)]
        out.extend(matches)
    return out, names


def _table_rows(table: Table) -> list[dict[str, object]]:
    return [{f"{table.name}.{c.name}": v for c, v in zip(table.columns, row)} for row in table.rows]


def _joined(left: dict[str, object], right: dict[str, object], lt: str, rt: str) -> dict[str, object]:
    out = dict(left); out.update(right)
    ln = {k.rsplit(".", 1)[1] for k in left}; rn = {k.rsplit(".", 1)[1] for k in right}
    for name in ln ^ rn:
        source, table = (left, lt) if name in ln else (right, rt)
        out[name] = source[f"{table}.{name}"]
    return out


def _groups(rows: list[dict[str, object]], keys: list[Expr], aggregate_needed: bool) -> list[list[dict[str, object]]]:
    if not keys:
        return [rows] if aggregate_needed else [[r] for r in rows]
    groups: list[list[dict[str, object]]] = []; signatures: list[list[object]] = []
    for row in rows:
        sig = [key.eval(row) for key in keys]
        index = next((i for i, old in enumerate(signatures) if _same(sig, old)), None)
        if index is None:
            signatures.append(sig); groups.append([row])
        else:
            groups[index].append(row)
    return groups


def _same(a: list[object], b: list[object]) -> bool:
    return all((x is None and y is None) or compare_eq(x, y) is True for x, y in zip(a, b))


def _project(items: list[SelectItem], group: list[dict[str, object]], q: Query,
             tables: dict[str, Table], grouped: bool) -> list[object]:
    row = group[0] if group else {}
    values: list[object] = []
    for item in items:
        if item.expr is None:
            table_names = [q.table] if item.star_table is None else [item.star_table]
            if item.star_table is None and q.join_table:
                table_names.append(q.join_table)
            for table_name in table_names:
                for column in tables[table_name].columns:
                    values.append(row.get(f"{table_name}.{column.name}"))
        elif grouped:
            values.append(eval_group(item.expr, group))
        else:
            values.append(item.expr.eval(row))
    return values


def _lookup(row: dict[str, object], name: str) -> object:
    if name in row:
        return row[name]
    matches = [v for k, v in row.items() if k.endswith("." + name)]
    if len(matches) > 1:
        from .errors import AmbiguousColumnError
        raise AmbiguousColumnError(name)
    if not matches:
        from .errors import UnknownColumnError
        raise UnknownColumnError(name)
    return matches[0]


def _output_names(q: Query, tables: dict[str, Table]) -> list[str]:
    out: list[str] = []
    for item in q.items:
        if item.expr is None:
            table_names = [q.table] if item.star_table is None else [item.star_table]
            if item.star_table is None and q.join_table:
                table_names.append(q.join_table)
            for table_name in table_names:
                if table_name not in tables:
                    raise UnknownTableError(table_name)
                out.extend(c.name for c in tables[table_name].columns)
        elif item.alias:
            out.append(item.alias)
        elif isinstance(item.expr, ColumnRef):
            out.append(item.expr.name)
        else:
            out.append(" ".join(item.expr.text.split()))
    return out


def _check_grouping(q: Query) -> None:
    allowed = {e.text for e in q.group_by}
    for item in q.items:
        if item.expr and not item.expr.aggregate and item.expr.text not in allowed:
            raise GroupingError("select expression is not grouped")


def _distinct(rows: list[tuple]) -> list[tuple]:
    out: list[tuple] = []
    seen: list[list[object]] = []
    for row in rows:
        if not any(_same(row[0], old) for old in seen):
            seen.append(row[0]); out.append(row)
    return out


def _compare_rows(a: tuple, b: tuple, orders: list[tuple[Expr, bool]]) -> int:
    for expr, desc in orders:
        if isinstance(expr, ColumnRef):
            av = a[1][expr.name] if expr.name in a[1] else expr.eval(a[2])
            bv = b[1][expr.name] if expr.name in b[1] else expr.eval(b[2])
        else:
            av, bv = _order_value(expr, a), _order_value(expr, b)
        if av is None or bv is None:
            if av is None and bv is None: continue
            return 1 if av is None else -1
        if compare_eq(av, bv) is True: continue
        result = -1 if compare_lt(av, bv) else 1
        return -result if desc else result
    return 0


def _order_value(expr: Expr, projected: tuple) -> object:
    if expr.aggregate:
        return eval_group(expr, projected[3])
    return expr.eval(projected[2])


def _validate_order(q: Query, output_names: list[str]) -> None:
    if not q.distinct:
        return
    allowed = set(output_names)
    for expr, _ in q.order_by:
        if isinstance(expr, ColumnRef) and expr.name not in allowed:
            raise UnknownColumnError(expr.name)
        if not isinstance(expr, ColumnRef) and expr.text not in allowed:
            raise UnknownColumnError(expr.text)


def _validate_tables(q: Query, tables: dict[str, Table], aliases: set[str]) -> None:
    allowed = {q.table} | ({q.join_table} if q.join_table else set())
    for item in q.items:
        if item.star_table and (item.star_table not in allowed or item.star_table not in tables):
            raise UnknownTableError(item.star_table)
    expressions = [i.expr for i in q.items if i.expr] + [q.where, q.join_on, q.having]
    expressions += q.group_by + [e for e, _ in q.order_by if not (isinstance(e, ColumnRef) and e.name in aliases)]
    for expr in expressions:
        _validate_expr_table(expr, allowed, tables)


def _validate_expr_table(expr: Expr | None, allowed: set[str], tables: dict[str, Table]) -> None:
    if expr is None:
        return
    if isinstance(expr, ColumnRef) and expr.table:
        if expr.table not in allowed or expr.table not in tables:
            raise UnknownTableError(expr.table)
        if expr.name not in {c.name for c in tables[expr.table].columns}:
            raise UnknownColumnError(f"{expr.table}.{expr.name}")
    elif isinstance(expr, ColumnRef):
        matches = sum(expr.name in {c.name for c in tables[name].columns} for name in allowed)
        if matches == 0:
            raise UnknownColumnError(expr.name)
        if matches > 1:
            raise AmbiguousColumnError(expr.name)
    if isinstance(expr, (Unary, IsNull)):
        _validate_expr_table(expr.child, allowed, tables)
    elif isinstance(expr, Binary):
        _validate_expr_table(expr.left, allowed, tables)
        _validate_expr_table(expr.right, allowed, tables)
    elif isinstance(expr, Call):
        for arg in expr.args:
            _validate_expr_table(arg, allowed, tables)
