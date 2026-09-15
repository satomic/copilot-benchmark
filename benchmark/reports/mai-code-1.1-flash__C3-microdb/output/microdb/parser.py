from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ParseError, AggregateError, ArityError
from .lexer import Token, tokenize


@dataclass(frozen=True)
class Literal:
    value: object


@dataclass(frozen=True)
class ColumnRef:
    name: str
    table: str | None = None


@dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: Any


@dataclass(frozen=True)
class BinaryOp:
    op: str
    left: Any
    right: Any


@dataclass(frozen=True)
class FunctionCall:
    name: str
    args: list[Any]


@dataclass(frozen=True)
class NullCheck:
    expr: Any
    op: str


@dataclass(frozen=True)
class Star:
    table: str | None = None


@dataclass(frozen=True)
class SelectItem:
    expr: Any
    alias: str | None = None


@dataclass(frozen=True)
class JoinSpec:
    table: str
    kind: str
    on: Any


@dataclass(frozen=True)
class Query:
    distinct: bool
    select_items: list[SelectItem]
    from_table: str
    join: JoinSpec | None
    where: Any | None
    group_by: list[Any]
    having: Any | None
    order_by: list[tuple[Any, str]]
    limit: int | None
    offset: int | None


class Parser:
    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.index = 0

    def parse(self) -> Query:
        self._expect("SELECT")
        distinct = self._match("DISTINCT")
        items = self._select_items()
        self._expect("FROM")
        table = self._ident()
        join = self._parse_join()
        where = self._parse_clause("WHERE")
        group_by = self._parse_group_by()
        having = self._parse_clause("HAVING")
        order_by = self._parse_order_by()
        limit = self._parse_limit()
        offset = self._parse_offset()
        self._expect("EOF")
        return Query(distinct, items, table, join, where, group_by, having, order_by, limit, offset)

    def _select_items(self) -> list[SelectItem]:
        items: list[SelectItem] = []
        while True:
            if self._match("*"):
                items.append(SelectItem(Star()))
            elif self._peek_kind() == "IDENT" and self._peek_next().kind == "." and self._peek_next_n(2).kind == "*":
                name = self._ident()
                self._expect(".")
                self._expect("*")
                items.append(SelectItem(Star(name)))
            else:
                expr = self._parse_expr()
                alias = None
                if self._match("AS"):
                    alias = self._ident()
                items.append(SelectItem(expr, alias))
            if not self._match(","):
                return items

    def _parse_expr_after_ident(self, name: str) -> Any:
        if self._peek_kind() == "(":
            self._expect("(")
            args: list[Any] = []
            if not self._match(")"):
                while True:
                    if self._peek_kind() == "*":
                        self._advance()
                        args.append(Star())
                    else:
                        args.append(self._parse_expr())
                    if self._match(")"):
                        break
                    self._expect(",")
            return FunctionCall(name, args)
        if self._match("."):
            right = self._ident()
            return ColumnRef(right, name)
        return ColumnRef(name)

    def _parse_join(self) -> JoinSpec | None:
        if self._peek_kind() == "INNER":
            self._advance()
            self._expect("JOIN")
            table = self._ident()
            self._expect("ON")
            return JoinSpec(table, "INNER", self._parse_expr())
        if self._peek_kind() == "LEFT":
            self._advance()
            self._expect("JOIN")
            table = self._ident()
            self._expect("ON")
            return JoinSpec(table, "LEFT", self._parse_expr())
        if self._peek_kind() == "JOIN":
            self._advance()
            table = self._ident()
            self._expect("ON")
            return JoinSpec(table, "INNER", self._parse_expr())
        return None

    def _parse_clause(self, keyword: str) -> Any | None:
        if self._peek_kind() != keyword:
            return None
        self._advance()
        return self._parse_expr()

    def _parse_group_by(self) -> list[Any]:
        if self._peek_kind() != "GROUP":
            return []
        self._advance()
        self._expect("BY")
        items = [self._parse_expr()]
        while self._match(","):
            items.append(self._parse_expr())
        return items

    def _parse_order_by(self) -> list[tuple[Any, str]]:
        if self._peek_kind() != "ORDER":
            return []
        self._advance()
        self._expect("BY")
        items: list[tuple[Any, str]] = []
        while True:
            expr = self._parse_expr()
            direction = "ASC"
            if self._peek_kind() in {"ASC", "DESC"}:
                direction = self._advance().kind
            items.append((expr, direction))
            if not self._match(","):
                return items

    def _parse_limit(self) -> int | None:
        if self._peek_kind() != "LIMIT":
            return None
        self._advance()
        value = self._expect_number()
        return int(value)

    def _parse_offset(self) -> int | None:
        if self._peek_kind() != "OFFSET":
            return None
        self._advance()
        value = self._expect_number()
        return int(value)

    def _parse_expr(self) -> Any:
        return self._parse_or()

    def _parse_or(self) -> Any:
        expr = self._parse_and()
        while self._match("OR"):
            expr = BinaryOp("OR", expr, self._parse_and())
        return expr

    def _parse_and(self) -> Any:
        expr = self._parse_not()
        while self._match("AND"):
            expr = BinaryOp("AND", expr, self._parse_not())
        return expr

    def _parse_not(self) -> Any:
        if self._match("NOT"):
            return UnaryOp("NOT", self._parse_not())
        return self._parse_predicate()

    def _parse_predicate(self) -> Any:
        expr = self._parse_additive()
        if self._peek_kind() == "IS":
            self._advance()
            if self._match("NOT"):
                self._expect("NULL")
                return NullCheck(expr, "IS NOT NULL")
            self._expect("NULL")
            return NullCheck(expr, "IS NULL")
        if self._peek_kind() in {"=", "<>", "<", "<=", ">", ">="}:
            op = self._advance().kind
            right = self._parse_additive()
            if self._peek_kind() in {"=", "<>", "<", "<=", ">", ">="}:
                raise ParseError(self._peek().offset)
            return BinaryOp(op, expr, right)
        return expr

    def _parse_additive(self) -> Any:
        expr = self._parse_multiplicative()
        while self._peek_kind() in {"+", "-"}:
            op = self._advance().kind
            expr = BinaryOp(op, expr, self._parse_multiplicative())
        return expr

    def _parse_multiplicative(self) -> Any:
        expr = self._parse_unary()
        while self._peek_kind() in {"*", "/", "%"}:
            op = self._advance().kind
            expr = BinaryOp(op, expr, self._parse_unary())
        return expr

    def _parse_unary(self) -> Any:
        if self._match("-"):
            return UnaryOp("-", self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Any:
        kind = self._peek_kind()
        if kind == "NUMBER":
            tok = self._advance()
            return Literal(tok.value)
        if kind in {"TEXT", "TRUE", "FALSE", "NULL"}:
            tok = self._advance()
            if tok.kind == "TEXT":
                return Literal(tok.value)
            if tok.kind == "TRUE":
                return Literal(True)
            if tok.kind == "FALSE":
                return Literal(False)
            return Literal(None)
        if kind == "IDENT":
            name = self._ident()
            if self._match("("):
                args: list[Any] = []
                if not self._match(")"):
                    while True:
                        if self._peek_kind() == "*":
                            self._advance()
                            args.append(Star())
                        else:
                            args.append(self._parse_expr())
                        if self._match(")"):
                            break
                        self._expect(",")
                return FunctionCall(name, args)
            if self._match("."):
                right = self._ident()
                return ColumnRef(right, name)
            return ColumnRef(name)
        if self._match("("):
            expr = self._parse_expr()
            self._expect(")")
            return expr
        raise ParseError(self._peek().offset)

    def _peek(self) -> Token:
        return self.tokens[self.index]

    def _peek_next(self) -> Token:
        return self.tokens[self.index + 1]

    def _peek_next_n(self, offset: int) -> Token:
        return self.tokens[self.index + offset]

    def _peek_kind(self) -> str:
        return self.tokens[self.index].kind

    def _advance(self) -> Token:
        tok = self.tokens[self.index]
        self.index += 1
        return tok

    def _match(self, kind: str) -> bool:
        if self._peek_kind() == kind:
            self.index += 1
            return True
        return False

    def _expect(self, kind: str) -> Token:
        if self._peek_kind() != kind:
            raise ParseError(self._peek().offset)
        return self._advance()

    def _expect_number(self) -> int:
        tok = self._expect("NUMBER")
        value = tok.value
        if not isinstance(value, (int, float)):
            raise ParseError(tok.offset)
        if isinstance(value, float):
            if int(value) != value:
                raise ParseError(tok.offset)
            return int(value)
        return int(value)

    def _ident(self) -> str:
        tok = self._expect("IDENT")
        return str(tok.value)


def parse(text: str) -> Query:
    return Parser(text).parse()
