"""Recursive-descent parser producing a small AST for MicroVM."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from .errors import ParseError
from .lexer import Token, tokenize


@dataclasses.dataclass
class Literal:
    value: object  # int, float, str or bool; the Python type is the MicroVM type


@dataclasses.dataclass
class Name:
    name: str
    offset: int


@dataclasses.dataclass
class Unary:
    op: str  # "-" or "not"
    operand: object


@dataclasses.dataclass
class Binary:
    op: str
    left: object
    right: object


@dataclasses.dataclass
class Logical:
    op: str  # "and" or "or"; short-circuiting
    left: object
    right: object


@dataclasses.dataclass
class Let:
    name: str
    offset: int
    value: object


@dataclasses.dataclass
class Assign:
    name: str
    offset: int
    value: object


@dataclasses.dataclass
class Print:
    value: object


@dataclasses.dataclass
class If:
    cond: object
    then_body: object
    else_body: object | None


@dataclasses.dataclass
class While:
    cond: object
    body: object


@dataclasses.dataclass
class Block:
    stmts: list[object]


_COMPARE_OPS: tuple[str, ...] = ("==", "!=", "<", "<=", ">", ">=")


def parse(src: str) -> Block:
    """Parse ``src`` into a Block holding the top-level statements."""
    parser = _Parser(src)
    stmts: list[object] = []
    while parser.peek() is not None:
        stmts.append(parser.statement())
    return Block(stmts)


class _Parser:
    def __init__(self, src: str) -> None:
        self.tokens: list[Token] = tokenize(src)
        self.end: int = len(src)
        self.pos: int = 0

    # ----- token helpers -------------------------------------------------
    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def advance(self) -> Token:
        token = self.peek()
        if token is None:
            raise self.error("unexpected end of input")
        self.pos += 1
        return token

    def check(self, kind: str, text: str | None = None) -> bool:
        token = self.peek()
        return token is not None and token.kind == kind and (text is None or token.text == text)

    def expect(self, kind: str, text: str | None = None) -> Token:
        if not self.check(kind, text):
            raise self.error(f"expected {text if text is not None else kind}")
        return self.advance()

    def next_is(self, ops: tuple[str, ...]) -> bool:
        token = self.peek()
        return token is not None and token.kind in ("OP", "KEYWORD") and token.text in ops

    def error(self, message: str) -> ParseError:
        token = self.peek()
        return ParseError(message, token.offset if token is not None else self.end)

    # ----- statements ----------------------------------------------------
    def statement(self) -> object:
        if self.check("KEYWORD", "let"):
            return self.let_stmt()
        if self.check("KEYWORD", "print"):
            return self.print_stmt()
        if self.check("KEYWORD", "if"):
            return self.if_stmt()
        if self.check("KEYWORD", "while"):
            return self.while_stmt()
        if self.check("OP", "{"):
            return self.block()
        if self.check("IDENT"):
            return self.assign_stmt()
        raise self.error("expected a statement")

    def let_stmt(self) -> Let:
        self.advance()
        name = self.expect("IDENT")
        self.expect("OP", "=")
        value = self.expression()
        self.expect("OP", ";")
        return Let(name.text, name.offset, value)

    def assign_stmt(self) -> Assign:
        name = self.expect("IDENT")
        self.expect("OP", "=")
        value = self.expression()
        self.expect("OP", ";")
        return Assign(name.text, name.offset, value)

    def print_stmt(self) -> Print:
        self.advance()
        value = self.expression()
        self.expect("OP", ";")
        return Print(value)

    def if_stmt(self) -> If:
        self.advance()
        cond = self.expression()
        then_body = self.block()
        else_body: object | None = None
        if self.check("KEYWORD", "else"):
            self.advance()
            else_body = self.if_stmt() if self.check("KEYWORD", "if") else self.block()
        return If(cond, then_body, else_body)

    def while_stmt(self) -> While:
        self.advance()
        cond = self.expression()
        return While(cond, self.block())

    def block(self) -> Block:
        self.expect("OP", "{")
        stmts: list[object] = []
        while not self.check("OP", "}"):
            if self.peek() is None:
                raise self.error("expected '}'")
            stmts.append(self.statement())
        self.advance()
        return Block(stmts)

    # ----- expressions ---------------------------------------------------
    def expression(self) -> object:
        return self.or_expr()

    def left_assoc(
        self,
        operand: Callable[[], object],
        ops: tuple[str, ...],
        make: Callable[[str, object, object], object],
    ) -> object:
        node = operand()
        while self.next_is(ops):
            op = self.advance().text
            node = make(op, node, operand())
        return node

    def or_expr(self) -> object:
        return self.left_assoc(self.and_expr, ("or",), Logical)

    def and_expr(self) -> object:
        return self.left_assoc(self.not_expr, ("and",), Logical)

    def not_expr(self) -> object:
        if self.next_is(("not",)):
            self.advance()
            return Unary("not", self.not_expr())
        return self.comparison()

    def comparison(self) -> object:
        left = self.additive()
        if not self.next_is(_COMPARE_OPS):
            return left
        op = self.advance().text
        right = self.additive()
        if self.next_is(_COMPARE_OPS):
            raise self.error("comparison operators cannot be chained")
        return Binary(op, left, right)

    def additive(self) -> object:
        return self.left_assoc(self.multiplicative, ("+", "-"), Binary)

    def multiplicative(self) -> object:
        return self.left_assoc(self.unary, ("*", "/", "%"), Binary)

    def unary(self) -> object:
        if self.check("OP", "-"):
            self.advance()
            return Unary("-", self.unary())
        return self.primary()

    def primary(self) -> object:
        token = self.peek()
        if token is None:
            raise self.error("expected an expression")
        if token.kind in ("INT", "FLOAT", "STRING"):
            self.advance()
            return Literal(token.value)
        if token.kind == "KEYWORD" and token.text in ("true", "false"):
            self.advance()
            return Literal(token.text == "true")
        if token.kind == "IDENT":
            self.advance()
            return Name(token.text, token.offset)
        if token.kind == "OP" and token.text == "(":
            self.advance()
            inner = self.expression()
            self.expect("OP", ")")
            return inner
        raise self.error("expected an expression")
