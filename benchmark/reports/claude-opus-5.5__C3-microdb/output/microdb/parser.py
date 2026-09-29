"""Recursive-descent parser producing a Query AST."""

from __future__ import annotations

import dataclasses
from typing import Callable, TypeVar

from .aggregate import AGGREGATE_NAMES
from .errors import ParseError
from .lexer import Token, tokenize

# ---------------------------------------------------------------- AST nodes


class Expr:
    """Base class of expression nodes."""


@dataclasses.dataclass(frozen=True)
class Literal(Expr):
    value: object
    kind: str  # included so that Literal(1) != Literal(True) != Literal(1.0)


@dataclasses.dataclass(frozen=True)
class ColumnRef(Expr):
    table: str | None
    name: str


@dataclasses.dataclass(frozen=True)
class UnaryMinus(Expr):
    operand: Expr


@dataclasses.dataclass(frozen=True)
class Not(Expr):
    operand: Expr


@dataclasses.dataclass(frozen=True)
class BinaryOp(Expr):
    op: str  # + - * / % = <> < <= > >= AND OR
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class IsNull(Expr):
    operand: Expr
    negated: bool


@dataclasses.dataclass(frozen=True)
class FuncCall(Expr):
    name: str  # lower case
    args: tuple


@dataclasses.dataclass(frozen=True)
class AggCall(Expr):
    name: str  # lower case
    args: tuple
    star: bool  # count(*)


@dataclasses.dataclass(frozen=True)
class SelectItem:
    expr: Expr | None  # None for star items
    alias: str | None
    star: bool
    star_table: str | None
    text: str  # source text, whitespace collapsed


@dataclasses.dataclass(frozen=True)
class JoinClause:
    kind: str  # "INNER" | "LEFT"
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class OrderItem:
    expr: Expr
    descending: bool


@dataclasses.dataclass(frozen=True)
class Query:
    distinct: bool
    items: tuple
    table: str
    join: JoinClause | None
    where: Expr | None
    group_by: tuple
    having: Expr | None
    order_by: tuple
    limit: int | None
    offset: int | None


_T = TypeVar("_T")
_COMPARISONS = ("=", "<>", "<", "<=", ">", ">=")


# ---------------------------------------------------------------- parser


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = tokenize(text)
        self.pos = 0
        self.in_aggregate = False

    # -- token helpers
    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def error(self, message: str, tok: Token | None = None) -> ParseError:
        tok = tok or self.tok
        found = "end of input" if tok.kind == "EOF" else repr(self.text[tok.offset : tok.end])
        return ParseError(f"{message}, found {found}", tok.offset)

    def is_kw(self, *words: str) -> bool:
        return self.tok.kind == "KEYWORD" and self.tok.value in words

    def is_op(self, *ops: str) -> bool:
        return self.tok.kind == "OP" and self.tok.value in ops

    def accept_kw(self, word: str) -> bool:
        if self.is_kw(word):
            self.advance()
            return True
        return False

    def accept_op(self, op: str) -> bool:
        if self.is_op(op):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> Token:
        if not self.is_kw(word):
            raise self.error(f"expected {word}")
        return self.advance()

    def expect_op(self, op: str) -> Token:
        if not self.is_op(op):
            raise self.error(f"expected {op!r}")
        return self.advance()

    def expect_ident(self, what: str) -> str:
        if self.tok.kind != "IDENT":
            raise self.error(f"expected {what}")
        return str(self.advance().value)

    def expect_int(self, what: str) -> int:
        if self.tok.kind != "INT":
            raise self.error(f"expected an integer after {what}")
        return int(self.advance().value)  # type: ignore[arg-type]

    # -- query
    def parse_query(self) -> Query:
        self.expect_kw("SELECT")
        distinct = self.accept_kw("DISTINCT")
        items = self.parse_list(self.parse_select_item)
        self.expect_kw("FROM")
        table = self.expect_ident("a table name")
        join = self.parse_join()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        group_by: list = []
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            group_by = self.parse_list(self.parse_expr)
        having = self.parse_expr() if self.accept_kw("HAVING") else None
        order_by: list = []
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            order_by = self.parse_list(self.parse_order_item)
        limit = self.expect_int("LIMIT") if self.accept_kw("LIMIT") else None
        offset = self.expect_int("OFFSET") if self.accept_kw("OFFSET") else None
        if self.tok.kind != "EOF":
            raise self.error("unexpected token")
        return Query(distinct, tuple(items), table, join, where, tuple(group_by),
                     having, tuple(order_by), limit, offset)

    def parse_list(self, parse_one: Callable[[], _T]) -> list[_T]:
        items = [parse_one()]
        while self.accept_op(","):
            items.append(parse_one())
        return items

    def parse_join(self) -> JoinClause | None:
        kind = "INNER"
        if self.accept_kw("LEFT"):
            kind = "LEFT"
        elif not self.accept_kw("INNER") and not self.is_kw("JOIN"):
            return None
        self.expect_kw("JOIN")
        table = self.expect_ident("a table name")
        self.expect_kw("ON")
        return JoinClause(kind, table, self.parse_expr())

    def parse_select_item(self) -> SelectItem:
        start = self.tok
        if self.accept_op("*"):
            return SelectItem(None, None, True, None, "*")
        nxt = self.tokens[self.pos + 1 : self.pos + 3]
        if (start.kind == "IDENT" and len(nxt) == 2 and nxt[0].value == "."
                and nxt[0].kind == "OP" and nxt[1].kind == "OP" and nxt[1].value == "*"):
            self.pos += 3
            return SelectItem(None, None, True, str(start.value), f"{start.value}.*")
        expr = self.parse_expr()
        end = self.tokens[self.pos - 1].end
        text = " ".join(self.text[start.offset : end].split())
        alias = self.expect_ident("an alias after AS") if self.accept_kw("AS") else None
        return SelectItem(expr, alias, False, None, text)

    def parse_order_item(self) -> OrderItem:
        expr = self.parse_expr()
        if self.accept_kw("DESC"):
            return OrderItem(expr, True)
        self.accept_kw("ASC")
        return OrderItem(expr, False)

    # -- expressions
    def parse_expr(self) -> Expr:
        left = self.parse_and()
        while self.accept_kw("OR"):
            left = BinaryOp("OR", left, self.parse_and())
        return left

    def parse_and(self) -> Expr:
        left = self.parse_not()
        while self.accept_kw("AND"):
            left = BinaryOp("AND", left, self.parse_not())
        return left

    def parse_not(self) -> Expr:
        if self.accept_kw("NOT"):
            return Not(self.parse_not())
        return self.parse_predicate()

    def parse_predicate(self) -> Expr:
        left = self.parse_additive()
        if self.is_op(*_COMPARISONS):
            op = str(self.advance().value)
            left = BinaryOp(op, left, self.parse_additive())
        elif self.accept_kw("IS"):
            negated = self.accept_kw("NOT")
            self.expect_kw("NULL")
            left = IsNull(left, negated)
        else:
            return left
        if self.is_op(*_COMPARISONS) or self.is_kw("IS"):
            raise self.error("comparison operators are not associative")
        return left

    def parse_additive(self) -> Expr:
        left = self.parse_multiplicative()
        while self.is_op("+", "-"):
            op = str(self.advance().value)
            left = BinaryOp(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self) -> Expr:
        left = self.parse_unary()
        while self.is_op("*", "/", "%"):
            op = str(self.advance().value)
            left = BinaryOp(op, left, self.parse_unary())
        return left

    def parse_unary(self) -> Expr:
        if self.accept_op("-"):
            return UnaryMinus(self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        tok = self.tok
        if tok.kind in ("INT", "FLOAT", "TEXT"):
            self.advance()
            return Literal(tok.value, tok.kind)
        if tok.kind == "KEYWORD" and tok.value in ("TRUE", "FALSE", "NULL"):
            self.advance()
            if tok.value == "NULL":
                return Literal(None, "NULL")
            return Literal(tok.value == "TRUE", "BOOL")
        if tok.kind == "IDENT":
            return self.parse_identifier()
        if self.accept_op("("):
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        raise self.error("expected an expression")

    def parse_identifier(self) -> Expr:
        tok = self.advance()
        name = str(tok.value)
        if self.accept_op("("):
            return self.parse_call(tok)
        if self.accept_op("."):
            column = self.expect_ident("a column name after '.'")
            return ColumnRef(name, column)
        return ColumnRef(None, name)

    def parse_call(self, name_tok: Token) -> Expr:
        name = str(name_tok.value).lower()
        is_agg = name in AGGREGATE_NAMES
        if is_agg and self.in_aggregate:
            raise ParseError(f"aggregate {name}() may not be nested", name_tok.offset)
        if self.is_op("*"):
            if name != "count":
                raise self.error(f"'*' is only allowed in count(*), not {name}()")
            self.advance()
            self.expect_op(")")
            return AggCall(name, (), True)
        saved = self.in_aggregate
        self.in_aggregate = saved or is_agg
        try:
            args = [] if self.is_op(")") else self.parse_list(self.parse_expr)
        finally:
            self.in_aggregate = saved
        self.expect_op(")")
        if is_agg:
            return AggCall(name, tuple(args), False)
        return FuncCall(name, tuple(args))


def parse(text: str) -> Query:
    """Parse a query string into a Query."""
    return _Parser(text).parse_query()
