import argparse
import csv
import sys
from .errors import MicroDBError, SchemaError
from .executor import execute
from .schema import Column, Table


def _table(spec: str) -> tuple[str, Table]:
    if "=" not in spec:
        raise ValueError("table must be NAME=PATH")
    name, path = spec.split("=", 1)
    with open(path, newline="", encoding="utf-8") as handle:
        records = list(csv.reader(handle))
    if not records:
        raise ValueError("empty CSV")
    try:
        columns = [Column(*field.split(":", 1)) for field in records[0]]
        rows = [[_convert(v, c.type) for v, c in zip(row, columns)] for row in records[1:]]
        return name, Table(name, columns, rows)
    except (ValueError, IndexError, SchemaError) as exc:
        raise ValueError("malformed CSV") from exc


def _convert(value: str, typ: str) -> object:
    if value == "":
        return None
    if typ == "INT": return int(value)
    if typ == "FLOAT": return float(value)
    if typ == "BOOL":
        if value.lower() not in {"true", "false"}: raise ValueError("bool")
        return value.lower() == "true"
    return value[2:-2] if value.startswith("''") and value.endswith("''") else value


def _field(value: object) -> str:
    if value is None: return ""
    text = str(value).lower() if isinstance(value, bool) else str(value)
    if any(c in text for c in ',\"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--table", action="append", required=True)
    parser.add_argument("query")
    try:
        args = parser.parse_args(argv)
        tables = dict(_table(spec) for spec in args.table)
        result = execute(args.query, tables)
        lines = [",".join(_field(x) for x in result.columns)]
        lines += [",".join(_field(x) for x in row) for row in result.rows]
        sys.stdout.write("\n".join(lines) + "\n")
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except (OSError, ValueError) as exc:
        sys.stderr.write(str(exc) + "\n"); return 2
    except MicroDBError as exc:
        sys.stderr.write(str(exc) + "\n"); return 3


if __name__ == "__main__":
    raise SystemExit(main())
