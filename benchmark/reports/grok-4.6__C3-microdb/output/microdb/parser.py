"""Recursive-descent parser for the microdb query language."""

from __future__ import annotations

import dataclasses

from microdb.errors import ParseError
from microdb.lexer import Token, tokenize

_AGGS = frozenset({"count", "sum", "avg", "min", "max"})
_CMP = frozenset({"=", "<>", "<", "<=", ">", ">="})
_CLAUSE = frozenset(
    {
        "FROM",
        "WHERE",
        "GROUP",
        "HAVING",
        "ORDER",
        "LIMIT",
        "OFFSET",
        "INNER",
        "LEFT",
        "JOIN",
        "EOF",
    }
)


@dataclasses.dataclass(frozen=True)
class Literal:
    value: object
    offset: int
    source: str


@dataclasses.dataclass(frozen=True)
class ColumnRef:
    name: str
    table: str | None
    offset: int
    source: str


@dataclasses.dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object
    offset: int
    source: str


@dataclasses.dataclass(frozen=True)
class Unary:
    op: str
    expr: object
    offset: int
    source: str


@dataclasses.dataclass(frozen=True)
class IsNull:
    expr: object
    negated: bool
    offset: int
    source: str


@dataclasses.dataclass(frozen=True)
class Call:
    name: str
    args: tuple[object, ...]
    star: bool
    offset: int
    source: str


@dataclasses.dataclass(frozen=True)
class Star:
    table: str | None
    offset: int
    source: str


@dataclasses.dataclass(frozen=True)
class SelectItem:
    value: object
    alias: str | None


@dataclasses.dataclass(frozen=True)
class JoinClause:
    kind: str
    table: str
    on: object


@dataclasses.dataclass(frozen=True)
class OrderItem:
    expr: object
    desc: bool


@dataclasses.dataclass(frozen=True)
class Query:
    distinct: bool
    select_items: list[SelectItem]
    from_table: str
    join: JoinClause | None
    where: object | None
    group_by: list[object]
    having: object | None
    order_by: list[OrderItem]
    limit: int | None
    offset: int | None


def parse(source: str) -> Query:
    return Parser(source).parse_query()


def collapse_ws(text: str) -> str:
    return " ".join(text.split())


class Parser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens = tokenize(source)
        self.i = 0
        self._end = 0
        self._agg_depth = 0

    def parse_query(self) -> Query:
        self._expect("SELECT")
        distinct = self._match("DISTINCT")
        items = self._select_list()
        self._expect("FROM")
        table = self._expect_ident()
        join = self._parse_join()
        where = self._parse_or() if self._match("WHERE") else None
        group_by = self._group_by()
        having = self._parse_or() if self._match("HAVING") else None
        order_by = self._order_by()
        limit = self._int_clause("LIMIT")
        offset = self._int_clause("OFFSET")
        if self._peek().kind != "EOF":
            raise ParseError("unexpected input after query", self._peek().offset)
        return Query(
            distinct, items, table, join, where, group_by, having, order_by, limit, offset
        )

    def _parse_join(self) -> JoinClause | None:
        kind = "INNER"
        if self._peek().kind in ("INNER", "LEFT"):
            kind = self._peek().kind
            self._advance()
            self._expect("JOIN")
        elif self._match("JOIN"):
            kind = "INNER"
        else:
            return None
        table = self._expect_ident()
        self._expect("ON")
        return JoinClause(kind, table, self._parse_or())

    def _group_by(self) -> list[object]:
        if not self._match("GROUP"):
            return []
        self._expect("BY")
        return self._expr_list()

    def _order_by(self) -> list[OrderItem]:
        if not self._match("ORDER"):
            return []
        self._expect("BY")
        items = [self._order_item()]
        while self._match(","):
            items.append(self._order_item())
        return items

    def _order_item(self) -> OrderItem:
        expr = self._parse_or()
        desc = False
        if self._match("DESC"):
            desc = True
        else:
            self._match("ASC")
        return OrderItem(expr, desc)

    def _int_clause(self, kind: str) -> int | None:
        if not self._match(kind):
            return None
        tok = self._peek()
        if tok.kind != "INT":
            raise ParseError(f"{kind} requires an integer", tok.offset)
        self._advance()
        return int(tok.value)  # type: ignore[arg-type]

    def _select_list(self) -> list[SelectItem]:
        items = [self._select_item()]
        while self._match(","):
            items.append(self._select_item())
        return items

    def _select_item(self) -> SelectItem:
        tok = self._peek()
        if tok.kind == "*":
            self._advance()
            return SelectItem(Star(None, tok.offset, "*"), None)
        if self._is_qualified_star():
            table = self._expect_ident()
            self._advance()
            star = self._peek()
            self._advance()
            src = collapse_ws(self.source[tok.offset : self._end])
            return SelectItem(Star(table, tok.offset, src), None)
        expr = self._parse_or()
        alias = self._expect_ident() if self._match("AS") else None
        return SelectItem(expr, alias)

    def _is_qualified_star(self) -> bool:
        if self._peek().kind != "IDENT":
            return False
        if self._ahead(1).kind != ".":
            return False
        return self._ahead(2).kind == "*"

    def _expr_list(self) -> list[object]:
        items = [self._parse_or()]
        while self._match(","):
            items.append(self._parse_or())
        return items

    def _parse_or(self) -> object:
        start = self._peek().offset
        left = self._parse_and()
        while self._match("OR"):
            right = self._parse_and()
            left = Binary("OR", left, right, start, self._src(start))
        return left

    def _parse_and(self) -> object:
        start = self._peek().offset
        left = self._parse_not()
        while self._match("AND"):
            right = self._parse_not()
            left = Binary("AND", left, right, start, self._src(start))
        return left

    def _parse_not(self) -> object:
        tok = self._peek()
        if self._match("NOT"):
            expr = self._parse_not()
            return Unary("NOT", expr, tok.offset, self._src(tok.offset))
        return self._parse_predicate()

    def _parse_predicate(self) -> object:
        start = self._peek().offset
        left = self._parse_additive()
        if self._match("IS"):
            return self._finish_is_null(left, start)
        tok = self._peek()
        if tok.kind in _CMP:
            self._advance()
            right = self._parse_additive()
            node: object = Binary(tok.kind, left, right, start, self._src(start))
            if self._peek().kind in _CMP or self._peek().kind == "IS":
                raise ParseError("predicate is not associative", self._peek().offset)
            return node
        return left

    def _finish_is_null(self, left: object, start: int) -> IsNull:
        negated = self._match("NOT")
        self._expect("NULL")
        return IsNull(left, negated, start, self._src(start))

    def _parse_additive(self) -> object:
        start = self._peek().offset
        left = self._parse_multiplicative()
        while self._peek().kind in ("+", "-"):
            op = self._peek().kind
            self._advance()
            right = self._parse_multiplicative()
            left = Binary(op, left, right, start, self._src(start))
        return left

    def _parse_multiplicative(self) -> object:
        start = self._peek().offset
        left = self._parse_unary()
        while self._peek().kind in ("*", "/", "%"):
            op = self._peek().kind
            self._advance()
            right = self._parse_unary()
            left = Binary(op, left, right, start, self._src(start))
        return left

    def _parse_unary(self) -> object:
        if self._match("-"):
            start = self._end - 1
            expr = self._parse_unary()
            return Unary("-", expr, start, self._src(start))
        return self._parse_primary()

    def _parse_primary(self) -> object:
        tok = self._peek()
        if tok.kind in ("INT", "FLOAT", "TEXT", "TRUE", "FALSE", "NULL"):
            self._advance()
            return Literal(tok.value, tok.offset, tok.text)
        if tok.kind == "(":
            self._advance()
            expr = self._parse_or()
            self._expect(")")
            return expr
        if tok.kind == "IDENT":
            return self._parse_ident_primary()
        raise ParseError("expected expression", tok.offset)

    def _parse_ident_primary(self) -> object:
        tok = self._peek()
        name = self._expect_ident()
        if self._match("("):
            return self._parse_call(name, tok.offset)
        table = None
        col = name
        if self._match("."):
            table = name
            col = self._expect_ident()
        src = collapse_ws(self.source[tok.offset : self._end])
        return ColumnRef(col, table, tok.offset, src)

    def _parse_call(self, name: str, start: int) -> Call:
        lower = name.lower()
        nested = lower in _AGGS
        if nested:
            if self._agg_depth:
                raise ParseError("nested aggregate", start)
            self._agg_depth += 1
        try:
            args, star = self._parse_args(lower)
        finally:
            if nested:
                self._agg_depth -= 1
        return Call(lower, tuple(args), star, start, self._src(start))

    def _parse_args(self, name: str) -> tuple[list[object], bool]:
        if name == "count" and self._match("*"):
            self._expect(")")
            return [], True
        if self._match(")"):
            return [], False
        args = [self._parse_or()]
        while self._match(","):
            args.append(self._parse_or())
        self._expect(")")
        return args, False

    def _src(self, start: int) -> str:
        return collapse_ws(self.source[start : self._end])

    def _peek(self) -> Token:
        return self.tokens[self.i]

    def _ahead(self, n: int) -> Token:
        j = self.i + n
        if j >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[j]

    def _advance(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != "EOF":
            self.i += 1
        self._end = tok.offset + len(tok.text)
        return tok

    def _match(self, kind: str) -> bool:
        if self._peek().kind == kind:
            self._advance()
            return True
        return False

    def _expect(self, kind: str) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            raise ParseError(f"expected {kind}", tok.offset)
        return self._advance()

    def _expect_ident(self) -> str:
        tok = self._peek()
        if tok.kind != "IDENT":
            raise ParseError("expected identifier", tok.offset)
        self._advance()
        return str(tok.value)
