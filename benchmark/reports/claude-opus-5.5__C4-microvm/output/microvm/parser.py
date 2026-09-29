"""Recursive-descent parser producing a small dataclass AST."""

from __future__ import annotations

import contextlib
import dataclasses
import sys
from typing import Callable, Iterator, Optional

from .errors import ParseError
from .lexer import Token, tokenize

_COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})
_RECURSION_LIMIT = 20_000


@dataclasses.dataclass(frozen=True)
class Literal:
    value: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Name:
    name: str
    offset: int


@dataclasses.dataclass(frozen=True)
class Unary:
    op: str
    operand: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Let:
    name: str
    value: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Assign:
    name: str
    value: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Print:
    value: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Block:
    body: tuple
    offset: int


@dataclasses.dataclass(frozen=True)
class If:
    cond: object
    then: Block
    orelse: object  # None, a Block, or a nested If
    offset: int


@dataclasses.dataclass(frozen=True)
class While:
    cond: object
    body: Block
    offset: int


@dataclasses.dataclass(frozen=True)
class Module:
    body: tuple


@contextlib.contextmanager
def deep_recursion() -> Iterator[None]:
    """Temporarily allow deeper recursion for deeply nested programs."""
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, _RECURSION_LIMIT))
    try:
        yield
    finally:
        sys.setrecursionlimit(old)


class _Parser:
    def __init__(self, src: str, tokens: list[Token]) -> None:
        self.src = src
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Optional[Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def at(self, kind: str, text: Optional[str] = None) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == kind and (text is None or tok.text == text)

    def offset(self) -> int:
        tok = self.peek()
        return tok.offset if tok is not None else len(self.src)

    def error(self, message: str) -> ParseError:
        tok = self.peek()
        found = "end of input" if tok is None else repr(tok.text)
        return ParseError(f"{message}, found {found}", self.offset())

    def advance(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise self.error("unexpected end of input")
        self.pos += 1
        return tok

    def expect(self, kind: str, text: Optional[str] = None) -> Token:
        if not self.at(kind, text):
            raise self.error(f"expected {text if text is not None else kind}")
        return self.advance()

    def program(self) -> Module:
        body = []
        while self.peek() is not None:
            body.append(self.statement())
        return Module(tuple(body))

    def statement(self) -> object:
        tok = self.peek()
        if tok is None:
            raise self.error("expected statement")
        if tok.kind == "KEYWORD" and tok.text == "let":
            self.advance()
            name = self.expect("IDENT")
            self.expect("OP", "=")
            value = self.expression()
            self.expect("OP", ";")
            return Let(name.text, value, tok.offset)
        if tok.kind == "KEYWORD" and tok.text == "print":
            self.advance()
            value = self.expression()
            self.expect("OP", ";")
            return Print(value, tok.offset)
        if tok.kind == "KEYWORD" and tok.text == "if":
            return self.if_statement()
        if tok.kind == "KEYWORD" and tok.text == "while":
            self.advance()
            cond = self.condition()
            return While(cond, self.block(), tok.offset)
        if tok.kind == "OP" and tok.text == "{":
            return self.block()
        if tok.kind == "IDENT":
            self.advance()
            self.expect("OP", "=")
            value = self.expression()
            self.expect("OP", ";")
            return Assign(tok.text, value, tok.offset)
        raise self.error("expected statement")

    def condition(self) -> object:
        self.expect("OP", "(")
        cond = self.expression()
        self.expect("OP", ")")
        return cond

    def if_statement(self) -> If:
        tok = self.expect("KEYWORD", "if")
        cond = self.condition()
        then = self.block()
        orelse: object = None
        if self.at("KEYWORD", "else"):
            self.advance()
            orelse = self.if_statement() if self.at("KEYWORD", "if") else self.block()
        return If(cond, then, orelse, tok.offset)

    def block(self) -> Block:
        start = self.expect("OP", "{")
        body = []
        while not self.at("OP", "}"):
            if self.peek() is None:
                raise self.error("expected '}'")
            body.append(self.statement())
        self.advance()
        return Block(tuple(body), start.offset)

    def expression(self) -> object:
        return self.logical("or", self.and_expr)

    def and_expr(self) -> object:
        return self.logical("and", self.not_expr)

    def logical(self, keyword: str, operand: Callable[[], object]) -> object:
        left = operand()
        while self.at("KEYWORD", keyword):
            tok = self.advance()
            left = Binary(keyword, left, operand(), tok.offset)
        return left

    def not_expr(self) -> object:
        if self.at("KEYWORD", "not"):
            tok = self.advance()
            return Unary("not", self.not_expr(), tok.offset)
        return self.comparison()

    def comparison(self) -> object:
        left = self.additive()
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.text in _COMPARISONS:
            self.advance()
            left = Binary(tok.text, left, self.additive(), tok.offset)
            nxt = self.peek()
            if nxt is not None and nxt.kind == "OP" and nxt.text in _COMPARISONS:
                raise self.error("comparison operators are not associative")
        return left

    def binary_chain(self, ops: frozenset[str], operand: Callable[[], object]) -> object:
        left = operand()
        while True:
            tok = self.peek()
            if tok is None or tok.kind != "OP" or tok.text not in ops:
                return left
            self.advance()
            left = Binary(tok.text, left, operand(), tok.offset)

    def additive(self) -> object:
        return self.binary_chain(frozenset({"+", "-"}), self.multiplicative)

    def multiplicative(self) -> object:
        return self.binary_chain(frozenset({"*", "/", "%"}), self.unary)

    def unary(self) -> object:
        if self.at("OP", "-"):
            tok = self.advance()
            return Unary("-", self.unary(), tok.offset)
        return self.primary()

    def primary(self) -> object:
        tok = self.peek()
        if tok is None:
            raise self.error("expected expression")
        if tok.kind in ("INT", "FLOAT", "STRING"):
            self.advance()
            return Literal(tok.value, tok.offset)
        if tok.kind == "KEYWORD" and tok.text in ("true", "false"):
            self.advance()
            return Literal(tok.text == "true", tok.offset)
        if tok.kind == "IDENT":
            self.advance()
            return Name(tok.text, tok.offset)
        if tok.kind == "OP" and tok.text == "(":
            self.advance()
            inner = self.expression()
            self.expect("OP", ")")
            return inner
        raise self.error("expected expression")


def parse(src: str) -> object:
    """Parse ``src`` into an AST (a ``Module``); raises ``ParseError``/``LexError``."""
    tokens = tokenize(src)
    parser = _Parser(src, tokens)
    try:
        with deep_recursion():
            return parser.program()
    except RecursionError:
        raise ParseError("program is nested too deeply", parser.offset()) from None
