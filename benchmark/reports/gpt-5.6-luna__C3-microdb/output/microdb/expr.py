from dataclasses import dataclass
from typing import Any
from .errors import (ArityError, AggregateError, UnknownColumnError, UnknownFunctionError,
                     TypeMismatchError)
from .value import and_, arith, compare_eq, compare_lt, negate, not_, or_, type_of


class Expr:
    text: str
    aggregate: bool = False
    def eval(self, row: dict[str, object]) -> object:
        raise NotImplementedError


@dataclass
class Literal(Expr):
    value: object
    text: str
    def eval(self, row: dict[str, object]) -> object:
        return self.value


@dataclass
class ColumnRef(Expr):
    name: str
    table: str | None
    text: str
    def eval(self, row: dict[str, object]) -> object:
        key = f"{self.table}.{self.name}" if self.table else self.name
        if key in row:
            return row[key]
        matches = [v for k, v in row.items() if k.endswith("." + self.name)]
        if self.table is None and len(matches) == 1:
            return matches[0]
        if self.table is None and len(matches) > 1:
            from .errors import AmbiguousColumnError
            raise AmbiguousColumnError(self.name)
        if key not in row:
            raise UnknownColumnError(key)
        return row[key]


@dataclass
class Unary(Expr):
    op: str
    child: Expr
    text: str
    @property
    def aggregate(self) -> bool:
        return self.child.aggregate
    def eval(self, row: dict[str, object]) -> object:
        value = self.child.eval(row)
        return not_(value) if self.op == "NOT" else negate(value)


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr
    text: str
    @property
    def aggregate(self) -> bool:
        return self.left.aggregate or self.right.aggregate
    def eval(self, row: dict[str, object]) -> object:
        a, b = self.left.eval(row), self.right.eval(row)
        if self.op == "AND": return and_(a, b)
        if self.op == "OR": return or_(a, b)
        if self.op == "=": return compare_eq(a, b)
        if self.op == "<>": return None if compare_eq(a, b) is None else not compare_eq(a, b)
        if self.op in {"<", "<=", ">", ">="}:
            lt, eq = compare_lt(a, b), compare_eq(a, b)
            if self.op == "<": return lt
            if self.op == ">": return None if lt is None else not (lt or eq)
            if self.op == "<=": return None if lt is None else lt or eq
            return None if lt is None else not lt
        return arith(self.op, a, b)


@dataclass
class IsNull(Expr):
    child: Expr
    negated: bool
    text: str
    @property
    def aggregate(self) -> bool:
        return self.child.aggregate
    def eval(self, row: dict[str, object]) -> object:
        result = self.child.eval(row) is None
        return not result if self.negated else result


@dataclass
class Call(Expr):
    name: str
    args: list[Expr]
    text: str
    @property
    def aggregate(self) -> bool:
        return self.name.lower() in {"count", "sum", "avg", "min", "max"} or any(a.aggregate for a in self.args)
    def eval(self, row: dict[str, object]) -> object:
        name = self.name.lower()
        if name in {"count", "sum", "avg", "min", "max"}:
            raise AggregateError("aggregate requires group evaluation")
        vals = [a.eval(row) for a in self.args]
        if name == "concat":
            _arity(name, len(vals), 2, None)
            return None if any(v is None for v in vals) else _text(vals)
        if name in {"upper", "lower"}:
            _arity(name, len(vals), 1, 1)
            if vals[0] is None: return None
            _need(vals[0], "TEXT")
            return vals[0].upper() if name == "upper" else vals[0].lower()
        if name == "length":
            _arity(name, len(vals), 1, 1)
            if vals[0] is None: return None
            _need(vals[0], "TEXT"); return len(vals[0])
        if name == "abs":
            _arity(name, len(vals), 1, 1)
            if vals[0] is None: return None
            if type_of(vals[0]) not in {"INT", "FLOAT"}: raise TypeMismatchError("abs needs numeric")
            return abs(vals[0])
        if name == "coalesce":
            _arity(name, len(vals), 1, None)
            return next((v for v in vals if v is not None), None)
        raise UnknownFunctionError(self.name)


def _arity(name: str, got: int, low: int, high: int | None) -> None:
    if got < low or high is not None and got > high:
        expected = str(low) if high == low else f"{low}+"
        raise ArityError(f"{name}: expected {expected}, got {got}")


def _need(value: object, typ: str) -> None:
    if type_of(value) != typ:
        raise TypeMismatchError(f"expected {typ}")


def _text(values: list[object]) -> str:
    for v in values:
        if v is not None and type_of(v) != "TEXT":
            raise TypeMismatchError("concat needs text")
    return "".join(values)
