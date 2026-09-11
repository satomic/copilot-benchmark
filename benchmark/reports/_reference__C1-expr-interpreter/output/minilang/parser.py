"""Recursive-descent parser producing a small AST."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import ParseError
from .lexer import Token, tokenize

_COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})
_ADDITIVE = frozenset({"+", "-"})
_MULTIPLICATIVE = frozenset({"*", "/", "%"})


@dataclass(frozen=True)
class Literal:
    value: object
    position: int


@dataclass(frozen=True)
class Var:
    name: str
    position: int


@dataclass(frozen=True)
class Call:
    name: str
    args: list = field(default_factory=list)
    position: int = 0


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object
    position: int


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object
    position: int


@dataclass(frozen=True)
class Logical:
    op: str            # "and" | "or"
    left: object
    right: object
    position: int


def parse(source: str) -> object:
    """Parse `source` into an AST root node without evaluating anything."""
    parser = _Parser(tokenize(source), len(source))
    node = parser.parse_expr()
    parser.expect_end()
    return node


class _Parser:
    def __init__(self, tokens: list[Token], source_length: int) -> None:
        self._tokens = tokens
        self._index = 0
        self._end = source_length

    # ------------------------------------------------------------ helpers --

    def _peek(self) -> Token | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _advance(self) -> Token:
        token = self._peek()
        if token is None:
            raise ParseError("unexpected end of input", self._end)
        self._index += 1
        return token

    def _match_op(self, values) -> Token | None:
        token = self._peek()
        if token is not None and token.kind == "OP" and token.value in values:
            self._index += 1
            return token
        return None

    def _match_keyword(self, word: str) -> Token | None:
        token = self._peek()
        if token is not None and token.kind == "KEYWORD" and token.value == word:
            self._index += 1
            return token
        return None

    def expect_end(self) -> None:
        token = self._peek()
        if token is not None:
            raise ParseError(f"unexpected trailing input {token.value!r}", token.position)

    # ------------------------------------------------------------ grammar --

    def parse_expr(self) -> object:
        return self._or_expr()

    def _or_expr(self) -> object:
        node = self._and_expr()
        while True:
            token = self._match_keyword("or")
            if token is None:
                return node
            node = Logical("or", node, self._and_expr(), token.position)

    def _and_expr(self) -> object:
        node = self._not_expr()
        while True:
            token = self._match_keyword("and")
            if token is None:
                return node
            node = Logical("and", node, self._not_expr(), token.position)

    def _not_expr(self) -> object:
        token = self._match_keyword("not")
        if token is not None:
            return Unary("not", self._not_expr(), token.position)
        return self._comparison()

    def _comparison(self) -> object:
        node = self._additive()
        token = self._match_op(_COMPARISONS)
        if token is None:
            return node
        right = self._additive()
        # Comparison is non-associative: a second operator is an error.
        follow = self._peek()
        if follow is not None and follow.kind == "OP" and follow.value in _COMPARISONS:
            raise ParseError(
                f"comparison operator {follow.value!r} cannot be chained", follow.position
            )
        return Binary(str(token.value), node, right, token.position)

    def _additive(self) -> object:
        node = self._multiplicative()
        while True:
            token = self._match_op(_ADDITIVE)
            if token is None:
                return node
            node = Binary(str(token.value), node, self._multiplicative(), token.position)

    def _multiplicative(self) -> object:
        node = self._unary()
        while True:
            token = self._match_op(_MULTIPLICATIVE)
            if token is None:
                return node
            node = Binary(str(token.value), node, self._unary(), token.position)

    def _unary(self) -> object:
        token = self._match_op({"-"})
        if token is not None:
            return Unary("-", self._unary(), token.position)
        return self._power()

    def _power(self) -> object:
        node = self._primary()
        token = self._match_op({"^"})
        if token is None:
            return node
        # Right-associative, and the exponent may itself be unary-negated.
        return Binary("^", node, self._unary(), token.position)

    def _primary(self) -> object:
        token = self._advance()

        if token.kind == "NUMBER" or token.kind == "STRING":
            return Literal(token.value, token.position)

        if token.kind == "KEYWORD":
            if token.value == "true":
                return Literal(True, token.position)
            if token.value == "false":
                return Literal(False, token.position)
            raise ParseError(f"unexpected keyword {token.value!r}", token.position)

        if token.kind == "IDENT":
            if self._match_op({"("}) is not None:
                return Call(str(token.value), self._arguments(), token.position)
            return Var(str(token.value), token.position)

        if token.kind == "OP" and token.value == "(":
            node = self.parse_expr()
            if self._match_op({")"}) is None:
                raise ParseError("expected ')'", self._current_position())
            return node

        raise ParseError(f"unexpected token {token.value!r}", token.position)

    def _arguments(self) -> list:
        if self._match_op({")"}) is not None:
            return []
        args = [self.parse_expr()]
        while self._match_op({","}) is not None:
            args.append(self.parse_expr())
        if self._match_op({")"}) is None:
            raise ParseError("expected ')'", self._current_position())
        return args

    def _current_position(self) -> int:
        token = self._peek()
        return token.position if token is not None else self._end
