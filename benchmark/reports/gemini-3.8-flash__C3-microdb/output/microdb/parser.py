"""Parser for microdb query language."""

from __future__ import annotations

import dataclasses
import re
from microdb.errors import ParseError
from microdb.expr import (
    AggregateCall,
    BinaryOp,
    ColumnRef,
    CompareOp,
    Expr,
    FunctionCall,
    IsNullOp,
    Literal,
    LogicalOp,
    NotOp,
    UnaryOp,
)
from microdb.lexer import Token, lex


@dataclasses.dataclass(frozen=True)
class SelectItem:
    """A projected item in SELECT."""

    expr: Expr | None
    alias: str | None
    is_star: bool = False
    table_star: str | None = None
    source_text: str = ""


@dataclasses.dataclass(frozen=True)
class JoinClause:
    """JOIN clause specification."""

    type: str  # "INNER" | "LEFT"
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class OrderItem:
    """ORDER BY sort item."""

    expr: Expr
    desc: bool = False


@dataclasses.dataclass(frozen=True)
class Query:
    """Parsed representation of a SELECT statement."""

    distinct: bool
    select_items: list[SelectItem]
    from_table: str
    join: JoinClause | None
    where: Expr | None
    group_by: list[Expr]
    having: Expr | None
    order_by: list[OrderItem]
    limit: int | None
    offset: int | None


class Parser:
    """Recursive-descent parser for microdb SQL."""

    def __init__(self, query_str: str, tokens: list[Token]) -> None:
        self._query_str: str = query_str
        self._tokens: list[Token] = tokens
        self._pos: int = 0
        self._in_aggregate: bool = False

    def _curr(self) -> Token:
        return self._tokens[self._pos]

    def _prev(self) -> Token:
        return self._tokens[self._pos - 1]

    def _peek_offset(self) -> int:
        return self._curr().offset

    def _match_keyword(self, kw: str) -> bool:
        tok = self._curr()
        if tok.kind == "KEYWORD" and tok.value == kw:
            self._pos += 1
            return True
        return False

    def _expect_keyword(self, kw: str) -> None:
        if not self._match_keyword(kw):
            tok = self._curr()
            raise ParseError(f"Expected keyword '{kw}', got {tok.value!r}", tok.offset)

    def _match_op(self, op: str) -> bool:
        tok = self._curr()
        if tok.kind == "OP" and tok.value == op:
            self._pos += 1
            return True
        return False

    def _expect_op(self, op: str) -> None:
        if not self._match_op(op):
            tok = self._curr()
            raise ParseError(f"Expected operator '{op}', got {tok.value!r}", tok.offset)

    def _expect_ident(self, desc: str = "identifier") -> str:
        tok = self._curr()
        if tok.kind == "IDENT":
            self._pos += 1
            return str(tok.value)
        raise ParseError(f"Expected {desc}, got {tok.value!r}", tok.offset)

    def _source_slice(self, start_tok: Token, end_tok: Token) -> str:
        raw = self._query_str[start_tok.offset : end_tok.offset + len(str(end_tok.value))]
        return re.sub(r"\s+", " ", raw).strip()

    def parse(self) -> Query:
        """Parse the full query statement."""
        self._expect_keyword("SELECT")
        distinct = self._match_keyword("DISTINCT")
        items = self._parse_select_items()
        self._expect_keyword("FROM")
        from_table = self._expect_ident("table name")
        join = self._parse_join()
        where = self._parse_where()
        group_by = self._parse_group_by()
        having = self._parse_having()
        order_by = self._parse_order_by()
        limit = self._parse_limit()
        offset = self._parse_offset()
        if self._curr().kind != "EOF":
            tok = self._curr()
            raise ParseError(f"Unexpected token {tok.value!r}", tok.offset)
        return Query(
            distinct=distinct,
            select_items=items,
            from_table=from_table,
            join=join,
            where=where,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def _parse_select_items(self) -> list[SelectItem]:
        items: list[SelectItem] = [self._parse_select_item()]
        while self._match_op(","):
            items.append(self._parse_select_item())
        return items

    def _parse_select_item(self) -> SelectItem:
        start_tok = self._curr()
        if self._match_op("*"):
            return SelectItem(
                expr=None, alias=None, is_star=True, table_star=None, source_text="*"
            )
        if (
            start_tok.kind == "IDENT"
            and self._pos + 2 < len(self._tokens)
            and self._tokens[self._pos + 1].kind == "OP"
            and self._tokens[self._pos + 1].value == "."
            and self._tokens[self._pos + 2].kind == "OP"
            and self._tokens[self._pos + 2].value == "*"
        ):
            table = str(start_tok.value)
            self._pos += 3
            return SelectItem(
                expr=None,
                alias=None,
                is_star=False,
                table_star=table,
                source_text=f"{table}.*",
            )
        expr = self._parse_or_expr()
        end_tok = self._prev()
        alias: str | None = None
        if self._match_keyword("AS"):
            alias = self._expect_ident("alias")
        source = self._source_slice(start_tok, end_tok)
        return SelectItem(
            expr=expr,
            alias=alias,
            is_star=False,
            table_star=None,
            source_text=source,
        )

    def _parse_join(self) -> JoinClause | None:
        join_type: str | None = None
        if self._match_keyword("INNER"):
            self._expect_keyword("JOIN")
            join_type = "INNER"
        elif self._match_keyword("LEFT"):
            self._expect_keyword("JOIN")
            join_type = "LEFT"
        elif self._match_keyword("JOIN"):
            join_type = "INNER"
        if join_type is None:
            return None
        table = self._expect_ident("joined table name")
        self._expect_keyword("ON")
        on_expr = self._parse_or_expr()
        return JoinClause(type=join_type, table=table, on=on_expr)

    def _parse_where(self) -> Expr | None:
        if self._match_keyword("WHERE"):
            return self._parse_or_expr()
        return None

    def _parse_group_by(self) -> list[Expr]:
        if not self._match_keyword("GROUP"):
            return []
        self._expect_keyword("BY")
        exprs: list[Expr] = [self._parse_or_expr()]
        while self._match_op(","):
            exprs.append(self._parse_or_expr())
        return exprs

    def _parse_having(self) -> Expr | None:
        if self._match_keyword("HAVING"):
            return self._parse_or_expr()
        return None

    def _parse_order_by(self) -> list[OrderItem]:
        if not self._match_keyword("ORDER"):
            return []
        self._expect_keyword("BY")
        items: list[OrderItem] = [self._parse_order_item()]
        while self._match_op(","):
            items.append(self._parse_order_item())
        return items

    def _parse_order_item(self) -> OrderItem:
        expr = self._parse_or_expr()
        desc = False
        if self._match_keyword("ASC"):
            desc = False
        elif self._match_keyword("DESC"):
            desc = True
        return OrderItem(expr=expr, desc=desc)

    def _parse_limit(self) -> int | None:
        if not self._match_keyword("LIMIT"):
            return None
        tok = self._curr()
        if tok.kind != "INT":
            raise ParseError("LIMIT requires non-negative integer", tok.offset)
        self._pos += 1
        val = int(tok.value)  # type: ignore[arg-type]
        if val < 0:
            raise ParseError("LIMIT must be non-negative", tok.offset)
        return val

    def _parse_offset(self) -> int | None:
        if not self._match_keyword("OFFSET"):
            return None
        tok = self._curr()
        if tok.kind != "INT":
            raise ParseError("OFFSET requires non-negative integer", tok.offset)
        self._pos += 1
        val = int(tok.value)  # type: ignore[arg-type]
        if val < 0:
            raise ParseError("OFFSET must be non-negative", tok.offset)
        return val

    def _parse_or_expr(self) -> Expr:
        expr = self._parse_and_expr()
        while self._match_keyword("OR"):
            right = self._parse_and_expr()
            expr = LogicalOp("OR", expr, right)
        return expr

    def _parse_and_expr(self) -> Expr:
        expr = self._parse_not_expr()
        while self._match_keyword("AND"):
            right = self._parse_not_expr()
            expr = LogicalOp("AND", expr, right)
        return expr

    def _parse_not_expr(self) -> Expr:
        if self._match_keyword("NOT"):
            return NotOp(self._parse_not_expr())
        return self._parse_predicate()

    def _parse_predicate(self) -> Expr:
        left = self._parse_additive()
        tok = self._curr()
        if tok.kind == "OP" and tok.value in ("=", "<>", "<", "<=", ">", ">="):
            op = str(tok.value)
            self._pos += 1
            right = self._parse_additive()
            return CompareOp(op, left, right)
        if self._match_keyword("IS"):
            negated = False
            if self._match_keyword("NOT"):
                negated = True
            tok = self._curr()
            if tok.kind == "NULL":
                self._pos += 1
                return IsNullOp(left, negated)
            raise ParseError(f"Expected NULL after IS, got {tok.value!r}", tok.offset)
        return left

    def _parse_additive(self) -> Expr:
        expr = self._parse_multiplicative()
        while True:
            tok = self._curr()
            if tok.kind == "OP" and tok.value in ("+", "-"):
                self._pos += 1
                right = self._parse_multiplicative()
                expr = BinaryOp(str(tok.value), expr, right)
            else:
                break
        return expr

    def _parse_multiplicative(self) -> Expr:
        expr = self._parse_unary()
        while True:
            tok = self._curr()
            if tok.kind == "OP" and tok.value in ("*", "/", "%"):
                self._pos += 1
                right = self._parse_unary()
                expr = BinaryOp(str(tok.value), expr, right)
            else:
                break
        return expr

    def _parse_unary(self) -> Expr:
        tok = self._curr()
        if tok.kind == "OP" and tok.value == "-":
            self._pos += 1
            return UnaryOp("-", self._parse_unary())
        return self._parse_primary()

    def _parse_aggregate_call(self, name: str, start_tok: Token) -> Expr:
        if self._in_aggregate:
            raise ParseError(f"Aggregates may not nest: {name}", start_tok.offset)
        lower_name = name.lower()
        if lower_name == "count" and self._match_op("*"):
            self._expect_op(")")
            return AggregateCall("count", arg=None, is_star=True)
        self._in_aggregate = True
        try:
            arg = self._parse_or_expr()
        finally:
            self._in_aggregate = False
        self._expect_op(")")
        return AggregateCall(lower_name, arg=arg, is_star=False)

    def _parse_scalar_call(self, name: str) -> Expr:
        args: list[Expr] = []
        if not self._match_op(")"):
            args.append(self._parse_or_expr())
            while self._match_op(","):
                args.append(self._parse_or_expr())
            self._expect_op(")")
        return FunctionCall(name.lower(), args)

    def _parse_ident_primary(self, tok: Token) -> Expr:
        name = str(tok.value)
        if self._match_op("("):
            if name.lower() in ("count", "sum", "avg", "min", "max"):
                return self._parse_aggregate_call(name, tok)
            return self._parse_scalar_call(name)
        if self._match_op("."):
            col_tok = self._curr()
            if col_tok.kind != "IDENT":
                raise ParseError("Expected column name after '.'", col_tok.offset)
            self._pos += 1
            return ColumnRef(table=name, column=str(col_tok.value))
        return ColumnRef(table=None, column=name)

    def _parse_primary(self) -> Expr:
        tok = self._curr()
        if tok.kind in ("INT", "FLOAT", "TEXT", "BOOL", "NULL"):
            self._pos += 1
            return Literal(tok.value)
        if tok.kind == "IDENT":
            self._pos += 1
            return self._parse_ident_primary(tok)
        if self._match_op("("):
            expr = self._parse_or_expr()
            self._expect_op(")")
            return expr
        raise ParseError(f"Unexpected token in expression: {tok.value!r}", tok.offset)


def parse(query_str: str) -> Query:
    """Parse a SQL query string into a Query AST."""
    tokens = lex(query_str)
    return Parser(query_str, tokens).parse()
