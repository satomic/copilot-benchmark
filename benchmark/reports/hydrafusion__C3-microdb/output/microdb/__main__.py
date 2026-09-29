import csv
import sys
from pathlib import Path

from .errors import MicroDBError, SchemaError
from .executor import Result, execute
from .schema import Column, Table


class UsageError(Exception):
    pass


def _arguments(argv: list[str]) -> tuple[list[str], str]:
    specs: list[str] = []
    query: str | None = None
    index = 0
    while index < len(argv):
        if argv[index] == "--table":
            if index + 1 >= len(argv):
                raise UsageError("--table requires NAME=PATH")
            specs.append(argv[index + 1])
            index += 2
        elif query is None:
            query = argv[index]
            index += 1
        else:
            raise UsageError("unexpected argument")
    if not specs or query is None:
        raise UsageError("usage: microdb --table NAME=PATH QUERY")
    return specs, query


def _header(row: list[str]) -> list[Column]:
    if not row:
        raise UsageError("malformed CSV header")
    columns: list[Column] = []
    for field in row:
        if field.count(":") != 1:
            raise UsageError("malformed CSV header")
        name, kind = field.split(":")
        if not name or kind not in {"INT", "FLOAT", "TEXT", "BOOL"}:
            raise UsageError("malformed CSV header")
        columns.append(Column(name, kind))
    if len({column.name for column in columns}) != len(columns):
        raise UsageError("malformed CSV header")
    return columns


def _cell(raw: str, kind: str) -> object:
    if raw == "":
        return None
    if kind == "TEXT":
        return "" if raw == "''" else raw
    if kind == "INT":
        return int(raw)
    if kind == "FLOAT":
        return float(raw)
    if raw.lower() not in {"true", "false"}:
        raise SchemaError(f"invalid BOOL value: {raw}")
    return raw.lower() == "true"


def _load(spec: str) -> tuple[str, Table]:
    if "=" not in spec:
        raise UsageError("--table requires NAME=PATH")
    name, filename = spec.split("=", 1)
    if not name or not filename:
        raise UsageError("--table requires NAME=PATH")
    try:
        with Path(filename).open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream, strict=True))
    except (OSError, UnicodeError, csv.Error) as error:
        raise UsageError(f"cannot read table {name}: {error}") from error
    if not rows:
        raise UsageError("malformed CSV header")
    columns = _header(rows[0])
    if any(len(row) != len(columns) for row in rows[1:]):
        raise SchemaError(f"row in table {name} has the wrong length")
    try:
        values = [
            [_cell(raw, column.type) for raw, column in zip(row, columns)]
            for row in rows[1:]
        ]
    except ValueError as error:
        raise SchemaError(f"invalid value in table {name}: {error}") from error
    return name, Table(name, columns, values)


def _field(value: object) -> str:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = str(value).lower()
    else:
        text = str(value)
    if any(character in text for character in ',\"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def _render(result: Result) -> str:
    lines = [",".join(_field(name) for name in result.columns)]
    lines.extend(",".join(_field(value) for value in row) for row in result.rows)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        specs, query = _arguments(arguments)
        loaded = [_load(spec) for spec in specs]
        tables = dict(loaded)
        if len(tables) != len(loaded):
            raise UsageError("duplicate table name")
        output = _render(execute(query, tables))
    except UsageError as error:
        print(error, file=sys.stderr)
        return 2
    except MicroDBError as error:
        print(error, file=sys.stderr)
        return 3
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
