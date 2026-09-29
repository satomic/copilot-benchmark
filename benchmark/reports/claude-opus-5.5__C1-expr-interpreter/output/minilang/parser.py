"""Recursive-descent parser for minilang."""

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
class Name:
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
    op: str
    left: object
    right: object
    position: int


_COMPARISON_OPS = frozenset({"==", "!=", "<", "<=", ">", ">="})


class _Parser:
    def __init__(self, source):
        self.tokens = tokenize(source)
        self.pos = 0
        self.end = len(source)

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def at(self, kind, value):
        tok = self.peek()
        return tok is not None and tok.kind == kind and tok.value == value

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def error(self, message, tok=None):
        tok = tok if tok is not None else self.peek()
        if tok is None:
            raise ParseError(f"{message}, got end of input", self.end)
        raise ParseError(f"{message}, got {tok.value!r}", tok.position)

    def expect_op(self, value):
        if not self.at("OP", value):
            self.error(f"expected {value!r}")
        return self.advance()

    def parse(self):
        if not self.tokens:
            raise ParseError("empty expression", self.end)
        node = self.expr()
        if self.peek() is not None:
            self.error("unexpected trailing input")
        return node

    def expr(self):
        return self.or_expr()

    def or_expr(self):
        node = self.and_expr()
        while self.at("KEYWORD", "or"):
            tok = self.advance()
            node = Binary("or", node, self.and_expr(), tok.position)
        return node

    def and_expr(self):
        node = self.not_expr()
        while self.at("KEYWORD", "and"):
            tok = self.advance()
            node = Binary("and", node, self.not_expr(), tok.position)
        return node

    def not_expr(self):
        if self.at("KEYWORD", "not"):
            tok = self.advance()
            return Unary("not", self.not_expr(), tok.position)
        return self.comparison()

    def comparison(self):
        node = self.additive()
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.value in _COMPARISON_OPS:
            self.advance()
            node = Binary(tok.value, node, self.additive(), tok.position)
            nxt = self.peek()
            if nxt is not None and nxt.kind == "OP" and nxt.value in _COMPARISON_OPS:
                raise ParseError(
                    f"comparison operators are non-associative: unexpected {nxt.value!r}",
                    nxt.position,
                )
        return node

    def additive(self):
        node = self.multiplicative()
        while self.at("OP", "+") or self.at("OP", "-"):
            tok = self.advance()
            node = Binary(tok.value, node, self.multiplicative(), tok.position)
        return node

    def multiplicative(self):
        node = self.unary()
        while self.at("OP", "*") or self.at("OP", "/") or self.at("OP", "%"):
            tok = self.advance()
            node = Binary(tok.value, node, self.unary(), tok.position)
        return node

    def unary(self):
        if self.at("OP", "-"):
            tok = self.advance()
            return Unary("-", self.unary(), tok.position)
        return self.power()

    def power(self):
        node = self.primary()
        if self.at("OP", "^"):
            tok = self.advance()
            node = Binary("^", node, self.unary(), tok.position)
        return node

    def primary(self):
        tok = self.peek()
        if tok is None:
            self.error("expected an expression")
        if tok.kind == "NUMBER":
            self.advance()
            return Number(tok.value, tok.position)
        if tok.kind == "STRING":
            self.advance()
            return String(tok.value, tok.position)
        if tok.kind == "KEYWORD" and tok.value in ("true", "false"):
            self.advance()
            return Boolean(tok.value == "true", tok.position)
        if tok.kind == "IDENT":
            self.advance()
            if self.at("OP", "("):
                self.advance()
                args = []
                if not self.at("OP", ")"):
                    args.append(self.expr())
                    while self.at("OP", ","):
                        self.advance()
                        args.append(self.expr())
                self.expect_op(")")
                return Call(tok.value, tuple(args), tok.position)
            return Name(tok.value, tok.position)
        if tok.kind == "OP" and tok.value == "(":
            self.advance()
            node = self.expr()
            self.expect_op(")")
            return node
        self.error("expected an expression")


def parse(source: str) -> object:
    parser = _Parser(source)
    try:
        return parser.parse()
    except RecursionError:
        raise ParseError("expression too deeply nested", None) from None
