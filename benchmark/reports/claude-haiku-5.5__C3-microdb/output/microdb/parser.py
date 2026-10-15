"""Recursive-descent parser: token list -> Query AST."""

from __future__ import annotations

from dataclasses import dataclass

from .aggregate import AGGREGATE_NAMES
from .errors import ParseError
from .lexer import Token, tokenize

CMP_OPS = frozenset({"=", "<>", "<", "<=", ">", ">="})


@dataclass(frozen=True)
class Lit:
    value: object
    tag: str  # INT, FLOAT, TEXT, BOOL or NULL; keeps Lit(1) apart from Lit(True)


@dataclass(frozen=True)
class Col:
    qualifier: str | None
    name: str


@dataclass(frozen=True)
class Unary:
    op: str  # "-" or "not"
    operand: "Expr"


@dataclass(frozen=True)
class Binary:
    op: str  # "and", "or", comparison operators, or arithmetic operators
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class IsNull:
    operand: "Expr"
    negated: bool


@dataclass(frozen=True)
class Call:
    name: str  # lower-cased
    args: tuple
    star: bool = False  # True only for count(*)


Expr = Lit | Col | Unary | Binary | IsNull | Call


@dataclass(frozen=True)
class SelectItem:
    expr: Expr
    alias: str | None
    text: str  # source text with whitespace collapsed


@dataclass(frozen=True)
class Star:
    table: str | None


@dataclass(frozen=True)
class Join:
    kind: str  # "INNER" or "LEFT"
    table: str
    on: Expr


@dataclass(frozen=True)
class OrderItem:
    expr: Expr
    desc: bool


@dataclass(frozen=True)
class Query:
    distinct: bool
    items: tuple
    table: str
    join: Join | None
    where: Expr | None
    group: tuple
    having: Expr | None
    order: tuple
    limit: int | None
    offset: int | None


def parse(source: str) -> Query:
    """Parse a query string into a Query; raises LexError or ParseError."""
    return _Parser(source).parse_query()


class _Parser:
    def __init__(self, source: str) -> None:
        self.src = source
        self.toks: list[Token] = tokenize(source)
        self.i = 0
        self.agg_depth = 0
        self.last_end = 0

    # token helpers
    def peek(self, ahead: int = 0) -> Token:
        return self.toks[min(self.i + ahead, len(self.toks) - 1)]

    def advance(self) -> Token:
        tok = self.toks[self.i]
        if tok.kind != "EOF":
            self.i += 1
        self.last_end = tok.end
        return tok

    def is_kw(self, word: str, ahead: int = 0) -> bool:
        tok = self.peek(ahead)
        return tok.kind == "KW" and tok.value == word

    def is_op(self, op: str, ahead: int = 0) -> bool:
        tok = self.peek(ahead)
        return tok.kind == "OP" and tok.value == op

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

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            raise self.error(f"expected {word}")

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error(f"expected '{op}'")

    def expect_ident(self) -> str:
        tok = self.peek()
        if tok.kind != "IDENT":
            raise self.error("expected an identifier")
        self.advance()
        return str(tok.value)

    def error(self, message: str) -> ParseError:
        tok = self.peek()
        return ParseError(f"{message} at offset {tok.offset}", tok.offset)

    # clauses
    def parse_query(self) -> Query:
        self.expect_kw("SELECT")
        distinct = self.accept_kw("DISTINCT")
        items = self.parse_select_list()
        self.expect_kw("FROM")
        table = self.expect_ident()
        join = self.parse_join()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        group: tuple = ()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            group = self.parse_expr_list()
        having = self.parse_expr() if self.accept_kw("HAVING") else None
        order: tuple = ()
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            order = self.parse_order_list()
        limit = self.parse_int_clause("LIMIT")
        offset = self.parse_int_clause("OFFSET")
        if self.peek().kind != "EOF":
            raise self.error("unexpected token")
        return Query(distinct, items, table, join, where, group, having, order, limit, offset)

    def parse_select_list(self) -> tuple:
        items = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        return tuple(items)

    def parse_select_item(self) -> SelectItem | Star:
        if self.accept_op("*"):
            return Star(None)
        if self.peek().kind == "IDENT" and self.is_op(".", 1) and self.is_op("*", 2):
            table = str(self.advance().value)
            self.advance()
            self.advance()
            return Star(table)
        start = self.peek().offset
        expr = self.parse_expr()
        text = " ".join(self.src[start:self.last_end].split())
        alias = self.expect_ident() if self.accept_kw("AS") else None
        return SelectItem(expr, alias, text)

    def parse_join(self) -> Join | None:
        if self.accept_kw("LEFT"):
            kind = "LEFT"
        elif self.accept_kw("INNER"):
            kind = "INNER"
        elif self.is_kw("JOIN"):
            kind = "INNER"
        else:
            return None
        self.expect_kw("JOIN")
        table = self.expect_ident()
        self.expect_kw("ON")
        return Join(kind, table, self.parse_expr())

    def parse_expr_list(self) -> tuple:
        exprs = [self.parse_expr()]
        while self.accept_op(","):
            exprs.append(self.parse_expr())
        return tuple(exprs)

    def parse_order_list(self) -> tuple:
        items = []
        while True:
            expr = self.parse_expr()
            desc = self.accept_kw("DESC")
            if not desc:
                self.accept_kw("ASC")
            items.append(OrderItem(expr, desc))
            if not self.accept_op(","):
                return tuple(items)

    def parse_int_clause(self, word: str) -> int | None:
        if not self.accept_kw(word):
            return None
        tok = self.peek()
        if tok.kind != "INT":
            raise self.error(f"{word} expects an integer")
        self.advance()
        return int(tok.value)  # type: ignore[call-overload]

    # expressions
    def parse_expr(self) -> Expr:
        left = self.parse_and()
        while self.accept_kw("OR"):
            left = Binary("or", left, self.parse_and())
        return left

    def parse_and(self) -> Expr:
        left = self.parse_not()
        while self.accept_kw("AND"):
            left = Binary("and", left, self.parse_not())
        return left

    def parse_not(self) -> Expr:
        if self.accept_kw("NOT"):
            return Unary("not", self.parse_not())
        return self.parse_predicate()

    def parse_predicate(self) -> Expr:
        left = self.parse_additive()
        tok = self.peek()
        if tok.kind == "OP" and tok.value in CMP_OPS:
            self.advance()
            return Binary(str(tok.value), left, self.parse_additive())
        if self.accept_kw("IS"):
            negated = self.accept_kw("NOT")
            self.expect_kw("NULL")
            return IsNull(left, negated)
        return left

    def parse_additive(self) -> Expr:
        left = self.parse_multiplicative()
        while self.is_op("+") or self.is_op("-"):
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self) -> Expr:
        left = self.parse_unary()
        while self.is_op("*") or self.is_op("/") or self.is_op("%"):
            op = str(self.advance().value)
            left = Binary(op, left, self.parse_unary())
        return left

    def parse_unary(self) -> Expr:
        if self.accept_op("-"):
            return Unary("-", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        tok = self.peek()
        if tok.kind in ("INT", "FLOAT", "TEXT"):
            self.advance()
            return Lit(tok.value, tok.kind)
        if tok.kind == "KW" and tok.value in ("TRUE", "FALSE"):
            self.advance()
            return Lit(tok.value == "TRUE", "BOOL")
        if tok.kind == "KW" and tok.value == "NULL":
            self.advance()
            return Lit(None, "NULL")
        if tok.kind == "IDENT":
            return self.parse_name()
        if self.accept_op("("):
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        raise self.error("expected an expression")

    def parse_name(self) -> Expr:
        name = str(self.advance().value)
        if self.is_op("("):
            return self.parse_call(name)
        if self.accept_op("."):
            return Col(name, self.expect_ident())
        return Col(None, name)

    def parse_call(self, name: str) -> Call:
        lname = name.lower()
        is_agg = lname in AGGREGATE_NAMES
        if is_agg and self.agg_depth > 0:
            raise self.error("aggregates may not be nested")
        self.expect_op("(")
        if self.is_op("*"):
            if lname != "count":
                raise self.error("'*' is only allowed in count(*)")
            self.advance()
            self.expect_op(")")
            return Call("count", (), True)
        if is_agg:
            self.agg_depth += 1
        args = []
        if not self.is_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        if is_agg:
            self.agg_depth -= 1
        return Call(lname, tuple(args), False)
