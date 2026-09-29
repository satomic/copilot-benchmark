from dataclasses import dataclass

from .errors import ParseError
from .lexer import Token, tokenize


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
class If:
    condition: object
    then_branch: object
    else_branch: object | None


@dataclass(frozen=True)
class While:
    condition: object
    body: object


@dataclass(frozen=True)
class Block:
    statements: tuple[object, ...]


class _Parser:
    def __init__(self, tokens: list[Token], source_length: int) -> None:
        self.tokens = tokens
        self.pos = 0
        self.source_length = source_length

    def error(self, message: str) -> ParseError:
        offset = self.tokens[self.pos].offset if self.pos < len(self.tokens) else self.source_length
        return ParseError(f"{message} at offset {offset}", offset)

    def peek(self, text: str | None = None, kind: str | None = None) -> bool:
        if self.pos >= len(self.tokens):
            return False
        token = self.tokens[self.pos]
        return (text is None or token.text == text) and (kind is None or token.kind == kind)

    def take(self, text: str | None = None, kind: str | None = None) -> Token:
        if not self.peek(text, kind):
            expected = text if text is not None else kind
            raise self.error(f"expected {expected}")
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def program(self) -> Block:
        statements: list[object] = []
        while self.pos < len(self.tokens):
            statements.append(self.statement())
        return Block(tuple(statements))

    def statement(self) -> object:
        if self.peek("let"):
            self.take("let")
            name = self.take(kind="IDENT").text
            self.take("=")
            value = self.expression()
            self.take(";")
            return Let(name, value)
        if self.peek("print"):
            self.take("print")
            value = self.expression()
            self.take(";")
            return Print(value)
        if self.peek("if"):
            return self.if_statement()
        if self.peek("while"):
            self.take("while")
            condition = self.parenthesized()
            return While(condition, self.block())
        if self.peek("{"):
            return self.block()
        if self.peek(kind="IDENT"):
            name = self.take(kind="IDENT").text
            self.take("=")
            value = self.expression()
            self.take(";")
            return Assign(name, value)
        raise self.error("expected statement")

    def if_statement(self) -> If:
        self.take("if")
        condition = self.parenthesized()
        then_branch = self.block()
        else_branch = None
        if self.peek("else"):
            self.take("else")
            else_branch = self.if_statement() if self.peek("if") else self.block()
        return If(condition, then_branch, else_branch)

    def block(self) -> Block:
        self.take("{")
        statements: list[object] = []
        while not self.peek("}"):
            if self.pos >= len(self.tokens):
                raise self.error("expected }")
            statements.append(self.statement())
        self.take("}")
        return Block(tuple(statements))

    def parenthesized(self) -> object:
        self.take("(")
        value = self.expression()
        self.take(")")
        return value

    def expression(self) -> object:
        return self.logical_or()

    def logical_or(self) -> object:
        node = self.logical_and()
        while self.peek("or"):
            self.take("or")
            node = Binary("or", node, self.logical_and())
        return node

    def logical_and(self) -> object:
        node = self.logical_not()
        while self.peek("and"):
            self.take("and")
            node = Binary("and", node, self.logical_not())
        return node

    def logical_not(self) -> object:
        if self.peek("not"):
            self.take("not")
            return Unary("not", self.logical_not())
        return self.comparison()

    def comparison(self) -> object:
        node = self.additive()
        comparisons = ("==", "!=", "<", "<=", ">", ">=")
        if self.pos < len(self.tokens) and self.tokens[self.pos].text in comparisons:
            op = self.take().text
            node = Binary(op, node, self.additive())
            if self.pos < len(self.tokens) and self.tokens[self.pos].text in comparisons:
                raise self.error("comparison is not associative")
        return node

    def additive(self) -> object:
        node = self.multiplicative()
        while self.peek("+") or self.peek("-"):
            op = self.take().text
            node = Binary(op, node, self.multiplicative())
        return node

    def multiplicative(self) -> object:
        node = self.unary()
        while self.peek("*") or self.peek("/") or self.peek("%"):
            op = self.take().text
            node = Binary(op, node, self.unary())
        return node

    def unary(self) -> object:
        if self.peek("-"):
            self.take("-")
            return Unary("-", self.unary())
        return self.primary()

    def primary(self) -> object:
        if self.peek(kind="INT") or self.peek(kind="FLOAT") or self.peek(kind="STRING"):
            return Literal(self.take().value)
        if self.peek("true") or self.peek("false"):
            return Literal(self.take().text == "true")
        if self.peek(kind="IDENT"):
            return Variable(self.take().text)
        if self.peek("("):
            return self.parenthesized()
        raise self.error("expected expression")


def parse(src: str) -> object:
    return _Parser(tokenize(src), len(src)).program()
