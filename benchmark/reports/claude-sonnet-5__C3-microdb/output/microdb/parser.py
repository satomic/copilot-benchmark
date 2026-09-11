"""Parser: token stream -> Query AST."""

from __future__ import annotations

import dataclasses
import re
from typing import Optional, Union

from microdb.errors import ParseError
from microdb.lexer import Token, tokenize

AGGREGATE_NAMES = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
_WS_RE = re.compile(r"\s+")


def collapse_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text.strip())


@dataclasses.dataclass(frozen=True)
class Literal:
    value: object
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class ColumnRef:
    table: Optional[str]
    name: str
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class Star:
    table: Optional[str]
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class FuncCall:
    name: str
    args: list
    star: bool
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: object
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class BinOp:
    op: str
    left: object
    right: object
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class IsNull:
    expr: object
    negated: bool
    start: int
    end: int


Expr = Union[Literal, ColumnRef, FuncCall, UnaryOp, BinOp, IsNull]


@dataclasses.dataclass(frozen=True)
class SelectItem:
    expr: object  # Expr | Star
    alias: Optional[str]
    default_name: str


@dataclasses.dataclass(frozen=True)
class JoinClause:
    kind: str
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class OrderItem:
    expr: Expr
    desc: bool


@dataclasses.dataclass(frozen=True)
class Query:
    distinct: bool
    select_items: list
    from_table: str
    join: Optional[JoinClause]
    where: Optional[Expr]
    group_by: list
    having: Optional[Expr]
    order_by: list
    limit: Optional[int]
    offset: Optional[int]


def _contains_aggregate_call(expr: object) -> bool:
    if isinstance(expr, FuncCall):
        if expr.name.upper() in AGGREGATE_NAMES:
            return True
        return any(_contains_aggregate_call(a) for a in expr.args)
    if isinstance(expr, (UnaryOp,)):
        return _contains_aggregate_call(expr.operand)
    if isinstance(expr, BinOp):
        return _contains_aggregate_call(expr.left) or _contains_aggregate_call(expr.right)
    if isinstance(expr, IsNull):
        return _contains_aggregate_call(expr.expr)
    return False


class Parser:
    def __init__(self, tokens: list[Token], src: str) -> None:
        self.tokens = tokens
        self.pos = 0
        self.src = src

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect_kw(self, kw: str) -> Token:
        tok = self._peek()
        if tok.kind == "KEYWORD" and tok.value == kw:
            return self._advance()
        raise ParseError(f"expected {kw!r}, got {tok.kind} {tok.value!r}", tok.start)

    def _expect_op(self, op: str) -> Token:
        tok = self._peek()
        if tok.kind == "OP" and tok.value == op:
            return self._advance()
        raise ParseError(f"expected {op!r}, got {tok.kind} {tok.value!r}", tok.start)

    def _is_kw(self, kw: str) -> bool:
        tok = self._peek()
        return tok.kind == "KEYWORD" and tok.value == kw

    def _is_op(self, op: str) -> bool:
        tok = self._peek()
        return tok.kind == "OP" and tok.value == op

    def _expect_ident(self) -> Token:
        tok = self._peek()
        if tok.kind == "IDENT":
            return self._advance()
        raise ParseError(f"expected identifier, got {tok.kind} {tok.value!r}", tok.start)

    # ---- expression grammar ----

    def parse_or_expr(self) -> object:
        start = self._peek().start
        left = self.parse_and_expr()
        while self._is_kw("OR"):
            self._advance()
            right = self.parse_and_expr()
            left = BinOp("OR", left, right, start, self.tokens[self.pos - 1].end)
        return left

    def parse_and_expr(self) -> object:
        start = self._peek().start
        left = self.parse_not_expr()
        while self._is_kw("AND"):
            self._advance()
            right = self.parse_not_expr()
            left = BinOp("AND", left, right, start, self.tokens[self.pos - 1].end)
        return left

    def parse_not_expr(self) -> object:
        if self._is_kw("NOT"):
            start = self._advance().start
            operand = self.parse_not_expr()
            return UnaryOp("NOT", operand, start, self.tokens[self.pos - 1].end)
        return self.parse_predicate()

    _CMP_OPS = {"=", "<>", "<", "<=", ">", ">="}

    def parse_predicate(self) -> object:
        start = self._peek().start
        left = self.parse_additive()
        tok = self._peek()
        if tok.kind == "OP" and tok.value in self._CMP_OPS:
            op = self._advance().value
            right = self.parse_additive()
            return BinOp(op, left, right, start, self.tokens[self.pos - 1].end)
        if tok.kind == "KEYWORD" and tok.value == "IS":
            self._advance()
            negated = False
            if self._is_kw("NOT"):
                self._advance()
                negated = True
            self._expect_kw("NULL")
            return IsNull(left, negated, start, self.tokens[self.pos - 1].end)
        return left

    def parse_additive(self) -> object:
        start = self._peek().start
        left = self.parse_multiplicative()
        while self._peek().kind == "OP" and self._peek().value in ("+", "-"):
            op = self._advance().value
            right = self.parse_multiplicative()
            left = BinOp(op, left, right, start, self.tokens[self.pos - 1].end)
        return left

    def parse_multiplicative(self) -> object:
        start = self._peek().start
        left = self.parse_unary()
        while self._peek().kind == "OP" and self._peek().value in ("*", "/", "%"):
            op = self._advance().value
            right = self.parse_unary()
            left = BinOp(op, left, right, start, self.tokens[self.pos - 1].end)
        return left

    def parse_unary(self) -> object:
        if self._is_op("-"):
            start = self._advance().start
            operand = self.parse_unary()
            return UnaryOp("-", operand, start, self.tokens[self.pos - 1].end)
        return self.parse_primary()

    def parse_primary(self) -> object:
        tok = self._peek()
        if tok.kind in ("INT", "FLOAT", "TEXT"):
            self._advance()
            return Literal(tok.value, tok.start, tok.end)
        if tok.kind == "KEYWORD" and tok.value == "TRUE":
            self._advance()
            return Literal(True, tok.start, tok.end)
        if tok.kind == "KEYWORD" and tok.value == "FALSE":
            self._advance()
            return Literal(False, tok.start, tok.end)
        if tok.kind == "KEYWORD" and tok.value == "NULL":
            self._advance()
            return Literal(None, tok.start, tok.end)
        if tok.kind == "IDENT":
            return self._parse_ident_primary()
        if tok.kind == "OP" and tok.value == "(":
            self._advance()
            inner = self.parse_or_expr()
            end_tok = self._expect_op(")")
            return _reparen(inner, tok.start, end_tok.end)
        raise ParseError(f"unexpected token {tok.kind} {tok.value!r}", tok.start)

    def _parse_ident_primary(self) -> object:
        tok = self._advance()
        if self._is_op("("):
            return self._parse_func_call(tok)
        if self._is_op(".") and self.tokens[self.pos + 1].kind == "IDENT":
            self._advance()
            name_tok = self._advance()
            return ColumnRef(tok.value, name_tok.value, tok.start, name_tok.end)
        return ColumnRef(None, tok.value, tok.start, tok.end)

    def _parse_func_call(self, name_tok: Token) -> object:
        self._advance()  # (
        name_upper = name_tok.value.upper()
        if name_upper == "COUNT" and self._is_op("*"):
            self._advance()
            end_tok = self._expect_op(")")
            return FuncCall(name_tok.value, [], True, name_tok.start, end_tok.end)
        args = []
        if not self._is_op(")"):
            args.append(self.parse_or_expr())
            while self._is_op(","):
                self._advance()
                args.append(self.parse_or_expr())
        end_tok = self._expect_op(")")
        call = FuncCall(name_tok.value, args, False, name_tok.start, end_tok.end)
        if name_upper in AGGREGATE_NAMES:
            for a in args:
                if _contains_aggregate_call(a):
                    raise ParseError("aggregate functions may not nest", name_tok.start)
        return call

    # ---- clauses ----

    def parse_select_item(self) -> SelectItem:
        start = self._peek().start
        if self._is_op("*"):
            tok = self._advance()
            return SelectItem(Star(None, tok.start, tok.end), None, "*")
        if (self._peek().kind == "IDENT" and self.pos + 2 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "OP" and self.tokens[self.pos + 1].value == "."
                and self.tokens[self.pos + 2].kind == "OP" and self.tokens[self.pos + 2].value == "*"):
            table_tok = self._advance()
            self._advance()
            star_tok = self._advance()
            name = f"{table_tok.value}.*"
            return SelectItem(Star(table_tok.value, table_tok.start, star_tok.end), None, name)
        expr = self.parse_or_expr()
        end = self.tokens[self.pos - 1].end
        alias = None
        if self._is_kw("AS"):
            self._advance()
            alias = self._expect_ident().value
        if alias is not None:
            default_name = alias
        elif isinstance(expr, ColumnRef):
            default_name = expr.name
        else:
            default_name = collapse_whitespace(self.src[start:end])
        return SelectItem(expr, alias, default_name)

    def parse_query(self) -> Query:
        self._expect_kw("SELECT")
        distinct = False
        if self._is_kw("DISTINCT"):
            self._advance()
            distinct = True
        select_items = [self.parse_select_item()]
        while self._is_op(","):
            self._advance()
            select_items.append(self.parse_select_item())
        self._expect_kw("FROM")
        from_table = self._expect_ident().value
        join = self._parse_join()
        where = None
        if self._is_kw("WHERE"):
            self._advance()
            where = self.parse_or_expr()
        group_by = self._parse_group_by()
        having = None
        if self._is_kw("HAVING"):
            self._advance()
            having = self.parse_or_expr()
        order_by = self._parse_order_by()
        limit = self._parse_int_clause("LIMIT")
        offset = self._parse_int_clause("OFFSET")
        tok = self._peek()
        if tok.kind != "EOF":
            raise ParseError(f"unexpected token {tok.kind} {tok.value!r}", tok.start)
        return Query(distinct, select_items, from_table, join, where, group_by, having, order_by, limit, offset)

    def _parse_join(self) -> Optional[JoinClause]:
        kind = None
        if self._is_kw("INNER"):
            self._advance()
            kind = "INNER"
        elif self._is_kw("LEFT"):
            self._advance()
            kind = "LEFT"
        if self._is_kw("JOIN"):
            self._advance()
            kind = kind or "INNER"
            table = self._expect_ident().value
            self._expect_kw("ON")
            on_expr = self.parse_or_expr()
            return JoinClause(kind, table, on_expr)
        if kind is not None:
            raise ParseError("expected JOIN", self._peek().start)
        return None

    def _parse_group_by(self) -> list:
        group_by = []
        if self._is_kw("GROUP"):
            self._advance()
            self._expect_kw("BY")
            group_by.append(self.parse_or_expr())
            while self._is_op(","):
                self._advance()
                group_by.append(self.parse_or_expr())
        return group_by

    def _parse_order_by(self) -> list:
        order_by = []
        if self._is_kw("ORDER"):
            self._advance()
            self._expect_kw("BY")
            order_by.append(self._parse_order_item())
            while self._is_op(","):
                self._advance()
                order_by.append(self._parse_order_item())
        return order_by

    def _parse_order_item(self) -> OrderItem:
        expr = self.parse_or_expr()
        desc = False
        if self._is_kw("ASC"):
            self._advance()
        elif self._is_kw("DESC"):
            self._advance()
            desc = True
        return OrderItem(expr, desc)

    def _parse_int_clause(self, kw: str) -> Optional[int]:
        if self._is_kw(kw):
            self._advance()
            tok = self._peek()
            if tok.kind != "INT":
                raise ParseError(f"expected integer after {kw}", tok.start)
            self._advance()
            return tok.value
        return None


def _reparen(inner: object, start: int, end: int) -> object:
    return dataclasses.replace(inner, start=start, end=end)


def parse(query: str) -> Query:
    """Parse a query string into a Query AST."""
    tokens = tokenize(query)
    parser = Parser(tokens, query)
    return parser.parse_query()
