from __future__ import annotations

from dataclasses import dataclass

from microvm.errors import ParseError
from microvm.lexer import Token, tokenize

_CMP_OPS: frozenset[str] = frozenset({"==", "!=", "<", "<=", ">", ">="})
_ADD_OPS: frozenset[str] = frozenset({"+", "-"})
_MUL_OPS: frozenset[str] = frozenset({"*", "/", "%"})


@dataclass
class Script:
    statements: list[object]


@dataclass
class Block:
    statements: list[object]
    offset: int


@dataclass
class Let:
    name: str
    expr: object
    offset: int


@dataclass
class Assign:
    name: str
    expr: object
    offset: int


@dataclass
class Print:
    expr: object
    offset: int


@dataclass
class If:
    cond: object
    then_body: object
    else_body: object | None
    offset: int


@dataclass
class While:
    cond: object
    body: object
    offset: int


@dataclass
class Literal:
    value: object
    offset: int


@dataclass
class Name:
    name: str
    offset: int


@dataclass
class Unary:
    op: str
    expr: object
    offset: int


@dataclass
class Binary:
    op: str
    left: object
    right: object
    offset: int


def parse(src: str) -> object:
    return _Parser(tokenize(src), src).parse_script()


class _Parser:
    def __init__(self, tokens: list[Token], src: str) -> None:
        self.tokens = tokens
        self.src = src
        self.pos = 0

    def parse_script(self) -> Script:
        stmts: list[object] = []
        while self._cur() is not None:
            stmts.append(self.parse_stmt())
        return Script(stmts)

    def parse_stmt(self) -> object:
        tok = self._need()
        if tok.kind == "KEYWORD":
            return self._stmt_keyword(tok)
        if tok.kind == "OP" and tok.text == "{":
            return self.parse_block()
        if tok.kind == "IDENT":
            return self.parse_assign()
        self._error("expected statement", tok.offset)
        raise AssertionError("unreachable")

    def _stmt_keyword(self, tok: Token) -> object:
        if tok.text == "let":
            return self.parse_let()
        if tok.text == "print":
            return self.parse_print()
        if tok.text == "if":
            return self.parse_if()
        if tok.text == "while":
            return self.parse_while()
        self._error("expected statement", tok.offset)
        raise AssertionError("unreachable")

    def parse_let(self) -> Let:
        tok = self._expect_kw("let")
        name = self._expect_kind("IDENT")
        self._expect_op("=")
        expr = self.parse_expr()
        self._expect_op(";")
        return Let(name.text, expr, tok.offset)

    def parse_assign(self) -> Assign:
        name = self._expect_kind("IDENT")
        self._expect_op("=")
        expr = self.parse_expr()
        self._expect_op(";")
        return Assign(name.text, expr, name.offset)

    def parse_print(self) -> Print:
        tok = self._expect_kw("print")
        expr = self.parse_expr()
        self._expect_op(";")
        return Print(expr, tok.offset)

    def parse_if(self) -> If:
        tok = self._expect_kw("if")
        self._expect_op("(")
        cond = self.parse_expr()
        self._expect_op(")")
        then = self.parse_block()
        else_body: object | None = None
        if self._is_kw("else"):
            self._advance()
            if self._is_kw("if"):
                else_body = self.parse_if()
            else:
                else_body = self.parse_block()
        return If(cond, then, else_body, tok.offset)

    def parse_while(self) -> While:
        tok = self._expect_kw("while")
        self._expect_op("(")
        cond = self.parse_expr()
        self._expect_op(")")
        return While(cond, self.parse_block(), tok.offset)

    def parse_block(self) -> Block:
        tok = self._expect_op("{")
        stmts: list[object] = []
        while not self._is_op("}"):
            if self._cur() is None:
                self._error("unclosed block", len(self.src))
            stmts.append(self.parse_stmt())
        self._expect_op("}")
        return Block(stmts, tok.offset)

    def parse_expr(self) -> object:
        return self.parse_or()

    def parse_or(self) -> object:
        return self._bin_loop(self.parse_and, self._is_kw, "or")

    def parse_and(self) -> object:
        return self._bin_loop(self.parse_not, self._is_kw, "and")

    def parse_not(self) -> object:
        tok = self._cur()
        if tok is not None and tok.kind == "KEYWORD" and tok.text == "not":
            self._advance()
            return Unary("not", self.parse_not(), tok.offset)
        return self.parse_comparison()

    def parse_comparison(self) -> object:
        left = self.parse_additive()
        tok = self._cur()
        if tok is None or tok.kind != "OP" or tok.text not in _CMP_OPS:
            return left
        self._advance()
        right = self.parse_additive()
        nxt = self._cur()
        if nxt is not None and nxt.kind == "OP" and nxt.text in _CMP_OPS:
            self._error("chained comparison is not allowed", nxt.offset)
        return Binary(tok.text, left, right, tok.offset)

    def parse_additive(self) -> object:
        return self._op_loop(self.parse_multiplicative, _ADD_OPS)

    def parse_multiplicative(self) -> object:
        return self._op_loop(self.parse_unary, _MUL_OPS)

    def parse_unary(self) -> object:
        tok = self._cur()
        if tok is not None and tok.kind == "OP" and tok.text == "-":
            self._advance()
            return Unary("-", self.parse_unary(), tok.offset)
        return self.parse_primary()

    def parse_primary(self) -> object:
        tok = self._need_expr()
        if tok.kind in {"INT", "FLOAT", "STRING"}:
            self._advance()
            return Literal(tok.value, tok.offset)
        if tok.kind == "KEYWORD" and tok.text in {"true", "false"}:
            self._advance()
            return Literal(tok.text == "true", tok.offset)
        if tok.kind == "IDENT":
            self._advance()
            return Name(tok.text, tok.offset)
        if tok.kind == "OP" and tok.text == "(":
            self._advance()
            expr = self.parse_expr()
            self._expect_op(")")
            return expr
        self._error("expected expression", tok.offset)
        raise AssertionError("unreachable")

    def _bin_loop(self, inner: object, pred: object, word: str) -> object:
        left = inner()  # type: ignore[operator]
        while pred(word):  # type: ignore[operator]
            op = self._advance()
            right = inner()  # type: ignore[operator]
            left = Binary(word, left, right, op.offset)
        return left

    def _op_loop(self, inner: object, ops: frozenset[str]) -> object:
        left = inner()  # type: ignore[operator]
        while True:
            tok = self._cur()
            if tok is None or tok.kind != "OP" or tok.text not in ops:
                return left
            self._advance()
            left = Binary(tok.text, left, inner(), tok.offset)  # type: ignore[operator]

    def _cur(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _need(self) -> Token:
        tok = self._cur()
        if tok is None:
            self._error("unexpected end of input", len(self.src))
        return tok  # type: ignore[return-value]

    def _need_expr(self) -> Token:
        tok = self._cur()
        if tok is None:
            self._error("expected expression", len(self.src))
        return tok  # type: ignore[return-value]

    def _advance(self) -> Token:
        tok = self._need()
        self.pos += 1
        return tok

    def _is_kw(self, word: str) -> bool:
        tok = self._cur()
        return tok is not None and tok.kind == "KEYWORD" and tok.text == word

    def _is_op(self, text: str) -> bool:
        tok = self._cur()
        return tok is not None and tok.kind == "OP" and tok.text == text

    def _expect_kw(self, word: str) -> Token:
        tok = self._need()
        if tok.kind != "KEYWORD" or tok.text != word:
            self._error(f"expected {word}", tok.offset)
        return self._advance()

    def _expect_op(self, text: str) -> Token:
        tok = self._need()
        if tok.kind != "OP" or tok.text != text:
            self._error(f"expected {text!r}", tok.offset)
        return self._advance()

    def _expect_kind(self, kind: str) -> Token:
        tok = self._need()
        if tok.kind != kind:
            self._error(f"expected {kind}", tok.offset)
        return self._advance()

    def _error(self, message: str, offset: int) -> None:
        raise ParseError(message, offset)
