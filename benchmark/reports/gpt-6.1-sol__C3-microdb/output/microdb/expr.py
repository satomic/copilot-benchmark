"""Expression binding and evaluation."""

from dataclasses import dataclass, field

from .aggregate import aggregate, check_arity
from .errors import (
    AggregateError, AmbiguousColumnError, ArityError, TypeMismatchError,
    UnknownColumnError, UnknownFunctionError, UnknownTableError,
)
from .parser import AGGREGATES, Binary, Call, Expr, Literal, Reference, Unary, children
from .schema import Column
from .value import and_, arith, compare_eq, compare_lt, is_numeric, key, negate, not_, or_


SCALARS = {"concat": 2, "upper": 1, "lower": 1, "length": 1, "abs": 1, "coalesce": 1}


@dataclass(frozen=True)
class Binding:
    table: str
    column: Column


@dataclass(frozen=True)
class Output(Expr):
    index: int


@dataclass
class Context:
    bindings: list[Binding]
    row: list[object]
    group: list[list[object]] | None = None
    aliases: dict[str, object] = field(default_factory=dict)
    cache: dict[object, object] = field(default_factory=dict)
    output: list[object] = field(default_factory=list)


def resolve(reference: Reference, bindings: list[Binding]) -> int:
    if reference.table is not None and not any(b.table == reference.table for b in bindings):
        raise UnknownTableError(f"Unknown table: {reference.table}")
    matches = [index for index, binding in enumerate(bindings)
               if binding.column.name == reference.name
               and (reference.table is None or binding.table == reference.table)]
    if not matches:
        label = f"{reference.table}." if reference.table else ""
        raise UnknownColumnError(f"Unknown column: {label}{reference.name}")
    if len(matches) > 1:
        raise AmbiguousColumnError(f"Ambiguous column: {reference.name}")
    return matches[0]


def validate_call(call: Call) -> None:
    if call.name in AGGREGATES:
        check_arity(call.name, 1 if call.star else len(call.args), 1)
        return
    if call.name not in SCALARS:
        raise UnknownFunctionError(f"Unknown function: {call.name}")
    minimum = SCALARS[call.name]
    if call.name in ("concat", "coalesce"):
        if len(call.args) < minimum:
            raise ArityError(f"{call.name} expects at least {minimum} arguments, "
                             f"got {len(call.args)}")
    else:
        check_arity(call.name, len(call.args), minimum)


def validate(expr: Expr, bindings: list[Binding], allow_aggregate: bool = True,
             aliases: set[str] | None = None) -> None:
    if isinstance(expr, Reference):
        if expr.table is None and aliases is not None and expr.name in aliases:
            return
        resolve(expr, bindings)
    if isinstance(expr, Call):
        if expr.name in AGGREGATES and not allow_aggregate:
            raise AggregateError("Aggregate is not allowed in this clause")
        validate_call(expr)
    for child in children(expr):
        validate(child, bindings, allow_aggregate, aliases)


def signature(expr: Expr, bindings: list[Binding]) -> object:
    if isinstance(expr, Output):
        return ("output", expr.index)
    if isinstance(expr, Reference):
        return ("ref", resolve(expr, bindings))
    if isinstance(expr, Literal):
        return ("literal", key(expr.value))
    if isinstance(expr, Call):
        return ("call", expr.name, expr.star, tuple(signature(a, bindings) for a in expr.args))
    if isinstance(expr, Unary):
        return ("unary", expr.op, signature(expr.operand, bindings))
    if isinstance(expr, Binary):
        return ("binary", expr.op, signature(expr.left, bindings),
                signature(expr.right, bindings))
    raise TypeMismatchError("Invalid expression node")


def scalar(name: str, args: list[object]) -> object:
    validate_call(Call(0, 0, name.lower(), tuple(Literal(0, 0, arg) for arg in args)))
    name = name.lower()
    if name == "coalesce":
        return next((arg for arg in args if arg is not None), None)
    for arg in args:
        if arg is not None and (not is_numeric(arg) if name == "abs" else type(arg) is not str):
            raise TypeMismatchError(f"{name} requires {'numeric' if name == 'abs' else 'TEXT'} input")
    if any(arg is None for arg in args):
        return None
    if name == "concat":
        return "".join(args)
    if name == "upper":
        return args[0].upper()
    if name == "lower":
        return args[0].lower()
    if name == "length":
        return len(args[0])
    return abs(args[0])


def _binary(op: str, a: object, b: object) -> object:
    if op in ("+", "-", "*", "/", "%"):
        return arith(op, a, b)
    if op == "AND":
        return and_(a, b)
    if op == "OR":
        return or_(a, b)
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
    raise TypeMismatchError(f"Invalid operator: {op}")


def evaluate(expr: Expr, context: Context) -> object:
    if isinstance(expr, Output):
        return context.output[expr.index]
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Reference):
        if expr.table is None and expr.name in context.aliases:
            return context.aliases[expr.name]
        return context.row[resolve(expr, context.bindings)]
    if isinstance(expr, Binary):
        return _binary(expr.op, evaluate(expr.left, context), evaluate(expr.right, context))
    if isinstance(expr, Unary):
        value = evaluate(expr.operand, context)
        if expr.op == "-":
            return negate(value)
        if expr.op == "NOT":
            return not_(value)
        if expr.op == "IS NULL":
            return value is None
        return value is not None
    if isinstance(expr, Call):
        validate_call(expr)
        if expr.name not in AGGREGATES:
            return scalar(expr.name, [evaluate(arg, context) for arg in expr.args])
        if context.group is None:
            raise AggregateError("Aggregate requires a group")
        cache_key = signature(expr, context.bindings)
        if cache_key not in context.cache:
            values = ([1] * len(context.group) if expr.star else
                      [evaluate(expr.args[0], Context(context.bindings, row))
                       for row in context.group])
            context.cache[cache_key] = aggregate(expr.name, values)
        return context.cache[cache_key]
    raise TypeMismatchError("Invalid expression node")
