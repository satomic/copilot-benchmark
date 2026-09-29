from dataclasses import dataclass

from .errors import ParseError
from .expr import (
    AGGREGATES,
    Binary,
    Call,
    ColumnRef,
    Expr,
    IsNull,
    Literal,
    Star,
    Unary,
    contains_aggregate,
)
from .lexer import Token, tokenize


@dataclass(frozen=True)
class SelectItem:
    expression: Expr
    alias: str | None = None


@dataclass(frozen=True)
class Join:
    kind: str
    table: str
    condition: Expr


@dataclass(frozen=True)
class OrderItem:
    expression: Expr
    descending: bool = False


@dataclass(frozen=True)
class Query:
    source: str
    distinct: bool
    select: tuple[SelectItem, ...]
    table: str
    join: Join | None
    where: Expr | None
    group_by: tuple[Expr, ...]
    having: Expr | None
    order_by: tuple[OrderItem, ...]
    limit: int | None
    offset: int


class Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = tokenize(text)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def accept(self, kind: str) -> Token | None:
        if self.current.kind != kind:
            return None
        token = self.current
        self.index += 1
        return token

    def expect(self, kind: str) -> Token:
        token = self.accept(kind)
        if token is None:
            raise ParseError(f"expected {kind}, got {self.current.kind}", self.current.start)
        return token

    def source_from(self, start: int) -> str:
        end = self.tokens[self.index - 1].end
        return " ".join(self._without_comments(self.text[start:end]).split())

    def _without_comments(self, text: str) -> str:
        result: list[str] = []
        index = 0
        quoted = False
        while index < len(text):
            if text[index] == "'":
                result.append(text[index])
                if quoted and index + 1 < len(text) and text[index + 1] == "'":
                    result.append("'")
                    index += 2
                    continue
                quoted = not quoted
                index += 1
            elif not quoted and text.startswith("--", index):
                newline = text.find("\n", index + 2)
                result.append(" ")
                index = len(text) if newline < 0 else newline + 1
            else:
                result.append(text[index])
                index += 1
        return "".join(result)

    def parse(self) -> Query:
        self.expect("SELECT")
        distinct = self.accept("DISTINCT") is not None
        select = self.select_list()
        self.expect("FROM")
        table = str(self.expect("IDENT").value)
        join = self.join_clause()
        where = self.expression() if self.accept("WHERE") else None
        group_by = self.expression_list() if self._accept_pair("GROUP", "BY") else ()
        having = self.expression() if self.accept("HAVING") else None
        order_by = self.order_list() if self._accept_pair("ORDER", "BY") else ()
        limit = self.integer_clause("LIMIT")
        offset = self.integer_clause("OFFSET")
        self.expect("EOF")
        return Query(
            self.text, distinct, select, table, join, where, group_by, having,
            order_by, limit, offset or 0,
        )

    def _accept_pair(self, first: str, second: str) -> bool:
        if self.current.kind != first:
            return False
        self.index += 1
        self.expect(second)
        return True

    def integer_clause(self, keyword: str) -> int | None:
        if not self.accept(keyword):
            return None
        return int(self.expect("INT").value)

    def select_list(self) -> tuple[SelectItem, ...]:
        items = [self.select_item()]
        while self.accept(","):
            items.append(self.select_item())
        return tuple(items)

    def select_item(self) -> SelectItem:
        if self.current.kind == "*":
            token = self.expect("*")
            expression: Expr = Star("*", None)
        elif (
            self.current.kind == "IDENT"
            and self.tokens[self.index + 1].kind == "."
            and self.tokens[self.index + 2].kind == "*"
        ):
            start = self.current.start
            table = str(self.expect("IDENT").value)
            self.expect(".")
            self.expect("*")
            expression = Star(self.source_from(start), table)
        else:
            expression = self.expression()
        alias = str(self.expect("IDENT").value) if self.accept("AS") else None
        return SelectItem(expression, alias)

    def join_clause(self) -> Join | None:
        kind = "INNER"
        if self.accept("LEFT"):
            kind = "LEFT"
            self.expect("JOIN")
        elif self.accept("INNER"):
            self.expect("JOIN")
        elif not self.accept("JOIN"):
            return None
        table = str(self.expect("IDENT").value)
        self.expect("ON")
        return Join(kind, table, self.expression())

    def expression_list(self) -> tuple[Expr, ...]:
        expressions = [self.expression()]
        while self.accept(","):
            expressions.append(self.expression())
        return tuple(expressions)

    def order_list(self) -> tuple[OrderItem, ...]:
        items: list[OrderItem] = []
        while True:
            expression = self.expression()
            descending = self.accept("DESC") is not None
            if not descending:
                self.accept("ASC")
            items.append(OrderItem(expression, descending))
            if not self.accept(","):
                return tuple(items)

    def expression(self) -> Expr:
        return self.or_expression()

    def or_expression(self) -> Expr:
        start = self.current.start
        result = self.and_expression()
        while self.accept("OR"):
            right = self.and_expression()
            result = Binary(self.source_from(start), "OR", result, right)
        return result

    def and_expression(self) -> Expr:
        start = self.current.start
        result = self.not_expression()
        while self.accept("AND"):
            right = self.not_expression()
            result = Binary(self.source_from(start), "AND", result, right)
        return result

    def not_expression(self) -> Expr:
        if self.current.kind != "NOT":
            return self.predicate()
        start = self.expect("NOT").start
        operand = self.not_expression()
        return Unary(self.source_from(start), "NOT", operand)

    def predicate(self) -> Expr:
        start = self.current.start
        result = self.additive()
        if self.current.kind in {"=", "<>", "<", "<=", ">", ">="}:
            operator = self.current.kind
            self.index += 1
            right = self.additive()
            result = Binary(self.source_from(start), operator, result, right)
        elif self.accept("IS"):
            negated = self.accept("NOT") is not None
            self.expect("NULL")
            result = IsNull(self.source_from(start), result, negated)
        if self.current.kind in {"=", "<>", "<", "<=", ">", ">=", "IS"}:
            raise ParseError("predicates are not associative", self.current.start)
        return result

    def additive(self) -> Expr:
        start = self.current.start
        result = self.multiplicative()
        while self.current.kind in {"+", "-"}:
            operator = self.current.kind
            self.index += 1
            right = self.multiplicative()
            result = Binary(self.source_from(start), operator, result, right)
        return result

    def multiplicative(self) -> Expr:
        start = self.current.start
        result = self.unary()
        while self.current.kind in {"*", "/", "%"}:
            operator = self.current.kind
            self.index += 1
            right = self.unary()
            result = Binary(self.source_from(start), operator, result, right)
        return result

    def unary(self) -> Expr:
        if self.current.kind != "-":
            return self.primary()
        start = self.expect("-").start
        operand = self.unary()
        return Unary(self.source_from(start), "-", operand)

    def primary(self) -> Expr:
        token = self.current
        if token.kind in {"INT", "FLOAT", "TEXT", "TRUE", "FALSE", "NULL"}:
            self.index += 1
            values = {"TRUE": True, "FALSE": False, "NULL": None}
            value = values.get(token.kind, token.value)
            return Literal(self.source_from(token.start), value)
        if self.accept("("):
            start = token.start
            expression = self.expression()
            self.expect(")")
            return _with_source(expression, self.source_from(start))
        if token.kind == "IDENT":
            return self.identifier_primary()
        raise ParseError(f"expected expression, got {token.kind}", token.start)

    def identifier_primary(self) -> Expr:
        start = self.current.start
        name = str(self.expect("IDENT").value)
        if self.accept("("):
            args = self.call_arguments()
            call = Call(self.source_from(start), name.lower(), args)
            self._validate_call(call)
            return call
        if self.accept("."):
            column = str(self.expect("IDENT").value)
            return ColumnRef(self.source_from(start), column, name)
        return ColumnRef(self.source_from(start), name)

    def call_arguments(self) -> tuple[Expr, ...]:
        if self.accept(")"):
            return ()
        if self.accept("*"):
            self.expect(")")
            return (Star("*", None),)
        args = [self.expression()]
        while self.accept(","):
            args.append(self.expression())
        self.expect(")")
        return tuple(args)

    def _validate_call(self, call: Call) -> None:
        lowered = call.name.lower()
        if any(isinstance(arg, Star) for arg in call.args) and lowered != "count":
            raise ParseError("* is only valid in count(*)", self.current.start)
        if lowered in AGGREGATES and any(contains_aggregate(arg) for arg in call.args):
            raise ParseError("aggregates may not nest", self.current.start)


def _with_source(expression: Expr, source: str) -> Expr:
    values = expression.__dict__.copy()
    values["source"] = source
    return type(expression)(**values)


def parse(text: str) -> Query:
    return Parser(text).parse()
