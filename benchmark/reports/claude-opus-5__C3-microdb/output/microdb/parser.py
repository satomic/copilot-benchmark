"""Parser: turns a token stream into a :class:`Query` tree."""

from __future__ import annotations

import dataclasses

from .errors import ParseError
from .lexer import (
    EOF_TOKEN,
    FLOAT_TOKEN,
    IDENT_TOKEN,
    INT_TOKEN,
    KEYWORD_TOKEN,
    OP_TOKEN,
    TEXT_TOKEN,
    Token,
    tokenize,
)

AGGREGATE_NAMES: frozenset[str] = frozenset({"count", "sum", "avg", "min", "max"})
COMPARISON_OPS: frozenset[str] = frozenset({"=", "<>", "<", "<=", ">", ">="})


@dataclasses.dataclass(frozen=True)
class Expr:
    """Base class for expression nodes; ``text`` is the collapsed source text."""

    text: str
    offset: int


@dataclasses.dataclass(frozen=True)
class Literal(Expr):
    value: object


@dataclasses.dataclass(frozen=True)
class ColumnRef(Expr):
    table: str | None
    name: str


@dataclasses.dataclass(frozen=True)
class Star(Expr):
    table: str | None


@dataclasses.dataclass(frozen=True)
class FuncCall(Expr):
    name: str
    args: tuple[Expr, ...]


@dataclasses.dataclass(frozen=True)
class Unary(Expr):
    op: str
    operand: Expr


@dataclasses.dataclass(frozen=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class Compare(Expr):
    op: str
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class IsNull(Expr):
    operand: Expr
    negated: bool


@dataclasses.dataclass(frozen=True)
class Not(Expr):
    operand: Expr


@dataclasses.dataclass(frozen=True)
class Logical(Expr):
    op: str
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class SelectItem:
    expr: Expr
    alias: str | None


@dataclasses.dataclass(frozen=True)
class JoinClause:
    kind: str
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class OrderItem:
    expr: Expr
    descending: bool


@dataclasses.dataclass(frozen=True)
class Query:
    """A parsed query, one field per clause."""

    select: tuple[SelectItem, ...]
    distinct: bool
    from_table: str
    join: JoinClause | None
    where: Expr | None
    group_by: tuple[Expr, ...]
    having: Expr | None
    order_by: tuple[OrderItem, ...]
    limit: int | None
    offset: int | None


def collapse(text: str) -> str:
    """Collapse every run of whitespace in ``text`` to a single space."""
    return " ".join(text.split())


def contains_aggregate(expr: Expr) -> bool:
    """Return True when ``expr`` contains an aggregate function call."""
    return any(isinstance(node, FuncCall) and node.name.lower() in AGGREGATE_NAMES
               for node in walk(expr))


def walk(expr: Expr) -> list[Expr]:
    """Return ``expr`` and all of its descendants in pre-order."""
    found: list[Expr] = [expr]
    for child in children(expr):
        found.extend(walk(child))
    return found


def children(expr: Expr) -> list[Expr]:
    """Return the direct sub-expressions of ``expr``."""
    if isinstance(expr, FuncCall):
        return list(expr.args)
    if isinstance(expr, (Binary, Compare, Logical)):
        return [expr.left, expr.right]
    if isinstance(expr, Unary):
        return [expr.operand]
    if isinstance(expr, Not):
        return [expr.operand]
    if isinstance(expr, IsNull):
        return [expr.operand]
    return []


class _Parser:
    """Recursive descent parser over a token list."""

    def __init__(self, src: str) -> None:
        self.src: str = src
        self.tokens: list[Token] = tokenize(src)
        self.pos: int = 0

    # -- token helpers ----------------------------------------------------

    def peek(self, ahead: int = 0) -> Token:
        index = min(self.pos + ahead, len(self.tokens) - 1)
        return self.tokens[index]

    def next(self) -> Token:
        token = self.tokens[self.pos]
        if token.kind != EOF_TOKEN:
            self.pos += 1
        return token

    def at_keyword(self, *names: str) -> bool:
        token = self.peek()
        return token.kind == KEYWORD_TOKEN and token.value in names

    def at_op(self, *ops: str) -> bool:
        token = self.peek()
        return token.kind == OP_TOKEN and token.value in ops

    def accept_keyword(self, *names: str) -> Token | None:
        if self.at_keyword(*names):
            return self.next()
        return None

    def accept_op(self, *ops: str) -> Token | None:
        if self.at_op(*ops):
            return self.next()
        return None

    def expect_keyword(self, name: str) -> Token:
        if not self.at_keyword(name):
            raise self.error(f"expected {name}")
        return self.next()

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            raise self.error(f"expected {op!r}")
        return self.next()

    def expect_ident(self) -> Token:
        token = self.peek()
        if token.kind != IDENT_TOKEN:
            raise self.error("expected an identifier")
        return self.next()

    def error(self, message: str) -> ParseError:
        token = self.peek()
        found = token.text if token.kind != EOF_TOKEN else "end of input"
        return ParseError(f"{message}, found {found!r}", token.offset)

    def span(self, start_token: Token) -> tuple[str, int]:
        """Return the collapsed source text and offset covering tokens since ``start_token``."""
        end = self.tokens[self.pos - 1]
        stop = end.offset + len(end.text)
        return collapse(self.src[start_token.offset : stop]), start_token.offset

    # -- expression grammar ----------------------------------------------

    def parse_expr(self) -> Expr:
        return self.parse_or()

    def parse_or(self) -> Expr:
        start = self.peek()
        node = self.parse_and()
        while self.accept_keyword("OR"):
            right = self.parse_and()
            text, offset = self.span(start)
            node = Logical(text, offset, "OR", node, right)
        return node

    def parse_and(self) -> Expr:
        start = self.peek()
        node = self.parse_not()
        while self.accept_keyword("AND"):
            right = self.parse_not()
            text, offset = self.span(start)
            node = Logical(text, offset, "AND", node, right)
        return node

    def parse_not(self) -> Expr:
        start = self.peek()
        if self.accept_keyword("NOT"):
            operand = self.parse_not()
            text, offset = self.span(start)
            return Not(text, offset, operand)
        return self.parse_predicate()

    def parse_predicate(self) -> Expr:
        start = self.peek()
        node = self.parse_additive()
        if self.at_op(*COMPARISON_OPS):
            op = str(self.next().value)
            right = self.parse_additive()
            text, offset = self.span(start)
            node = Compare(text, offset, op, node, right)
        elif self.accept_keyword("IS"):
            negated = self.accept_keyword("NOT") is not None
            self.expect_keyword("NULL")
            text, offset = self.span(start)
            node = IsNull(text, offset, node, negated)
        else:
            return node
        if self.at_op(*COMPARISON_OPS) or self.at_keyword("IS"):
            raise self.error("comparison operators are not associative")
        return node

    def parse_additive(self) -> Expr:
        start = self.peek()
        node = self.parse_multiplicative()
        while self.at_op("+", "-"):
            op = str(self.next().value)
            right = self.parse_multiplicative()
            text, offset = self.span(start)
            node = Binary(text, offset, op, node, right)
        return node

    def parse_multiplicative(self) -> Expr:
        start = self.peek()
        node = self.parse_unary()
        while self.at_op("*", "/", "%"):
            op = str(self.next().value)
            right = self.parse_unary()
            text, offset = self.span(start)
            node = Binary(text, offset, op, node, right)
        return node

    def parse_unary(self) -> Expr:
        start = self.peek()
        if self.accept_op("-"):
            operand = self.parse_unary()
            text, offset = self.span(start)
            return Unary(text, offset, "-", operand)
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        start = self.peek()
        literal = self.parse_literal()
        if literal is not None:
            return literal
        if start.kind == IDENT_TOKEN:
            return self.parse_ident_expr()
        if self.accept_op("("):
            node = self.parse_expr()
            self.expect_op(")")
            return node
        raise self.error("expected an expression")

    def parse_literal(self) -> Expr | None:
        start = self.peek()
        if start.kind in (INT_TOKEN, FLOAT_TOKEN, TEXT_TOKEN):
            self.next()
            text, offset = self.span(start)
            return Literal(text, offset, start.value)
        if self.at_keyword("TRUE", "FALSE", "NULL"):
            self.next()
            value = {"TRUE": True, "FALSE": False, "NULL": None}[str(start.value)]
            text, offset = self.span(start)
            return Literal(text, offset, value)
        return None

    def parse_ident_expr(self) -> Expr:
        start = self.next()
        name = str(start.value)
        if self.at_op("("):
            return self.parse_call(start, name)
        if self.at_op(".") and self.peek(1).kind == IDENT_TOKEN:
            self.next()
            column = str(self.next().value)
            text, offset = self.span(start)
            return ColumnRef(text, offset, name, column)
        text, offset = self.span(start)
        return ColumnRef(text, offset, None, name)

    def parse_call(self, start: Token, name: str) -> Expr:
        self.expect_op("(")
        args: list[Expr] = self.parse_arg_list(name)
        self.expect_op(")")
        text, offset = self.span(start)
        node = FuncCall(text, offset, name, tuple(args))
        if name.lower() in AGGREGATE_NAMES:
            for arg in args:
                if contains_aggregate(arg):
                    raise ParseError(f"aggregate {name!r} may not be nested", offset)
        return node

    def parse_arg_list(self, name: str) -> list[Expr]:
        args: list[Expr] = []
        if self.at_op(")"):
            return args
        while True:
            star = self.peek()
            if star.kind == OP_TOKEN and star.value == "*":
                if name.lower() != "count":
                    raise self.error("'*' is only allowed as the argument of count")
                self.next()
                args.append(Star(collapse(self.src[star.offset : star.offset + 1]),
                                 star.offset, None))
            else:
                args.append(self.parse_expr())
            if not self.accept_op(","):
                return args

    # -- clause grammar ---------------------------------------------------

    def parse_query(self) -> Query:
        self.expect_keyword("SELECT")
        distinct = self.accept_keyword("DISTINCT") is not None
        select = self.parse_select_list()
        self.expect_keyword("FROM")
        from_table = str(self.expect_ident().value)
        join = self.parse_join()
        where = self.parse_where()
        group_by = self.parse_group_by()
        having = self.parse_having()
        order_by = self.parse_order_by()
        limit = self.parse_count_clause("LIMIT")
        offset = self.parse_count_clause("OFFSET")
        if self.peek().kind != EOF_TOKEN:
            raise self.error("unexpected trailing input")
        return Query(tuple(select), distinct, from_table, join, where,
                     tuple(group_by), having, tuple(order_by), limit, offset)

    def parse_select_list(self) -> list[SelectItem]:
        items: list[SelectItem] = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        return items

    def parse_select_item(self) -> SelectItem:
        start = self.peek()
        if self.at_op("*"):
            self.next()
            return SelectItem(Star("*", start.offset, None), None)
        if (start.kind == IDENT_TOKEN and self.peek(1).kind == OP_TOKEN
                and self.peek(1).value == "." and self.peek(2).kind == OP_TOKEN
                and self.peek(2).value == "*"):
            self.next()
            self.next()
            self.next()
            text, offset = self.span(start)
            return SelectItem(Star(text, offset, str(start.value)), None)
        expr = self.parse_expr()
        alias: str | None = None
        if self.accept_keyword("AS"):
            alias = str(self.expect_ident().value)
        return SelectItem(expr, alias)

    def parse_join(self) -> JoinClause | None:
        kind = "INNER"
        if self.accept_keyword("INNER"):
            self.expect_keyword("JOIN")
        elif self.accept_keyword("LEFT"):
            kind = "LEFT"
            self.expect_keyword("JOIN")
        elif self.accept_keyword("JOIN"):
            pass
        else:
            return None
        table = str(self.expect_ident().value)
        self.expect_keyword("ON")
        return JoinClause(kind, table, self.parse_expr())

    def parse_where(self) -> Expr | None:
        if self.accept_keyword("WHERE"):
            return self.parse_expr()
        return None

    def parse_group_by(self) -> list[Expr]:
        if not self.accept_keyword("GROUP"):
            return []
        self.expect_keyword("BY")
        items = [self.parse_expr()]
        while self.accept_op(","):
            items.append(self.parse_expr())
        return items

    def parse_having(self) -> Expr | None:
        if self.accept_keyword("HAVING"):
            return self.parse_expr()
        return None

    def parse_order_by(self) -> list[OrderItem]:
        if not self.accept_keyword("ORDER"):
            return []
        self.expect_keyword("BY")
        items: list[OrderItem] = []
        while True:
            expr = self.parse_expr()
            descending = False
            if self.accept_keyword("DESC"):
                descending = True
            else:
                self.accept_keyword("ASC")
            items.append(OrderItem(expr, descending))
            if not self.accept_op(","):
                return items

    def parse_count_clause(self, keyword: str) -> int | None:
        if not self.accept_keyword(keyword):
            return None
        token = self.peek()
        if token.kind != INT_TOKEN:
            raise self.error(f"{keyword} requires an integer")
        self.next()
        return int(token.value)  # type: ignore[arg-type]


def parse(src: str) -> Query:
    """Parse ``src`` into a :class:`Query`."""
    return _Parser(src).parse_query()
