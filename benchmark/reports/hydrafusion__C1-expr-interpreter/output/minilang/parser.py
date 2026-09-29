from dataclasses import dataclass

from .errors import ParseError
from .lexer import Token, tokenize


@dataclass(frozen=True, slots=True)
class Literal:
    value: object


@dataclass(frozen=True, slots=True)
class Variable:
    name: str


@dataclass(frozen=True, slots=True)
class Call:
    name: str
    arguments: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class Unary:
    operator: str
    operand: object


@dataclass(frozen=True, slots=True)
class Binary:
    operator: str
    left: object
    right: object


class _Parser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens = tokenize(source)
        self.index = 0

    def current(self) -> Token | None:
        if self.index == len(self.tokens):
            return None
        return self.tokens[self.index]

    def position(self) -> int:
        token = self.current()
        return len(self.source) if token is None else token.position

    def match(self, *values: str) -> Token | None:
        token = self.current()
        if token is not None and token.value in values:
            self.index += 1
            return token
        return None

    def expect(self, value: str) -> Token:
        token = self.match(value)
        if token is None:
            raise ParseError(f"expected '{value}'", self.position())
        return token

    def expression(self) -> object:
        return self.or_expression()

    def or_expression(self) -> object:
        node = self.and_expression()
        while self.match("or"):
            node = Binary("or", node, self.and_expression())
        return node

    def and_expression(self) -> object:
        node = self.not_expression()
        while self.match("and"):
            node = Binary("and", node, self.not_expression())
        return node

    def not_expression(self) -> object:
        if self.match("not"):
            return Unary("not", self.not_expression())
        return self.comparison()

    def comparison(self) -> object:
        node = self.additive()
        token = self.match("==", "!=", "<", "<=", ">", ">=")
        if token is not None:
            node = Binary(str(token.value), node, self.additive())
            chained = self.current()
            if chained is not None and chained.value in {
                "==",
                "!=",
                "<",
                "<=",
                ">",
                ">=",
            }:
                raise ParseError("comparison operators are non-associative", chained.position)
        return node

    def additive(self) -> object:
        node = self.multiplicative()
        while True:
            token = self.match("+", "-")
            if token is None:
                return node
            node = Binary(str(token.value), node, self.multiplicative())

    def multiplicative(self) -> object:
        node = self.unary()
        while True:
            token = self.match("*", "/", "%")
            if token is None:
                return node
            node = Binary(str(token.value), node, self.unary())

    def unary(self) -> object:
        if self.match("-"):
            return Unary("-", self.unary())
        return self.power()

    def power(self) -> object:
        node = self.primary()
        if self.match("^"):
            node = Binary("^", node, self.unary())
        return node

    def primary(self) -> object:
        token = self.current()
        if token is None:
            raise ParseError("expected expression", len(self.source))

        if token.kind in {"NUMBER", "STRING"}:
            self.index += 1
            return Literal(token.value)
        if token.kind == "KEYWORD" and token.value in {"true", "false"}:
            self.index += 1
            return Literal(token.value == "true")
        if token.kind == "IDENT":
            self.index += 1
            name = str(token.value)
            if not self.match("("):
                return Variable(name)
            arguments: list[object] = []
            if not self.match(")"):
                arguments.append(self.expression())
                while self.match(","):
                    arguments.append(self.expression())
                self.expect(")")
            return Call(name, tuple(arguments))
        if self.match("("):
            node = self.expression()
            self.expect(")")
            return node
        raise ParseError("expected expression", token.position)


def parse(source: str) -> object:
    parser = _Parser(source)
    if not parser.tokens:
        raise ParseError("expected expression", len(source))
    node = parser.expression()
    trailing = parser.current()
    if trailing is not None:
        raise ParseError("unexpected trailing input", trailing.position)
    return node
