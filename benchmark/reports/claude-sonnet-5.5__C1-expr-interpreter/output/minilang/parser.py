from dataclasses import dataclass

from .errors import ParseError
from .lexer import tokenize


@dataclass(frozen=True)
class Number:
    value: float
    position: int


@dataclass(frozen=True)
class String:
    value: str
    position: int


@dataclass(frozen=True)
class Boolean:
    value: bool
    position: int


@dataclass(frozen=True)
class Variable:
    name: str
    position: int


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple
    position: int


@dataclass(frozen=True)
class Unary:
    op: str  # "-" or "not"
    operand: object
    position: int


@dataclass(frozen=True)
class Binary:
    op: str  # arithmetic, comparison, "and", "or"
    left: object
    right: object
    position: int


COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")


class _Parser:
    def __init__(self, tokens, length):
        self.tokens = tokens
        self.length = length
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self):
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.length)
        self.i += 1
        return tok

    def is_op(self, *ops):
        t = self.peek()
        return t is not None and t.kind == "OP" and t.value in ops

    def is_kw(self, kw):
        t = self.peek()
        return t is not None and t.kind == "KEYWORD" and t.value == kw

    def parse_all(self):
        node = self.expr()
        t = self.peek()
        if t is not None:
            raise ParseError(f"unexpected token: {t.value!r}", t.position)
        return node

    def expr(self):
        node = self.and_expr()
        while self.is_kw("or"):
            t = self.next()
            node = Binary("or", node, self.and_expr(), t.position)
        return node

    def and_expr(self):
        node = self.not_expr()
        while self.is_kw("and"):
            t = self.next()
            node = Binary("and", node, self.not_expr(), t.position)
        return node

    def not_expr(self):
        if self.is_kw("not"):
            t = self.next()
            return Unary("not", self.not_expr(), t.position)
        return self.comparison()

    def comparison(self):
        node = self.additive()
        if self.is_op(*COMPARISONS):
            t = self.next()
            node = Binary(t.value, node, self.additive(), t.position)
            if self.is_op(*COMPARISONS):
                raise ParseError("comparison operators cannot be chained", self.peek().position)
        return node

    def additive(self):
        node = self.multiplicative()
        while self.is_op("+", "-"):
            t = self.next()
            node = Binary(t.value, node, self.multiplicative(), t.position)
        return node

    def multiplicative(self):
        node = self.unary()
        while self.is_op("*", "/", "%"):
            t = self.next()
            node = Binary(t.value, node, self.unary(), t.position)
        return node

    def unary(self):
        if self.is_op("-"):
            t = self.next()
            return Unary("-", self.unary(), t.position)
        return self.power()

    def power(self):
        node = self.primary()
        if self.is_op("^"):
            t = self.next()
            node = Binary("^", node, self.unary(), t.position)
        return node

    def primary(self):
        t = self.next()
        if t.kind == "NUMBER":
            return Number(t.value, t.position)
        if t.kind == "STRING":
            return String(t.value, t.position)
        if t.kind == "KEYWORD" and t.value in ("true", "false"):
            return Boolean(t.value == "true", t.position)
        if t.kind == "IDENT":
            if self.is_op("("):
                self.next()
                args = []
                if self.is_op(")"):
                    self.next()
                else:
                    args.append(self.expr())
                    while self.is_op(","):
                        self.next()
                        args.append(self.expr())
                    close = self.next()
                    if not (close.kind == "OP" and close.value == ")"):
                        raise ParseError("expected ')' or ','", close.position)
                return Call(t.value, tuple(args), t.position)
            return Variable(t.value, t.position)
        if t.kind == "OP" and t.value == "(":
            node = self.expr()
            close = self.next()
            if not (close.kind == "OP" and close.value == ")"):
                raise ParseError("expected ')'", close.position)
            return node
        raise ParseError(f"unexpected token: {t.value!r}", t.position)


def parse(source):
    return _Parser(tokenize(source), len(source)).parse_all()
