"""CSV command-line interface."""

import argparse
import csv
import io
import re
import sys

from .errors import MicroDBError, SchemaError
from .executor import Result, execute
from .lexer import IDENTIFIER, KEYWORDS
from .schema import Column, Table


class UsageError(Exception):
    pass


class Arguments(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def _identifier(name: str) -> bool:
    return IDENTIFIER.fullmatch(name) is not None and name.upper() not in KEYWORDS


def _header(fields: list[str]) -> list[Column]:
    columns = []
    for field in fields:
        parts = field.split(":")
        if (len(parts) != 2 or not _identifier(parts[0])
                or parts[1] not in ("INT", "FLOAT", "TEXT", "BOOL")):
            raise UsageError(f"Malformed header field: {field}")
        columns.append(Column(*parts))
    if not columns or len({column.name for column in columns}) != len(columns):
        raise UsageError("Malformed header: missing or duplicate columns")
    return columns


def _cell(text: str, column: Column) -> object:
    if text == "":
        return None
    if text == "''":
        if column.type != "TEXT":
            raise SchemaError(f"Empty string is not valid {column.type}")
        return ""
    if column.type == "TEXT":
        return text
    if column.type == "BOOL":
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
        raise SchemaError(f"Invalid BOOL field: {text}")
    try:
        if column.type == "INT":
            if re.fullmatch(r"[+-]?[0-9]+", text) is None:
                raise ValueError("not an integer")
            return int(text)
        return float(text)
    except ValueError as error:
        raise SchemaError(f"Invalid {column.type} field: {text}") from error


def _load(spec: str) -> Table:
    name, separator, path = spec.partition("=")
    if not separator or not _identifier(name) or not path:
        raise UsageError(f"Expected NAME=PATH, got {spec}")
    try:
        with open(path, encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            try:
                header = next(reader)
            except (StopIteration, csv.Error) as error:
                raise UsageError("Missing or malformed CSV header") from error
            columns = _header(header)
            rows = []
            for fields in reader:
                # A blank physical record represents one NULL in a one-column CSV.
                if not fields and len(columns) == 1:
                    fields = [""]
                if len(fields) != len(columns):
                    raise SchemaError("CSV row length does not match header")
                rows.append([_cell(text, column) for text, column in zip(fields, columns)])
    except (OSError, UnicodeError) as error:
        raise UsageError(f"Cannot read {path}: {error}") from error
    except csv.Error as error:
        raise SchemaError(f"Malformed CSV data: {error}") from error
    return Table(name, columns, rows)


def _field(value: object) -> str:
    text = "" if value is None else str(value).lower() if type(value) is bool else str(value)
    if any(char in text for char in (",", '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def _render(result: Result) -> str:
    lines = [",".join(_field(name) for name in result.columns)]
    lines.extend(",".join(_field(value) for value in row) for row in result.rows)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = Arguments(prog="microdb")
    parser.add_argument("--table", action="append", default=[])
    parser.add_argument("query")
    try:
        args = parser.parse_args(argv)
        if not args.table:
            raise UsageError("At least one --table is required")
        tables = {}
        for spec in args.table:
            table = _load(spec)
            if table.name in tables:
                raise UsageError(f"Duplicate table: {table.name}")
            tables[table.name] = table
        output = _render(execute(args.query, tables))
    except UsageError as error:
        print(str(error), file=sys.stderr)
        return 2
    except MicroDBError as error:
        print(str(error), file=sys.stderr)
        return 3
    except SystemExit as error:
        return int(error.code)
    # Suppress Windows newline translation without replacing a caller's test stream.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(newline="\n")
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
