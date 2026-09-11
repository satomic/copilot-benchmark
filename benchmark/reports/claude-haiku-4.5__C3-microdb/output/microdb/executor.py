import dataclasses
from .planner import Plan, Stage, FromStage, WhereStage, GroupByStage, HavingStage, SelectStage, OrderByStage, LimitOffsetStage
from .schema import Table
from .expr import evaluate, expr_to_string, is_aggregate_expr
from .aggregate import Aggregator
from .value import compare_lt, type_of
from .errors import (
    TypeMismatchError, UnknownColumnError, AmbiguousColumnError,
    UnknownTableError, GroupingError
)


@dataclasses.dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[list[object]]


def execute_plan(plan: Plan, tables: dict[str, Table]) -> Result:
    """Execute a query plan and return the result."""
    rows = []
    output_columns = []
    
    for stage in plan:
        if isinstance(stage, FromStage):
            rows = _execute_from(stage, tables)
        elif isinstance(stage, WhereStage):
            rows = _execute_where(stage, rows)
        elif isinstance(stage, GroupByStage):
            rows = _execute_group_by(stage, rows)
        elif isinstance(stage, HavingStage):
            rows = _execute_having(stage, rows)
        elif isinstance(stage, SelectStage):
            rows, output_columns = _execute_select(stage, rows, tables, plan)
        elif isinstance(stage, LimitOffsetStage):
            rows = _execute_limit_offset(stage, rows)
        elif isinstance(stage, OrderByStage):
            rows = _execute_order_by(stage, rows, output_columns, tables, plan)
        elif stage.name == "DISTINCT":
            rows = _execute_distinct(rows)
    
    return Result(columns=output_columns, rows=rows)


def _execute_from(stage: FromStage, tables: dict[str, Table]) -> list[dict[str, object]]:
    """Execute FROM clause."""
    if not stage.table:
        return []
    if stage.table not in tables:
        raise UnknownTableError(f"Table '{stage.table}' not found")
    
    left_table = tables[stage.table]
    rows = []
    for row_data in left_table.rows:
        row = {}
        for i, col in enumerate(left_table.columns):
            row[f"{stage.table}.{col.name}"] = row_data[i]
            row[col.name] = row_data[i]
        rows.append(row)
    
    if stage.join_type:
        if stage.join_table not in tables:
            raise UnknownTableError(f"Table '{stage.join_table}' not found")
        right_table = tables[stage.join_table]
        
        if stage.join_type == "INNER":
            rows = _execute_inner_join(rows, right_table, stage.join_table, stage.join_on_expr)
        elif stage.join_type == "LEFT":
            rows = _execute_left_join(rows, right_table, stage.join_table, stage.join_on_expr)
    
    return rows


def _execute_inner_join(
    left_rows: list[dict[str, object]], right_table: Table, right_name: str, on_expr: object
) -> list[dict[str, object]]:
    """Execute INNER JOIN."""
    result = []
    for left_row in left_rows:
        for right_row_data in right_table.rows:
            combined = left_row.copy()
            for i, col in enumerate(right_table.columns):
                combined[f"{right_name}.{col.name}"] = right_row_data[i]
                if col.name not in combined:
                    combined[col.name] = right_row_data[i]
            
            pred = evaluate(on_expr, combined)
            if pred is True:
                result.append(combined)
    return result


def _execute_left_join(
    left_rows: list[dict[str, object]], right_table: Table, right_name: str, on_expr: object
) -> list[dict[str, object]]:
    """Execute LEFT JOIN."""
    result = []
    for left_row in left_rows:
        found = False
        for right_row_data in right_table.rows:
            combined = left_row.copy()
            for i, col in enumerate(right_table.columns):
                combined[f"{right_name}.{col.name}"] = right_row_data[i]
                if col.name not in combined:
                    combined[col.name] = right_row_data[i]
            
            pred = evaluate(on_expr, combined)
            if pred is True:
                result.append(combined)
                found = True
        
        if not found:
            combined = left_row.copy()
            for col in right_table.columns:
                combined[f"{right_name}.{col.name}"] = None
                if col.name not in combined or col.name.startswith(right_name + "."):
                    combined[col.name] = None
            result.append(combined)
    return result


def _execute_where(stage: WhereStage, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Execute WHERE clause."""
    result = []
    for row in rows:
        pred = evaluate(stage.expr, row)
        if pred is True:
            result.append(row)
    return result


def _execute_group_by(stage: GroupByStage, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Execute GROUP BY clause."""
    if not stage.exprs:
        if rows:
            return [rows]
        return [[]]
    
    groups = {}
    group_order = []
    
    for row in rows:
        keys = tuple(evaluate(expr, row) for expr in stage.exprs)
        if keys not in groups:
            groups[keys] = []
            group_order.append(keys)
        groups[keys].append(row)
    
    return [groups[key] for key in group_order]


def _execute_having(stage: HavingStage, rows: list[list[dict[str, object]]]) -> list[list[dict[str, object]]]:
    """Execute HAVING clause."""
    result = []
    for group in rows:
        group_row = {}
        if group:
            for key in group[0].keys():
                group_row[key] = group[0][key]
        pred = evaluate(stage.expr, group_row)
        if pred is True:
            result.append(group)
    return result


def _execute_select(
    stage: SelectStage, rows: list[dict[str, object]] | list[list[dict[str, object]]],
    tables: dict[str, Table], plan: Plan
) -> tuple[list[list[object]], list[str]]:
    """Execute SELECT clause."""
    is_grouped = isinstance(rows[0], list) if rows else False
    
    if is_grouped:
        return _execute_select_grouped(stage, rows, tables)
    else:
        return _execute_select_ungrouped(stage, rows, tables)


def _execute_select_ungrouped(
    stage: SelectStage, rows: list[dict[str, object]], tables: dict[str, Table]
) -> tuple[list[list[object]], list[str]]:
    """Execute SELECT on ungrouped rows."""
    output_rows = []
    output_columns = []
    
    if not rows and stage.items[0][0] is None and stage.items[0][2] is None:
        return [], []
    
    for row in rows:
        output_row = []
        if not output_columns:
            for item in stage.items:
                if item[0] is None and item[2]:
                    table_name = item[2]
                    if table_name not in tables:
                        raise UnknownTableError(f"Table '{table_name}' not found")
                    for col in tables[table_name].columns:
                        output_columns.append(col.name)
                elif item[0] is None and not item[2]:
                    for key in row.keys():
                        if "." not in key:
                            output_columns.append(key)
                else:
                    output_columns.append(item[1] or expr_to_string(item[0]))
        
        for item in stage.items:
            if item[0] is None and item[2]:
                table_name = item[2]
                for col in tables[table_name].columns:
                    output_row.append(row.get(f"{table_name}.{col.name}", None))
            elif item[0] is None and not item[2]:
                for key in output_columns:
                    output_row.append(row.get(key, None))
            else:
                val = evaluate(item[0], row)
                output_row.append(val)
        
        output_rows.append(output_row)
    
    return output_rows, output_columns


def _execute_select_grouped(
    stage: SelectStage, groups: list[list[dict[str, object]]], tables: dict[str, Table]
) -> tuple[list[list[object]], list[str]]:
    """Execute SELECT on grouped rows."""
    output_rows = []
    output_columns = []
    
    for group in groups:
        output_row = []
        if not output_columns:
            for item in stage.items:
                if item[0] is None and item[2]:
                    table_name = item[2]
                    for col in tables[table_name].columns:
                        output_columns.append(col.name)
                elif item[0] is None:
                    raise ValueError("Invalid select item")
                else:
                    output_columns.append(item[1] or expr_to_string(item[0]))
        
        for item in stage.items:
            if item[0] is None and item[2]:
                table_name = item[2]
                for col in tables[table_name].columns:
                    output_row.append(group[0].get(f"{table_name}.{col.name}", None) if group else None)
            elif item[0] is None:
                raise ValueError("Invalid select item")
            elif is_aggregate_expr(item[0]):
                agg = Aggregator(item[0], group)
                output_row.append(agg.compute())
            else:
                val = evaluate(item[0], group[0]) if group else None
                output_row.append(val)
        
        output_rows.append(output_row)
    
    return output_rows, output_columns


def _execute_order_by(
    stage: OrderByStage, rows: list[list[object]], output_columns: list[str],
    tables: dict[str, Table], plan: Plan
) -> list[list[object]]:
    """Execute ORDER BY clause."""
    def sort_key(row_idx: int) -> tuple:
        row = rows[row_idx]
        keys = []
        for expr, direction in stage.items:
            try:
                val = evaluate(expr, {output_columns[i]: row[i] for i in range(len(output_columns))})
            except (KeyError, UnknownColumnError):
                for table in tables.values():
                    temp_row = {}
                    for i, r in enumerate(rows):
                        if i == row_idx:
                            for j, col in enumerate(table.columns):
                                temp_row[col.name] = r[j] if j < len(r) else None
                    try:
                        val = evaluate(expr, temp_row)
                        break
                    except:
                        pass
                else:
                    raise
            
            if val is None:
                keys.append((1, None))
            else:
                keys.append((0, val))
        return tuple(keys)
    
    sorted_indices = sorted(range(len(rows)), key=sort_key)
    result = []
    
    for idx in sorted_indices:
        result.append(rows[idx])
    
    return result


def _execute_distinct(rows: list[list[object]]) -> list[list[object]]:
    """Execute DISTINCT."""
    seen = set()
    result = []
    for row in rows:
        row_tuple = tuple(row)
        if row_tuple not in seen:
            seen.add(row_tuple)
            result.append(row)
    return result


def _execute_limit_offset(stage: LimitOffsetStage, rows: list[list[object]]) -> list[list[object]]:
    """Execute LIMIT and OFFSET."""
    offset = stage.offset or 0
    limit = stage.limit
    
    if limit is None:
        return rows[offset:]
    else:
        return rows[offset:offset+limit]
