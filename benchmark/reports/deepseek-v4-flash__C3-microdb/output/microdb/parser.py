"""Recursive-descent parser for the microdb query language.

Produces a Query dataclass with expression AST nodes.
"""

from dataclasses import dataclass, field
from typing import Any

from microdb.errors import ParseError
from microdb.lexer import (
    Token,
    tokenize,
    INT,
    FLOAT,
    TEXT,
    IDENTIFIER,
    KEYWORD,
    OPERATOR,
    EOF,
)


# ── Expression AST nodes ───────────────────────────────────────────────


@dataclass
class Literal:
    """A literal value (int, float, str, bool, None)."""
    value: object


@dataclass
class ColumnRef:
    """An unqualified column reference."""
    name: str


@dataclass
class QualifiedColumnRef:
    """A qualified column reference (table.column)."""
    table: str
    name: str


@dataclass
class FunctionCall:
    """A function or aggregate call."""
    name: str
    args: list[Any]


@dataclass
class BinaryOp:
    """A binary operation."""
    op: str
    left: Any
    right: Any


@dataclass
class UnaryOp:
    """A unary operation (NOT or negation)."""
    op: str
    operand: Any


@dataclass
class IsNull:
    """IS NULL or IS NOT NULL predicate."""
    operand: Any
    negated: bool = False


# ── Select items ───────────────────────────────────────────────────────


@dataclass
class Star:
    """SELECT *"""
    pass


@dataclass
class StarTable:
    """SELECT table_name.*"""
    table: str


@dataclass
class SelectExpr:
    """SELECT expression [AS alias]"""
    expr: Any
    alias: str | None = None


# ── Join ───────────────────────────────────────────────────────────────


@dataclass
class Join:
    """A JOIN clause."""
    type: str  # "INNER" or "LEFT"
    table: str
    on: Any


# ── ORDER BY ───────────────────────────────────────────────────────────


@dataclass
class OrderBy:
    """A single ORDER BY item."""
    expr: Any
    ascending: bool = True


# ── Query ──────────────────────────────────────────────────────────────


@dataclass
class Query:
    """A fully parsed query."""
    distinct: bool = False
    select_items: list[Any] = field(default_factory=list)
    from_table: str = ""
    join: Join | None = None
    where: Any = None
    group_by: list[Any] = field(default_factory=list)
    having: Any = None
    order_by: list[OrderBy] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None


# ── Parser ─────────────────────────────────────────────────────────────


class Parser:
    """Recursive-descent parser."""

    __slots__ = ("tokens", "pos")

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # ── helpers ─────────────────────────────────────────────────────

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, kind: str, value: Any = None) -> Token:
        tok = self._peek()
        if value is not None:
            if tok.type != kind or tok.value != value:
                raise ParseError(
                    f"expected {value!r}, got {tok.value!r}",
                    tok.offset,
                )
        elif tok.type != kind:
            raise ParseError(
                f"expected {kind}, got {tok.type} ({tok.value!r})",
                tok.offset,
            )
        return self._advance()

    def _match(self, kind: str, value: Any = None) -> bool:
        tok = self._peek()
        if value is not None:
            if tok.type == kind and tok.value == value:
                self._advance()
                return True
            return False
        if tok.type == kind:
            self._advance()
            return True
        return False

    # ── main entry ──────────────────────────────────────────────────

    def parse(self) -> Query:
        """Parse a full SELECT statement."""
        q = Query()
        self._parse_select(q)
        self._parse_from(q)
        self._parse_join(q)
        self._parse_where(q)
        self._parse_group_by(q)
        self._parse_having(q)
        self._parse_order_by(q)
        self._parse_limit(q)
        self._parse_offset(q)
        self._expect(EOF)
        return q

    def _parse_select(self, q: Query) -> None:
        self._expect(KEYWORD, "SELECT")
        if self._match(KEYWORD, "DISTINCT"):
            q.distinct = True

        items: list[Any] = []
        while True:
            items.append(self._parse_select_item())
            if not self._match(OPERATOR, ","):
                break
        q.select_items = items

    def _parse_select_item(self) -> Any:
        """Parse a single select item: * | ident.* | expr [AS alias]."""
        tok = self._peek()

        if tok.type == OPERATOR and tok.value == "*":
            self._advance()
            return Star()

        if tok.type == IDENTIFIER:
            # Check for ident.* or ident (function call)
            name = tok.value
            save = self.pos
            self._advance()
            if self._match(OPERATOR, "."):
                if self._match(OPERATOR, "*"):
                    return StarTable(name)
                # Qualified column reference: t.c
                # Rewind: we need to parse as expression
                self.pos = save
                expr = self._parse_or_expr()
                if self._match(KEYWORD, "AS"):
                    alias = self._expect(IDENTIFIER).value
                    return SelectExpr(expr, alias)
                return SelectExpr(expr)
            # Rewind and parse as expression
            self.pos = save

        expr = self._parse_or_expr()
        if self._match(KEYWORD, "AS"):
            alias = self._expect(IDENTIFIER).value
            return SelectExpr(expr, alias)
        return SelectExpr(expr)

    # ── FROM ────────────────────────────────────────────────────────

    def _parse_from(self, q: Query) -> None:
        self._expect(KEYWORD, "FROM")
        q.from_table = self._expect(IDENTIFIER).value

    # ── JOIN ────────────────────────────────────────────────────────

    def _parse_join(self, q: Query) -> None:
        if not self._match(KEYWORD, "INNER") and not self._match(KEYWORD, "LEFT"):
            if self._peek().type == KEYWORD and self._peek().value == "JOIN":
                # Bare JOIN defaults to INNER
                pass
            else:
                return

        join_type = "INNER"
        if self.tokens[self.pos - 1].value == "LEFT":
            join_type = "LEFT"

        self._expect(KEYWORD, "JOIN")
        table = self._expect(IDENTIFIER).value
        self._expect(KEYWORD, "ON")
        on_expr = self._parse_or_expr()
        q.join = Join(type=join_type, table=table, on=on_expr)

    # ── WHERE ───────────────────────────────────────────────────────

    def _parse_where(self, q: Query) -> None:
        if not self._match(KEYWORD, "WHERE"):
            return
        q.where = self._parse_or_expr()

    # ── GROUP BY ────────────────────────────────────────────────────

    def _parse_group_by(self, q: Query) -> None:
        if not self._match(KEYWORD, "GROUP"):
            return
        self._expect(KEYWORD, "BY")
        exprs: list[Any] = []
        while True:
            exprs.append(self._parse_or_expr())
            if not self._match(OPERATOR, ","):
                break
        q.group_by = exprs

    # ── HAVING ──────────────────────────────────────────────────────

    def _parse_having(self, q: Query) -> None:
        if not self._match(KEYWORD, "HAVING"):
            return
        q.having = self._parse_or_expr()

    # ── ORDER BY ────────────────────────────────────────────────────

    def _parse_order_by(self, q: Query) -> None:
        if not self._match(KEYWORD, "ORDER"):
            return
        self._expect(KEYWORD, "BY")
        items: list[OrderBy] = []
        while True:
            expr = self._parse_or_expr()
            asc = True
            if self._match(KEYWORD, "ASC"):
                asc = True
            elif self._match(KEYWORD, "DESC"):
                asc = False
            items.append(OrderBy(expr, asc))
            if not self._match(OPERATOR, ","):
                break
        q.order_by = items

    # ── LIMIT / OFFSET ──────────────────────────────────────────────

    def _parse_limit(self, q: Query) -> None:
        if not self._match(KEYWORD, "LIMIT"):
            return
        tok = self._expect(INT)
        q.limit = int(tok.value)

    def _parse_offset(self, q: Query) -> None:
        if not self._match(KEYWORD, "OFFSET"):
            return
        tok = self._expect(INT)
        q.offset = int(tok.value)

    # ── Expression parsing ──────────────────────────────────────────
    #
    #  or_expr        := and_expr (OR and_expr)*
    #  and_expr       := not_expr (AND not_expr)*
    #  not_expr       := NOT not_expr | predicate
    #  predicate      := additive (cmp_op additive | IS [NOT] NULL)?
    #  additive       := multiplicative ((+ | -) multiplicative)*
    #  multiplicative := unary ((* | / | %) unary)*
    #  unary          := - unary | primary
    #  primary        := INT | FLOAT | TEXT | TRUE | FALSE | NULL
    #                   | ident | ident . ident
    #                   | ident ( arg_list? )
    #                   | ( or_expr )

    def _parse_or_expr(self) -> Any:
        left = self._parse_and_expr()
        while self._match(KEYWORD, "OR"):
            right = self._parse_and_expr()
            left = BinaryOp("OR", left, right)
        return left

    def _parse_and_expr(self) -> Any:
        left = self._parse_not_expr()
        while self._match(KEYWORD, "AND"):
            right = self._parse_not_expr()
            left = BinaryOp("AND", left, right)
        return left

    def _parse_not_expr(self) -> Any:
        if self._match(KEYWORD, "NOT"):
            operand = self._parse_not_expr()
            return UnaryOp("NOT", operand)
        return self._parse_predicate()

    def _parse_predicate(self) -> Any:
        left = self._parse_additive()

        tok = self._peek()
        if tok.type == OPERATOR and tok.value in ("=", "<>", "<", "<=", ">", ">="):
            op = self._advance().value
            right = self._parse_additive()
            return BinaryOp(op, left, right)

        if tok.type == KEYWORD and tok.value == "IS":
            self._advance()
            negated = self._match(KEYWORD, "NOT")
            # NULL is a KEYWORD now (after lexer change)
            if self._peek().type == KEYWORD and self._peek().value == "NULL":
                self._advance()
                return IsNull(left, negated)
            raise ParseError("expected NULL after IS", self._peek().offset)

        return left  # no comparison or IS NULL

    def _parse_additive(self) -> Any:
        left = self._parse_multiplicative()
        while True:
            tok = self._peek()
            if tok.type == OPERATOR and tok.value in ("+", "-"):
                op = self._advance().value
                right = self._parse_multiplicative()
                left = BinaryOp(op, left, right)
            else:
                break
        return left

    def _parse_multiplicative(self) -> Any:
        left = self._parse_unary()
        while True:
            tok = self._peek()
            if tok.type == OPERATOR and tok.value in ("*", "/", "%"):
                op = self._advance().value
                right = self._parse_unary()
                left = BinaryOp(op, left, right)
            else:
                break
        return left

    def _parse_unary(self) -> Any:
        if self._match(OPERATOR, "-"):
            operand = self._parse_unary()
            return UnaryOp("-", operand)
        return self._parse_primary()

    def _parse_primary(self) -> Any:
        tok = self._peek()

        if tok.type in (INT, FLOAT, TEXT):
            self._advance()
            return Literal(tok.value)

        if tok.type == KEYWORD and tok.value == "NULL":
            self._advance()
            return Literal(None)

        if tok.type == IDENTIFIER:
            name = tok.value
            self._advance()
            # Check for function call
            if self._peek().type == OPERATOR and self._peek().value == "(":
                return self._parse_function_call(name)
            # Check for qualified reference
            if self._match(OPERATOR, "."):
                col = self._expect(IDENTIFIER).value
                return QualifiedColumnRef(name, col)
            return ColumnRef(name)

        if tok.type == OPERATOR and tok.value == "(":
            self._advance()
            expr = self._parse_or_expr()
            self._expect(OPERATOR, ")")
            return expr

        raise ParseError(
            f"unexpected token: {tok.type} ({tok.value!r})",
            tok.offset,
        )

    def _parse_function_call(self, name: str) -> FunctionCall:
        """Parse ( arg_list? ).  The opening '(' has not been consumed."""
        args: list[Any] = []
        self._advance()  # consume '('
        if not (self._peek().type == OPERATOR and self._peek().value == ")"):
            # Check for star arg (count(*))
            if (
                self._peek().type == OPERATOR
                and self._peek().value == "*"
                and name.upper() == "COUNT"
            ):
                self._advance()  # consume *
                args.append(Star())
            else:
                while True:
                    args.append(self._parse_or_expr())
                    if not self._match(OPERATOR, ","):
                        break
        self._expect(OPERATOR, ")")
        return FunctionCall(name, args)


# ── Convenience wrapper ────────────────────────────────────────────────


def parse(source: str) -> Query:
    """Tokenize and parse a query string into a Query object."""
    tokens = tokenize(source)
    return Parser(tokens).parse()