from __future__ import annotations

import dataclasses

from microdb.errors import ParseError
from microdb.lexer import Token, tokenize

AGGREGATE_NAMES: frozenset[str] = frozenset({"count", "sum", "avg", "min", "max"})
COMPARE_OPS: frozenset[str] = frozenset({"=", "<>", "<", "<=", ">", ">="})


@dataclasses.dataclass(frozen=True)
class Expr:
    source_text: str


@dataclasses.dataclass(frozen=True)
class LiteralExpr(Expr):
    value: object


@dataclasses.dataclass(frozen=True)
class ColumnRef(Expr):
    table: str | None
    name: str
    bare: bool = True


@dataclasses.dataclass(frozen=True)
class UnaryExpr(Expr):
    op: str
    operand: Expr


@dataclasses.dataclass(frozen=True)
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class IsNullExpr(Expr):
    operand: Expr
    negated: bool


@dataclasses.dataclass(frozen=True)
class FuncCall(Expr):
    name: str
    args: tuple[Expr, ...]


@dataclasses.dataclass(frozen=True)
class AggregateCall(Expr):
    name: str
    args: tuple[Expr, ...]
    is_star: bool = False


@dataclasses.dataclass(frozen=True)
class StarSelectItem:
    table: str | None = None


@dataclasses.dataclass(frozen=True)
class ExprSelectItem:
    expr: Expr
    alias: str | None = None


SelectItem = StarSelectItem | ExprSelectItem


@dataclasses.dataclass(frozen=True)
class JoinClause:
    join_type: str  # "INNER" | "LEFT"
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class OrderItem:
    expr: Expr
    ascending: bool = True


@dataclasses.dataclass(frozen=True)
class Query:
    distinct: bool
    select_items: tuple[SelectItem, ...]
    from_table: str
    join: JoinClause | None
    where: Expr | None
    group_by: tuple[Expr, ...]
    having: Expr | None
    order_by: tuple[OrderItem, ...]
    limit: int | None
    offset: int | None


def contains_aggregate(expr: Expr) -> bool:
    if isinstance(expr, AggregateCall):
        return True
    if isinstance(expr, UnaryExpr):
        return contains_aggregate(expr.operand)
    if isinstance(expr, BinaryExpr):
        return contains_aggregate(expr.left) or contains_aggregate(expr.right)
    if isinstance(expr, IsNullExpr):
        return contains_aggregate(expr.operand)
    if isinstance(expr, FuncCall):
        return any(contains_aggregate(a) for a in expr.args)
    return False


def _format_tokens(tokens: list[Token], start_idx: int, end_idx: int) -> str:
    parts: list[str] = []
    for i in range(start_idx, end_idx):
        if i > start_idx and tokens[i - 1].end < tokens[i].offset:
            parts.append(" ")
        parts.append(tokens[i].text)
    return "".join(parts)


class _Parser:
    def __init__(self, tokens: list[Token], source_len: int) -> None:
        self.tokens: list[Token] = tokens
        self.pos: int = 0
        self.source_len: int = source_len

    def _current_offset(self) -> int:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos].offset
        return self.source_len

    def _peek(self, offset: int = 0) -> Token | None:
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else None

    def _match_kw(self, kw: str) -> bool:
        tok = self._peek()
        if tok is not None and tok.kind == "KEYWORD" and tok.value == kw:
            self.pos += 1
            return True
        return False

    def _expect_kw(self, kw: str) -> Token:
        tok = self._peek()
        if tok is None or tok.kind != "KEYWORD" or tok.value != kw:
            raise ParseError(f"Expected keyword {kw}", offset=self._current_offset())
        self.pos += 1
        return tok

    def _match_op(self, op: str) -> bool:
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.value == op:
            self.pos += 1
            return True
        return False

    def _expect_op(self, op: str) -> Token:
        tok = self._peek()
        if tok is None or tok.kind != "OP" or tok.value != op:
            raise ParseError(f"Expected operator {op!r}", offset=self._current_offset())
        self.pos += 1
        return tok

    def _expect_ident(self) -> str:
        tok = self._peek()
        if tok is None or tok.kind != "IDENT":
            raise ParseError("Expected identifier", offset=self._current_offset())
        self.pos += 1
        assert isinstance(tok.value, str)
        return tok.value

    def parse_query(self) -> Query:
        self._expect_kw("SELECT")
        distinct = self._match_kw("DISTINCT")
        select_items = self._parse_select_items()
        self._expect_kw("FROM")
        from_table = self._expect_ident()
        join = self._parse_join()
        where = self.parse_expr() if self._match_kw("WHERE") else None
        group_by = self._parse_group_by()
        having = self.parse_expr() if self._match_kw("HAVING") else None
        order_by = self._parse_order_by()
        limit = self._parse_int_clause("LIMIT")
        offset = self._parse_int_clause("OFFSET")
        if self.pos < len(self.tokens):
            raise ParseError("Unexpected trailing tokens", offset=self._current_offset())
        return Query(
            distinct=distinct,
            select_items=tuple(select_items),
            from_table=from_table,
            join=join,
            where=where,
            group_by=tuple(group_by),
            having=having,
            order_by=tuple(order_by),
            limit=limit,
            offset=offset,
        )

    def _parse_select_items(self) -> list[SelectItem]:
        items: list[SelectItem] = [self._parse_one_select_item()]
        while self._match_op(","):
            items.append(self._parse_one_select_item())
        return items

    def _parse_one_select_item(self) -> SelectItem:
        if self._match_op("*"):
            return StarSelectItem(table=None)
        t0, t1, t2 = self._peek(0), self._peek(1), self._peek(2)
        if (
            t0 is not None
            and t0.kind == "IDENT"
            and t1 is not None
            and t1.kind == "OP"
            and t1.value == "."
            and t2 is not None
            and t2.kind == "OP"
            and t2.value == "*"
        ):
            self.pos += 3
            assert isinstance(t0.value, str)
            return StarSelectItem(table=t0.value)
        expr = self.parse_expr()
        alias: str | None = None
        if self._match_kw("AS"):
            alias = self._expect_ident()
        return ExprSelectItem(expr=expr, alias=alias)

    def _parse_join(self) -> JoinClause | None:
        join_type: str | None = None
        if self._match_kw("INNER"):
            self._expect_kw("JOIN")
            join_type = "INNER"
        elif self._match_kw("LEFT"):
            self._expect_kw("JOIN")
            join_type = "LEFT"
        elif self._match_kw("JOIN"):
            join_type = "INNER"
        if join_type is None:
            return None
        right_table = self._expect_ident()
        self._expect_kw("ON")
        on_expr = self.parse_expr()
        return JoinClause(join_type=join_type, table=right_table, on=on_expr)

    def _parse_group_by(self) -> list[Expr]:
        if not self._match_kw("GROUP"):
            return []
        self._expect_kw("BY")
        exprs: list[Expr] = [self.parse_expr()]
        while self._match_op(","):
            exprs.append(self.parse_expr())
        return exprs

    def _parse_order_by(self) -> list[OrderItem]:
        if not self._match_kw("ORDER"):
            return []
        self._expect_kw("BY")
        items: list[OrderItem] = [self._parse_one_order_item()]
        while self._match_op(","):
            items.append(self._parse_one_order_item())
        return items

    def _parse_one_order_item(self) -> OrderItem:
        expr = self.parse_expr()
        ascending = True
        if self._match_kw("ASC"):
            ascending = True
        elif self._match_kw("DESC"):
            ascending = False
        return OrderItem(expr=expr, ascending=ascending)

    def _parse_int_clause(self, kw: str) -> int | None:
        if not self._match_kw(kw):
            return None
        tok = self._peek()
        if tok is None or tok.kind != "INT":
            raise ParseError(f"Expected integer after {kw}", offset=self._current_offset())
        self.pos += 1
        assert isinstance(tok.value, int)
        return tok.value

    def parse_expr(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        start = self.pos
        left = self._parse_and()
        while self._match_kw("OR"):
            right = self._parse_and()
            text = _format_tokens(self.tokens, start, self.pos)
            left = BinaryExpr(op="OR", left=left, right=right, source_text=text)
        return left

    def _parse_and(self) -> Expr:
        start = self.pos
        left = self._parse_not()
        while self._match_kw("AND"):
            right = self._parse_not()
            text = _format_tokens(self.tokens, start, self.pos)
            left = BinaryExpr(op="AND", left=left, right=right, source_text=text)
        return left

    def _parse_not(self) -> Expr:
        start = self.pos
        if self._match_kw("NOT"):
            operand = self._parse_not()
            text = _format_tokens(self.tokens, start, self.pos)
            return UnaryExpr(op="NOT", operand=operand, source_text=text)
        return self._parse_predicate()

    def _parse_predicate(self) -> Expr:
        start = self.pos
        left = self._parse_additive()
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.value in COMPARE_OPS:
            self.pos += 1
            assert isinstance(tok.value, str)
            right = self._parse_additive()
            text = _format_tokens(self.tokens, start, self.pos)
            result: Expr = BinaryExpr(op=tok.value, left=left, right=right, source_text=text)
        elif self._match_kw("IS"):
            negated = self._match_kw("NOT")
            self._expect_kw("NULL")
            text = _format_tokens(self.tokens, start, self.pos)
            result = IsNullExpr(operand=left, negated=negated, source_text=text)
        else:
            return left
        next_tok = self._peek()
        if next_tok is not None and (
            (next_tok.kind == "OP" and next_tok.value in COMPARE_OPS)
            or (next_tok.kind == "KEYWORD" and next_tok.value == "IS")
        ):
            raise ParseError("Comparison predicates cannot be chained", offset=next_tok.offset)
        return result

    def _parse_additive(self) -> Expr:
        start = self.pos
        left = self._parse_multiplicative()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "OP" and tok.value in ("+", "-"):
                self.pos += 1
                assert isinstance(tok.value, str)
                right = self._parse_multiplicative()
                text = _format_tokens(self.tokens, start, self.pos)
                left = BinaryExpr(op=tok.value, left=left, right=right, source_text=text)
            else:
                break
        return left

    def _parse_multiplicative(self) -> Expr:
        start = self.pos
        left = self._parse_unary()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "OP" and tok.value in ("*", "/", "%"):
                self.pos += 1
                assert isinstance(tok.value, str)
                right = self._parse_unary()
                text = _format_tokens(self.tokens, start, self.pos)
                left = BinaryExpr(op=tok.value, left=left, right=right, source_text=text)
            else:
                break
        return left

    def _parse_unary(self) -> Expr:
        start = self.pos
        if self._match_op("-"):
            operand = self._parse_unary()
            text = _format_tokens(self.tokens, start, self.pos)
            return UnaryExpr(op="-", operand=operand, source_text=text)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        start = self.pos
        tok = self._peek()
        if tok is None:
            raise ParseError("Unexpected end of input in expression", offset=self._current_offset())
        if tok.kind in ("INT", "FLOAT", "TEXT"):
            self.pos += 1
            return LiteralExpr(value=tok.value, source_text=tok.text)
        if tok.kind == "KEYWORD" and tok.value in ("TRUE", "FALSE", "NULL"):
            self.pos += 1
            val = True if tok.value == "TRUE" else (False if tok.value == "FALSE" else None)
            return LiteralExpr(value=val, source_text=tok.text)
        if self._match_op("("):
            inner = self.parse_expr()
            self._expect_op(")")
            text = _format_tokens(self.tokens, start, self.pos)
            if isinstance(inner, ColumnRef):
                return ColumnRef(table=inner.table, name=inner.name, source_text=text, bare=False)
            return dataclasses.replace(inner, source_text=text)
        if tok.kind == "IDENT":
            return self._parse_ident_primary(start)
        raise ParseError(f"Unexpected token {tok.text!r}", offset=tok.offset)

    def _parse_ident_primary(self, start: int) -> Expr:
        ident = self._expect_ident()
        if self._match_op("."):
            col_name = self._expect_ident()
            text = _format_tokens(self.tokens, start, self.pos)
            return ColumnRef(table=ident, name=col_name, source_text=text, bare=True)
        if self._match_op("("):
            return self._parse_call(ident, start)
        text = _format_tokens(self.tokens, start, self.pos)
        return ColumnRef(table=None, name=ident, source_text=text, bare=True)

    def _parse_call(self, ident: str, start: int) -> Expr:
        lower_name = ident.lower()
        if self._match_op("*"):
            if lower_name != "count":
                raise ParseError("'*' is only allowed in count(*)", offset=self.tokens[start].offset)
            self._expect_op(")")
            text = _format_tokens(self.tokens, start, self.pos)
            return AggregateCall(name=lower_name, args=(), is_star=True, source_text=text)
        args: list[Expr] = []
        if not self._match_op(")"):
            args.append(self.parse_expr())
            while self._match_op(","):
                args.append(self.parse_expr())
            self._expect_op(")")
        text = _format_tokens(self.tokens, start, self.pos)
        if lower_name in AGGREGATE_NAMES:
            for arg in args:
                if contains_aggregate(arg):
                    raise ParseError("Aggregates may not nest", offset=self.tokens[start].offset)
            return AggregateCall(name=lower_name, args=tuple(args), is_star=False, source_text=text)
        return FuncCall(name=lower_name, args=tuple(args), source_text=text)


def parse(source: str) -> Query:
    tokens = tokenize(source)
    if not tokens:
        raise ParseError("Empty query", offset=0)
    parser = _Parser(tokens, len(source))
    return parser.parse_query()
