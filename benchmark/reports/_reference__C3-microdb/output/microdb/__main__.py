"""CLI: run one query against CSV tables."""

from __future__ import annotations

import argparse
import csv
import io
import pathlib
import sys

from .errors import MicroDBError
from .executor import Result, execute
from .schema import Column, Table
from .value import BOOL, FLOAT, INT, TEXT, TYPE_NAMES

__all__ = ["build_parser", "load_table", "format_result", "main"]

_USAGE_EXIT = 2
_QUERY_EXIT = 3


class _UsageError(Exception):
    """Raised for anything that should exit with code 2."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microdb", allow_abbrev=False)
    parser.add_argument("--table", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("query")
    return parser


def _parse_cell(raw: str, type_name: str) -> object:
    if raw == "":
        return None
    if type_name == INT:
        return int(raw)
    if type_name == FLOAT:
        return float(raw)
    if type_name == BOOL:
        lowered = raw.lower()
        if lowered not in ("true", "false"):
            raise _UsageError(f"bad BOOL value {raw!r}")
        return lowered == "true"
    return raw


def load_table(name: str, path: pathlib.Path) -> Table:
    """Read a CSV whose header is a list of ``name:TYPE`` pairs."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from None
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise _UsageError(f"{path} is empty") from None
    columns: list[Column] = []
    for field in header:
        if field.count(":") != 1:
            raise _UsageError(f"bad header field {field!r} in {path}")
        col_name, type_name = field.split(":")
        if type_name not in TYPE_NAMES:
            raise _UsageError(f"unknown type {type_name!r} in {path}")
        columns.append(Column(col_name, type_name))
    rows: list[list[object]] = []
    for raw_row in reader:
        if len(raw_row) != len(columns):
            raise _UsageError(f"{path} has a row with {len(raw_row)} fields")
        rows.append(
            [_parse_cell(cell, col.type) for cell, col in zip(raw_row, columns)]
        )
    try:
        return Table(name, columns, rows)
    except MicroDBError as exc:
        raise _UsageError(str(exc)) from None


def _render(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _quote(field: str) -> str:
    """Quote only when the field carries a comma, a quote or a newline.

    An empty field stays empty, which is why csv.writer is not used for output:
    it renders a row holding a single empty field as a pair of quote characters.
    """
    if any(ch in field for ch in (",", '"', "\n", "\r")):
        return '"' + field.replace('"', '""') + '"'
    return field


def format_result(result: Result) -> str:
    """Render a result as CSV text, NULL as an empty field."""
    lines = [",".join(_quote(name) for name in result.columns)]
    for row in result.rows:
        lines.append(",".join(_quote(_render(cell)) for cell in row))
    return "".join(line + "\n" for line in lines)


def _load_all(specs: list[str]) -> dict[str, Table]:
    if not specs:
        raise _UsageError("at least one --table is required")
    tables: dict[str, Table] = {}
    for spec in specs:
        if "=" not in spec:
            raise _UsageError(f"--table needs NAME=PATH, got {spec!r}")
        name, _, raw_path = spec.partition("=")
        if not name:
            raise _UsageError(f"--table needs a name, got {spec!r}")
        tables[name] = load_table(name, pathlib.Path(raw_path))
    return tables


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _USAGE_EXIT if exc.code else 0
    try:
        tables = _load_all(args.table)
    except _UsageError as exc:
        print(str(exc), file=sys.stderr)
        return _USAGE_EXIT
    try:
        result = execute(args.query, tables)
    except MicroDBError as exc:
        print(str(exc), file=sys.stderr)
        return _QUERY_EXIT
    sys.stdout.write(format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
