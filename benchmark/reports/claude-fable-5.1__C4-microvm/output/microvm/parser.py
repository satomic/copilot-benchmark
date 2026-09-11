"""Recursive-descent parser producing a small dataclass-based AST."""

from __future__ import annotations

import dataclasses

from .errors import ParseError
from .lexer import Token, tokenize


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
    op: str  # "-" or "not"
    operand: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Binary:
    op: str  # arithmetic, comparison, "and", "or"
    left: object
    right: object
    offset: int


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
    offset: int


@dataclasses.dataclass(frozen=True)
class If:
    cond: object
    then: object
    orelse: object | None
    offset: int


@dataclasses.dataclass(frozen=True)
class While:
    cond: object
    body: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Block:
    stmts: tuple
    offset: int


@dataclasses.dataclass(frozen=True)
class Module:
    stmts: tuple


_COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")


class _Parser:
    def __init__(self, src: str) -> None:
        self.tokens: list[Token] = tokenize(src)
        self.pos = 0
        self.end_offset = len(src)

    # -- token helpers -------------------------------------------------
    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def offset(self) -> int:
        tok = self.peek()
        return self.end_offset if tok is None else tok.offset

    def check(self, kind: str, text: str | None = None) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == kind and (text is None or tok.text == text)

    def advance(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.end_offset)
        self.pos += 1
        return tok

    def expect(self, kind: str, text: str) -> Token:
        if not self.check(kind, text):
            found = self.peek()
            what = "end of input" if found is None else repr(found.text)
            raise ParseError(f"expected {text!r} but found {what}", self.offset())
        return self.advance()

    # -- statements ----------------------------------------------------
    def parse_module(self) -> Module:
        stmts = []
        while self.peek() is not None:
            stmts.append(self.parse_statement())
        return Module(tuple(stmts))

    def parse_statement(self) -> object:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.end_offset)
        if tok.kind == "KEYWORD":
            if tok.text == "let":
                return self.parse_let()
            if tok.text == "print":
                return self.parse_print()
            if tok.text == "if":
                return self.parse_if()
            if tok.text == "while":
                return self.parse_while()
            raise ParseError(f"unexpected keyword {tok.text!r}", tok.offset)
        if tok.kind == "OP" and tok.text == "{":
            return self.parse_block()
        if tok.kind == "IDENT":
            return self.parse_assign()
        raise ParseError(f"unexpected token {tok.text!r}", tok.offset)

    def parse_let(self) -> Let:
        start = self.expect("KEYWORD", "let")
        name = self.expect_ident()
        self.expect("OP", "=")
        expr = self.parse_expr()
        self.expect("OP", ";")
        return Let(name.text, expr, start.offset)

    def parse_assign(self) -> Assign:
        name = self.expect_ident()
        self.expect("OP", "=")
        expr = self.parse_expr()
        self.expect("OP", ";")
        return Assign(name.text, expr, name.offset)

    def parse_print(self) -> Print:
        start = self.expect("KEYWORD", "print")
        expr = self.parse_expr()
        self.expect("OP", ";")
        return Print(expr, start.offset)

    def parse_if(self) -> If:
        start = self.expect("KEYWORD", "if")
        self.expect("OP", "(")
        cond = self.parse_expr()
        self.expect("OP", ")")
        then = self.parse_block()
        orelse: object | None = None
        if self.check("KEYWORD", "else"):
            self.advance()
            orelse = self.parse_if() if self.check("KEYWORD", "if") else self.parse_block()
        return If(cond, then, orelse, start.offset)

    def parse_while(self) -> While:
        start = self.expect("KEYWORD", "while")
        self.expect("OP", "(")
        cond = self.parse_expr()
        self.expect("OP", ")")
        body = self.parse_block()
        return While(cond, body, start.offset)

    def parse_block(self) -> Block:
        start = self.expect("OP", "{")
        stmts = []
        while not self.check("OP", "}"):
            if self.peek() is None:
                raise ParseError("unterminated block", self.end_offset)
            stmts.append(self.parse_statement())
        self.advance()
        return Block(tuple(stmts), start.offset)

    def expect_ident(self) -> Token:
        if not self.check("IDENT"):
            raise ParseError("expected identifier", self.offset())
        return self.advance()

    # -- expressions ---------------------------------------------------
    def parse_expr(self) -> object:
        return self.parse_or()

    def parse_or(self) -> object:
        left = self.parse_and()
        while self.check("KEYWORD", "or"):
            op = self.advance()
            right = self.parse_and()
            left = Binary("or", left, right, op.offset)
        return left

    def parse_and(self) -> object:
        left = self.parse_not()
        while self.check("KEYWORD", "and"):
            op = self.advance()
            right = self.parse_not()
            left = Binary("and", left, right, op.offset)
        return left

    def parse_not(self) -> object:
        if self.check("KEYWORD", "not"):
            op = self.advance()
            return Unary("not", self.parse_not(), op.offset)
        return self.parse_comparison()

    def parse_comparison(self) -> object:
        left = self.parse_additive()
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.text in _COMPARISONS:
            self.advance()
            right = self.parse_additive()
            left = Binary(tok.text, left, right, tok.offset)
            again = self.peek()
            # Comparison is deliberately non-associative: 1 < 2 < 3 is rejected.
            if again is not None and again.kind == "OP" and again.text in _COMPARISONS:
                raise ParseError("comparison operators cannot be chained", again.offset)
        return left

    def parse_additive(self) -> object:
        left = self.parse_multiplicative()
        while self.check("OP", "+") or self.check("OP", "-"):
            op = self.advance()
            right = self.parse_multiplicative()
            left = Binary(op.text, left, right, op.offset)
        return left

    def parse_multiplicative(self) -> object:
        left = self.parse_unary()
        while self.check("OP", "*") or self.check("OP", "/") or self.check("OP", "%"):
            op = self.advance()
            right = self.parse_unary()
            left = Binary(op.text, left, right, op.offset)
        return left

    def parse_unary(self) -> object:
        if self.check("OP", "-"):
            op = self.advance()
            return Unary("-", self.parse_unary(), op.offset)
        return self.parse_primary()

    def parse_primary(self) -> object:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input in expression", self.end_offset)
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
            expr = self.parse_expr()
            self.expect("OP", ")")
            return expr
        raise ParseError(f"unexpected token {tok.text!r} in expression", tok.offset)


def parse(src: str) -> object:
    """Parse ``src`` into an AST ``Module``; raises ``ParseError`` or ``LexError``."""
    return _Parser(src).parse_module()
