from .parser import Expr
from .errors import TypeMismatchError, UnknownFunctionError, ArityError, AggregateError
from .value import (
    compare_eq, compare_lt, arith, negate, type_of, and_, or_, not_,
    is_numeric
)


def _eval_comparison(op: str, left: object, right: object) -> bool | None:
    """Evaluate a comparison operation."""
    if op == "=":
        return compare_eq(left, right)
    if op == "<>":
        return not_(compare_eq(left, right))
    if op == "<":
        return compare_lt(left, right)
    if op == "<=":
        eq = compare_eq(left, right)
        lt = compare_lt(left, right)
        return None if (eq is None and lt is None) else (eq or lt)
    if op == ">":
        return compare_lt(right, left)
    if op == ">=":
        eq = compare_eq(left, right)
        lt = compare_lt(right, left)
        return None if (eq is None and lt is None) else (eq or lt)
    return None


def evaluate(expr: Expr, row: dict[str, object], is_aggregate_context: bool = False) -> object:
    """Evaluate an expression in a row context."""
    if expr.type == "lit":
        return expr.value
    if expr.type == "col":
        if expr.col_name not in row:
            raise KeyError(f"Column '{expr.col_name}' not found")
        return row[expr.col_name]
    if expr.type == "cmp":
        left = evaluate(expr.left, row, is_aggregate_context)
        right = evaluate(expr.right, row, is_aggregate_context)
        return _eval_comparison(expr.value, left, right)
    if expr.type == "arith":
        left = evaluate(expr.left, row, is_aggregate_context)
        right = evaluate(expr.right, row, is_aggregate_context)
        return arith(expr.value, left, right)
    if expr.type == "neg":
        val = evaluate(expr.left, row, is_aggregate_context)
        return negate(val)
    if expr.type == "and":
        left = evaluate(expr.left, row, is_aggregate_context)
        right = evaluate(expr.right, row, is_aggregate_context)
        return and_(left, right)
    if expr.type == "or":
        left = evaluate(expr.left, row, is_aggregate_context)
        right = evaluate(expr.right, row, is_aggregate_context)
        return or_(left, right)
    if expr.type == "not":
        val = evaluate(expr.left, row, is_aggregate_context)
        return not_(val)
    if expr.type == "is_null":
        val = evaluate(expr.left, row, is_aggregate_context)
        return val is None
    if expr.type == "is_not_null":
        val = evaluate(expr.left, row, is_aggregate_context)
        return val is not None
    if expr.type == "call":
        if is_aggregate_context:
            raise AggregateError(f"Cannot use function {expr.value} in aggregate context")
        return evaluate_call(expr.value, expr.args or [], row)
    raise ValueError(f"Unknown expression type: {expr.type}")


def _eval_func_concat(args: list[Expr], row: dict[str, object]) -> str:
    if len(args) < 2:
        raise ArityError(f"concat() takes at least 2 arguments, got {len(args)}", "concat", 2)
    result = ""
    for arg in args:
        val = evaluate(arg, row)
        if val is None:
            return None
        if not isinstance(val, str):
            raise TypeMismatchError(f"concat() requires TEXT arguments")
        result += val
    return result


def _eval_func_text(func_name: str, args: list[Expr], row: dict[str, object]) -> object:
    if len(args) != 1:
        raise ArityError(f"{func_name}() takes 1 argument, got {len(args)}", func_name, 1)
    val = evaluate(args[0], row)
    if val is None:
        return None
    if not isinstance(val, str):
        raise TypeMismatchError(f"{func_name}() requires TEXT argument")
    if func_name == "upper":
        return val.upper()
    return val.lower()


def _eval_func_length(args: list[Expr], row: dict[str, object]) -> object:
    if len(args) != 1:
        raise ArityError(f"length() takes 1 argument, got {len(args)}", "length", 1)
    val = evaluate(args[0], row)
    return None if val is None else len(val) if isinstance(val, str) else None


def _eval_func_abs(args: list[Expr], row: dict[str, object]) -> object:
    if len(args) != 1:
        raise ArityError(f"abs() takes 1 argument, got {len(args)}", "abs", 1)
    val = evaluate(args[0], row)
    if val is None:
        return None
    if not is_numeric(val):
        raise TypeMismatchError(f"abs() requires numeric argument")
    return abs(val)


def _eval_func_coalesce(args: list[Expr], row: dict[str, object]) -> object:
    if len(args) < 1:
        raise ArityError(f"coalesce() takes at least 1 argument, got {len(args)}", "coalesce", 1)
    for arg in args:
        val = evaluate(arg, row)
        if val is not None:
            return val
    return None


def evaluate_call(func_name: str, args: list[Expr], row: dict[str, object]) -> object:
    """Evaluate a function call."""
    func_lower = func_name.lower()
    if func_lower == "concat":
        return _eval_func_concat(args, row)
    if func_lower in ("upper", "lower"):
        return _eval_func_text(func_lower, args, row)
    if func_lower == "length":
        return _eval_func_length(args, row)
    if func_lower == "abs":
        return _eval_func_abs(args, row)
    if func_lower == "coalesce":
        return _eval_func_coalesce(args, row)
    raise UnknownFunctionError(f"Unknown function: {func_name}")


def is_aggregate_expr(expr: Expr) -> bool:
    """Check if an expression contains an aggregate function."""
    if expr is None:
        return False
    if expr.type == "call":
        func_name = expr.value.lower()
        return func_name in ("count", "sum", "avg", "min", "max")
    if expr.left and is_aggregate_expr(expr.left):
        return True
    if expr.right and is_aggregate_expr(expr.right):
        return True
    if expr.args:
        return any(is_aggregate_expr(arg) for arg in expr.args)
    return False


def expr_to_string(expr: Expr) -> str:
    """Convert an expression to string for column naming."""
    if expr.type == "lit":
        return str(expr.value)
    if expr.type == "col":
        if expr.col_table:
            return f"{expr.col_table}.{expr.col_name}"
        return expr.col_name
    if expr.type == "call":
        args_str = ", ".join(expr_to_string(arg) for arg in (expr.args or []))
        return f"{expr.value}({args_str})"
    if expr.type == "cmp":
        return f"{expr_to_string(expr.left)} {expr.value} {expr_to_string(expr.right)}"
    if expr.type == "arith":
        return f"{expr_to_string(expr.left)} {expr.value} {expr_to_string(expr.right)}"
    if expr.type == "neg":
        return f"-{expr_to_string(expr.left)}"
    if expr.type == "and":
        return f"{expr_to_string(expr.left)} AND {expr_to_string(expr.right)}"
    if expr.type == "or":
        return f"{expr_to_string(expr.left)} OR {expr_to_string(expr.right)}"
    if expr.type == "not":
        return f"NOT {expr_to_string(expr.left)}"
    if expr.type == "is_null":
        return f"{expr_to_string(expr.left)} IS NULL"
    if expr.type == "is_not_null":
        return f"{expr_to_string(expr.left)} IS NOT NULL"
    return str(expr)
