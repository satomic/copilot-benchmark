from collections.abc import Callable
from dataclasses import dataclass, field

from .errors import ArityError, TypeMismatchError, UnknownFunctionError
from .value import arith, compare_eq, compare_lt, negate, not_, and_, or_

AGGREGATES = {"count", "sum", "avg", "min", "max"}


@dataclass(frozen=True)
class Expr:
    source: str = field(compare=False)


@dataclass(frozen=True)
class Literal(Expr):
    value: object


@dataclass(frozen=True)
class ColumnRef(Expr):
    name: str
    table: str | None = None


@dataclass(frozen=True)
class Star(Expr):
    table: str | None = None


@dataclass(frozen=True)
class Unary(Expr):
    op: str
    operand: Expr


@dataclass(frozen=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class IsNull(Expr):
    operand: Expr
    negated: bool


@dataclass(frozen=True)
class Call(Expr):
    name: str
    args: tuple[Expr, ...]


Resolver = Callable[[ColumnRef], object]
AggregateResolver = Callable[[Call], object]


def contains_aggregate(expression: Expr) -> bool:
    if isinstance(expression, Call):
        return expression.name.lower() in AGGREGATES or any(
            contains_aggregate(arg) for arg in expression.args
        )
    if isinstance(expression, Unary):
        return contains_aggregate(expression.operand)
    if isinstance(expression, Binary):
        return contains_aggregate(expression.left) or contains_aggregate(expression.right)
    if isinstance(expression, IsNull):
        return contains_aggregate(expression.operand)
    return False


def _arity(name: str, actual: int, minimum: int, maximum: int | None) -> None:
    valid = actual >= minimum and (maximum is None or actual <= maximum)
    if not valid:
        expected = str(minimum) if minimum == maximum else (
            f"at least {minimum}" if maximum is None else f"{minimum} to {maximum}"
        )
        raise ArityError(f"{name} expects {expected} arguments, got {actual}")


def _text_function(name: str, args: list[object]) -> object:
    _arity(name, len(args), 1, 1)
    value = args[0]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeMismatchError(f"{name} requires TEXT")
    if name == "upper":
        return value.upper()
    if name == "lower":
        return value.lower()
    return len(value)


def scalar_call(name: str, args: list[object]) -> object:
    lowered = name.lower()
    if lowered == "coalesce":
        _arity(name, len(args), 1, None)
        return next((value for value in args if value is not None), None)
    if lowered == "concat":
        _arity(name, len(args), 2, None)
        if any(value is None for value in args):
            return None
        if any(not isinstance(value, str) for value in args):
            raise TypeMismatchError("concat requires TEXT arguments")
        return "".join(args)  # type: ignore[arg-type]
    if lowered in {"upper", "lower", "length"}:
        return _text_function(lowered, args)
    if lowered == "abs":
        _arity(name, len(args), 1, 1)
        if args[0] is None:
            return None
        if isinstance(args[0], bool) or not isinstance(args[0], (int, float)):
            raise TypeMismatchError("abs requires a numeric argument")
        return abs(args[0])
    raise UnknownFunctionError(f"unknown function: {name}")


def _comparison(op: str, left: object, right: object) -> bool | None:
    if op == "=":
        return compare_eq(left, right)
    if op == "<>":
        result = compare_eq(left, right)
        return None if result is None else not result
    if op == "<":
        return compare_lt(left, right)
    if op == ">":
        return compare_lt(right, left)
    less = compare_lt(left, right) if op == "<=" else compare_lt(right, left)
    equal = compare_eq(left, right)
    return or_(less, equal)


def evaluate(
    expression: Expr,
    resolver: Resolver,
    aggregate_resolver: AggregateResolver | None = None,
) -> object:
    if isinstance(expression, Literal):
        return expression.value
    if isinstance(expression, ColumnRef):
        return resolver(expression)
    if isinstance(expression, Unary):
        value = evaluate(expression.operand, resolver, aggregate_resolver)
        return negate(value) if expression.op == "-" else not_(_logical(value))
    if isinstance(expression, IsNull):
        result = evaluate(expression.operand, resolver, aggregate_resolver) is None
        return not result if expression.negated else result
    if isinstance(expression, Binary):
        left = evaluate(expression.left, resolver, aggregate_resolver)
        right = evaluate(expression.right, resolver, aggregate_resolver)
        if expression.op in {"+", "-", "*", "/", "%"}:
            return arith(expression.op, left, right)
        if expression.op == "AND":
            return and_(_logical(left), _logical(right))
        if expression.op == "OR":
            return or_(_logical(left), _logical(right))
        return _comparison(expression.op, left, right)
    if isinstance(expression, Call):
        if expression.name.lower() in AGGREGATES:
            if aggregate_resolver is None:
                raise TypeMismatchError("aggregate outside a group")
            return aggregate_resolver(expression)
        args = [evaluate(arg, resolver, aggregate_resolver) for arg in expression.args]
        return scalar_call(expression.name, args)
    raise TypeMismatchError("invalid expression")


def _logical(value: object) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise TypeMismatchError("logical expression requires BOOL")
