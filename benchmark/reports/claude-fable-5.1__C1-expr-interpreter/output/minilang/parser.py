"""Recursive-descent parser for minilang."""

from dataclasses import dataclass

from .errors import ParseError
from .lexer import Token, tokenize


@dataclass(frozen=True)
class Node:
    position: int


@dataclass(frozen=True)
class Number(Node):
    value: float


@dataclass(frozen=True)
class String(Node):
    value: str


@dataclass(frozen=True)
class Boolean(Node):
    value: bool


@dataclass(frozen=True)
class Variable(Node):
    name: str


@dataclass(frozen=True)
class Call(Node):
    name: str
    args: "tuple[Node, ...]"


@dataclass(frozen=True)
class Unary(Node):
    op: str  # "-" or "not"
    operand: Node


@dataclass(frozen=True)
class Binary(Node):
    op: str
    left: Node
    right: Node


_COMPARISON_OPS = ("==", "!=", "<", "<=", ">", ">=")


class _Parser:
    def __init__(self, tokens: "list[Token]", source_length: int):
        self.tokens = tokens
        self.pos = 0
        self.end = source_length

    # -- helpers -----------------------------------------------------------

    def _peek(self) -> "Token | None":
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _position(self) -> int:
        tok = self._peek()
        return tok.position if tok is not None else self.end

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _at_op(self, *ops: str) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == "OP" and tok.value in ops

    def _at_keyword(self, word: str) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == "KEYWORD" and tok.value == word

    def _expect_op(self, op: str) -> Token:
        if not self._at_op(op):
            tok = self._peek()
            found = "end of input" if tok is None else repr(tok.value)
            raise ParseError(f"expected '{op}', got {found}", self._position())
        return self._advance()

    # -- grammar -----------------------------------------------------------

    def parse(self) -> Node:
        if not self.tokens:
            raise ParseError("empty expression", self.end)
        node = self.expr()
        if self._peek() is not None:
            tok = self._peek()
            raise ParseError(f"unexpected token {tok.value!r}", tok.position)
        return node

    def expr(self) -> Node:
        return self.or_expr()

    def or_expr(self) -> Node:
        node = self.and_expr()
        while self._at_keyword("or"):
            tok = self._advance()
            right = self.and_expr()
            node = Binary(tok.position, "or", node, right)
        return node

    def and_expr(self) -> Node:
        node = self.not_expr()
        while self._at_keyword("and"):
            tok = self._advance()
            right = self.not_expr()
            node = Binary(tok.position, "and", node, right)
        return node

    def not_expr(self) -> Node:
        if self._at_keyword("not"):
            tok = self._advance()
            return Unary(tok.position, "not", self.not_expr())
        return self.comparison()

    def comparison(self) -> Node:
        node = self.additive()
        if self._at_op(*_COMPARISON_OPS):
            tok = self._advance()
            right = self.additive()
            node = Binary(tok.position, tok.value, node, right)
            if self._at_op(*_COMPARISON_OPS):
                raise ParseError(
                    "comparison operators cannot be chained", self._position()
                )
        return node

    def additive(self) -> Node:
        node = self.multiplicative()
        while self._at_op("+", "-"):
            tok = self._advance()
            right = self.multiplicative()
            node = Binary(tok.position, tok.value, node, right)
        return node

    def multiplicative(self) -> Node:
        node = self.unary()
        while self._at_op("*", "/", "%"):
            tok = self._advance()
            right = self.unary()
            node = Binary(tok.position, tok.value, node, right)
        return node

    def unary(self) -> Node:
        if self._at_op("-"):
            tok = self._advance()
            return Unary(tok.position, "-", self.unary())
        return self.power()

    def power(self) -> Node:
        node = self.primary()
        if self._at_op("^"):
            tok = self._advance()
            right = self.unary()
            node = Binary(tok.position, "^", node, right)
        return node

    def primary(self) -> Node:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.end)
        if tok.kind == "NUMBER":
            self._advance()
            return Number(tok.position, tok.value)
        if tok.kind == "STRING":
            self._advance()
            return String(tok.position, tok.value)
        if tok.kind == "KEYWORD" and tok.value in ("true", "false"):
            self._advance()
            return Boolean(tok.position, tok.value == "true")
        if tok.kind == "IDENT":
            self._advance()
            if self._at_op("("):
                self._advance()
                args = []
                if not self._at_op(")"):
                    args.append(self.expr())
                    while self._at_op(","):
                        self._advance()
                        args.append(self.expr())
                self._expect_op(")")
                return Call(tok.position, tok.value, tuple(args))
            return Variable(tok.position, tok.value)
        if tok.kind == "OP" and tok.value == "(":
            self._advance()
            node = self.expr()
            self._expect_op(")")
            return node
        raise ParseError(f"unexpected token {tok.value!r}", tok.position)


def parse(source: str) -> Node:
    tokens = tokenize(source)
    return _Parser(tokens, len(source)).parse()
