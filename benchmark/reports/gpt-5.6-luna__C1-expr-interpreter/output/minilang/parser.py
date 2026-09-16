from dataclasses import dataclass
from .errors import ParseError
from .lexer import tokenize


@dataclass(frozen=True)
class Literal:
    value: object


@dataclass(frozen=True)
class Variable:
    name: str


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple


class Parser:
    def __init__(self, source):
        self.tokens = tokenize(source)
        self.i = 0

    def current(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self, value=None):
        token = self.current()
        if token is None or (value is not None and token.value != value):
            pos = len(self.source) if hasattr(self, "source") else (
                token.position if token else 0)
            raise ParseError("expected expression" if token is None else
                             f"unexpected token: {token.value}", pos)
        self.i += 1
        return token

    def parse(self, source):
        self.source = source
        if not self.tokens:
            raise ParseError("expected expression", 0)
        node = self.or_expr()
        if self.current() is not None:
            t = self.current()
            raise ParseError(f"unexpected token: {t.value}", t.position)
        return node

    def or_expr(self):
        node = self.and_expr()
        while self.current() is not None and self.current().value == "or":
            self.take()
            node = Binary("or", node, self.and_expr())
        return node

    def and_expr(self):
        node = self.not_expr()
        while self.current() is not None and self.current().value == "and":
            self.take()
            node = Binary("and", node, self.not_expr())
        return node

    def not_expr(self):
        if self.current() is not None and self.current().value == "not":
            self.take()
            return Unary("not", self.not_expr())
        return self.comparison()

    def comparison(self):
        node = self.additive()
        if self.current() is not None and self.current().value in {"==", "!=", "<", "<=", ">", ">="}:
            op = self.take().value
            node = Binary(op, node, self.additive())
            if self.current() is not None and self.current().value in {"==", "!=", "<", "<=", ">", ">="}:
                t = self.current()
                raise ParseError("comparisons are not associative", t.position)
        return node

    def additive(self):
        node = self.multiplicative()
        while self.current() is not None and self.current().value in {"+", "-"}:
            op = self.take().value
            node = Binary(op, node, self.multiplicative())
        return node

    def multiplicative(self):
        node = self.unary()
        while self.current() is not None and self.current().value in {"*", "/", "%"}:
            op = self.take().value
            node = Binary(op, node, self.unary())
        return node

    def unary(self):
        if self.current() is not None and self.current().value == "-":
            self.take()
            return Unary("-", self.unary())
        return self.power()

    def power(self):
        node = self.primary()
        if self.current() is not None and self.current().value == "^":
            self.take()
            node = Binary("^", node, self.unary())
        return node

    def primary(self):
        t = self.current()
        if t is None:
            raise ParseError("expected expression", len(self.source))
        if t.kind == "NUMBER":
            self.take()
            return Literal(t.value)
        if t.kind == "STRING":
            self.take()
            return Literal(t.value)
        if t.kind == "KEYWORD" and t.value in {"true", "false"}:
            self.take()
            return Literal(t.value == "true")
        if t.kind == "IDENT":
            self.take()
            if self.current() is not None and self.current().value == "(":
                self.take("(")
                args = []
                if self.current() is not None and self.current().value != ")":
                    args.append(self.or_expr())
                    while self.current() is not None and self.current().value == ",":
                        self.take(",")
                        args.append(self.or_expr())
                self.take(")")
                return Call(t.value, tuple(args))
            return Variable(t.value)
        if t.value == "(":
            self.take("(")
            node = self.or_expr()
            self.take(")")
            return node
        raise ParseError(f"unexpected token: {t.value}", t.position)


def parse(source: str):
    return Parser(source).parse(source)
