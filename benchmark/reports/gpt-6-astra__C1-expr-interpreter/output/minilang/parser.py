from dataclasses import dataclass
from typing import TypeAlias

from .errors import ParseError
from .lexer import Token, tokenize


@dataclass(frozen=True)
class Literal:
    value: float | str | bool


@dataclass(frozen=True)
class Variable:
    name: str


@dataclass(frozen=True)
class Unary:
    operator: str
    operand: "Node"


@dataclass(frozen=True)
class Binary:
    operator: str
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class Call:
    name: str
    arguments: tuple["Node", ...]


Node: TypeAlias = Literal | Variable | Unary | Binary | Call
_COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})


class _Parser:
    def __init__(self, source: str) -> None:
        self.tokens = tokenize(source)
        self.index = 0
        self.end = len(source)

    def peek(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def accept(self, *values: str) -> str | None:
        token = self.peek()
        if token is not None and token.kind in {"OP", "KEYWORD"}:
            if isinstance(token.value, str) and token.value in values:
                self.index += 1
                return token.value
        return None

    def error(self, message: str) -> ParseError:
        token = self.peek()
        # Missing tokens are located at the end of the original source.
        return ParseError(message, token.position if token is not None else self.end)

    def expect(self, value: str) -> None:
        if self.accept(value) is None:
            raise self.error(f"expected {value!r}")

    def expression(self) -> Node:
        node = self.and_expression()
        while self.accept("or") is not None:
            node = Binary("or", node, self.and_expression())
        return node

    def and_expression(self) -> Node:
        node = self.not_expression()
        while self.accept("and") is not None:
            node = Binary("and", node, self.not_expression())
        return node

    def not_expression(self) -> Node:
        if self.accept("not") is not None:
            return Unary("not", self.not_expression())
        return self.comparison()

    def comparison(self) -> Node:
        node = self.additive()
        operator = self.accept(*_COMPARISONS)
        if operator is not None:
            node = Binary(operator, node, self.additive())
        return node

    def additive(self) -> Node:
        node = self.multiplicative()
        while (operator := self.accept("+", "-")) is not None:
            node = Binary(operator, node, self.multiplicative())
        return node

    def multiplicative(self) -> Node:
        node = self.unary()
        while (operator := self.accept("*", "/", "%")) is not None:
            node = Binary(operator, node, self.unary())
        return node

    def unary(self) -> Node:
        if self.accept("-") is not None:
            return Unary("-", self.unary())
        return self.power()

    def power(self) -> Node:
        node = self.primary()
        if self.accept("^") is not None:
            node = Binary("^", node, self.unary())
        return node

    def primary(self) -> Node:
        token = self.peek()
        if token is None:
            raise self.error("expected expression")
        if token.kind in {"NUMBER", "STRING"}:
            self.index += 1
            return Literal(token.value)
        if self.accept("true") is not None:
            return Literal(True)
        if self.accept("false") is not None:
            return Literal(False)
        if token.kind == "IDENT":
            self.index += 1
            assert isinstance(token.value, str)
            if self.accept("(") is None:
                return Variable(token.value)
            arguments: list[Node] = []
            if self.accept(")") is None:
                arguments.append(self.expression())
                while self.accept(",") is not None:
                    arguments.append(self.expression())
                self.expect(")")
            return Call(token.value, tuple(arguments))
        if self.accept("(") is not None:
            node = self.expression()
            self.expect(")")
            return node
        raise self.error("expected expression")


def parse(source: str) -> Node:
    parser = _Parser(source)
    node = parser.expression()
    if parser.peek() is not None:
        raise parser.error("unexpected token")
    return node
