"""Recursive-descent parser producing a Query AST."""

from __future__ import annotations

import dataclasses
from typing import Optional

from .aggregate import AGGREGATE_NAMES
from .errors import ArityError, ParseError
from .lexer import Token, tokenize

# --- AST ----------------------------------------------------------------------


class Expr:
    """Base class of expression nodes."""


@dataclasses.dataclass(frozen=True)
class Literal(Expr):
    value: object


@dataclasses.dataclass(frozen=True)
class ColumnRef(Expr):
    table: Optional[str]
    name: str


@dataclasses.dataclass(frozen=True)
class FuncCall(Expr):
    name: str  # lower-cased
    args: tuple[Expr, ...]
    star: bool = False

    @property
    def is_aggregate(self) -> bool:
        return self.name in AGGREGATE_NAMES


@dataclasses.dataclass(frozen=True)
class BinaryOp(Expr):
    op: str  # AND OR = <> < <= > >= + - * / %
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class UnaryOp(Expr):
    op: str  # NOT or -
    operand: Expr


@dataclasses.dataclass(frozen=True)
class IsNull(Expr):
    operand: Expr
    negated: bool


@dataclasses.dataclass(frozen=True)
class SelectItem:
    expr: Optional[Expr]  # None for * and t.*
    alias: Optional[str]
    source: str  # source text, whitespace collapsed
    star_table: Optional[str] = None  # table name for t.*
    star: bool = False


@dataclasses.dataclass(frozen=True)
class Join:
    kind: str  # INNER or LEFT
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class OrderKey:
    expr: Expr
    desc: bool


@dataclasses.dataclass(frozen=True)
class Query:
    distinct: bool
    select: tuple[SelectItem, ...]
    table: str
    join: Optional[Join]
    where: Optional[Expr]
    group_by: tuple[Expr, ...]
    having: Optional[Expr]
    order_by: tuple[OrderKey, ...]
    limit: Optional[int]
    offset: Optional[int]


COMPARISON_OPS = ("=", "<>", "<", "<=", ">", ">=")


def collapse_ws(text: str) -> str:
    return " ".join(text.split())


# --- parser -------------------------------------------------------------------


class Parser:
    def __init__(self, src: str) -> None:
        self.src = src
        self.tokens = tokenize(src)
        self.pos = 0
        self._agg_depth = 0

    # token helpers
    @property
    def cur(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _is_kw(self, *names: str) -> bool:
        return self.cur.kind == "KW" and self.cur.value in names

    def _is_op(self, *ops: str) -> bool:
        return self.cur.kind == "OP" and self.cur.value in ops

    def _accept_kw(self, name: str) -> bool:
        if self._is_kw(name):
            self._advance()
            return True
        return False

    def _accept_op(self, op: str) -> bool:
        if self._is_op(op):
            self._advance()
            return True
        return False

    def _error(self, message: str) -> ParseError:
        return ParseError(message, self.cur.offset)

    def _expect_kw(self, name: str) -> Token:
        if not self._is_kw(name):
            raise self._error(f"expected {name}")
        return self._advance()

    def _expect_op(self, op: str) -> Token:
        if not self._is_op(op):
            raise self._error(f"expected {op!r}")
        return self._advance()

    def _expect_ident(self) -> str:
        if self.cur.kind != "IDENT":
            raise self._error("expected identifier")
        return str(self._advance().value)

    def _expect_int(self) -> int:
        if self.cur.kind != "INT":
            raise self._error("expected integer")
        return int(self._advance().value)  # type: ignore[arg-type]

    # query
    def parse_query(self) -> Query:
        self._expect_kw("SELECT")
        distinct = self._accept_kw("DISTINCT")
        items = [self._parse_select_item()]
        while self._accept_op(","):
            items.append(self._parse_select_item())
        self._expect_kw("FROM")
        table = self._expect_ident()
        join = self._parse_join()
        where = self._parse_expr() if self._accept_kw("WHERE") else None
        group_by: list[Expr] = []
        if self._accept_kw("GROUP"):
            self._expect_kw("BY")
            group_by.append(self._parse_expr())
            while self._accept_op(","):
                group_by.append(self._parse_expr())
        having = self._parse_expr() if self._accept_kw("HAVING") else None
        order_by: list[OrderKey] = []
        if self._accept_kw("ORDER"):
            self._expect_kw("BY")
            order_by.append(self._parse_order_key())
            while self._accept_op(","):
                order_by.append(self._parse_order_key())
        limit = self._expect_int() if self._accept_kw("LIMIT") else None
        offset = self._expect_int() if self._accept_kw("OFFSET") else None
        if self.cur.kind != "EOF":
            raise self._error("unexpected token after end of query")
        return Query(
            distinct=distinct,
            select=tuple(items),
            table=table,
            join=join,
            where=where,
            group_by=tuple(group_by),
            having=having,
            order_by=tuple(order_by),
            limit=limit,
            offset=offset,
        )

    def _parse_join(self) -> Optional[Join]:
        kind = "INNER"
        if self._accept_kw("LEFT"):
            kind = "LEFT"
        elif self._accept_kw("INNER"):
            kind = "INNER"
        elif not self._is_kw("JOIN"):
            return None
        self._expect_kw("JOIN")
        table = self._expect_ident()
        self._expect_kw("ON")
        return Join(kind, table, self._parse_expr())

    def _parse_select_item(self) -> SelectItem:
        start = self.cur
        if self._accept_op("*"):
            return SelectItem(None, None, "*", star=True)
        if (
            start.kind == "IDENT"
            and self.tokens[self.pos + 1].kind == "OP"
            and self.tokens[self.pos + 1].value == "."
            and self.tokens[self.pos + 2].kind == "OP"
            and self.tokens[self.pos + 2].value == "*"
        ):
            self.pos += 3
            return SelectItem(None, None, f"{start.value}.*", star_table=str(start.value), star=True)
        expr = self._parse_expr()
        end = self.tokens[self.pos - 1].end
        source = collapse_ws(self.src[start.offset : end])
        alias = self._expect_ident() if self._accept_kw("AS") else None
        return SelectItem(expr, alias, source)

    def _parse_order_key(self) -> OrderKey:
        expr = self._parse_expr()
        desc = False
        if self._accept_kw("DESC"):
            desc = True
        else:
            self._accept_kw("ASC")
        return OrderKey(expr, desc)

    # expressions
    def _parse_expr(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._accept_kw("OR"):
            left = BinaryOp("OR", left, self._parse_and())
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        while self._accept_kw("AND"):
            left = BinaryOp("AND", left, self._parse_not())
        return left

    def _parse_not(self) -> Expr:
        if self._accept_kw("NOT"):
            return UnaryOp("NOT", self._parse_not())
        return self._parse_predicate()

    def _parse_predicate(self) -> Expr:
        left = self._parse_additive()
        result: Expr = left
        if self._is_op(*COMPARISON_OPS):
            op = str(self._advance().value)
            result = BinaryOp(op, left, self._parse_additive())
        elif self._accept_kw("IS"):
            negated = self._accept_kw("NOT")
            self._expect_kw("NULL")
            result = IsNull(left, negated)
        # Predicates are not associative: a second comparison is an error.
        if self._is_op(*COMPARISON_OPS) or self._is_kw("IS"):
            raise self._error("comparison operators do not chain")
        return result

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while self._is_op("+", "-"):
            op = str(self._advance().value)
            left = BinaryOp(op, left, self._parse_multiplicative())
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while self._is_op("*", "/", "%"):
            op = str(self._advance().value)
            left = BinaryOp(op, left, self._parse_unary())
        return left

    def _parse_unary(self) -> Expr:
        if self._accept_op("-"):
            return UnaryOp("-", self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        tok = self.cur
        if tok.kind in ("INT", "FLOAT", "TEXT"):
            self._advance()
            return Literal(tok.value)
        if tok.kind == "KW" and tok.value in ("TRUE", "FALSE", "NULL"):
            self._advance()
            return Literal({"TRUE": True, "FALSE": False, "NULL": None}[str(tok.value)])
        if self._accept_op("("):
            inner = self._parse_expr()
            self._expect_op(")")
            return inner
        if tok.kind == "IDENT":
            name = self._expect_ident()
            if self._accept_op("("):
                return self._parse_call(name, tok)
            if self._accept_op("."):
                return ColumnRef(name, self._expect_ident())
            return ColumnRef(None, name)
        raise self._error("expected expression")

    def _parse_call(self, name: str, name_tok: Token) -> FuncCall:
        lname = name.lower()
        is_agg = lname in AGGREGATE_NAMES
        if is_agg and self._agg_depth > 0:
            raise ParseError("aggregates may not nest", name_tok.offset)
        if self._is_op("*"):
            if lname != "count":
                raise self._error("'*' is only allowed inside count()")
            self._advance()
            self._expect_op(")")
            return FuncCall(lname, (), star=True)
        args: list[Expr] = []
        if not self._is_op(")"):
            if is_agg:
                self._agg_depth += 1
            args.append(self._parse_expr())
            while self._accept_op(","):
                args.append(self._parse_expr())
            if is_agg:
                self._agg_depth -= 1
        self._expect_op(")")
        if is_agg and len(args) != 1:
            raise ArityError(f"{lname} expects 1 argument, got {len(args)}")
        return FuncCall(lname, tuple(args), star=False)


def parse(src: str) -> Query:
    return Parser(src).parse_query()


def parse_expr(src: str) -> Expr:
    """Parse a standalone expression (used by tests and tooling)."""
    p = Parser(src)
    expr = p._parse_expr()
    if p.cur.kind != "EOF":
        raise p._error("unexpected token after expression")
    return expr
