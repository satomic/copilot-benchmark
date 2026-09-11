"""Expression nodes and evaluation shared by all execution stages."""

from collections.abc import Callable
from dataclasses import dataclass, field

from .aggregate import AGGREGATES, aggregate, check_arity
from .errors import (AggregateError, ArityError, TypeMismatchError,
                     UnknownColumnError, UnknownFunctionError)
from .value import (and_, arith, compare_eq, compare_lt, is_numeric, logical,
                    negate, not_, or_, type_of)


class Expr:
    pass


@dataclass(frozen=True)
class Literal(Expr):
    value: object


@dataclass(frozen=True)
class Ref(Expr):
    name: str
    table: str | None = None


@dataclass(frozen=True)
class BoundRef(Expr):
    index: int


@dataclass(frozen=True)
class OutputRef(Expr):
    index: int


@dataclass(frozen=True)
class Star(Expr):
    table: str | None = None


@dataclass(frozen=True)
class Unary(Expr):
    op: str
    arg: Expr


@dataclass(frozen=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class IsNull(Expr):
    arg: Expr
    negated: bool = False


@dataclass(frozen=True)
class Call(Expr):
    name: str
    args: tuple[Expr, ...]


@dataclass
class Context:
    row: list[object]
    group: list[list[object]] | None = None
    output: list[object] | None = None
    aggregates: dict[tuple, object] = field(default_factory=dict)


def children(expr: Expr) -> tuple[Expr, ...]:
    if isinstance(expr, (Unary, IsNull)):
        return (expr.arg,)
    if isinstance(expr, Binary):
        return (expr.left, expr.right)
    if isinstance(expr, Call):
        return expr.args
    return ()


def transform(expr: Expr, visit: Callable[[Expr], Expr | None]) -> Expr:
    replacement = visit(expr)
    if replacement is not None:
        return replacement
    if isinstance(expr, Unary):
        return Unary(expr.op, transform(expr.arg, visit))
    if isinstance(expr, IsNull):
        return IsNull(transform(expr.arg, visit), expr.negated)
    if isinstance(expr, Binary):
        return Binary(expr.op, transform(expr.left, visit), transform(expr.right, visit))
    if isinstance(expr, Call):
        return Call(expr.name, tuple(transform(arg, visit) for arg in expr.args))
    return expr


def expression_key(expr: Expr) -> tuple:
    if isinstance(expr, Literal):
        return ("literal", type_of(expr.value), expr.value)
    if isinstance(expr, Ref):
        return ("ref", expr.table, expr.name)
    if isinstance(expr, (BoundRef, OutputRef)):
        return (type(expr).__name__, expr.index)
    if isinstance(expr, Star):
        return ("star", expr.table)
    if isinstance(expr, Call):
        return ("call", expr.name.lower(), tuple(map(expression_key, expr.args)))
    if isinstance(expr, IsNull):
        return ("isnull", expr.negated, expression_key(expr.arg))
    if isinstance(expr, (Unary, Binary)):
        return (expr.op, tuple(map(expression_key, children(expr))))
    raise TypeError(f"Unknown expression: {expr!r}")


def has_aggregate(expr: Expr) -> bool:
    return (isinstance(expr, Call) and expr.name.lower() in AGGREGATES
            or any(has_aggregate(child) for child in children(expr)))


def validate_call(call: Call) -> None:
    name, actual = call.name.lower(), len(call.args)
    if name in AGGREGATES:
        check_arity(name, actual, any(isinstance(arg, Star) for arg in call.args))
        return
    arities = {"concat": (2, None), "upper": (1, 1), "lower": (1, 1),
               "length": (1, 1), "abs": (1, 1), "coalesce": (1, None)}
    if name not in arities:
        raise UnknownFunctionError(f"Unknown function: {call.name}")
    minimum, maximum = arities[name]
    if actual < minimum or (maximum is not None and actual > maximum):
        expected = str(minimum) if maximum else f"at least {minimum}"
        raise ArityError(f"{name} expects {expected} arguments; got {actual}")


def scalar(name: str, args: list[object]) -> object:
    name = name.lower()
    validate_call(Call(name, tuple(Literal(arg) for arg in args)))
    if name == "coalesce":
        return next((arg for arg in args if arg is not None), None)
    if name == "abs":
        if args[0] is None:
            return None
        if not is_numeric(args[0]):
            raise TypeMismatchError("abs requires numeric input")
        return abs(args[0])
    if any(arg is not None and type(arg) is not str for arg in args):
        raise TypeMismatchError(f"{name} requires TEXT input")
    if any(arg is None for arg in args):
        return None
    if name == "concat":
        return "".join(args)
    if name == "upper":
        return args[0].upper()
    if name == "lower":
        return args[0].lower()
    return len(args[0])


def _binary(op: str, a: object, b: object) -> object:
    if op in ("+", "-", "*", "/", "%"):
        return arith(op, a, b)
    if op == "AND":
        return and_(logical(a), logical(b))
    if op == "OR":
        return or_(logical(a), logical(b))
    if op == "=":
        return compare_eq(a, b)
    if op == "<>":
        return not_(compare_eq(a, b))
    if op == "<":
        return compare_lt(a, b)
    if op == ">":
        return compare_lt(b, a)
    if op == "<=":
        return not_(compare_lt(b, a))
    if op == ">=":
        return not_(compare_lt(a, b))
    raise ValueError(f"Unknown binary operator: {op}")


def _call(call: Call, context: Context) -> object:
    validate_call(call)
    name = call.name.lower()
    if name in AGGREGATES:
        if context.group is None:
            raise AggregateError(f"{name} requires a group")
        key = expression_key(call)
        if key not in context.aggregates:
            if isinstance(call.args[0], Star):
                result = len(context.group)
            else:
                values = (evaluate(call.args[0], Context(row)) for row in context.group)
                result = aggregate(name, values)
            context.aggregates[key] = result
        return context.aggregates[key]
    if name == "coalesce":
        for arg in call.args:
            value = evaluate(arg, context)
            if value is not None:
                return value
        return None
    return scalar(name, [evaluate(arg, context) for arg in call.args])


def evaluate(expr: Expr, context: Context) -> object:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, BoundRef):
        return context.row[expr.index]
    if isinstance(expr, OutputRef):
        if context.output is None:
            raise UnknownColumnError("Output column is not available at this stage")
        return context.output[expr.index]
    if isinstance(expr, Ref):
        raise UnknownColumnError(f"Unbound column: {expr.name}")
    if isinstance(expr, Unary):
        value = evaluate(expr.arg, context)
        return not_(logical(value)) if expr.op == "NOT" else negate(value)
    if isinstance(expr, IsNull):
        result = evaluate(expr.arg, context) is None
        return not result if expr.negated else result
    if isinstance(expr, Binary):
        return _binary(expr.op, evaluate(expr.left, context),
                       evaluate(expr.right, context))
    if isinstance(expr, Call):
        return _call(expr, context)
    raise TypeMismatchError("Wildcard cannot be evaluated as an expression")
