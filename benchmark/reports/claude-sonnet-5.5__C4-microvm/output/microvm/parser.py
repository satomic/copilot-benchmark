"""Recursive-descent parser.

AST nodes are tuples whose first element is a tag:
  expressions: ("lit", v) ("var", name) ("un", "-", e) ("not", e)
               ("bin", op, l, r) ("and", l, r) ("or", l, r)
  statements:  ("let", name, e) ("assign", name, e) ("print", e)
               ("if", cond, block, else_block_or_if_or_None)
               ("while", cond, block) ("block", [stmts])
  root:        ("program", [stmts])
"""

from typing import Callable

from .errors import ParseError
from .lexer import Token, tokenize

_COMPARE = ("==", "!=", "<", "<=", ">", ">=")


class _Parser:
    def __init__(self, src: str) -> None:
        self.src = src
        self.tokens = tokenize(src)
        self.pos = 0

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def offset(self) -> int:
        tok = self.peek()
        return tok.offset if tok else len(self.src)

    def is_op(self, text: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "OP" and tok.text == text

    def is_kw(self, text: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "KEYWORD" and tok.text == text

    def expect_op(self, text: str) -> None:
        if not self.is_op(text):
            raise ParseError(f"expected {text!r}", self.offset())
        self.pos += 1

    def expect_ident(self) -> str:
        tok = self.peek()
        if tok is None or tok.kind != "IDENT":
            raise ParseError("expected identifier", self.offset())
        self.pos += 1
        return tok.text

    # statements
    def program(self) -> tuple:
        stmts = []
        while self.peek() is not None:
            stmts.append(self.statement())
        return ("program", stmts)

    def block(self) -> tuple:
        self.expect_op("{")
        stmts = []
        while not self.is_op("}"):
            if self.peek() is None:
                raise ParseError("unterminated block", self.offset())
            stmts.append(self.statement())
        self.pos += 1
        return ("block", stmts)

    def statement(self) -> tuple:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.offset())
        if tok.kind == "KEYWORD":
            handler = {
                "let": self.let_stmt, "print": self.print_stmt,
                "if": self.if_stmt, "while": self.while_stmt,
            }.get(tok.text)
            if handler is not None:
                self.pos += 1
                return handler()
        elif tok.kind == "IDENT":
            self.pos += 1
            self.expect_op("=")
            value = self.expr()
            self.expect_op(";")
            return ("assign", tok.text, value)
        elif self.is_op("{"):
            return self.block()
        raise ParseError(f"unexpected token {tok.text!r}", tok.offset)

    def let_stmt(self) -> tuple:
        name = self.expect_ident()
        self.expect_op("=")
        value = self.expr()
        self.expect_op(";")
        return ("let", name, value)

    def print_stmt(self) -> tuple:
        value = self.expr()
        self.expect_op(";")
        return ("print", value)

    def paren_cond(self) -> tuple:
        self.expect_op("(")
        cond = self.expr()
        self.expect_op(")")
        return cond

    def if_stmt(self) -> tuple:
        cond = self.paren_cond()
        then = self.block()
        other = None
        if self.is_kw("else"):
            self.pos += 1
            if self.is_kw("if"):
                self.pos += 1
                other = self.if_stmt()
            else:
                other = self.block()
        return ("if", cond, then, other)

    def while_stmt(self) -> tuple:
        cond = self.paren_cond()
        return ("while", cond, self.block())

    # expressions
    def expr(self) -> tuple:
        node = self.and_expr()
        while self.is_kw("or"):
            self.pos += 1
            node = ("or", node, self.and_expr())
        return node

    def and_expr(self) -> tuple:
        node = self.not_expr()
        while self.is_kw("and"):
            self.pos += 1
            node = ("and", node, self.not_expr())
        return node

    def not_expr(self) -> tuple:
        if self.is_kw("not"):
            self.pos += 1
            return ("not", self.not_expr())
        return self.comparison()

    def comparison(self) -> tuple:
        left = self.additive()
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.text in _COMPARE:
            self.pos += 1
            node = ("bin", tok.text, left, self.additive())
            nxt = self.peek()
            if nxt is not None and nxt.kind == "OP" and nxt.text in _COMPARE:
                raise ParseError("comparison is not associative", nxt.offset)
            return node
        return left

    def binary_level(self, ops: tuple, sub: Callable[[], tuple]) -> tuple:
        node = sub()
        while True:
            tok = self.peek()
            if tok is None or tok.kind != "OP" or tok.text not in ops:
                return node
            self.pos += 1
            node = ("bin", tok.text, node, sub())

    def additive(self) -> tuple:
        return self.binary_level(("+", "-"), self.multiplicative)

    def multiplicative(self) -> tuple:
        return self.binary_level(("*", "/", "%"), self.unary)

    def unary(self) -> tuple:
        if self.is_op("-"):
            self.pos += 1
            return ("un", "-", self.unary())
        return self.primary()

    def primary(self) -> tuple:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.offset())
        if tok.kind in ("INT", "FLOAT", "STRING"):
            self.pos += 1
            return ("lit", tok.value)
        if tok.kind == "KEYWORD" and tok.text in ("true", "false"):
            self.pos += 1
            return ("lit", tok.text == "true")
        if tok.kind == "IDENT":
            self.pos += 1
            return ("var", tok.text)
        if self.is_op("("):
            self.pos += 1
            node = self.expr()
            self.expect_op(")")
            return node
        raise ParseError(f"unexpected token {tok.text!r}", tok.offset)


def parse(src: str) -> object:
    try:
        return _Parser(src).program()
    except RecursionError:
        raise ParseError("nesting too deep", 0) from None
