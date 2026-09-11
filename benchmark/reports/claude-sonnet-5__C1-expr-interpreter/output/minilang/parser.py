"""Recursive-descent parser for minilang.

Produces an AST built from simple dataclasses; parsing never evaluates
anything (e.g. ``parse("1 / 0")`` succeeds).
"""

from dataclasses import dataclass, field
from typing import Any, List

from .errors import ParseError
from .lexer import tokenize

_COMPARISON_OPS = ("==", "!=", "<", "<=", ">", ">=")


@dataclass
class NumberNode:
    value: float
    position: int


@dataclass
class StringNode:
    value: str
    position: int


@dataclass
class BoolNode:
    value: bool
    position: int


@dataclass
class IdentNode:
    name: str
    position: int


@dataclass
class CallNode:
    name: str
    args: List[Any] = field(default_factory=list)
    position: int = 0


@dataclass
class UnaryMinusNode:
    operand: Any
    position: int


@dataclass
class NotNode:
    operand: Any
    position: int


@dataclass
class AndNode:
    left: Any
    right: Any
    position: int


@dataclass
class OrNode:
    left: Any
    right: Any
    position: int


@dataclass
class BinOpNode:
    op: str
    left: Any
    right: Any
    position: int


class _Parser:
    def __init__(self, tokens, source_len):
        self.tokens = tokens
        self.pos = 0
        self.source_len = source_len

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def at_end(self):
        return self.pos >= len(self.tokens)

    def eof_position(self):
        return self.source_len

    def is_op(self, tok, value):
        return tok is not None and tok.kind == "OP" and tok.value == value

    def is_op_in(self, tok, values):
        return tok is not None and tok.kind == "OP" and tok.value in values

    def is_keyword(self, tok, value):
        return tok is not None and tok.kind == "KEYWORD" and tok.value == value

    # expr := or_expr
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.is_keyword(self.peek(), "or"):
            self.advance()
            right = self.parse_and()
            left = OrNode(left, right, left.position)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.is_keyword(self.peek(), "and"):
            self.advance()
            right = self.parse_not()
            left = AndNode(left, right, left.position)
        return left

    def parse_not(self):
        tok = self.peek()
        if self.is_keyword(tok, "not"):
            self.advance()
            operand = self.parse_not()
            return NotNode(operand, tok.position)
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        tok = self.peek()
        if self.is_op_in(tok, _COMPARISON_OPS):
            op = tok.value
            pos = tok.position
            self.advance()
            right = self.parse_additive()
            node = BinOpNode(op, left, right, pos)
            tok2 = self.peek()
            if self.is_op_in(tok2, _COMPARISON_OPS):
                raise ParseError(
                    "comparison operators are non-associative", tok2.position
                )
            return node
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            tok = self.peek()
            if self.is_op_in(tok, ("+", "-")):
                self.advance()
                right = self.parse_multiplicative()
                left = BinOpNode(tok.value, left, right, tok.position)
            else:
                break
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if self.is_op_in(tok, ("*", "/", "%")):
                self.advance()
                right = self.parse_unary()
                left = BinOpNode(tok.value, left, right, tok.position)
            else:
                break
        return left

    def parse_unary(self):
        tok = self.peek()
        if self.is_op(tok, "-"):
            self.advance()
            operand = self.parse_unary()
            return UnaryMinusNode(operand, tok.position)
        return self.parse_power()

    def parse_power(self):
        left = self.parse_primary()
        tok = self.peek()
        if self.is_op(tok, "^"):
            self.advance()
            right = self.parse_unary()
            return BinOpNode("^", left, right, tok.position)
        return left

    def parse_primary(self):
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.eof_position())

        if tok.kind == "NUMBER":
            self.advance()
            return NumberNode(tok.value, tok.position)

        if tok.kind == "STRING":
            self.advance()
            return StringNode(tok.value, tok.position)

        if tok.kind == "KEYWORD" and tok.value in ("true", "false"):
            self.advance()
            return BoolNode(tok.value == "true", tok.position)

        if tok.kind == "IDENT":
            self.advance()
            nxt = self.peek()
            if self.is_op(nxt, "("):
                self.advance()
                args = []
                if not self.is_op(self.peek(), ")"):
                    args.append(self.parse_expr())
                    while self.is_op(self.peek(), ","):
                        self.advance()
                        args.append(self.parse_expr())
                if not self.is_op(self.peek(), ")"):
                    p = self.peek()
                    pos = p.position if p is not None else self.eof_position()
                    raise ParseError("expected ')'", pos)
                self.advance()
                return CallNode(tok.value, args, tok.position)
            return IdentNode(tok.value, tok.position)

        if self.is_op(tok, "("):
            self.advance()
            node = self.parse_expr()
            if not self.is_op(self.peek(), ")"):
                p = self.peek()
                pos = p.position if p is not None else self.eof_position()
                raise ParseError("expected ')'", pos)
            self.advance()
            return node

        raise ParseError(f"unexpected token: {tok.value!r}", tok.position)


def parse(source: str):
    tokens = tokenize(source)
    if not tokens:
        raise ParseError("empty expression", 0)
    parser = _Parser(tokens, len(source))
    node = parser.parse_expr()
    if not parser.at_end():
        tok = parser.peek()
        raise ParseError("unexpected trailing input", tok.position)
    return node
