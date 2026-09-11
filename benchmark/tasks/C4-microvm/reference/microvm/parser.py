"""Recursive descent parser. The AST shape is package-internal by design."""

from __future__ import annotations

import dataclasses

from .errors import ParseError
from .lexer import Token, tokenize

__all__ = [
    "parse",
    "Literal", "Name", "Unary", "NotOp", "Binary", "Logical",
    "Let", "Assign", "Print", "If", "While", "Block", "Module",
]

_COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")


@dataclasses.dataclass(frozen=True)
class Literal:
    value: object


@dataclasses.dataclass(frozen=True)
class Name:
    name: str
    offset: int


@dataclasses.dataclass(frozen=True)
class Unary:
    operand: object


@dataclasses.dataclass(frozen=True)
class NotOp:
    operand: object


@dataclasses.dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclasses.dataclass(frozen=True)
class Logical:
    op: str  # "and" | "or"
    left: object
    right: object


@dataclasses.dataclass(frozen=True)
class Let:
    name: str
    expr: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Assign:
    name: str
    expr: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Print:
    expr: object


@dataclasses.dataclass(frozen=True)
class If:
    cond: object
    then: object
    orelse: object | None


@dataclasses.dataclass(frozen=True)
class While:
    cond: object
    body: object


@dataclasses.dataclass(frozen=True)
class Block:
    statements: tuple


@dataclasses.dataclass(frozen=True)
class Module:
    statements: tuple


class _Parser:
    def __init__(self, src: str) -> None:
        self._src = src
        self._tokens = tokenize(src)
        self._pos = 0

    def _peek(self) -> Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _end(self) -> int:
        return len(self._src)

    def _next(self) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input", self._end())
        self._pos += 1
        return tok

    def _at(self, kind: str, text: str | None = None) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == kind and (text is None or tok.text == text)

    def _expect(self, kind: str, text: str) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError(f"expected {text!r}", self._end())
        if tok.kind != kind or tok.text != text:
            raise ParseError(f"expected {text!r}, got {tok.text!r}", tok.offset)
        return self._next()

    # -- statements -----------------------------------------------------------

    def parse_module(self) -> Module:
        statements = []
        while self._peek() is not None:
            statements.append(self._statement())
        return Module(tuple(statements))

    def _statement(self) -> object:
        if self._at("KEYWORD", "let"):
            return self._let()
        if self._at("KEYWORD", "print"):
            self._next()
            expr = self._expr()
            self._expect("OP", ";")
            return Print(expr)
        if self._at("KEYWORD", "if"):
            return self._if()
        if self._at("KEYWORD", "while"):
            self._next()
            self._expect("OP", "(")
            cond = self._expr()
            self._expect("OP", ")")
            return While(cond, self._block())
        if self._at("OP", "{"):
            return self._block()
        if self._at("IDENT"):
            tok = self._next()
            self._expect("OP", "=")
            expr = self._expr()
            self._expect("OP", ";")
            return Assign(tok.text, expr, tok.offset)
        tok = self._peek()
        offset = tok.offset if tok else self._end()
        raise ParseError(f"unexpected {tok.text!r}" if tok else "unexpected end of input", offset)

    def _let(self) -> Let:
        self._next()
        tok = self._peek()
        if tok is None or tok.kind != "IDENT":
            raise ParseError("expected a name after let", tok.offset if tok else self._end())
        self._next()
        self._expect("OP", "=")
        expr = self._expr()
        self._expect("OP", ";")
        return Let(tok.text, expr, tok.offset)

    def _if(self) -> If:
        self._next()
        self._expect("OP", "(")
        cond = self._expr()
        self._expect("OP", ")")
        then = self._block()
        orelse: object | None = None
        if self._at("KEYWORD", "else"):
            self._next()
            if self._at("KEYWORD", "if"):
                orelse = self._if()
            else:
                orelse = self._block()
        return If(cond, then, orelse)

    def _block(self) -> Block:
        self._expect("OP", "{")
        statements = []
        while not self._at("OP", "}"):
            if self._peek() is None:
                raise ParseError("unterminated block", self._end())
            statements.append(self._statement())
        self._next()
        return Block(tuple(statements))

    # -- expressions ----------------------------------------------------------

    def _expr(self) -> object:
        return self._or()

    def _or(self) -> object:
        node = self._and()
        while self._at("KEYWORD", "or"):
            self._next()
            node = Logical("or", node, self._and())
        return node

    def _and(self) -> object:
        node = self._not()
        while self._at("KEYWORD", "and"):
            self._next()
            node = Logical("and", node, self._not())
        return node

    def _not(self) -> object:
        if self._at("KEYWORD", "not"):
            self._next()
            return NotOp(self._not())
        return self._comparison()

    def _comparison(self) -> object:
        node = self._additive()
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.text in _COMPARISONS:
            self._next()
            right = self._additive()
            after = self._peek()
            if after is not None and after.kind == "OP" and after.text in _COMPARISONS:
                raise ParseError("comparisons are not associative", after.offset)
            return Binary(tok.text, node, right)
        return node

    def _additive(self) -> object:
        node = self._multiplicative()
        while self._at("OP", "+") or self._at("OP", "-"):
            op = self._next().text
            node = Binary(op, node, self._multiplicative())
        return node

    def _multiplicative(self) -> object:
        node = self._unary()
        while self._at("OP", "*") or self._at("OP", "/") or self._at("OP", "%"):
            op = self._next().text
            node = Binary(op, node, self._unary())
        return node

    def _unary(self) -> object:
        if self._at("OP", "-"):
            self._next()
            return Unary(self._unary())
        return self._primary()

    def _primary(self) -> object:
        tok = self._next()
        if tok.kind in ("INT", "FLOAT", "STRING"):
            return Literal(tok.value)
        if tok.kind == "KEYWORD" and tok.text in ("true", "false"):
            return Literal(tok.text == "true")
        if tok.kind == "IDENT":
            return Name(tok.text, tok.offset)
        if tok.kind == "OP" and tok.text == "(":
            inner = self._expr()
            self._expect("OP", ")")
            return inner
        raise ParseError(f"unexpected {tok.text!r}", tok.offset)


def parse(src: str) -> Module:
    """Parse a complete program."""
    return _Parser(src).parse_module()
