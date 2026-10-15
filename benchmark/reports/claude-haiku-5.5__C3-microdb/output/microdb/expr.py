"""Expression evaluation over a row environment, with scalar functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator

from .aggregate import AGGREGATE_NAMES
from .errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    GroupingError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from .parser import Binary, Call, Col, Expr, IsNull, Lit, Unary
from .value import and_, arith, as_logical, compare, is_numeric, negate, not_, or_, type_of

CMP_OPS = frozenset({"=", "<>", "<", "<=", ">", ">="})


def _label(qualifier: str | None, name: str) -> str:
    return f"{qualifier}.{name}" if qualifier else name


@dataclass(frozen=True)
class Scope:
    """Ordered (table, column) pairs describing the layout of a working row."""

    entries: tuple[tuple[str, str], ...]

    def resolve(self, qualifier: str | None, name: str) -> int:
        if qualifier is not None:
            if qualifier not in {t for t, _ in self.entries}:
                raise UnknownTableError(f"unknown table {qualifier!r}")
            hits = [i for i, e in enumerate(self.entries) if e == (qualifier, name)]
        else:
            hits = [i for i, (_, c) in enumerate(self.entries) if c == name]
        if not hits:
            raise UnknownColumnError(f"unknown column {_label(qualifier, name)!r}")
        if len(hits) > 1:
            raise AmbiguousColumnError(f"ambiguous column {name!r}")
        return hits[0]


@dataclass(frozen=True)
class Env:
    """Evaluation context.

    keys is None outside grouping. In a grouped context it maps grouping
    expressions and aggregate calls to their values for the current group.
    aliases holds SELECT output values; only ORDER BY sees them.
    members holds the rows of the group, used when computing aggregates.
    """

    row: list
    scope: Scope | None
    keys: dict | None = None
    aliases: dict = field(default_factory=dict)
    members: tuple = ()


def evaluate(node: Expr, env: Env) -> object:
    if isinstance(node, Col) and node.qualifier is None and node.name in env.aliases:
        return env.aliases[node.name]
    if env.keys is not None and node in env.keys:
        return env.keys[node]
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, Col):
        return _column(node, env)
    if isinstance(node, Unary):
        return _unary(node, env)
    if isinstance(node, Binary):
        return _binary(node, env)
    if isinstance(node, IsNull):
        result = evaluate(node.operand, env) is None
        return not result if node.negated else result
    return _call(node, env)


def _column(node: Col, env: Env) -> object:
    label = _label(node.qualifier, node.name)
    if env.keys is not None:
        raise GroupingError(f"column {label!r} must appear in GROUP BY or inside an aggregate")
    if env.scope is None:
        raise UnknownColumnError(f"column {label!r} is not available after DISTINCT")
    return env.row[env.scope.resolve(node.qualifier, node.name)]


def _unary(node: Unary, env: Env) -> object:
    value = evaluate(node.operand, env)
    if node.op == "not":
        return not_(as_logical(value))
    return negate(value)


def _binary(node: Binary, env: Env) -> object:
    if node.op in ("and", "or"):
        left = as_logical(evaluate(node.left, env))
        right = as_logical(evaluate(node.right, env))
        return and_(left, right) if node.op == "and" else or_(left, right)
    left_value = evaluate(node.left, env)
    right_value = evaluate(node.right, env)
    if node.op in CMP_OPS:
        return compare(node.op, left_value, right_value)
    return arith(node.op, left_value, right_value)


def _call(node: Call, env: Env) -> object:
    if node.name in AGGREGATE_NAMES:
        raise AggregateError(f"aggregate {node.name}() is not allowed here")
    args = [evaluate(arg, env) for arg in node.args]
    return SCALARS[node.name][2](args)


def children(node: Expr) -> tuple:
    if isinstance(node, Unary):
        return (node.operand,)
    if isinstance(node, Binary):
        return (node.left, node.right)
    if isinstance(node, IsNull):
        return (node.operand,)
    if isinstance(node, Call):
        return tuple(node.args)
    return ()


def iter_nodes(node: Expr) -> Iterator[Expr]:
    """Yield node and all of its descendants, depth first."""
    yield node
    for child in children(node):
        yield from iter_nodes(child)


def _expected(lo: int, hi: int | None) -> str:
    if hi is None:
        return f"at least {lo}"
    if lo == hi:
        return str(lo)
    return f"{lo} to {hi}"


def check_call(node: Call) -> None:
    """Static check of a call's name and argument count."""
    n = len(node.args)
    if node.name in AGGREGATE_NAMES:
        if not node.star and n != 1:
            raise ArityError(f"{node.name}() expects 1 argument(s), got {n}")
        return
    if node.name not in SCALARS:
        raise UnknownFunctionError(f"unknown function {node.name}()")
    lo, hi, _ = SCALARS[node.name]
    if n < lo or (hi is not None and n > hi):
        raise ArityError(f"{node.name}() expects {_expected(lo, hi)} argument(s), got {n}")


def _check_text(name: str, values: list[object]) -> None:
    for v in values:
        if v is not None and not isinstance(v, str):
            raise TypeMismatchError(f"{name}() requires TEXT arguments, got {type_of(v)}")


def _concat(args: list[object]) -> object:
    _check_text("concat", args)
    if any(a is None for a in args):
        return None
    return "".join(args)  # type: ignore[arg-type]


def _text_fn(name: str, fn: Callable[[str], object]) -> Callable[[list[object]], object]:
    def run(args: list[object]) -> object:
        _check_text(name, args)
        return None if args[0] is None else fn(args[0])  # type: ignore[arg-type]
    return run


def _abs(args: list[object]) -> object:
    value = args[0]
    if value is not None and not is_numeric(value):
        raise TypeMismatchError(f"abs() requires a numeric argument, got {type_of(value)}")
    return None if value is None else abs(value)  # type: ignore[arg-type]


def _coalesce(args: list[object]) -> object:
    return next((a for a in args if a is not None), None)


SCALARS: dict[str, tuple[int, int | None, Callable[[list[object]], object]]] = {
    "concat": (2, None, _concat),
    "upper": (1, 1, _text_fn("upper", str.upper)),
    "lower": (1, 1, _text_fn("lower", str.lower)),
    "length": (1, 1, _text_fn("length", len)),
    "abs": (1, 1, _abs),
    "coalesce": (1, None, _coalesce),
}
