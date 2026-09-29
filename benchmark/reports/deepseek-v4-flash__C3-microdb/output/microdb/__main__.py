"""CLI entry point for microdb.

Usage:
    python -m microdb --table NAME=PATH [--table NAME=PATH] QUERY
"""

import sys
import csv
import io

from microdb import execute, Column, Table, MicroDBError
from microdb.lexer import tokenize
from microdb.parser import parse
from microdb.planner import plan
from microdb.executor import execute_plan, Result


def _parse_header(line: str) -> list[Column]:
    """Parse a CSV header line like 'id:INT,name:TEXT'."""
    parts = [p.strip() for p in line.split(",")]
    if not parts or not parts[0]:
        raise ValueError("empty header")
    columns: list[Column] = []
    for p in parts:
        if ":" not in p:
            raise ValueError(f"invalid header field: {p!r}")
        name, typ = p.rsplit(":", 1)
        name = name.strip()
        typ = typ.strip().upper()
        if typ not in ("INT", "FLOAT", "TEXT", "BOOL"):
            raise ValueError(f"invalid type {typ!r} in header")
        columns.append(Column(name, typ))
    return columns


def _parse_csv_value(raw: str, col_type: str) -> object:
    """Parse a single CSV field value."""
    if raw == "":
        return None  # empty field = NULL
    if col_type == "INT":
        return int(raw)
    if col_type == "FLOAT":
        return float(raw)
    if col_type == "BOOL":
        lower = raw.strip().lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        raise ValueError(f"invalid BOOL: {raw!r}")
    # TEXT
    return raw


def _read_table(name: str, path: str) -> Table:
    """Read a CSV file into a Table."""
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # Handle BOM and split lines
    lines = content.splitlines()
    if not lines:
        raise ValueError(f"empty file: {path}")

    header = lines[0]
    columns = _parse_header(header)

    rows: list[list[object]] = []
    for line_num, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        # Parse CSV with basic quoting support
        fields = _parse_csv_line(line)
        if len(fields) != len(columns):
            raise ValueError(
                f"line {line_num}: expected {len(columns)} fields, "
                f"got {len(fields)}"
            )
        row: list[object] = []
        for raw, col in zip(fields, columns):
            row.append(_parse_csv_value(raw, col.type))
        rows.append(row)

    return Table(name, columns, rows)


def _parse_csv_line(line: str) -> list[str]:
    """Parse a single CSV line handling quoting."""
    fields: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    current.append('"')
                    i += 2
                    continue
                in_quotes = False
                i += 1
                continue
            current.append(ch)
            i += 1
        else:
            if ch == '"':
                in_quotes = True
                i += 1
            elif ch == ",":
                fields.append("".join(current))
                current = []
                i += 1
            else:
                current.append(ch)
                i += 1
    fields.append("".join(current))
    return fields


def _format_csv_cell(value: object) -> str:
    """Format a single value for CSV output."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # Use str() for floats
        return str(value)
    s = str(value)
    # Quote if contains comma, double quote, or newline
    if "," in s or '"' in s or "\n" in s:
        s = '"' + s.replace('"', '""') + '"'
    return s


def main(argv: list[str] | None = None) -> int:
    """Main entry point. Returns exit code."""
    if argv is None:
        argv = sys.argv[1:]

    # Parse arguments
    tables: dict[str, Table] = {}
    query_parts: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--table":
            i += 1
            if i >= len(argv):
                print("--table requires NAME=PATH", file=sys.stderr)
                return 2
            spec = argv[i]
            if "=" not in spec:
                print(f"invalid --table spec: {spec!r}", file=sys.stderr)
                return 2
            name, path = spec.split("=", 1)
            try:
                tables[name] = _read_table(name, path)
            except (FileNotFoundError, PermissionError) as e:
                print(f"error reading {path!r}: {e}", file=sys.stderr)
                return 2
            except ValueError as e:
                print(f"error in {path!r}: {e}", file=sys.stderr)
                return 2
        else:
            query_parts.append(arg)
        i += 1

    if not tables:
        print("at least one --table is required", file=sys.stderr)
        return 2

    query_str = " ".join(query_parts)
    if not query_str:
        print("query is required", file=sys.stderr)
        return 2

    try:
        result = execute(query_str, tables)
    except MicroDBError as e:
        print(str(e), file=sys.stderr)
        return 3

    # Output CSV to stdout
    out_lines: list[str] = []
    out_lines.append(",".join(result.columns))
    for row in result.rows:
        out_lines.append(
            ",".join(_format_csv_cell(v) for v in row)
        )
    sys.stdout.write("\n".join(out_lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())