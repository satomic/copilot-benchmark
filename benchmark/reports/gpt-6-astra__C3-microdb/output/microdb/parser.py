"""Recursive-descent parser for the fixed-order microdb query language."""

from dataclasses import dataclass
import re

from .aggregate import AGGREGATES
from .errors import ParseError
from .expr import (Binary, Call, Expr, IsNull, Literal, Ref, Star, Unary,
                   has_aggregate)
from .lexer import Token, tokenize


@dataclass(frozen=True)
class SelectItem:
    expr: Expr
    alias: str | None
    text: str


@dataclass(frozen=True)
class Join:
    table: str
    kind: str
    on: Expr


@dataclass(frozen=True)
class OrderItem:
    expr: Expr
    descending: bool = False


@dataclass(frozen=True)
class Query:
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


class _Parser:
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
            raise ParseError(f"Expected {kind}, got {self.current.kind}",
                             self.current.offset)
        return token

    def query(self) -> Query:
        self.expect("SELECT")
        distinct = self.accept("DISTINCT") is not None
        items = [self.select_item()]
        while self.accept(","):
            items.append(self.select_item())
        self.expect("FROM")
        table = self.expect("IDENT").value
        join = self.join_clause()
        where = self.or_expr() if self.accept("WHERE") else None
        group = []
        if self.accept("GROUP"):
            self.expect("BY")
            group.append(self.or_expr())
            while self.accept(","):
                group.append(self.or_expr())
        having = self.or_expr() if self.accept("HAVING") else None
        order = []
        if self.accept("ORDER"):
            self.expect("BY")
            order.append(self.order_item())
            while self.accept(","):
                order.append(self.order_item())
        limit = self.expect("INT").value if self.accept("LIMIT") else None
        offset = self.expect("INT").value if self.accept("OFFSET") else 0
        self.expect("EOF")
        return Query(tuple(items), table, distinct, join, where, tuple(group),
                     having, tuple(order), limit, offset)

    def join_clause(self) -> Join | None:
        if self.current.kind not in ("INNER", "LEFT", "JOIN"):
            return None
        kind = "INNER"
        if self.current.kind != "JOIN":
            kind = self.current.kind
            self.position += 1
        self.expect("JOIN")
        table = self.expect("IDENT").value
        self.expect("ON")
        return Join(table, kind, self.or_expr())

    def select_item(self) -> SelectItem:
        start = self.current.offset
        if self.accept("*"):
            expr = Star()
        elif (self.current.kind == "IDENT"
              and self.tokens[self.position + 1].kind == "."
              and self.tokens[self.position + 2].kind == "*"):
            expr = Star(self.current.value)
            self.position += 3
        else:
            expr = self.or_expr()
        end = self.tokens[self.position - 1].end
        text = re.sub(r"\s+", " ", self.source[start:end])
        alias = None
        if not isinstance(expr, Star) and self.accept("AS"):
            alias = self.expect("IDENT").value
        return SelectItem(expr, alias, text)

    def order_item(self) -> OrderItem:
        expr = self.or_expr()
        descending = self.accept("DESC") is not None
        if not descending:
            self.accept("ASC")
        return OrderItem(expr, descending)

    def or_expr(self) -> Expr:
        expr = self.and_expr()
        while self.accept("OR"):
            expr = Binary("OR", expr, self.and_expr())
        return expr

    def and_expr(self) -> Expr:
        expr = self.not_expr()
        while self.accept("AND"):
            expr = Binary("AND", expr, self.not_expr())
        return expr

    def not_expr(self) -> Expr:
        if self.accept("NOT"):
            return Unary("NOT", self.not_expr())
        return self.predicate()

    def predicate(self) -> Expr:
        expr = self.additive()
        if self.current.kind in ("=", "<>", "<", "<=", ">", ">="):
            op = self.current.kind
            self.position += 1
            return Binary(op, expr, self.additive())
        if self.accept("IS"):
            negated = self.accept("NOT") is not None
            self.expect("NULL")
            return IsNull(expr, negated)
        return expr

    def additive(self) -> Expr:
        expr = self.multiplicative()
        while self.current.kind in ("+", "-"):
            op = self.current.kind
            self.position += 1
            expr = Binary(op, expr, self.multiplicative())
        return expr

    def multiplicative(self) -> Expr:
        expr = self.unary()
        while self.current.kind in ("*", "/", "%"):
            op = self.current.kind
            self.position += 1
            expr = Binary(op, expr, self.unary())
        return expr

    def unary(self) -> Expr:
        if self.accept("-"):
            return Unary("-", self.unary())
        return self.primary()

    def primary(self) -> Expr:
        token = self.current
        if token.kind in ("INT", "FLOAT", "TEXT", "TRUE", "FALSE", "NULL"):
            self.position += 1
            value = {"TRUE": True, "FALSE": False, "NULL": None}.get(
                token.kind, token.value)
            return Literal(value)
        if self.accept("("):
            expr = self.or_expr()
            self.expect(")")
            return expr
        if self.accept("IDENT"):
            name = token.value
            if self.accept("("):
                return self.call(name, token.offset)
            if self.accept("."):
                return Ref(self.expect("IDENT").value, name)
            return Ref(name)
        raise ParseError(f"Expected expression, got {token.kind}", token.offset)

    def call(self, name: str, offset: int) -> Call:
        args = []
        if self.current.kind == "*":
            if name.lower() != "count":
                raise ParseError("Only count(*) accepts a wildcard", self.current.offset)
            self.position += 1
            args.append(Star())
        elif self.current.kind != ")":
            args.append(self.or_expr())
            while self.accept(","):
                args.append(self.or_expr())
        self.expect(")")
        if name.lower() in AGGREGATES and any(has_aggregate(arg) for arg in args):
            raise ParseError("Aggregates may not nest", offset)
        return Call(name.lower(), tuple(args))


def parse(source: str) -> Query:
    return _Parser(source).query()
