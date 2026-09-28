from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .errors import MicroDBError
from .executor import execute
from .schema import Column, Table


class _ArgumentParser(argparse.ArgumentParser):
    def error(self: _ArgumentParser, message: str) -> None:
        raise ValueError(message)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = _ArgumentParser(prog="microdb")
    parser.add_argument("--table", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("query")
    return parser.parse_args(argv)


def _load_table(specification: str) -> tuple[str, Table]:
    if "=" not in specification:
        raise ValueError("--table must be NAME=PATH")
    name, path = specification.split("=", 1)
    if not name or not path:
        raise ValueError("--table must be NAME=PATH")
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if not header or any(":" not in field for field in header):
                raise ValueError(f"malformed header in {path}")
            columns = [_parse_column(field, path) for field in header]
            rows = [[_parse_cell(value, column.type) for value, column in zip(row, columns)]
                    for row in reader]
            if any(len(row) != len(columns) for row in rows):
                raise ValueError(f"malformed row in {path}")
    except csv.Error as exc:
        raise ValueError(f"malformed CSV in {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    return name, Table(name, columns, rows)


def _parse_column(field: str, path: str) -> Column:
    name, separator, kind = field.partition(":")
    if not separator or not name or kind not in {"INT", "FLOAT", "TEXT", "BOOL"}:
        raise ValueError(f"malformed header in {path}")
    return Column(name, kind)


def _parse_cell(value: str, kind: str) -> object:
    if value == "":
        return None
    if kind == "TEXT":
        return value
    if kind == "BOOL":
        if value.lower() not in {"true", "false"}:
            raise ValueError(f"invalid BOOL value: {value}")
        return value.lower() == "true"
    try:
        return int(value) if kind == "INT" else float(value)
    except ValueError as exc:
        raise ValueError(f"invalid {kind} value: {value}") from exc


def _render(value: object) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _csv_field(value: object) -> str:
    text = _render(value)
    if any(character in text for character in ',\"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def _write_result(columns: list[str], rows: list[list[object]]) -> None:
    for record in [columns, *rows]:
        sys.stdout.write(",".join(_csv_field(value) for value in record) + "\n")


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _arguments(argv)
        tables: dict[str, Table] = {}
        for specification in arguments.table:
            name, table = _load_table(specification)
            if name in tables:
                raise ValueError(f"duplicate table: {name}")
            tables[name] = table
    except SystemExit as exc:
        return int(exc.code or 0)
    except MicroDBError as exc:
        print(f"microdb: {exc}", file=sys.stderr)
        return 2
    except (ValueError, argparse.ArgumentError) as exc:
        print(f"microdb: {exc}", file=sys.stderr)
        return 2
    try:
        result = execute(arguments.query, tables)
        _write_result(result.columns, result.rows)
    except MicroDBError as exc:
        print(f"microdb: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
