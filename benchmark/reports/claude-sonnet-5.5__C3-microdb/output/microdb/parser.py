"""Recursive-descent parser: source text -> Query."""

import dataclasses

from .aggregate import AGGREGATES
from .errors import ArityError, ParseError
from .lexer import Token, tokenize


@dataclasses.dataclass(frozen=True)
class Literal:
    value: object
    kind: str  # keeps Literal(1) distinct from Literal(True) and Literal(1.0)


@dataclasses.dataclass(frozen=True)
class ColumnRef:
    table: str | None
    name: str


@dataclasses.dataclass(frozen=True)
class BoundColumn:
    index: int


@dataclasses.dataclass(frozen=True)
class OutColumn:
    index: int


@dataclasses.dataclass(frozen=True)
class Star:
    table: str | None


@dataclasses.dataclass(frozen=True)
class Unary:
    op: str  # "-" or "NOT"
    operand: object


@dataclasses.dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclasses.dataclass(frozen=True)
class IsNull:
    operand: object
    negated: bool


@dataclasses.dataclass(frozen=True)
class Call:
    name: str  # lower-cased
    args: tuple
    star: bool = False


@dataclasses.dataclass(frozen=True)
class SelectItem:
    expr: object
    alias: str | None
    text: str


@dataclasses.dataclass(frozen=True)
class OrderItem:
    expr: object
    desc: bool


@dataclasses.dataclass(frozen=True)
class JoinClause:
    kind: str  # "INNER" or "LEFT"
    table: str
    on: object


@dataclasses.dataclass(frozen=True)
class Query:
    distinct: bool
    items: tuple
    table: str
    join: JoinClause | None
    where: object | None
    group_by: tuple
    having: object | None
    order_by: tuple
    limit: int | None
    offset: int | None


_COMPARISONS = ("=", "<>", "<", "<=", ">", ">=")


class _Parser:
    def __init__(self, source: str) -> None:
        self.src = source
        self.toks = tokenize(source)
        self.pos = 0
        self.in_agg = False

    def peek(self, k: int = 0) -> Token:
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def advance(self) -> Token:
        tok = self.peek()
        self.pos += 1
        return tok

    def fail(self, message: str, tok: Token | None = None) -> ParseError:
        tok = tok or self.peek()
        found = "end of input" if tok.kind == "EOF" else repr(self.src[tok.start:tok.end])
        return ParseError(f"{message}, found {found}", tok.start)

    def at_kw(self, *names: str, k: int = 0) -> bool:
        tok = self.peek(k)
        return tok.kind == "KW" and tok.value in names

    def at_op(self, *ops: str, k: int = 0) -> bool:
        tok = self.peek(k)
        return tok.kind == "OP" and tok.value in ops

    def accept_kw(self, name: str) -> bool:
        if self.at_kw(name):
            self.pos += 1
            return True
        return False

    def accept_op(self, op: str) -> bool:
        if self.at_op(op):
            self.pos += 1
            return True
        return False

    def expect_kw(self, name: str) -> None:
        if not self.accept_kw(name):
            raise self.fail(f"expected {name}")

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.fail(f"expected '{op}'")

    def ident(self, what: str) -> str:
        tok = self.peek()
        if tok.kind != "IDENT":
            raise self.fail(f"expected {what}")
        self.pos += 1
        return str(tok.value)

    def int_literal(self, what: str) -> int:
        tok = self.peek()
        if tok.kind != "INT":
            raise self.fail(f"expected integer after {what}")
        self.pos += 1
        return int(tok.value)  # type: ignore[call-overload]

    def comma_list(self, fn) -> list:
        items = [fn()]
        while self.accept_op(","):
            items.append(fn())
        return items

    # ---- query ----
    def query(self) -> Query:
        self.expect_kw("SELECT")
        distinct = self.accept_kw("DISTINCT")
        items = self.comma_list(self.select_item)
        self.expect_kw("FROM")
        table = self.ident("table name")
        join = self.join_clause()
        where = self.or_expr() if self.accept_kw("WHERE") else None
        group_by: list = []
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            group_by = self.comma_list(self.or_expr)
        having = self.or_expr() if self.accept_kw("HAVING") else None
        order_by: list = []
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            order_by = self.comma_list(self.order_item)
        limit = self.int_literal("LIMIT") if self.accept_kw("LIMIT") else None
        offset = self.int_literal("OFFSET") if self.accept_kw("OFFSET") else None
        if self.peek().kind != "EOF":
            raise self.fail("unexpected token")
        return Query(distinct, tuple(items), table, join, where, tuple(group_by),
                     having, tuple(order_by), limit, offset)

    def join_clause(self) -> JoinClause | None:
        kind = "INNER"
        if self.at_kw("INNER", "LEFT"):
            kind = str(self.advance().value)
            self.expect_kw("JOIN")
        elif not self.accept_kw("JOIN"):
            return None
        table = self.ident("table name")
        self.expect_kw("ON")
        return JoinClause(kind, table, self.or_expr())

    def select_item(self) -> SelectItem:
        if self.at_op("*"):
            self.pos += 1
            return SelectItem(Star(None), None, "*")
        if self.peek().kind == "IDENT" and self.at_op(".", k=1) and self.at_op("*", k=2):
            name = str(self.advance().value)
            self.pos += 2
            return SelectItem(Star(name), None, name + ".*")
        start = self.peek().start
        expr = self.or_expr()
        text = " ".join(self.src[start:self.toks[self.pos - 1].end].split())
        alias = self.ident("alias") if self.accept_kw("AS") else None
        return SelectItem(expr, alias, text)

    def order_item(self) -> OrderItem:
        expr = self.or_expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        return OrderItem(expr, desc)

    # ---- expressions ----
    def or_expr(self) -> object:
        node = self.and_expr()
        while self.accept_kw("OR"):
            node = Binary("OR", node, self.and_expr())
        return node

    def and_expr(self) -> object:
        node = self.not_expr()
        while self.accept_kw("AND"):
            node = Binary("AND", node, self.not_expr())
        return node

    def not_expr(self) -> object:
        if self.accept_kw("NOT"):
            return Unary("NOT", self.not_expr())
        return self.predicate()

    def predicate(self) -> object:
        node = self.additive()
        if self.at_op(*_COMPARISONS):
            op = str(self.advance().value)
            return Binary(op, node, self.additive())
        if self.accept_kw("IS"):
            negated = self.accept_kw("NOT")
            self.expect_kw("NULL")
            return IsNull(node, negated)
        return node

    def additive(self) -> object:
        node = self.multiplicative()
        while self.at_op("+", "-"):
            op = str(self.advance().value)
            node = Binary(op, node, self.multiplicative())
        return node

    def multiplicative(self) -> object:
        node = self.unary()
        while self.at_op("*", "/", "%"):
            op = str(self.advance().value)
            node = Binary(op, node, self.unary())
        return node

    def unary(self) -> object:
        if self.accept_op("-"):
            return Unary("-", self.unary())
        return self.primary()

    def primary(self) -> object:
        tok = self.peek()
        if tok.kind in ("INT", "FLOAT", "TEXT"):
            self.pos += 1
            return Literal(tok.value, tok.kind)
        if tok.kind == "KW" and tok.value in ("TRUE", "FALSE", "NULL"):
            self.pos += 1
            value = {"TRUE": True, "FALSE": False, "NULL": None}[str(tok.value)]
            return Literal(value, "NULL" if value is None else "BOOL")
        if tok.kind == "IDENT":
            return self.name_or_call()
        if self.accept_op("("):
            node = self.or_expr()
            self.expect_op(")")
            return node
        raise self.fail("expected expression")

    def name_or_call(self) -> object:
        tok = self.advance()
        if self.at_op("("):
            return self.call(tok)
        if self.accept_op("."):
            return ColumnRef(str(tok.value), self.ident("column name after '.'"))
        return ColumnRef(None, str(tok.value))

    def call(self, name_tok: Token) -> Call:
        name = str(name_tok.value).lower()
        is_agg = name in AGGREGATES
        if is_agg and self.in_agg:
            raise self.fail("aggregates cannot be nested", name_tok)
        self.expect_op("(")
        if self.at_op("*"):
            if name != "count":
                raise self.fail("'*' is only allowed in count(*)")
            self.pos += 1
            self.expect_op(")")
            return Call(name, (), True)
        previous = self.in_agg
        self.in_agg = previous or is_agg
        args = self.comma_list(self.or_expr) if not self.at_op(")") else []
        self.in_agg = previous
        self.expect_op(")")
        if is_agg and len(args) != 1:
            raise ArityError(f"{name}() takes exactly 1 argument, got {len(args)}")
        return Call(name, tuple(args))


def parse(source: str) -> Query:
    return _Parser(source).query()
