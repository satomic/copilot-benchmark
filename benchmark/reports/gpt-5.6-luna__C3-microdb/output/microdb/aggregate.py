from .errors import TypeMismatchError
from .expr import Expr, Call
from .value import is_numeric, compare_lt, type_of


def aggregate(expr: Call, rows: list[dict[str, object]]) -> object:
    name = expr.name.lower()
    if name == "count" and expr.args and getattr(expr.args[0], "value", None) == "*":
        return len(rows)
    vals = [expr.args[0].eval(r) for r in rows] if expr.args else []
    vals = [v for v in vals if v is not None]
    if name == "count":
        return len(vals)
    if not vals:
        return None
    if name in {"sum", "avg"} and not all(is_numeric(v) for v in vals):
        raise TypeMismatchError(f"{name} requires numeric input")
    if name == "sum":
        result = sum(vals)
        return result if all(isinstance(v, int) and not isinstance(v, bool) for v in vals) else float(result)
    if name == "avg":
        return float(sum(vals)) / len(vals)
    result = vals[0]
    for value in vals[1:]:
        less = compare_lt(value, result)
        if (name == "min" and less) or (name == "max" and less is False):
            result = value
    return result


def eval_group(expr: Expr, rows: list[dict[str, object]]) -> object:
    if isinstance(expr, Call) and expr.name.lower() in {"count", "sum", "avg", "min", "max"}:
        return aggregate(expr, rows)
    from .expr import Binary, Unary, IsNull
    if isinstance(expr, (Binary, Unary, IsNull)):
        if isinstance(expr, Unary):
            return type(expr)(expr.op, _group_child(expr.child, rows), expr.text).eval({})
        if isinstance(expr, IsNull):
            return type(expr)(_group_child(expr.child, rows), expr.negated, expr.text).eval({})
        return type(expr)(expr.op, _group_child(expr.left, rows), _group_child(expr.right, rows), expr.text).eval({})
    if isinstance(expr, Call):
        vals = [eval_group(a, rows) for a in expr.args]
        return type(expr)(expr.name, [type("_", (), {"eval": lambda self, r, v=v: v, "aggregate": False})() for v in vals], expr.text).eval({})
    return expr.eval(rows[0] if rows else {})


def _group_child(expr: Expr, rows: list[dict[str, object]]) -> Expr:
    value = eval_group(expr, rows)
    return type("_Value", (), {"eval": lambda self, row, v=value: v, "aggregate": False})()
