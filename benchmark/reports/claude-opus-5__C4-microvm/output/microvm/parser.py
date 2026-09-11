"""Recursive descent parser producing a small dataclass based AST.

The AST shape is an implementation detail of this package: only ``parse``'s
error behaviour is specified.  Every node carries the offset of the token it
started at so that later stages can report useful positions.
"""

from __future__ import annotations

import dataclasses

from .errors import ParseError
from .lexer import Token, tokenize


@dataclasses.dataclass(frozen=True)
class Literal:
    """An INT, FLOAT, STRING or BOOL literal (also produced by folding)."""

    value: object
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Name:
    identifier: str
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Unary:
    op: str  # "-" or "not"
    operand: object
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Binary:
    op: str  # arithmetic or comparison operator
    left: object
    right: object
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Logical:
    op: str  # "and" or "or"
    left: object
    right: object
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Let:
    identifier: str
    expr: object
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Assign:
    identifier: str
    expr: object
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Print:
    expr: object
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class If:
    condition: object
    then_branch: object
    else_branch: object | None = None
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class While:
    condition: object
    body: object
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Block:
    statements: tuple[object, ...]
    offset: int = 0


@dataclasses.dataclass(frozen=True)
class Module:
    statements: tuple[object, ...]
    offset: int = 0


_COMPARISONS: frozenset[str] = frozenset({"==", "!=", "<", "<=", ">", ">="})


class _Parser:
    """Token cursor plus one method per grammar production."""

    def __init__(self, tokens: list[Token], end_offset: int) -> None:
        self.tokens: list[Token] = tokens
        self.pos: int = 0
        self.end_offset: int = end_offset

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def offset(self) -> int:
        token = self.peek()
        return self.end_offset if token is None else token.offset

    def at(self, kind: str, text: str | None = None) -> bool:
        token = self.peek()
        if token is None or token.kind != kind:
            return False
        return text is None or token.text == text

    def advance(self) -> Token:
        token = self.peek()
        if token is None:
            raise ParseError("unexpected end of input", self.end_offset)
        self.pos += 1
        return token

    def expect(self, kind: str, text: str) -> Token:
        if not self.at(kind, text):
            raise ParseError(f"expected {text!r}", self.offset())
        return self.advance()

    # -- statements ---------------------------------------------------
    def parse_module(self) -> Module:
        statements: list[object] = []
        while self.peek() is not None:
            statements.append(self.statement())
        return Module(tuple(statements), 0)

    def statement(self) -> object:
        token = self.peek()
        if token is None:
            raise ParseError("unexpected end of input", self.end_offset)
        if token.kind == "KEYWORD":
            handler = {
                "let": self.let_statement,
                "print": self.print_statement,
                "if": self.if_statement,
                "while": self.while_statement,
            }.get(token.text)
            if handler is not None:
                return handler()
        if token.kind == "OP" and token.text == "{":
            return self.block()
        if token.kind == "IDENT":
            return self.assign_statement()
        raise ParseError("expected a statement", token.offset)

    def let_statement(self) -> Let:
        start = self.advance().offset
        name = self.identifier()
        self.expect("OP", "=")
        expr = self.expression()
        self.expect("OP", ";")
        return Let(name.text, expr, start)

    def assign_statement(self) -> Assign:
        name = self.advance()
        self.expect("OP", "=")
        expr = self.expression()
        self.expect("OP", ";")
        return Assign(name.text, expr, name.offset)

    def print_statement(self) -> Print:
        start = self.advance().offset
        expr = self.expression()
        self.expect("OP", ";")
        return Print(expr, start)

    def if_statement(self) -> If:
        start = self.advance().offset
        self.expect("OP", "(")
        condition = self.expression()
        self.expect("OP", ")")
        then_branch = self.block()
        else_branch: object | None = None
        if self.at("KEYWORD", "else"):
            self.advance()
            if self.at("KEYWORD", "if"):
                else_branch = self.if_statement()
            else:
                else_branch = self.block()
        return If(condition, then_branch, else_branch, start)

    def while_statement(self) -> While:
        start = self.advance().offset
        self.expect("OP", "(")
        condition = self.expression()
        self.expect("OP", ")")
        return While(condition, self.block(), start)

    def block(self) -> Block:
        start = self.expect("OP", "{").offset
        statements: list[object] = []
        while not self.at("OP", "}"):
            if self.peek() is None:
                raise ParseError("unterminated block", self.end_offset)
            statements.append(self.statement())
        self.advance()
        return Block(tuple(statements), start)

    def identifier(self) -> Token:
        if not self.at("IDENT"):
            raise ParseError("expected an identifier", self.offset())
        return self.advance()

    # -- expressions --------------------------------------------------
    def expression(self) -> object:
        return self.or_expr()

    def or_expr(self) -> object:
        node = self.and_expr()
        while self.at("KEYWORD", "or"):
            offset = self.advance().offset
            node = Logical("or", node, self.and_expr(), offset)
        return node

    def and_expr(self) -> object:
        node = self.not_expr()
        while self.at("KEYWORD", "and"):
            offset = self.advance().offset
            node = Logical("and", node, self.not_expr(), offset)
        return node

    def not_expr(self) -> object:
        if self.at("KEYWORD", "not"):
            offset = self.advance().offset
            return Unary("not", self.not_expr(), offset)
        return self.comparison()

    def comparison(self) -> object:
        node = self.additive()
        token = self.peek()
        if token is not None and token.kind == "OP" and token.text in _COMPARISONS:
            self.advance()
            right = self.additive()
            follow = self.peek()
            if follow is not None and follow.kind == "OP" and follow.text in _COMPARISONS:
                raise ParseError("comparison operators do not chain", follow.offset)
            return Binary(token.text, node, right, token.offset)
        return node

    def additive(self) -> object:
        node = self.multiplicative()
        while self.at("OP", "+") or self.at("OP", "-"):
            token = self.advance()
            node = Binary(token.text, node, self.multiplicative(), token.offset)
        return node

    def multiplicative(self) -> object:
        node = self.unary()
        while self.at("OP", "*") or self.at("OP", "/") or self.at("OP", "%"):
            token = self.advance()
            node = Binary(token.text, node, self.unary(), token.offset)
        return node

    def unary(self) -> object:
        if self.at("OP", "-"):
            offset = self.advance().offset
            return Unary("-", self.unary(), offset)
        return self.primary()

    def primary(self) -> object:
        token = self.peek()
        if token is None:
            raise ParseError("unexpected end of input", self.end_offset)
        if token.kind in ("INT", "FLOAT", "STRING"):
            self.advance()
            return Literal(token.value, token.offset)
        if token.kind == "KEYWORD" and token.text in ("true", "false"):
            self.advance()
            return Literal(token.text == "true", token.offset)
        if token.kind == "IDENT":
            self.advance()
            return Name(token.text, token.offset)
        if token.kind == "OP" and token.text == "(":
            self.advance()
            inner = self.expression()
            self.expect("OP", ")")
            return inner
        raise ParseError("expected an expression", token.offset)


def parse(src: str) -> object:
    """Parse *src* and return the AST root (a :class:`Module`)."""
    tokens = tokenize(src)
    return _Parser(tokens, len(src)).parse_module()
