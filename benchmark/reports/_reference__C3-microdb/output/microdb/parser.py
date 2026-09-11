"""Recursive descent parser: token list to a Query tree.

The node classes double as the expression AST used by :mod:`microdb.expr`.
Every node carries the source text it came from, so the projection can name an
output column after the expression that produced it.
"""

from __future__ import annotations

import dataclasses

from .errors import AggregateError, ParseError
from .lexer import Token, tokenize

__all__ = [
    "Expr",
    "Literal",
    "ColumnRef",
    "Unary",
    "Binary",
    "Logical",
    "Not",
    "IsNull",
    "Call",
    "Star",
    "SelectItem",
    "SortKey",
    "JoinClause",
    "Query",
    "AGGREGATE_NAMES",
    "parse",
]

AGGREGATE_NAMES = frozenset({"count", "sum", "avg", "min", "max"})
_COMPARISONS = ("=", "<>", "<", "<=", ">", ">=")


class Expr:
    """Base class for expression nodes. ``source`` is the collapsed source text."""

    source: str


@dataclasses.dataclass(frozen=True)
class Literal(Expr):
    value: object
    source: str


@dataclasses.dataclass(frozen=True)
class ColumnRef(Expr):
    table: str | None
    name: str
    source: str


@dataclasses.dataclass(frozen=True)
class Unary(Expr):
    operand: Expr
    source: str


@dataclasses.dataclass(frozen=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr
    source: str


@dataclasses.dataclass(frozen=True)
class Logical(Expr):
    op: str  # AND or OR
    left: Expr
    right: Expr
    source: str


@dataclasses.dataclass(frozen=True)
class Not(Expr):
    operand: Expr
    source: str


@dataclasses.dataclass(frozen=True)
class IsNull(Expr):
    operand: Expr
    negated: bool
    source: str


@dataclasses.dataclass(frozen=True)
class Star(Expr):
    """The ``*`` inside ``count(*)``."""

    source: str = "*"


@dataclasses.dataclass(frozen=True)
class Call(Expr):
    name: str
    args: tuple[Expr, ...]
    source: str

    @property
    def is_aggregate(self) -> bool:
        return self.name.lower() in AGGREGATE_NAMES


@dataclasses.dataclass(frozen=True)
class SelectItem:
    expr: Expr | None  # None means a bare * or table.*
    alias: str | None
    star_table: str | None


@dataclasses.dataclass(frozen=True)
class SortKey:
    expr: Expr
    descending: bool


@dataclasses.dataclass(frozen=True)
class JoinClause:
    table: str
    kind: str  # INNER or LEFT
    on: Expr


@dataclasses.dataclass(frozen=True)
class Query:
    select: tuple[SelectItem, ...]
    distinct: bool
    from_table: str
    join: JoinClause | None
    where: Expr | None
    group_by: tuple[Expr, ...]
    having: Expr | None
    order_by: tuple[SortKey, ...]
    limit: int | None
    offset: int | None


def contains_aggregate(node: Expr | None) -> bool:
    """True when the subtree holds at least one aggregate call."""
    if node is None:
        return False
    if isinstance(node, Call):
        return node.is_aggregate or any(contains_aggregate(a) for a in node.args)
    for field in dataclasses.fields(node):
        child = getattr(node, field.name)
        if isinstance(child, Expr) and contains_aggregate(child):
            return True
    return False


class _Parser:
    def __init__(self, src: str) -> None:
        self._src = src
        self._tokens = tokenize(src)
        self._pos = 0

    # -- token helpers --------------------------------------------------------

    def _peek(self) -> Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _end_offset(self) -> int:
        return len(self._src)

    def _at(self, kind: str, text: str | None = None) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == kind and (text is None or tok.text == text)

    def _at_keyword(self, *words: str) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == "KEYWORD" and tok.text in words

    def _next(self) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of query", self._end_offset())
        self._pos += 1
        return tok

    def _expect(self, kind: str, text: str | None = None) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError(f"expected {text or kind}", self._end_offset())
        if tok.kind != kind or (text is not None and tok.text != text):
            raise ParseError(f"expected {text or kind}, got {tok.text!r}", tok.offset)
        return self._next()

    def _source_between(self, start: int, end: int) -> str:
        raw = self._src[start:end]
        return " ".join(raw.split())

    # -- query ----------------------------------------------------------------

    def parse_query(self) -> Query:
        self._expect("KEYWORD", "SELECT")
        distinct = False
        if self._at_keyword("DISTINCT"):
            self._next()
            distinct = True
        select = self._parse_select_list()
        self._expect("KEYWORD", "FROM")
        from_table = self._expect("IDENT").text
        join = self._parse_join()
        where = self._parse_optional_clause("WHERE")
        if where is not None and contains_aggregate(where):
            raise AggregateError("WHERE may not contain an aggregate")
        group_by = self._parse_group_by()
        having = self._parse_optional_clause("HAVING")
        order_by = self._parse_order_by()
        limit = self._parse_count("LIMIT")
        offset = self._parse_count("OFFSET")
        tok = self._peek()
        if tok is not None:
            raise ParseError(f"unexpected trailing input {tok.text!r}", tok.offset)
        return Query(
            select=select,
            distinct=distinct,
            from_table=from_table,
            join=join,
            where=where,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def _parse_select_list(self) -> tuple[SelectItem, ...]:
        items = [self._parse_select_item()]
        while self._at("OP", ","):
            self._next()
            items.append(self._parse_select_item())
        return tuple(items)

    def _parse_select_item(self) -> SelectItem:
        if self._at("OP", "*"):
            self._next()
            return SelectItem(None, None, None)
        tok = self._peek()
        if (
            tok is not None
            and tok.kind == "IDENT"
            and self._pos + 2 < len(self._tokens)
            and self._tokens[self._pos + 1].text == "."
            and self._tokens[self._pos + 2].text == "*"
        ):
            name = self._next().text
            self._next()
            self._next()
            return SelectItem(None, None, name)
        start = self._peek().offset if self._peek() else self._end_offset()
        expr = self._parse_or()
        end = self._peek().offset if self._peek() else self._end_offset()
        alias = None
        if self._at_keyword("AS"):
            self._next()
            alias = self._expect("IDENT").text
        object.__setattr__(expr, "source", self._source_between(start, end))
        return SelectItem(expr, alias, None)

    def _parse_join(self) -> JoinClause | None:
        kind = "INNER"
        if self._at_keyword("INNER", "LEFT"):
            kind = self._next().text
        elif not self._at_keyword("JOIN"):
            return None
        self._expect("KEYWORD", "JOIN")
        table = self._expect("IDENT").text
        self._expect("KEYWORD", "ON")
        return JoinClause(table, kind, self._parse_or())

    def _parse_optional_clause(self, keyword: str) -> Expr | None:
        if not self._at_keyword(keyword):
            return None
        self._next()
        return self._parse_or()

    def _parse_group_by(self) -> tuple[Expr, ...]:
        if not self._at_keyword("GROUP"):
            return ()
        self._next()
        self._expect("KEYWORD", "BY")
        exprs = [self._parse_or()]
        while self._at("OP", ","):
            self._next()
            exprs.append(self._parse_or())
        return tuple(exprs)

    def _parse_order_by(self) -> tuple[SortKey, ...]:
        if not self._at_keyword("ORDER"):
            return ()
        self._next()
        self._expect("KEYWORD", "BY")
        keys = [self._parse_sort_key()]
        while self._at("OP", ","):
            self._next()
            keys.append(self._parse_sort_key())
        return tuple(keys)

    def _parse_sort_key(self) -> SortKey:
        start = self._peek().offset if self._peek() else self._end_offset()
        expr = self._parse_or()
        end = self._peek().offset if self._peek() else self._end_offset()
        object.__setattr__(expr, "source", self._source_between(start, end))
        descending = False
        if self._at_keyword("ASC", "DESC"):
            descending = self._next().text == "DESC"
        return SortKey(expr, descending)

    def _parse_count(self, keyword: str) -> int | None:
        if not self._at_keyword(keyword):
            return None
        tok = self._next()
        number = self._peek()
        if number is None or number.kind != "INT":
            raise ParseError(
                f"{keyword} requires an integer", number.offset if number else tok.offset
            )
        self._next()
        if number.value < 0:
            raise ParseError(f"{keyword} may not be negative", number.offset)
        return int(number.value)

    # -- expressions ----------------------------------------------------------

    def _parse_or(self) -> Expr:
        node = self._parse_and()
        while self._at_keyword("OR"):
            self._next()
            right = self._parse_and()
            node = Logical("OR", node, right, f"{node.source} OR {right.source}")
        return node

    def _parse_and(self) -> Expr:
        node = self._parse_not()
        while self._at_keyword("AND"):
            self._next()
            right = self._parse_not()
            node = Logical("AND", node, right, f"{node.source} AND {right.source}")
        return node

    def _parse_not(self) -> Expr:
        if self._at_keyword("NOT"):
            self._next()
            operand = self._parse_not()
            return Not(operand, f"NOT {operand.source}")
        return self._parse_predicate()

    def _parse_predicate(self) -> Expr:
        left = self._parse_additive()
        if self._at_keyword("IS"):
            self._next()
            negated = False
            if self._at_keyword("NOT"):
                self._next()
                negated = True
            self._expect("KEYWORD", "NULL")
            suffix = "IS NOT NULL" if negated else "IS NULL"
            return IsNull(left, negated, f"{left.source} {suffix}")
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.text in _COMPARISONS:
            self._next()
            right = self._parse_additive()
            after = self._peek()
            if after is not None and after.kind == "OP" and after.text in _COMPARISONS:
                raise ParseError("comparison operators are not associative", after.offset)
            return Binary(
                tok.text, left, right, f"{left.source} {tok.text} {right.source}"
            )
        return left

    def _parse_additive(self) -> Expr:
        node = self._parse_multiplicative()
        while self._at("OP", "+") or self._at("OP", "-"):
            op = self._next().text
            right = self._parse_multiplicative()
            node = Binary(op, node, right, f"{node.source} {op} {right.source}")
        return node

    def _parse_multiplicative(self) -> Expr:
        node = self._parse_unary()
        while self._at("OP", "*") or self._at("OP", "/") or self._at("OP", "%"):
            op = self._next().text
            right = self._parse_unary()
            node = Binary(op, node, right, f"{node.source} {op} {right.source}")
        return node

    def _parse_unary(self) -> Expr:
        if self._at("OP", "-"):
            self._next()
            operand = self._parse_unary()
            return Unary(operand, f"- {operand.source}")
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        tok = self._next()
        if tok.kind in ("INT", "FLOAT", "TEXT"):
            return Literal(tok.value, tok.text if tok.kind != "TEXT" else f"'{tok.text}'")
        if tok.kind == "KEYWORD" and tok.text in ("TRUE", "FALSE", "NULL"):
            value = None if tok.text == "NULL" else tok.text == "TRUE"
            return Literal(value, tok.text)
        if tok.kind == "OP" and tok.text == "(":
            inner = self._parse_or()
            self._expect("OP", ")")
            return inner
        if tok.kind == "IDENT":
            return self._parse_ident_tail(tok)
        raise ParseError(f"unexpected token {tok.text!r}", tok.offset)

    def _parse_ident_tail(self, tok: Token) -> Expr:
        if self._at("OP", "."):
            self._next()
            name = self._expect("IDENT").text
            return ColumnRef(tok.text, name, f"{tok.text}.{name}")
        if self._at("OP", "("):
            return self._parse_call(tok)
        return ColumnRef(None, tok.text, tok.text)

    def _parse_call(self, tok: Token) -> Expr:
        self._expect("OP", "(")
        args: list[Expr] = []
        if self._at("OP", "*"):
            self._next()
            args.append(Star())
        elif not self._at("OP", ")"):
            args.append(self._parse_or())
            while self._at("OP", ","):
                self._next()
                args.append(self._parse_or())
        self._expect("OP", ")")
        rendered = ", ".join(a.source for a in args)
        call = Call(tok.text, tuple(args), f"{tok.text}({rendered})")
        if call.is_aggregate:
            for arg in call.args:
                if contains_aggregate(arg):
                    raise AggregateError("aggregates may not nest")
        return call


def parse(src: str) -> Query:
    """Parse a complete query."""
    return _Parser(src).parse_query()
