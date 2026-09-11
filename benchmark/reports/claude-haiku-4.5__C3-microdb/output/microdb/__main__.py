import sys
import csv
import io
from .schema import Table, Column
from . import execute
from .errors import MicroDBError


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI."""
    if argv is None:
        argv = sys.argv[1:]
    
    if not argv:
        return 2
    
    tables = {}
    query = None
    i = 0
    
    while i < len(argv):
        if argv[i] == "--table" and i + 1 < len(argv):
            table_def = argv[i + 1]
            if "=" not in table_def:
                return 2
            name, path = table_def.split("=", 1)
            try:
                table = _load_csv(name, path)
                tables[name] = table
            except (FileNotFoundError, IOError):
                return 2
            except Exception:
                return 2
            i += 2
        else:
            query = argv[i]
            i += 1
            break
    
    if query is None:
        return 2
    
    if i < len(argv):
        return 2
    
    try:
        result = execute(query, tables)
        _write_csv(result)
        return 0
    except MicroDBError as e:
        sys.stderr.write(str(e) + "\n")
        return 3
    except Exception as e:
        sys.stderr.write(str(e) + "\n")
        return 3


def _load_csv(name: str, path: str) -> Table:
    """Load a CSV file as a table."""
    with open(path, "r") as f:
        reader = csv.reader(f)
        header = next(reader)
        
        columns = []
        for col_def in header:
            if ":" not in col_def:
                raise ValueError(f"Invalid column definition: {col_def}")
            col_name, col_type = col_def.split(":", 1)
            columns.append(Column(name=col_name, type=col_type))
        
        rows = []
        for row_data in reader:
            row = []
            for i, cell in enumerate(row_data):
                col_type = columns[i].type
                if not cell:
                    row.append(None)
                elif col_type == "INT":
                    row.append(int(cell))
                elif col_type == "FLOAT":
                    row.append(float(cell))
                elif col_type == "TEXT":
                    row.append(cell)
                elif col_type == "BOOL":
                    if cell.lower() == "true":
                        row.append(True)
                    elif cell.lower() == "false":
                        row.append(False)
                    else:
                        raise ValueError(f"Invalid BOOL value: {cell}")
                else:
                    raise ValueError(f"Unknown type: {col_type}")
            rows.append(row)
    
    return Table(name, columns, rows)


def _write_csv(result: object) -> None:
    """Write result as CSV to stdout."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    
    writer.writerow(result.columns)
    
    for row in result.rows:
        output_row = []
        for cell in row:
            if cell is None:
                output_row.append("")
            elif isinstance(cell, bool):
                output_row.append("true" if cell else "false")
            else:
                output_row.append(str(cell))
        writer.writerow(output_row)
    
    sys.stdout.write(buffer.getvalue())


if __name__ == "__main__":
    sys.exit(main())
