"""Parser: tokenize + recursive-descent parse producing a Query AST.

Every AST node carries ``start``/``end`` offsets into the source text so the
executor can recover the (whitespace-collapsed) source text of an expression
for output column naming.  Offsets never take part in node equality.
"""

from __future__ import annotations

import dataclasses

from .aggregate import AGGREGATE_NAMES, contains_aggregate
from .errors import ParseError
from .lexer import Token, tokenize


# ---------------------------------------------------------------------------
# AST nodes (keyword-only fields; offsets excluded from equality)
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True, kw_only=True)
class Node:
    start: int = dataclasses.field(default=0, compare=False)
    end: int = dataclasses.field(default=0, compare=False)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Literal(Node):
    value: object = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class ColumnRef(Node):
    name: str = ""
    table: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Star(Node):
    table: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class FuncCall(Node):
    name: str = ""
    args: tuple[Node, ...] = ()
    star: bool = False  # count(*)


@dataclasses.dataclass(frozen=True, kw_only=True)
class UnaryOp(Node):
    op: str = "-"
    operand: Node = dataclasses.field(default_factory=Node)


@dataclasses.dataclass(frozen=True, kw_only=True)
class BinaryOp(Node):
    op: str = ""
    left: Node = dataclasses.field(default_factory=Node)
    right: Node = dataclasses.field(default_factory=Node)


@dataclasses.dataclass(frozen=True, kw_only=True)
class NotOp(Node):
    operand: Node = dataclasses.field(default_factory=Node)


@dataclasses.dataclass(frozen=True, kw_only=True)
class IsNull(Node):
    operand: Node = dataclasses.field(default_factory=Node)
    negated: bool = False


@dataclasses.dataclass(frozen=True)
class SelectItem:
    expr: Node  # Star or an expression
    alias: str | None


@dataclasses.dataclass(frozen=True)
class OrderItem:
    expr: Node
    desc: bool


@dataclasses.dataclass(frozen=True)
class Join:
    kind: str  # "INNER" | "LEFT"
    table: str
    on: Node


@dataclasses.dataclass(frozen=True)
class Query:
    distinct: bool
    select: tuple[SelectItem, ...]
    from_table: str
    join: Join | None
    where: Node | None
    group_by: tuple[Node, ...]
    having: Node | None
    order_by: tuple[OrderItem, ...]
    limit: int | None
    offset: int | None
    source: str


def parse(text: str) -> Query:
    """Parse query text into a Query; raises LexError or ParseError."""
    return _Parser(tokenize(text), text).parse_query()


# ---------------------------------------------------------------------------
# Recursive-descent parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens: list[Token], source: str) -> None:
        self.tokens = tokens
        self.source = source
        self.pos = 0

    # -- token helpers ------------------------------------------------------

    def peek(self, ahead: int = 0) -> Token:
        return self.tokens[min(self.pos + ahead, len(self.tokens) - 1)]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def at_kw(self, kw: str) -> bool:
        t = self.peek()
        return t.kind == "KW" and t.value == kw

    def at_op(self, op: str) -> bool:
        t = self.peek()
        return t.kind == "OP" and t.value == op

    def accept_kw(self, kw: str) -> Token | None:
        if self.at_kw(kw):
            return self.advance()
        return None

    def accept_op(self, op: str) -> Token | None:
        if self.at_op(op):
            return self.advance()
        return None

    def expect_kw(self, kw: str) -> Token:
        tok = self.accept_kw(kw)
        if tok is None:
            raise ParseError(f"expected {kw}", self.peek().offset)
        return tok

    def expect_op(self, op: str) -> Token:
        tok = self.accept_op(op)
        if tok is None:
            raise ParseError(f"expected {op!r}", self.peek().offset)
        return tok

    def expect_ident(self) -> Token:
        tok = self.peek()
        if tok.kind != "IDENT":
            raise ParseError("expected an identifier", tok.offset)
        return self.advance()

    # -- query --------------------------------------------------------------

    def parse_query(self) -> Query:
        self.expect_kw("SELECT")
        distinct = self.accept_kw("DISTINCT") is not None
        select = self.parse_select_list()
        self.expect_kw("FROM")
        from_table = str(self.expect_ident().value)
        join = self.parse_join()
        where = self.parse_expr() if self.accept_kw("WHERE") else None
        group_by = self.parse_group_by()
        having = self.parse_expr() if self.accept_kw("HAVING") else None
        order_by = self.parse_order_by()
        limit = self.parse_int_clause("LIMIT")
        offset = self.parse_int_clause("OFFSET")
        end = self.peek()
        if end.kind != "EOF":
            raise ParseError(f"unexpected {end.text!r}", end.offset)
        return Query(
            distinct=distinct, select=select, from_table=from_table,
            join=join, where=where, group_by=group_by, having=having,
            order_by=order_by, limit=limit, offset=offset, source=self.source,
        )

    def parse_int_clause(self, kw: str) -> int | None:
        if self.accept_kw(kw) is None:
            return None
        tok = self.peek()
        if tok.kind != "INT":
            raise ParseError(f"{kw} requires an integer", tok.offset)
        self.advance()
        return int(tok.value)  # type: ignore[arg-type]

    def parse_select_list(self) -> tuple[SelectItem, ...]:
        items = [self.parse_select_item()]
        while self.accept_op(","):
            items.append(self.parse_select_item())
        return tuple(items)

    def parse_select_item(self) -> SelectItem:
        tok = self.peek()
        if self.accept_op("*"):
            expr: Node = Star(start=tok.offset, end=tok.end)
        elif (tok.kind == "IDENT" and self.peek(1).value == "."
              and self.peek(2).value == "*"):
            self.advance()
            self.advance()
            star = self.advance()
            expr = Star(table=str(tok.value), start=tok.offset, end=star.end)
        else:
            expr = self.parse_expr()
        alias = None
        if self.accept_kw("AS"):
            alias = str(self.expect_ident().value)
        return SelectItem(expr=expr, alias=alias)

    def parse_join(self) -> Join | None:
        kind: str | None = None
        if self.accept_kw("INNER"):
            kind = "INNER"
            self.expect_kw("JOIN")
        elif self.accept_kw("LEFT"):
            kind = "LEFT"
            self.expect_kw("JOIN")
        elif self.accept_kw("JOIN"):
            kind = "INNER"
        if kind is None:
            return None
        table = str(self.expect_ident().value)
        self.expect_kw("ON")
        return Join(kind=kind, table=table, on=self.parse_expr())

    def parse_group_by(self) -> tuple[Node, ...]:
        if self.accept_kw("GROUP") is None:
            return ()
        self.expect_kw("BY")
        exprs = [self.parse_expr()]
        while self.accept_op(","):
            exprs.append(self.parse_expr())
        return tuple(exprs)

    def parse_order_by(self) -> tuple[OrderItem, ...]:
        if self.accept_kw("ORDER") is None:
            return ()
        self.expect_kw("BY")
        items = [self.parse_order_item()]
        while self.accept_op(","):
            items.append(self.parse_order_item())
        return tuple(items)

    def parse_order_item(self) -> OrderItem:
        expr = self.parse_expr()
        desc = False
        if self.accept_kw("ASC"):
            desc = False
        elif self.accept_kw("DESC"):
            desc = True
        return OrderItem(expr=expr, desc=desc)

    # -- expressions --------------------------------------------------------

    def parse_expr(self) -> Node:
        return self.parse_or()

    def parse_or(self) -> Node:
        node = self.parse_and()
        while self.at_kw("OR"):
            self.advance()
            right = self.parse_and()
            node = BinaryOp(op="OR", left=node, right=right,
                            start=node.start, end=right.end)
        return node

    def parse_and(self) -> Node:
        node = self.parse_not()
        while self.at_kw("AND"):
            self.advance()
            right = self.parse_not()
            node = BinaryOp(op="AND", left=node, right=right,
                            start=node.start, end=right.end)
        return node

    def parse_not(self) -> Node:
        tok = self.accept_kw("NOT")
        if tok is not None:
            operand = self.parse_not()
            return NotOp(operand=operand, start=tok.offset, end=operand.end)
        return self.parse_predicate()

    def parse_predicate(self) -> Node:
        node = self.parse_additive()
        for op in ("=", "<>", "<=", ">=", "<", ">"):
            if self.at_op(op):
                self.advance()
                right = self.parse_additive()
                return BinaryOp(op=op, left=node, right=right,
                                start=node.start, end=right.end)
        if self.accept_kw("IS"):
            negated = self.accept_kw("NOT") is not None
            null_tok = self.expect_kw("NULL")
            return IsNull(operand=node, negated=negated,
                          start=node.start, end=null_tok.end)
        return node

    def parse_additive(self) -> Node:
        node = self.parse_multiplicative()
        while self.at_op("+") or self.at_op("-"):
            op = str(self.advance().value)
            right = self.parse_multiplicative()
            node = BinaryOp(op=op, left=node, right=right,
                            start=node.start, end=right.end)
        return node

    def parse_multiplicative(self) -> Node:
        node = self.parse_unary()
        while self.at_op("*") or self.at_op("/") or self.at_op("%"):
            op = str(self.advance().value)
            right = self.parse_unary()
            node = BinaryOp(op=op, left=node, right=right,
                            start=node.start, end=right.end)
        return node

    def parse_unary(self) -> Node:
        tok = self.accept_op("-")
        if tok is not None:
            operand = self.parse_unary()
            return UnaryOp(op="-", operand=operand,
                           start=tok.offset, end=operand.end)
        return self.parse_primary()

    def parse_primary(self) -> Node:
        tok = self.peek()
        if tok.kind in ("INT", "FLOAT", "TEXT"):
            self.advance()
            return Literal(value=tok.value, start=tok.offset, end=tok.end)
        if tok.kind == "KW" and tok.value in ("TRUE", "FALSE", "NULL"):
            self.advance()
            value = {"TRUE": True, "FALSE": False, "NULL": None}[str(tok.value)]
            return Literal(value=value, start=tok.offset, end=tok.end)
        if tok.kind == "IDENT":
            return self.parse_ident_primary()
        if self.accept_op("("):
            open_tok = tok
            node = self.parse_expr()
            close = self.expect_op(")")
            return dataclasses.replace(
                node, start=open_tok.offset, end=close.end)
        raise ParseError(f"unexpected {tok.text!r}", tok.offset)

    def parse_ident_primary(self) -> Node:
        tok = self.advance()  # the identifier
        name = str(tok.value)
        if self.accept_op("("):
            return self.finish_call(tok, name)
        if self.accept_op("."):
            col = self.expect_ident()
            return ColumnRef(table=name, name=str(col.value),
                             start=tok.offset, end=col.end)
        return ColumnRef(name=name, start=tok.offset, end=tok.end)

    def finish_call(self, tok: Token, name: str) -> Node:
        """Parse the argument list of a call after '('."""
        args: list[Node] = []
        star = False
        if self.accept_op(")"):
            end = self.tokens[self.pos - 1].end
        else:
            if self.accept_op("*"):
                star = True
            else:
                args.append(self.parse_expr())
                while self.accept_op(","):
                    args.append(self.parse_expr())
            end = self.expect_op(")").end
        lower = name.lower()
        if star and lower != "count":
            raise ParseError(f"only count(*) may use '*'", tok.offset)
        if lower in AGGREGATE_NAMES and any(
            contains_aggregate(a) for a in args
        ):
            raise ParseError("aggregate functions may not nest", tok.offset)
        return FuncCall(name=name, args=tuple(args), star=star,
                        start=tok.offset, end=end)
