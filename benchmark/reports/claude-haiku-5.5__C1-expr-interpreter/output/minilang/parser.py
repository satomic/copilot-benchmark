"""Recursive-descent parser for minilang. Parsing never evaluates anything."""

from dataclasses import dataclass
from typing import Any

from .errors import ParseError
from .lexer import tokenize

_COMPARISON_OPS = frozenset({"==", "!=", "<", "<=", ">", ">="})


@dataclass(frozen=True)
class Literal:
    value: Any
    position: int


@dataclass(frozen=True)
class Var:
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
    operand: Any
    position: int


@dataclass(frozen=True)
class Binary:
    op: str  # arithmetic, comparison, "and" or "or"
    left: Any
    right: Any
    position: int


class _Parser:
    def __init__(self, tokens, source_length):
        self._tokens = tokens
        self._pos = 0
        self._end = source_length

    def at_end(self):
        return self._pos >= len(self._tokens)

    def _peek(self):
        return None if self.at_end() else self._tokens[self._pos]

    def _match(self, *values):
        """Consume the next token if it is an operator/keyword whose value is in ``values``."""
        tok = self._peek()
        if tok is not None and tok.kind in ("OP", "KEYWORD") and tok.value in values:
            self._pos += 1
            return tok
        return None

    def _expect(self, value):
        if self._match(value) is None:
            raise self.error(f"expected {value!r}")

    def error(self, message):
        tok = self._peek()
        if tok is None:
            return ParseError(f"{message}, found end of input", self._end)
        return ParseError(f"{message}, found {tok.value!r}", tok.position)

    def _binary_level(self, ops, operand):
        node = operand()
        while True:
            tok = self._match(*ops)
            if tok is None:
                return node
            node = Binary(tok.value, node, operand(), tok.position)

    def expression(self):
        return self._binary_level(("or",), self._and)

    def _and(self):
        return self._binary_level(("and",), self._not)

    def _not(self):
        tok = self._match("not")
        if tok is not None:
            return Unary("not", self._not(), tok.position)
        return self._comparison()

    def _comparison(self):
        left = self._binary_level(("+", "-"), self._multiplicative)
        tok = self._peek()
        if tok is None or tok.kind != "OP" or tok.value not in _COMPARISON_OPS:
            return left
        self._pos += 1
        right = self._binary_level(("+", "-"), self._multiplicative)
        node = Binary(tok.value, left, right, tok.position)
        nxt = self._peek()
        if nxt is not None and nxt.kind == "OP" and nxt.value in _COMPARISON_OPS:
            raise ParseError("comparison operators cannot be chained", nxt.position)
        return node

    def _multiplicative(self):
        return self._binary_level(("*", "/", "%"), self._unary)

    def _unary(self):
        tok = self._match("-")
        if tok is not None:
            return Unary("-", self._unary(), tok.position)
        return self._power()

    def _power(self):
        base = self._primary()
        tok = self._match("^")
        if tok is not None:
            # right-associative; the exponent is a unary so that 2 ^ -1 is valid
            return Binary("^", base, self._unary(), tok.position)
        return base

    def _primary(self):
        tok = self._peek()
        if tok is None:
            raise self.error("expected expression")
        if tok.kind in ("NUMBER", "STRING"):
            self._pos += 1
            return Literal(tok.value, tok.position)
        if tok.kind == "KEYWORD" and tok.value in ("true", "false"):
            self._pos += 1
            return Literal(tok.value == "true", tok.position)
        if tok.kind == "IDENT":
            self._pos += 1
            if self._match("(") is not None:
                return Call(tok.value, tuple(self._arguments()), tok.position)
            return Var(tok.value, tok.position)
        if self._match("(") is not None:
            node = self.expression()
            self._expect(")")
            return node
        raise self.error("expected expression")

    def _arguments(self):
        args = []
        if self._match(")") is not None:
            return args
        while True:
            args.append(self.expression())
            if self._match(",") is not None:
                continue
            self._expect(")")
            return args


def parse(source):
    """Parse ``source`` into an AST. Raises LexError/ParseError; never evaluates."""
    parser = _Parser(tokenize(source), len(source))
    node = parser.expression()
    if not parser.at_end():
        raise parser.error("unexpected token")
    return node
