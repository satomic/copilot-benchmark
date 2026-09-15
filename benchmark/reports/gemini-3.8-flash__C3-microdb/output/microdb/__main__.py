"""Command-line interface for microdb."""

from __future__ import annotations

import csv
import sys
from microdb.errors import MicroDBError
from microdb.executor import execute
from microdb.schema import Column, Table

VALID_TYPES = frozenset({"INT", "FLOAT", "TEXT", "BOOL"})


def _format_cell(v: object) -> str:
    if v is None:
        raw = ""
    elif isinstance(v, bool):
        raw = "true" if v else "false"
    elif isinstance(v, (int, float, str)):
        raw = str(v)
    else:
        raw = str(v)
    if "," in raw or '"' in raw or "\n" in raw or "\r" in raw:
        escaped = raw.replace('"', '""')
        return f'"{escaped}"'
    return raw


def _parse_header(header_row: list[str]) -> list[Column] | None:
    if not header_row:
        return None
    columns: list[Column] = []
    for col_def in header_row:
        if ":" not in col_def:
            return None
        name, col_type = col_def.split(":", 1)
        name = name.strip()
        col_type = col_type.strip().upper()
        if not name or col_type not in VALID_TYPES:
            return None
        columns.append(Column(name, col_type))
    return columns


def _parse_row_cell(cell: str, col_type: str) -> object:
    if cell == "":
        return None
    if cell == "''":
        return ""
    if col_type == "INT":
        try:
            return int(cell)
        except ValueError:
            return cell
    if col_type == "FLOAT":
        try:
            return float(cell)
        except ValueError:
            return cell
    if col_type == "BOOL":
        lower = cell.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        return cell
    return cell


def _load_table(path: str, table_name: str) -> Table | None:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return None
            columns = _parse_header(header)
            if columns is None:
                return None
            rows: list[list[object]] = []
            for raw_row in reader:
                parsed_row = [
                    _parse_row_cell(raw_row[i] if i < len(raw_row) else "", col.type)
                    for i, col in enumerate(columns)
                ]
                rows.append(parsed_row)
            return Table(table_name, columns, rows)
    except (OSError, csv.Error):
        return None


def _parse_args(
    argv: list[str],
) -> tuple[dict[str, str], str] | None:
    tables_map: dict[str, str] = {}
    query_parts: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--table":
            if i + 1 >= len(argv):
                return None
            spec = argv[i + 1]
            i += 2
        elif arg.startswith("--table="):
            spec = arg[len("--table=") :]
            i += 1
        elif arg.startswith("-"):
            return None
        else:
            query_parts.append(arg)
            i += 1
            continue
        if "=" not in spec:
            return None
        t_name, t_path = spec.split("=", 1)
        t_name, t_path = t_name.strip(), t_path.strip()
        if not t_name or not t_path:
            return None
        tables_map[t_name] = t_path
    if not tables_map or len(query_parts) != 1:
        return None
    return tables_map, query_parts[0]


def main(argv: list[str] | None = None) -> int:
    """Entry point for microdb CLI."""
    if argv is None:
        argv = sys.argv[1:]
    parsed = _parse_args(argv)
    if parsed is None:
        return 2
    tables_map, query_str = parsed
    tables: dict[str, Table] = {}
    for name, path in tables_map.items():
        tbl = _load_table(path, name)
        if tbl is None:
            return 2
        tables[name] = tbl
    try:
        result = execute(query_str, tables)
    except MicroDBError as err:
        sys.stderr.write(f"{err}\n")
        return 3
    lines = [",".join(_format_cell(col) for col in result.columns) + "\n"]
    for row in result.rows:
        lines.append(",".join(_format_cell(cell) for cell in row) + "\n")
    sys.stdout.write("".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
