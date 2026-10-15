from __future__ import annotations

from collections.abc import Sequence
import csv
import io
import sys

from microdb.errors import MicroDBError, SchemaError
from microdb.executor import Result, execute
from microdb.schema import Column, Table
from microdb.value import VALID_TYPES


class _UsageError(Exception):
    """Internal exception for CLI usage/file/header errors (exit code 2)."""


def _parse_args(argv: Sequence[str]) -> tuple[list[tuple[str, str]], str]:
    tables: list[tuple[str, str]] = []
    positional: list[str] = []
    i = 0
    n = len(argv)
    while i < n:
        arg = argv[i]
        if arg == "--table":
            if i + 1 >= n:
                raise _UsageError("Missing value for --table")
            spec = argv[i + 1]
            i += 2
            tables.append(_parse_table_spec(spec))
        elif arg.startswith("--table="):
            spec = arg[len("--table=") :]
            i += 1
            tables.append(_parse_table_spec(spec))
        elif arg.startswith("-"):
            raise _UsageError(f"Unknown option: {arg}")
        else:
            positional.append(arg)
            i += 1
    if not tables:
        raise _UsageError("At least one --table NAME=PATH is required")
    if len(positional) != 1:
        raise _UsageError("Expected exactly one QUERY argument")
    return tables, positional[0]


def _parse_table_spec(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise _UsageError(f"Invalid table specification {spec!r}, expected NAME=PATH")
    name, path = spec.split("=", 1)
    if not name or not path:
        raise _UsageError(f"Invalid table specification {spec!r}, expected NAME=PATH")
    return name, path


def _parse_header(header_row: Sequence[str]) -> list[Column]:
    if not header_row:
        raise _UsageError("Empty CSV header")
    columns: list[Column] = []
    for raw_col in header_row:
        if ":" not in raw_col:
            raise _UsageError(f"Malformed column header {raw_col!r}, expected name:TYPE")
        parts = raw_col.split(":")
        if len(parts) != 2 or not parts[0] or parts[1] not in VALID_TYPES:
            raise _UsageError(f"Malformed column header {raw_col!r}, expected name:TYPE")
        columns.append(Column(name=parts[0], type=parts[1]))
    return columns


def _convert_csv_cell(raw_val: str, col: Column) -> object:
    if raw_val == "":
        return None
    if raw_val == "''":
        if col.type == "TEXT":
            return ""
        raise SchemaError(f"Empty string is not valid for column {col.name!r} of type {col.type}")
    if col.type == "TEXT":
        return raw_val
    if col.type == "INT":
        try:
            return int(raw_val)
        except ValueError as exc:
            raise SchemaError(f"Invalid INT {raw_val!r} for column {col.name!r}") from exc
    if col.type == "FLOAT":
        try:
            return float(raw_val)
        except ValueError as exc:
            raise SchemaError(f"Invalid FLOAT {raw_val!r} for column {col.name!r}") from exc
    low = raw_val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise SchemaError(f"Invalid BOOL {raw_val!r} for column {col.name!r}")


def _load_csv_table(name: str, path: str) -> Table:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            content = f.read()
    except OSError as exc:
        raise _UsageError(f"Cannot read table file {path!r}: {exc}") from exc

    if not content.strip():
        raise _UsageError(f"CSV file {path!r} is empty")

    reader = csv.reader(io.StringIO(content))
    try:
        header_row = next(reader)
    except StopIteration as exc:
        raise _UsageError(f"CSV file {path!r} has no header") from exc

    columns = _parse_header(header_row)
    rows: list[list[object]] = []
    for raw_row in reader:
        if not raw_row:
            if len(columns) == 1:
                raw_row = [""]
            else:
                continue
        if len(raw_row) != len(columns):
            raise SchemaError(
                f"CSV row length {len(raw_row)} does not match column count {len(columns)}"
            )
        row = [_convert_csv_cell(cell, col) for cell, col in zip(raw_row, columns)]
        rows.append(row)
    return Table(name=name, columns=columns, rows=rows)


def _format_csv_field(text: str) -> str:
    if any(ch in text for ch in (",", '"', "\n", "\r")):
        escaped = text.replace('"', '""')
        return f'"{escaped}"'
    return text


def _format_cell(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    return _format_csv_field(str(val))


def _write_result(result: Result) -> None:
    lines: list[str] = [",".join(_format_csv_field(c) for c in result.columns)]
    for row in result.rows:
        lines.append(",".join(_format_cell(v) for v in row))
    sys.stdout.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        table_specs, query_str = _parse_args(args)
        tables: dict[str, Table] = {}
        for tbl_name, tbl_path in table_specs:
            tables[tbl_name] = _load_csv_table(tbl_name, tbl_path)
        result = execute(query_str, tables)
    except _UsageError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    except MicroDBError as exc:
        sys.stderr.write(f"{exc}\n")
        return 3
    _write_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
