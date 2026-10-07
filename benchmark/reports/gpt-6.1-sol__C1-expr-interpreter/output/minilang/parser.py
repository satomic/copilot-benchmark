from dataclasses import dataclass

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


Node = Literal | Variable | Unary | Binary | Call
COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})


class _Parser:
    def __init__(self, tokens: list[Token], end: int):
        self.tokens = tokens
        self.index = 0
        self.end = end

    def peek(self) -> Token | None:
        if self.index < len(self.tokens):
            return self.tokens[self.index]
        return None

    def position(self) -> int:
        token = self.peek()
        return self.end if token is None else token.position

    def matches(self, values: set[str] | frozenset[str]) -> bool:
        token = self.peek()
        return (
            token is not None
            and token.kind in {"OP", "KEYWORD"}
            and token.value in values
        )

    def accept(self, value: str) -> bool:
        if self.matches({value}):
            self.index += 1
            return True
        return False

    def require(self, value: str) -> None:
        if not self.accept(value):
            raise ParseError(f"expected {value!r}", self.position())

    def left_chain(self, operand, operators: set[str]) -> Node:
        node = operand()
        while self.matches(operators):
            operator = self.tokens[self.index].value
            self.index += 1
            node = Binary(operator, node, operand())
        return node

    def expression(self) -> Node:
        return self.left_chain(self.and_expression, {"or"})

    def and_expression(self) -> Node:
        return self.left_chain(self.not_expression, {"and"})

    def not_expression(self) -> Node:
        if self.accept("not"):
            return Unary("not", self.not_expression())
        return self.comparison()

    def comparison(self) -> Node:
        node = self.additive()
        if self.matches(COMPARISONS):
            operator = self.tokens[self.index].value
            self.index += 1
            node = Binary(operator, node, self.additive())
            if self.matches(COMPARISONS):
                raise ParseError("comparisons cannot be chained", self.position())
        return node

    def additive(self) -> Node:
        return self.left_chain(self.multiplicative, {"+", "-"})

    def multiplicative(self) -> Node:
        return self.left_chain(self.unary, {"*", "/", "%"})

    def unary(self) -> Node:
        if self.accept("-"):
            return Unary("-", self.unary())
        return self.power()

    def power(self) -> Node:
        node = self.primary()
        if self.accept("^"):
            node = Binary("^", node, self.unary())
        return node

    def primary(self) -> Node:
        token = self.peek()
        if token is None:
            raise ParseError("expected an expression", self.end)
        if token.kind in {"NUMBER", "STRING"}:
            self.index += 1
            return Literal(token.value)
        if token.kind == "KEYWORD" and token.value in {"true", "false"}:
            self.index += 1
            return Literal(token.value == "true")
        if token.kind == "IDENT":
            self.index += 1
            name = token.value
            if not self.accept("("):
                return Variable(name)
            arguments = []
            if not self.accept(")"):
                arguments.append(self.expression())
                while self.accept(","):
                    arguments.append(self.expression())
                self.require(")")
            return Call(name, tuple(arguments))
        if self.accept("("):
            node = self.expression()
            self.require(")")
            return node
        raise ParseError("expected an expression", token.position)


def parse(source: str) -> Node:
    parser = _Parser(tokenize(source), len(source))
    node = parser.expression()
    if parser.peek() is not None:
        raise ParseError("unexpected trailing input", parser.position())
    return node
