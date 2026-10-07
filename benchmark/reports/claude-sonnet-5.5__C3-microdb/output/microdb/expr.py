"""Expression binding and evaluation, plus scalar functions."""

from typing import Callable

from .aggregate import AGGREGATES
from .errors import (AggregateError, ArityError, TypeMismatchError,
                     UnknownColumnError, UnknownFunctionError)
from .parser import (Binary, BoundColumn, Call, ColumnRef, IsNull, Literal,
                     OutColumn, Unary)
from .value import (and_, arith, compare_eq, compare_lt, negate, not_, or_,
                    type_of)


def _need_text(name: str, v: object) -> None:
    if v is not None and not isinstance(v, str):
        raise TypeMismatchError(f"{name}() needs TEXT, got {type_of(v)}")


def _concat(args: list[object]) -> object:
    for v in args:
        _need_text("concat", v)
    if any(v is None for v in args):
        return None
    return "".join(args)  # type: ignore[arg-type]


def _upper(args: list[object]) -> object:
    _need_text("upper", args[0])
    return None if args[0] is None else args[0].upper()  # type: ignore[union-attr]


def _lower(args: list[object]) -> object:
    _need_text("lower", args[0])
    return None if args[0] is None else args[0].lower()  # type: ignore[union-attr]


def _length(args: list[object]) -> object:
    _need_text("length", args[0])
    return None if args[0] is None else len(args[0])  # type: ignore[arg-type]


def _abs(args: list[object]) -> object:
    v = args[0]
    if v is None:
        return None
    if type_of(v) not in ("INT", "FLOAT"):
        raise TypeMismatchError(f"abs() needs a number, got {type_of(v)}")
    return abs(v)  # type: ignore[arg-type]


def _coalesce(args: list[object]) -> object:
    for v in args:
        if v is not None:
            return v
    return None


# name -> (min args, max args or None, implementation)
_SCALARS: dict[str, tuple[int, int | None, Callable[[list[object]], object]]] = {
    "concat": (2, None, _concat),
    "upper": (1, 1, _upper),
    "lower": (1, 1, _lower),
    "length": (1, 1, _length),
    "abs": (1, 1, _abs),
    "coalesce": (1, None, _coalesce),
}


def validate_call(name: str, argc: int) -> None:
    if name in AGGREGATES:
        return
    if name not in _SCALARS:
        raise UnknownFunctionError(f"unknown function {name!r}")
    low, high, _ = _SCALARS[name]
    if argc < low or (high is not None and argc > high):
        if high is None:
            need = f"at least {low}"
        else:
            need = f"exactly {low}"
        raise ArityError(f"{name}() takes {need} argument(s), got {argc}")


def is_aggregate(node: object) -> bool:
    return isinstance(node, Call) and node.name in AGGREGATES


def children(node: object) -> tuple:
    if isinstance(node, Unary):
        return (node.operand,)
    if isinstance(node, Binary):
        return (node.left, node.right)
    if isinstance(node, IsNull):
        return (node.operand,)
    if isinstance(node, Call):
        return node.args
    return ()


def contains_aggregate(node: object) -> bool:
    return is_aggregate(node) or any(contains_aggregate(c) for c in children(node))


def collect_aggregates(node: object, found: list[Call]) -> None:
    if is_aggregate(node):
        if node not in found:
            found.append(node)  # type: ignore[arg-type]
        return
    for child in children(node):
        collect_aggregates(child, found)


def rewrite(node: object, fn: Callable[[object], object | None]) -> object:
    """Top-down rewrite: fn returns a replacement, or None to recurse."""
    replaced = fn(node)
    if replaced is not None:
        return replaced
    if isinstance(node, Unary):
        return Unary(node.op, rewrite(node.operand, fn))
    if isinstance(node, Binary):
        return Binary(node.op, rewrite(node.left, fn), rewrite(node.right, fn))
    if isinstance(node, IsNull):
        return IsNull(rewrite(node.operand, fn), node.negated)
    if isinstance(node, Call):
        return Call(node.name, tuple(rewrite(a, fn) for a in node.args), node.star)
    return node


def bind(node: object, resolve: Callable[[ColumnRef], object]) -> object:
    """Resolve column references and validate function calls."""
    def step(n: object) -> object | None:
        if isinstance(n, ColumnRef):
            return resolve(n)
        if isinstance(n, Call):
            validate_call(n.name, len(n.args))
        return None
    return rewrite(node, step)


def _logical(v: object) -> bool | None:
    if v is not None and not isinstance(v, bool):
        raise TypeMismatchError(f"expected BOOL, got {type_of(v)}")
    return v


_COMPARE: dict[str, Callable[[object, object], bool | None]] = {
    "=": compare_eq,
    "<>": lambda a, b: not_(compare_eq(a, b)),
    "<": compare_lt,
    ">": lambda a, b: compare_lt(b, a),
    "<=": lambda a, b: not_(compare_lt(b, a)),
    ">=": lambda a, b: not_(compare_lt(a, b)),
}


def _eval_binary(node: Binary, row: list | None, out: list | None,
                 aggs: dict | None) -> object:
    left = evaluate(node.left, row, out, aggs)
    right = evaluate(node.right, row, out, aggs)
    if node.op == "AND":
        return and_(_logical(left), _logical(right))
    if node.op == "OR":
        return or_(_logical(left), _logical(right))
    if node.op in _COMPARE:
        return _COMPARE[node.op](left, right)
    return arith(node.op, left, right)


def _eval_call(node: Call, row: list | None, out: list | None,
               aggs: dict | None) -> object:
    if node.name in AGGREGATES:
        if aggs is None or node not in aggs:
            raise AggregateError(f"aggregate {node.name}() is not allowed here")
        return aggs[node]
    validate_call(node.name, len(node.args))
    args = [evaluate(a, row, out, aggs) for a in node.args]
    return _SCALARS[node.name][2](args)


def evaluate(node: object, row: list | None, out: list | None = None,
             aggs: dict | None = None) -> object:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, BoundColumn):
        return row[node.index]  # type: ignore[index]
    if isinstance(node, OutColumn):
        return out[node.index]  # type: ignore[index]
    if isinstance(node, Unary):
        value = evaluate(node.operand, row, out, aggs)
        return negate(value) if node.op == "-" else not_(_logical(value))
    if isinstance(node, Binary):
        return _eval_binary(node, row, out, aggs)
    if isinstance(node, IsNull):
        is_null = evaluate(node.operand, row, out, aggs) is None
        return (not is_null) if node.negated else is_null
    if isinstance(node, Call):
        return _eval_call(node, row, out, aggs)
    if isinstance(node, ColumnRef):
        raise UnknownColumnError(f"unbound column {node.name!r}")
    raise TypeError(f"cannot evaluate {node!r}")
