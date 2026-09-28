from __future__ import annotations

from dataclasses import dataclass, field

from .errors import ParseError
from .lexer import Token, tokenize


@dataclass(frozen=True)
class Expr:
    kind: str
    value: object = None
    children: tuple[Expr, ...] = ()
    source: str = field(default="", compare=False)
    offset: int = field(default=0, compare=False)


@dataclass(frozen=True)
class SelectItem:
    expr: Expr | None
    alias: str | None = None
    star_table: str | None = None


@dataclass(frozen=True)
class Join:
    kind: str
    table: str
    on: Expr


@dataclass(frozen=True)
class OrderItem:
    expr: Expr
    descending: bool = False


@dataclass(frozen=True)
class Query:
    items: tuple[SelectItem, ...]
    table: str
    join: Join | None = None
    where: Expr | None = None
    group_by: tuple[Expr, ...] = ()
    having: Expr | None = None
    order_by: tuple[OrderItem, ...] = ()
    distinct: bool = False
    limit: int | None = None
    offset: int = 0
    source: str = field(default="", compare=False)


AGGREGATES = {"count", "sum", "avg", "min", "max"}


class Parser:
    def __init__(self: Parser, source: str) -> None:
        self.source = source
        self.tokens = tokenize(source)
        self.position = 0

    def parse(self: Parser) -> Query:
        self._expect("SELECT")
        distinct = self._accept("DISTINCT") is not None
        items = [self._select_item()]
        while self._accept(","):
            items.append(self._select_item())
        self._expect("FROM")
        table = self._identifier()
        join = self._join()
        where = self._expression() if self._accept("WHERE") else None
        group_by: list[Expr] = []
        if self._accept("GROUP"):
            self._expect("BY")
            group_by.append(self._expression())
            while self._accept(","):
                group_by.append(self._expression())
        having = self._expression() if self._accept("HAVING") else None
        order_by = self._order_by()
        limit = self._integer_clause("LIMIT")
        offset = self._integer_clause("OFFSET")
        if self._peek().kind != "EOF":
            self._fail("unexpected token")
        query = Query(tuple(items), table, join, where, tuple(group_by), having,
                      tuple(order_by), distinct, limit, offset, self.source)
        self._validate_aggregate_nesting(query)
        return query

    def _join(self: Parser) -> Join | None:
        if self._accept("JOIN"):
            kind = "INNER"
        elif self._accept("INNER"):
            self._expect("JOIN")
            kind = "INNER"
        elif self._accept("LEFT"):
            self._expect("JOIN")
            kind = "LEFT"
        else:
            return None
        table = self._identifier()
        self._expect("ON")
        return Join(kind, table, self._expression())

    def _select_item(self: Parser) -> SelectItem:
        if self._accept("OP", "*"):
            return SelectItem(None)
        if (self._peek().kind == "IDENT" and self._peek(1).kind == "."
                and self._peek(2).kind == "OP" and self._peek(2).value == "*"):
            table = self._take().value
            self._take()
            self._take()
            return SelectItem(None, star_table=table)
        expr = self._expression()
        alias = self._take().value if self._accept("AS") else None
        return SelectItem(expr, alias)

    def _order_by(self: Parser) -> list[OrderItem]:
        items: list[OrderItem] = []
        if not self._accept("ORDER"):
            return items
        self._expect("BY")
        while True:
            expr = self._expression()
            direction = self._accept("ASC", "DESC")
            items.append(OrderItem(expr, direction is not None and direction.kind == "DESC"))
            if not self._accept(","):
                return items

    def _integer_clause(self: Parser, name: str) -> int | None:
        if self._accept(name) is None:
            return None
        token = self._expect("INT")
        value = int(token.value)
        if value < 0:
            self._fail("expected a non-negative integer", token)
        return value

    def _expression(self: Parser) -> Expr:
        return self._or()

    def _or(self: Parser) -> Expr:
        left = self._and()
        while self._accept("OR"):
            left = self._binary("OR", left, self._and())
        return left

    def _and(self: Parser) -> Expr:
        left = self._not()
        while self._accept("AND"):
            left = self._binary("AND", left, self._not())
        return left

    def _not(self: Parser) -> Expr:
        token = self._accept("NOT")
        if token is not None:
            child = self._not()
            return self._node("NOT", "NOT", (child,), token.offset, self._previous().end)
        return self._predicate()

    def _predicate(self: Parser) -> Expr:
        left = self._additive()
        if self._peek().kind == "IS":
            token = self._take()
            negated = self._accept("NOT") is not None
            end = self._expect("NULL").end
            return self._node("IS_NOT_NULL" if negated else "IS_NULL", None,
                              (left,), left.offset, end)
        if self._peek().kind == "OP" and self._peek().value in {"=", "<>", "<", "<=", ">", ">="}:
            operator = self._take()
            right = self._additive()
            left = self._binary(operator.value, left, right)
            if self._peek().kind == "OP" and self._peek().value in {"=", "<>", "<", "<=", ">", ">="}:
                self._fail("comparison predicates are not associative")
        return left

    def _additive(self: Parser) -> Expr:
        left = self._multiplicative()
        while self._peek().kind == "OP" and self._peek().value in {"+", "-"}:
            operator = self._take().value
            left = self._binary(operator, left, self._multiplicative())
        return left

    def _multiplicative(self: Parser) -> Expr:
        left = self._unary()
        while self._peek().kind == "OP" and self._peek().value in {"*", "/", "%"}:
            operator = self._take().value
            left = self._binary(operator, left, self._unary())
        return left

    def _unary(self: Parser) -> Expr:
        token = self._accept("OP", "-")
        if token is not None:
            child = self._unary()
            return self._node("NEGATE", "-", (child,), token.offset, self._previous().end)
        return self._primary()

    def _primary(self: Parser) -> Expr:
        token = self._peek()
        if token.kind in {"INT", "FLOAT", "TEXT", "TRUE", "FALSE", "NULL"}:
            self._take()
            value: object = token.value
            if token.kind == "INT":
                value = int(token.value)
            elif token.kind == "FLOAT":
                value = float(token.value)
            elif token.kind == "TRUE":
                value = True
            elif token.kind == "FALSE":
                value = False
            elif token.kind == "NULL":
                value = None
            return self._node("LITERAL", value, (), token.offset, token.end)
        if token.kind == "(":
            start = self._take()
            expr = self._expression()
            end = self._expect(")").end
            return self._node(expr.kind, expr.value, expr.children, start.offset, end)
        if token.kind != "IDENT":
            self._fail("expected an expression", token)
        name = self._take()
        if self._accept("("):
            args: list[Expr] = []
            if not self._accept(")"):
                args.append(self._call_argument())
                while self._accept(","):
                    args.append(self._call_argument())
                end = self._expect(")").end
            else:
                end = self._previous().end
            return self._node("CALL", name.value, tuple(args), name.offset, end)
        if self._accept("."):
            column = self._expect("IDENT")
            return self._node("COLUMN", (name.value, column.value), (), name.offset, column.end)
        return self._node("COLUMN", (None, name.value), (), name.offset, name.end)

    def _call_argument(self: Parser) -> Expr:
        if self._accept("OP", "*"):
            token = self._previous()
            return self._node("STAR", "*", (), token.offset, token.end)
        return self._expression()

    def _binary(self: Parser, operator: str, left: Expr, right: Expr) -> Expr:
        return self._node("BINARY", operator, (left, right), left.offset,
                          self._previous().end)

    def _node(self: Parser, kind: str, value: object, children: tuple[Expr, ...],
              start: int, end: int) -> Expr:
        source = " ".join(self.source[start:end].split())
        return Expr(kind, value, children, source, start)

    def _validate_aggregate_nesting(self: Parser, query: Query) -> None:
        expressions = [item.expr for item in query.items if item.expr is not None]
        expressions.extend(expr for expr in (query.where, query.having) if expr is not None)
        expressions.extend(query.group_by)
        expressions.extend(item.expr for item in query.order_by)
        if query.join is not None:
            expressions.append(query.join.on)
        for expr in expressions:
            self._check_nested(expr, False)

    def _check_nested(self: Parser, expr: Expr, inside: bool) -> None:
        aggregate = expr.kind == "CALL" and str(expr.value).lower() in AGGREGATES
        if aggregate and inside:
            raise ParseError("aggregate functions may not nest", expr.offset)
        for child in expr.children:
            self._check_nested(child, inside or aggregate)

    def _identifier(self: Parser) -> str:
        return self._expect("IDENT").value

    def _peek(self: Parser, ahead: int = 0) -> Token:
        return self.tokens[min(self.position + ahead, len(self.tokens) - 1)]

    def _previous(self: Parser) -> Token:
        return self.tokens[self.position - 1]

    def _take(self: Parser) -> Token:
        token = self._peek()
        self.position += 1
        return token

    def _accept(self: Parser, *kinds: str) -> Token | None:
        matches = (self._peek().kind == kinds[0] and self._peek().value == kinds[1]
                   if len(kinds) == 2 and kinds[0] == "OP"
                   else self._peek().kind in kinds)
        if matches:
            return self._take()
        return None

    def _expect(self: Parser, kind: str) -> Token:
        if self._peek().kind != kind:
            self._fail(f"expected {kind}")
        return self._take()

    def _fail(self: Parser, message: str, token: Token | None = None) -> None:
        current = token or self._peek()
        raise ParseError(message, current.offset)


def parse(source: str) -> Query:
    return Parser(source).parse()
