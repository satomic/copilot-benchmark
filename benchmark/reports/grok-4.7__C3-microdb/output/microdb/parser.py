"""Recursive-descent parser. Keywords are case-insensitive."""

from __future__ import annotations

import dataclasses
from dataclasses import replace as _replace

from microdb.aggregate import is_aggregate_name
from microdb.errors import ParseError
from microdb.lexer import Token, tokenize

# Choice: a predicate comparison is not associative, so `1 < 2 < 3` is a ParseError.
# Choice: `1.e3` is one float when the exponent is complete; otherwise `1.` is the float.


@dataclasses.dataclass(frozen=True)
class Literal:
    value: object
    source: str


@dataclasses.dataclass(frozen=True)
class ColumnRef:
    table: str | None
    name: str
    source: str


@dataclasses.dataclass(frozen=True)
class BinaryOp:
    op: str
    left: Expr
    right: Expr
    source: str


@dataclasses.dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: Expr
    source: str


@dataclasses.dataclass(frozen=True)
class IsNull:
    operand: Expr
    negated: bool
    source: str


@dataclasses.dataclass(frozen=True)
class FuncCall:
    name: str
    args: tuple[Expr, ...]
    star: bool
    source: str


Expr = Literal | ColumnRef | BinaryOp | UnaryOp | IsNull | FuncCall


@dataclasses.dataclass(frozen=True)
class SelectItem:
    kind: str
    expr: Expr | None
    alias: str | None
    table: str | None
    source: str


@dataclasses.dataclass(frozen=True)
class JoinClause:
    kind: str
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class OrderItem:
    expr: Expr
    direction: str


@dataclasses.dataclass(frozen=True)
class Query:
    distinct: bool
    items: tuple[SelectItem, ...]
    table: str
    join: JoinClause | None
    where: Expr | None
    group_by: tuple[Expr, ...]
    having: Expr | None
    order_by: tuple[OrderItem, ...]
    limit: int | None
    offset: int | None


_CMP = {"=", "<>", "<", "<=", ">", ">="}


def parse(sql: str) -> Query:
    """Parse a query string into a Query AST."""
    return _Parser(tokenize(sql), sql).parse_query()


class _Parser:
    def __init__(self, tokens: list[Token], sql: str) -> None:
        self.tokens = tokens
        self.sql = sql
        self.pos = 0
        self.agg_depth = 0

    def parse_query(self) -> Query:
        self._expect_kw("SELECT")
        distinct = self._match_kw("DISTINCT")
        items = self._select_list()
        self._expect_kw("FROM")
        table = self._expect_ident()
        join = self._join()
        where = self._optional_clause("WHERE")
        group_by = self._group_by()
        having = self._optional_clause("HAVING")
        order_by = self._order_by()
        limit = self._int_clause("LIMIT")
        offset = self._int_clause("OFFSET")
        self._expect_eof()
        return Query(distinct, items, table, join, where, group_by, having, order_by, limit, offset)

    def _select_list(self) -> tuple[SelectItem, ...]:
        items = [self._select_item()]
        while self._match_op(","):
            items.append(self._select_item())
        return tuple(items)

    def _select_item(self) -> SelectItem:
        if self._is_star_item():
            return self._star_item()
        start = self._peek().start
        expr = self._or()
        alias = self._alias()
        return SelectItem("expr", expr, alias, None, self._span(start))

    def _is_star_item(self) -> bool:
        if self._at_op("*"):
            return True
        return self._peek().kind == "IDENT" and self._ahead(1, "OP", ".") and self._ahead(2, "OP", "*")

    def _star_item(self) -> SelectItem:
        start = self._peek().start
        if self._at_op("*"):
            self._advance()
            return SelectItem("star", None, None, None, self._span(start))
        table = self._expect_ident()
        self._expect_op(".")
        self._expect_op("*")
        return SelectItem("table_star", None, None, table, self._span(start))

    def _alias(self) -> str | None:
        if not self._match_kw("AS"):
            return None
        return self._expect_ident()

    def _join(self) -> JoinClause | None:
        kind = self._join_kind()
        if kind is None:
            return None
        self._expect_kw("JOIN")
        table = self._expect_ident()
        self._expect_kw("ON")
        return JoinClause(kind, table, self._or())

    def _join_kind(self) -> str | None:
        if self._match_kw("INNER"):
            return "INNER"
        if self._match_kw("LEFT"):
            return "LEFT"
        return None

    def _optional_clause(self, keyword: str) -> Expr | None:
        if not self._match_kw(keyword):
            return None
        return self._or()

    def _group_by(self) -> tuple[Expr, ...]:
        if not self._match_kw("GROUP"):
            return ()
        self._expect_kw("BY")
        exprs = [self._or()]
        while self._match_op(","):
            exprs.append(self._or())
        return tuple(exprs)

    def _order_by(self) -> tuple[OrderItem, ...]:
        if not self._match_kw("ORDER"):
            return ()
        self._expect_kw("BY")
        items = [self._order_item()]
        while self._match_op(","):
            items.append(self._order_item())
        return tuple(items)

    def _order_item(self) -> OrderItem:
        expr = self._or()
        if self._match_kw("DESC"):
            return OrderItem(expr, "DESC")
        self._match_kw("ASC")
        return OrderItem(expr, "ASC")

    def _int_clause(self, keyword: str) -> int | None:
        if not self._match_kw(keyword):
            return None
        tok = self._peek()
        if tok.kind != "INT":
            raise ParseError(f"{keyword} expects an integer", tok.start)
        self._advance()
        return int(tok.value)  # type: ignore[arg-type]

    def _or(self) -> Expr:
        start = self._peek().start
        left = self._and()
        while self._match_kw("OR"):
            right = self._and()
            left = BinaryOp("OR", left, right, self._span(start))
        return left

    def _and(self) -> Expr:
        start = self._peek().start
        left = self._not()
        while self._match_kw("AND"):
            right = self._not()
            left = BinaryOp("AND", left, right, self._span(start))
        return left

    def _not(self) -> Expr:
        if not self._match_kw("NOT"):
            return self._predicate()
        start = self.tokens[self.pos - 1].start
        return UnaryOp("NOT", self._not(), self._span(start))

    def _predicate(self) -> Expr:
        start = self._peek().start
        left = self._additive()
        if self._peek().kind == "OP" and self._peek().value in _CMP:
            op = str(self._advance().value)
            return BinaryOp(op, left, self._additive(), self._span(start))
        if self._match_kw("IS"):
            negated = self._match_kw("NOT")
            self._expect_kw("NULL")
            return IsNull(left, negated, self._span(start))
        return left

    def _additive(self) -> Expr:
        return self._binary_level(self._multiplicative, {"+", "-"})

    def _multiplicative(self) -> Expr:
        return self._binary_level(self._unary, {"*", "/", "%"})

    def _binary_level(self, lower: object, ops: set[str]) -> Expr:
        start = self._peek().start
        left = lower()  # type: ignore[operator]
        while self._peek().kind == "OP" and self._peek().value in ops:
            op = str(self._advance().value)
            right = lower()  # type: ignore[operator]
            left = BinaryOp(op, left, right, self._span(start))
        return left

    def _unary(self) -> Expr:
        if not self._at_op("-"):
            return self._primary()
        start = self._peek().start
        self._advance()
        return UnaryOp("-", self._unary(), self._span(start))

    def _primary(self) -> Expr:
        tok = self._peek()
        if tok.kind in {"INT", "FLOAT", "TEXT"}:
            return self._literal(tok)
        if tok.kind == "KEYWORD" and tok.value in {"TRUE", "FALSE", "NULL"}:
            return self._bool_or_null(tok)
        if tok.kind == "IDENT":
            return self._ident_primary()
        if tok.kind == "OP" and tok.value == "(":
            return self._paren()
        raise ParseError("expected expression", tok.start)

    def _literal(self, tok: Token) -> Expr:
        self._advance()
        return Literal(tok.value, self.sql[tok.start:tok.end])

    def _bool_or_null(self, tok: Token) -> Expr:
        self._advance()
        value: object = {"TRUE": True, "FALSE": False, "NULL": None}[str(tok.value)]
        return Literal(value, self.sql[tok.start:tok.end])

    def _paren(self) -> Expr:
        start = self._peek().start
        self._advance()
        expr = self._or()
        self._expect_op(")")
        return _replace(expr, source=self._span(start))

    def _ident_primary(self) -> Expr:
        start = self._peek().start
        name = self._expect_ident()
        if self._match_op("("):
            return self._call(name, start)
        if self._match_op("."):
            column = self._expect_ident()
            return ColumnRef(name, column, self._span(start))
        return ColumnRef(None, name, self._span(start))

    def _call(self, name: str, start: int) -> Expr:
        is_agg = is_aggregate_name(name)
        if is_agg and self.agg_depth > 0:
            raise ParseError("aggregates may not nest", start)
        if is_agg:
            self.agg_depth += 1
        try:
            args, star = self._args(name, start)
        finally:
            if is_agg:
                self.agg_depth -= 1
        return FuncCall(name, tuple(args), star, self._span(start))

    def _args(self, name: str, start: int) -> tuple[list[Expr], bool]:
        if self._match_op("*"):
            if name.lower() != "count":
                raise ParseError("* is only valid in count(*)", start)
            self._expect_op(")")
            return [], True
        args: list[Expr] = []
        if not self._at_op(")"):
            args.append(self._or())
            while self._match_op(","):
                args.append(self._or())
        self._expect_op(")")
        return args, False

    def _span(self, start: int) -> str:
        end = self.tokens[self.pos - 1].end
        return collapse_ws(self.sql[start:end])

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _ahead(self, n: int, kind: str, value: object) -> bool:
        idx = self.pos + n
        if idx >= len(self.tokens):
            return False
        tok = self.tokens[idx]
        return tok.kind == kind and tok.value == value

    def _at_op(self, op: str) -> bool:
        tok = self._peek()
        return tok.kind == "OP" and tok.value == op

    def _match_kw(self, kw: str) -> bool:
        tok = self._peek()
        if tok.kind == "KEYWORD" and tok.value == kw:
            self._advance()
            return True
        return False

    def _match_op(self, op: str) -> bool:
        if not self._at_op(op):
            return False
        self._advance()
        return True

    def _expect_kw(self, kw: str) -> Token:
        if not self._match_kw(kw):
            raise ParseError(f"expected {kw}", self._peek().start)
        return self.tokens[self.pos - 1]

    def _expect_op(self, op: str) -> Token:
        if not self._match_op(op):
            raise ParseError(f"expected {op}", self._peek().start)
        return self.tokens[self.pos - 1]

    def _expect_ident(self) -> str:
        tok = self._peek()
        if tok.kind != "IDENT":
            raise ParseError("expected identifier", tok.start)
        self._advance()
        return str(tok.value)

    def _expect_eof(self) -> None:
        tok = self._peek()
        if tok.kind != "EOF":
            raise ParseError("unexpected token", tok.start)


def collapse_ws(text: str) -> str:
    """Collapse whitespace outside string literals to a single space."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    pending = False
    while i < n:
        ch = text[i]
        if in_str:
            i, in_str = _in_string(text, i, out)
            continue
        if ch == "'":
            _emit_space(out, pending)
            pending = False
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "-" and i + 1 < n and text[i + 1] == "-":
            i = _skip_comment(text, i + 2)
            pending = True
            continue
        if ch.isspace():
            pending = True
            i += 1
            continue
        _emit_space(out, pending)
        pending = False
        out.append(ch)
        i += 1
    return "".join(out).strip()


def _in_string(text: str, i: int, out: list[str]) -> tuple[int, bool]:
    out.append(text[i])
    if text[i] != "'":
        return i + 1, True
    if i + 1 < len(text) and text[i + 1] == "'":
        out.append("'")
        return i + 2, True
    return i + 1, False


def _skip_comment(text: str, i: int) -> int:
    while i < len(text) and text[i] != "\n":
        i += 1
    return i


def _emit_space(out: list[str], pending: bool) -> None:
    if pending and out:
        out.append(" ")
