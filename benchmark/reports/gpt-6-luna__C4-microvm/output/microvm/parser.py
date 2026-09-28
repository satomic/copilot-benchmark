from dataclasses import dataclass
from collections.abc import Callable

from .errors import ParseError
from .lexer import Token, tokenize


@dataclass(frozen=True)
class Literal:
    value: object


@dataclass(frozen=True)
class Name:
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
class Let:
    name: str
    value: object


@dataclass(frozen=True)
class Assign:
    name: str
    value: object


@dataclass(frozen=True)
class Print:
    value: object


@dataclass(frozen=True)
class Block:
    statements: list[object]


@dataclass(frozen=True)
class If:
    condition: object
    consequent: object
    alternative: object | None


@dataclass(frozen=True)
class While:
    condition: object
    body: object


def parse(src: str) -> Block:
    return _Parser(src, tokenize(src)).program()


class _Parser:
    def __init__(self, src: str, tokens: list[Token]):
        self.src = src
        self.tokens = tokens
        self.index = 0

    def program(self) -> Block:
        statements: list[object] = []
        while self.peek() is not None:
            statements.append(self.statement())
        return Block(statements)

    def statement(self) -> object:
        token = self.peek()
        if token is None:
            raise self.error("expected statement")
        if token.text == "{":
            return self.block()
        if token.text == "let":
            self.take()
            name = self.expect_kind("IDENT", "expected variable name")
            self.expect("=", "expected '=' after variable name")
            value = self.expression()
            self.expect(";", "expected ';' after declaration")
            return Let(name.text, value)
        if token.text == "print":
            self.take()
            value = self.expression()
            self.expect(";", "expected ';' after print")
            return Print(value)
        if token.text == "if":
            return self.if_statement()
        if token.text == "while":
            self.take()
            condition = self.parenthesized()
            return While(condition, self.block())
        if token.kind == "IDENT" and self.peek(1) is not None and self.peek(1).text == "=":
            name = self.take().text
            self.take()
            value = self.expression()
            self.expect(";", "expected ';' after assignment")
            return Assign(name, value)
        raise self.error("expected statement")

    def block(self) -> Block:
        self.expect("{", "expected '{'")
        statements: list[object] = []
        while self.peek() is not None and self.peek().text != "}":
            statements.append(self.statement())
        self.expect("}", "expected '}'")
        return Block(statements)

    def if_statement(self) -> If:
        self.take()
        condition = self.parenthesized()
        consequent = self.block()
        alternative = None
        if self.peek() is not None and self.peek().text == "else":
            self.take()
            alternative = self.if_statement() if self.is_text("if") else self.block()
        return If(condition, consequent, alternative)

    def parenthesized(self) -> object:
        self.expect("(", "expected '('")
        condition = self.expression()
        self.expect(")", "expected ')'")
        return condition

    def expression(self) -> object:
        return self.binary_chain(self.and_expression, {"or"})

    def and_expression(self) -> object:
        return self.binary_chain(self.not_expression, {"and"})

    def binary_chain(self, child: Callable[[], object], operators: set[str]) -> object:
        left = child()
        while self.peek() is not None and self.peek().text in operators:
            op = self.take().text
            left = Binary(op, left, child())
        return left

    def not_expression(self) -> object:
        if self.is_text("not"):
            self.take()
            return Unary("not", self.not_expression())
        return self.comparison()

    def comparison(self) -> object:
        left = self.additive()
        allowed = {"==", "!=", "<", "<=", ">", ">="}
        if self.peek() is not None and self.peek().text in allowed:
            op = self.take().text
            left = Binary(op, left, self.additive())
            if self.peek() is not None and self.peek().text in allowed:
                raise self.error("comparison operators are not associative")
        return left

    def additive(self) -> object:
        return self.binary_chain(self.multiplicative, {"+", "-"})

    def multiplicative(self) -> object:
        return self.binary_chain(self.unary, {"*", "/", "%"})

    def unary(self) -> object:
        if self.is_text("-"):
            self.take()
            return Unary("-", self.unary())
        return self.primary()

    def primary(self) -> object:
        token = self.peek()
        if token is None:
            raise self.error("expected expression")
        if token.kind in {"INT", "FLOAT", "STRING"}:
            self.take()
            return Literal(token.value)
        if token.text in {"true", "false"}:
            self.take()
            return Literal(token.text == "true")
        if token.kind == "IDENT":
            self.take()
            return Name(token.text)
        if token.text == "(":
            self.take()
            value = self.expression()
            self.expect(")", "expected ')'")
            return value
        raise self.error("expected expression")

    def expect_kind(self, kind: str, message: str) -> Token:
        token = self.peek()
        if token is None or token.kind != kind:
            raise self.error(message)
        return self.take()

    def expect(self, text: str, message: str) -> Token:
        if not self.is_text(text):
            raise self.error(message)
        return self.take()

    def is_text(self, text: str) -> bool:
        return self.peek() is not None and self.peek().text == text

    def peek(self, ahead: int = 0) -> Token | None:
        pos = self.index + ahead
        return self.tokens[pos] if pos < len(self.tokens) else None

    def take(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def error(self, message: str) -> ParseError:
        token = self.peek()
        return ParseError(message, len(self.src) if token is None else token.offset)
