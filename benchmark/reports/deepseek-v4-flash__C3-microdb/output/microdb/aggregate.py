"""Aggregate function implementations."""

from microdb.value import type_of, is_numeric
from microdb.errors import TypeMismatchError, ArityError
from microdb.parser import Star, FunctionCall


def eval_aggregate(
    call: FunctionCall,
    rows: list[list[object]],
    eval_row_fn: object,
) -> object:
    """Evaluate an aggregate function over a list of rows.

    eval_row_fn is a callable(expr, row) -> value that evaluates
    an expression against a single row.
    """
    name = call.name.upper()
    args = call.args

    if name == "COUNT":
        if len(args) != 1:
            raise ArityError(
                f"count requires 1 argument, got {len(args)}"
            )
        if isinstance(args[0], Star):
            return len(rows)
        # count(expr) - count non-NULL values
        count = 0
        for row in rows:
            val = eval_row_fn(args[0], row)
            if val is not None:
                count += 1
        return count

    if name == "SUM":
        if len(args) != 1:
            raise ArityError(f"sum requires 1 argument, got {len(args)}")
        return _numeric_agg(name, args[0], rows, eval_row_fn, "sum")

    if name == "AVG":
        if len(args) != 1:
            raise ArityError(f"avg requires 1 argument, got {len(args)}")
        return _numeric_agg(name, args[0], rows, eval_row_fn, "avg")

    if name == "MIN":
        if len(args) != 1:
            raise ArityError(f"min requires 1 argument, got {len(args)}")
        return _ordered_agg(name, args[0], rows, eval_row_fn, "min")

    if name == "MAX":
        if len(args) != 1:
            raise ArityError(f"max requires 1 argument, got {len(args)}")
        return _ordered_agg(name, args[0], rows, eval_row_fn, "max")

    raise ValueError(f"unknown aggregate: {call.name}")


def _numeric_agg(
    name: str,
    expr: object,
    rows: list[list[object]],
    eval_row_fn: object,
    op: str,
) -> object:
    """Evaluate SUM or AVG over non-NULL values."""
    values: list[object] = []
    for row in rows:
        val = eval_row_fn(expr, row)
        if val is None:
            continue
        t = type_of(val)
        if not is_numeric(val):
            raise TypeMismatchError(
                f"{name} requires numeric, got {t}"
            )
        values.append(val)

    if not values:
        return None  # sum/avg of nothing is NULL

    if op == "sum":
        # sum: INT if all INT, FLOAT otherwise
        all_int = all(isinstance(v, int) for v in values)
        result = sum(values)
        if all_int:
            return result  # int
        return float(result)

    # avg: always FLOAT
    total = sum(float(v) for v in values)
    return total / len(values)


def _ordered_agg(
    name: str,
    expr: object,
    rows: list[list[object]],
    eval_row_fn: object,
    op: str,
) -> object:
    """Evaluate MIN or MAX over non-NULL values."""
    from microdb.value import compare_lt

    found: object = None
    found_type: str | None = None

    for row in rows:
        val = eval_row_fn(expr, row)
        if val is None:
            continue
        vt = type_of(val)
        if found is None:
            found = val
            found_type = vt
        else:
            # Type check: all must be same type (or INT/FLOAT mix)
            if vt != found_type:
                if {vt, found_type} <= {"INT", "FLOAT"}:
                    # Promote to FLOAT for mixing types
                    found_v = float(found) if isinstance(found, int) else found
                    val_v = float(val) if isinstance(val, int) else val
                    if op == "min":
                        found = found_v if found_v < val_v else val_v
                    else:
                        found = found_v if found_v > val_v else val_v
                    found_type = "FLOAT"
                else:
                    raise TypeMismatchError(
                        f"{name} type mismatch: {found_type} vs {vt}"
                    )
            else:
                if op == "min":
                    if compare_lt(val, found) is True:
                        found = val
                else:
                    if compare_lt(found, val) is True:
                        found = val

    return found