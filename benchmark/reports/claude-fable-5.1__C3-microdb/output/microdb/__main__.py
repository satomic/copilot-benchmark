"""Command line interface: ``python -m microdb --table NAME=PATH ... QUERY``."""

from __future__ import annotations

import csv
import io
import sys
from typing import Optional

from .errors import MicroDBError
from .executor import Result, execute
from .schema import Column, Table
from .value import TYPE_NAMES

USAGE = "usage: python -m microdb --table NAME=PATH [--table NAME=PATH ...] QUERY"


class UsageError(Exception):
    """Bad arguments or unreadable/malformed input file (exit code 2)."""


def parse_args(argv: list[str]) -> tuple[list[tuple[str, str]], str]:
    tables: list[tuple[str, str]] = []
    query: Optional[str] = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--table":
            if i + 1 >= len(argv):
                raise UsageError("--table requires NAME=PATH")
            spec = argv[i + 1]
            i += 2
        elif arg.startswith("--table="):
            spec = arg[len("--table=") :]
            i += 1
        elif arg.startswith("--") and arg != "--":
            raise UsageError(f"unknown option {arg!r}")
        else:
            if query is not None:
                raise UsageError("exactly one QUERY argument is expected")
            query = arg
            i += 1
            continue
        name, sep, path = spec.partition("=")
        if not sep or not name or not path:
            raise UsageError(f"bad --table value {spec!r}, expected NAME=PATH")
        tables.append((name, path))
    if query is None:
        raise UsageError("missing QUERY")
    if not tables:
        raise UsageError("at least one --table is required")
    return tables, query


def parse_header(header: list[str], path: str) -> list[Column]:
    if not header:
        raise UsageError(f"{path}: empty header")
    columns: list[Column] = []
    for cell in header:
        name, sep, typ = cell.strip().partition(":")
        typ = typ.strip().upper()
        if not sep or not name or typ not in TYPE_NAMES:
            raise UsageError(f"{path}: malformed header field {cell!r}, expected name:TYPE")
        columns.append(Column(name.strip(), typ))
    return columns


def parse_cell(text: str, col: Column, path: str, line: int) -> object:
    """Convert one CSV field. Empty is NULL; the two characters '' are the empty string."""
    if text == "":
        return None
    if text == "''":
        text = ""
    try:
        if col.type == "TEXT":
            return text
        if col.type == "INT":
            return int(text)
        if col.type == "FLOAT":
            return float(text)
        lowered = text.strip().lower()
        if lowered in ("true", "false"):
            return lowered == "true"
        raise ValueError(text)
    except ValueError:
        # Malformed data counts as an unreadable file: usage error, exit code 2.
        raise UsageError(
            f"{path}:{line}: cannot convert {text!r} to {col.type} for column {col.name!r}"
        ) from None


def load_table(name: str, path: str) -> Table:
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            records = list(csv.reader(fh))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise UsageError(f"cannot read {path}: {exc}") from None
    if not records:
        raise UsageError(f"{path}: empty file")
    columns = parse_header(records[0], path)
    rows: list[list[object]] = []
    for line_no, record in enumerate(records[1:], start=2):
        if not record:
            if len(columns) != 1:
                continue  # skip blank lines in multi-column files
            record = [""]  # a single NULL column is written as an empty line
        if len(record) != len(columns):
            raise UsageError(f"{path}:{line_no}: expected {len(columns)} fields, got {len(record)}")
        rows.append([parse_cell(c, col, path, line_no) for c, col in zip(record, columns)])
    try:
        return Table(name, columns, rows)
    except MicroDBError as exc:  # e.g. duplicate header names
        raise UsageError(f"{path}: {exc}") from None


def format_value(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def format_field(text: str) -> str:
    if any(ch in text for ch in ',"\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text


def format_result(result: Result) -> str:
    out = io.StringIO()
    out.write(",".join(format_field(c) for c in result.columns) + "\n")
    for row in result.rows:
        out.write(",".join(format_field(format_value(v)) for v in row) + "\n")
    return out.getvalue()


def _write_stdout(text: str) -> None:
    stream = sys.stdout
    try:
        stream.reconfigure(newline="\n")  # type: ignore[union-attr]
    except (AttributeError, ValueError, io.UnsupportedOperation):
        pass
    stream.write(text)
    stream.flush()


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        specs, query = parse_args(args)
        tables = {name: load_table(name, path) for name, path in specs}
    except UsageError as exc:
        print(f"error: {exc}\n{USAGE}", file=sys.stderr)
        return 2
    try:
        result = execute(query, tables)
    except MicroDBError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    _write_stdout(format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
