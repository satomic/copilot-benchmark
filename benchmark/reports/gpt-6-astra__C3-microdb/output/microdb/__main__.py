"""CSV command-line interface; buffers results before writing any output."""

import argparse
import csv
import re
import sys

from .errors import MicroDBError, SchemaError
from .executor import Result, execute
from .lexer import KEYWORDS
from .schema import Column, Table


def _columns(header: list[str]) -> list[Column]:
    columns = []
    for field in header:
        parts = field.split(":")
        if (len(parts) != 2 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parts[0])
                or parts[0].upper() in KEYWORDS
                or parts[1] not in ("INT", "FLOAT", "TEXT", "BOOL")):
            raise ValueError(f"Malformed header field: {field!r}")
        columns.append(Column(parts[0], parts[1]))
    if not columns or len({column.name for column in columns}) != len(columns):
        raise ValueError("Malformed header: empty or duplicate columns")
    return columns


def _cell(text: str, column: Column) -> object:
    if text == "":
        return None
    if text == "''":
        return ""
    try:
        if column.type == "INT":
            if not re.fullmatch(r"[+-]?[0-9]+", text):
                raise ValueError("not an integer")
            return int(text)
        if column.type == "FLOAT":
            return float(text)
        if column.type == "BOOL":
            if text.lower() not in ("true", "false"):
                raise ValueError("not a boolean")
            return text.lower() == "true"
        return text
    except ValueError as error:
        raise SchemaError(f"Invalid {column.type} cell in {column.name}: {text!r}") from error


def _load(name: str, path: str) -> Table:
    with open(path, encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        try:
            header = next(reader)
        except (StopIteration, csv.Error) as error:
            raise ValueError("Missing or malformed CSV header") from error
        columns = _columns(header)
        rows = []
        try:
            for row in reader:
                # csv.reader represents a blank single-NULL record as [].
                if not row and len(columns) == 1:
                    row = [""]
                if len(row) != len(columns):
                    raise SchemaError("CSV row length does not match header")
                rows.append([_cell(text, column) for text, column in zip(row, columns)])
        except csv.Error as error:
            raise SchemaError(f"Malformed CSV row: {error}") from error
    return Table(name, columns, rows)


def _quote(value: object) -> str:
    if value is None:
        text = ""
    elif type(value) is bool:
        text = "true" if value else "false"
    else:
        text = str(value)
    if any(char in text for char in (",", '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def _render(result: Result) -> str:
    rows = [result.columns, *result.rows]
    return "".join(",".join(_quote(value) for value in row) + "\n" for row in rows)


def _arguments(argv: list[str] | None) -> argparse.Namespace | int:
    parser = argparse.ArgumentParser(prog="microdb")
    parser.add_argument("--table", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("query", metavar="QUERY")
    try:
        return parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if isinstance(args, int):
        return args
    try:
        tables = {}
        for specification in args.table:
            name, separator, path = specification.partition("=")
            if (not separator or not path
                    or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                    or name.upper() in KEYWORDS or name in tables):
                raise ValueError(f"Invalid or duplicate table specification: {specification}")
            tables[name] = _load(name, path)
        output = _render(execute(args.query, tables))
    except (OSError, UnicodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except MicroDBError as error:
        print(str(error), file=sys.stderr)
        return 3
    # Avoid Windows text-mode CRLF translation; record separators are always LF.
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(output.encode("utf-8"))
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
