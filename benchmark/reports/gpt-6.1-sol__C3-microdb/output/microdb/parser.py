"""Handwritten recursive-descent parser and immutable syntax nodes."""

from dataclasses import dataclass, field, replace
from collections.abc import Callable

from .errors import ParseError
from .lexer import Token, tokenize


AGGREGATES = frozenset(("count", "sum", "avg", "min", "max"))


@dataclass(frozen=True)
class Expr:
    start: int = field(compare=False)
    end: int = field(compare=False)


@dataclass(frozen=True)
class Literal(Expr):
    value: object


@dataclass(frozen=True)
class Reference(Expr):
    name: str
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
class Call(Expr):
    name: str
    args: tuple[Expr, ...]
    star: bool = False


@dataclass(frozen=True)
class SelectItem:
    expr: Expr | None
    alias: str | None = None
    wildcard_table: str | None = None


@dataclass(frozen=True)
class Join:
    kind: str
    table: str
    on: Expr


@dataclass(frozen=True)
class OrderItem:
    expr: Expr
    descending: bool = False


@dataclass(frozen=True)
class Query:
    source: str
    select: tuple[SelectItem, ...]
    table: str
    distinct: bool = False
    join: Join | None = None
    where: Expr | None = None
    group_by: tuple[Expr, ...] = ()
    having: Expr | None = None
    order_by: tuple[OrderItem, ...] = ()
    limit: int | None = None
    offset: int = 0


def children(expr: Expr) -> tuple[Expr, ...]:
    if isinstance(expr, Binary):
        return (expr.left, expr.right)
    if isinstance(expr, Unary):
        return (expr.operand,)
    if isinstance(expr, Call):
        return expr.args
    return ()


def has_aggregate(expr: Expr) -> bool:
    return (isinstance(expr, Call) and expr.name in AGGREGATES
            or any(has_aggregate(child) for child in children(expr)))


class Parser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens = tokenize(source)
        self.position = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.position]

    def accept(self, kind: str) -> Token | None:
        if self.current.kind != kind:
            return None
        token = self.current
        self.position += 1
        return token

    def expect(self, kind: str) -> Token:
        token = self.accept(kind)
        if token is None:
            raise ParseError(f"Expected {kind}, got {self.current.kind}", self.current.offset)
        return token

    def query(self) -> Query:
        self.expect("SELECT")
        distinct = self.accept("DISTINCT") is not None
        select = [self.select_item()]
        while self.accept(","):
            select.append(self.select_item())
        self.expect("FROM")
        table = self.expect("IDENT").value
        join = self.join()
        where = self.expression() if self.accept("WHERE") else None
        group = []
        if self.accept("GROUP"):
            self.expect("BY")
            group.append(self.expression())
            while self.accept(","):
                group.append(self.expression())
        having = self.expression() if self.accept("HAVING") else None
        order = []
        if self.accept("ORDER"):
            self.expect("BY")
            order.append(self.order_item())
            while self.accept(","):
                order.append(self.order_item())
        limit = self.expect("INT").value if self.accept("LIMIT") else None
        offset = self.expect("INT").value if self.accept("OFFSET") else 0
        self.expect("EOF")
        return Query(self.source, tuple(select), table, distinct, join, where,
                     tuple(group), having, tuple(order), limit, offset)

    def join(self) -> Join | None:
        kind = "INNER"
        explicit = False
        if self.current.kind in ("INNER", "LEFT"):
            kind = self.current.kind
            self.position += 1
            explicit = True
        if explicit:
            self.expect("JOIN")
        elif not self.accept("JOIN"):
            return None
        table = self.expect("IDENT").value
        self.expect("ON")
        return Join(kind, table, self.expression())

    def select_item(self) -> SelectItem:
        if self.accept("*"):
            return SelectItem(None)
        if (self.current.kind == "IDENT"
                and self.tokens[self.position + 1].kind == "."
                and self.tokens[self.position + 2].kind == "*"):
            table = self.current.value
            self.position += 3
            return SelectItem(None, wildcard_table=table)
        expr = self.expression()
        alias = self.expect("IDENT").value if self.accept("AS") else None
        return SelectItem(expr, alias)

    def order_item(self) -> OrderItem:
        expr = self.expression()
        descending = self.accept("DESC") is not None
        if not descending:
            self.accept("ASC")
        return OrderItem(expr, descending)

    def expression(self) -> Expr:
        return self.chain(self.and_expr, ("OR",))

    def and_expr(self) -> Expr:
        return self.chain(self.not_expr, ("AND",))

    def chain(self, operand: Callable[[], Expr], operators: tuple[str, ...]) -> Expr:
        left = operand()
        while self.current.kind in operators:
            op = self.current.kind
            self.position += 1
            right = operand()
            left = Binary(left.start, right.end, op, left, right)
        return left

    def not_expr(self) -> Expr:
        token = self.accept("NOT")
        if token:
            operand = self.not_expr()
            return Unary(token.offset, operand.end, "NOT", operand)
        return self.predicate()

    def predicate(self) -> Expr:
        left = self.additive()
        if self.current.kind in ("=", "<>", "<", "<=", ">", ">="):
            op = self.current.kind
            self.position += 1
            right = self.additive()
            return Binary(left.start, right.end, op, left, right)
        if self.accept("IS"):
            inverted = self.accept("NOT") is not None
            end = self.expect("NULL").end
            return Unary(left.start, end, "IS NOT NULL" if inverted else "IS NULL", left)
        return left

    def additive(self) -> Expr:
        return self.chain(self.multiplicative, ("+", "-"))

    def multiplicative(self) -> Expr:
        return self.chain(self.unary, ("*", "/", "%"))

    def unary(self) -> Expr:
        token = self.accept("-")
        if token:
            operand = self.unary()
            return Unary(token.offset, operand.end, "-", operand)
        return self.primary()

    def primary(self) -> Expr:
        token = self.current
        if token.kind in ("INT", "FLOAT", "TEXT", "TRUE", "FALSE", "NULL"):
            self.position += 1
            value = {"TRUE": True, "FALSE": False, "NULL": None}.get(token.kind, token.value)
            return Literal(token.offset, token.end, value)
        if self.accept("("):
            expr = self.expression()
            end = self.expect(")").end
            return replace(expr, start=token.offset, end=end)
        if self.accept("IDENT"):
            if self.accept("("):
                return self.call(token)
            if self.accept("."):
                name = self.expect("IDENT")
                return Reference(token.offset, name.end, name.value, token.value)
            return Reference(token.offset, token.end, token.value)
        raise ParseError(f"Expected expression, got {token.kind}", token.offset)

    def call(self, token: Token) -> Call:
        name = token.value.lower()
        args = []
        star = self.accept("*") is not None
        if star and name != "count":
            raise ParseError("Only count(*) accepts a star argument", token.offset)
        if not star and self.current.kind != ")":
            args.append(self.expression())
            while self.accept(","):
                args.append(self.expression())
        end = self.expect(")").end
        if name in AGGREGATES and any(has_aggregate(arg) for arg in args):
            raise ParseError("Aggregates cannot nest", token.offset)
        return Call(token.offset, end, name, tuple(args), star)


def parse(source: str) -> Query:
    return Parser(source).query()
