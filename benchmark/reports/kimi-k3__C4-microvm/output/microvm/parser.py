"""Recursive-descent parser producing an untyped AST of dataclass nodes."""

import dataclasses

from .errors import ParseError
from .lexer import Token, tokenize

# ---------------------------------------------------------------------------
# AST nodes (representation is internal; only error behaviour is observable).


@dataclasses.dataclass
class Literal:
    value: object
    offset: int


@dataclasses.dataclass
class Var:
    name: str
    offset: int


@dataclasses.dataclass
class BinOp:
    op: str
    left: object
    right: object
    offset: int


@dataclasses.dataclass
class UnaryOp:
    op: str          # "-" or "not"
    operand: object
    offset: int


@dataclasses.dataclass
class Let:
    name: str
    value: object
    offset: int


@dataclasses.dataclass
class Assign:
    name: str
    value: object
    offset: int


@dataclasses.dataclass
class Print:
    value: object
    offset: int


@dataclasses.dataclass
class If:
    cond: object
    then: list
    otherwise: list  # empty when there is no else
    offset: int


@dataclasses.dataclass
class While:
    cond: object
    body: list
    offset: int


_COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")


class _Parser:
    """Token cursor with precedence-climbing expression parsing."""

    def __init__(self, src: str) -> None:
        self.tokens = tokenize(src)
        self.pos = 0
        self.end = len(src)

    def _peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _advance(self) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.end)
        self.pos += 1
        return tok

    def _error(self, message: str) -> ParseError:
        tok = self._peek()
        return ParseError(message, tok.offset if tok is not None else self.end)

    def _expect_op(self, op: str) -> Token:
        tok = self._peek()
        if tok is None or tok.kind != "OP" or tok.text != op:
            raise self._error(f"expected {op!r}")
        self.pos += 1
        return tok

    def _expect_kw(self, kw: str) -> Token:
        tok = self._peek()
        if tok is None or tok.kind != "KEYWORD" or tok.text != kw:
            raise self._error(f"expected keyword {kw!r}")
        self.pos += 1
        return tok

    # -- statements ------------------------------------------------------

    def parse_program(self) -> list:
        stmts: list = []
        while self._peek() is not None:
            stmts.append(self._statement())
        return stmts

    def _statement(self) -> object:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.end)
        if tok.kind == "KEYWORD":
            if tok.text == "let":
                return self._let()
            if tok.text == "print":
                return self._print()
            if tok.text == "if":
                return self._if()
            if tok.text == "while":
                return self._while()
        if tok.kind == "OP" and tok.text == "{":
            return self._block()
        if tok.kind == "IDENT":
            return self._assign()
        raise self._error(f"unexpected token {tok.text!r}")

    def _block(self) -> list:
        self._expect_op("{")
        stmts: list = []
        while True:
            tok = self._peek()
            if tok is None:
                raise ParseError("unterminated block", self.end)
            if tok.kind == "OP" and tok.text == "}":
                self.pos += 1
                return stmts
            stmts.append(self._statement())

    def _let(self) -> Let:
        kw = self._expect_kw("let")
        name = self._advance()
        if name.kind != "IDENT":
            raise ParseError("expected identifier after 'let'", name.offset)
        self._expect_op("=")
        value = self._expression()
        self._expect_op(";")
        return Let(name.text, value, kw.offset)

    def _assign(self) -> Assign:
        name = self._advance()
        self._expect_op("=")
        value = self._expression()
        self._expect_op(";")
        return Assign(name.text, value, name.offset)

    def _print(self) -> Print:
        kw = self._expect_kw("print")
        value = self._expression()
        self._expect_op(";")
        return Print(value, kw.offset)

    def _if(self) -> If:
        kw = self._expect_kw("if")
        self._expect_op("(")
        cond = self._expression()
        self._expect_op(")")
        then = self._block()
        otherwise: list = []
        tok = self._peek()
        if tok is not None and tok.kind == "KEYWORD" and tok.text == "else":
            self.pos += 1
            nxt = self._peek()
            if nxt is not None and nxt.kind == "KEYWORD" and nxt.text == "if":
                otherwise = [self._if()]
            else:
                otherwise = self._block()
        return If(cond, then, otherwise, kw.offset)

    def _while(self) -> While:
        kw = self._expect_kw("while")
        self._expect_op("(")
        cond = self._expression()
        self._expect_op(")")
        body = self._block()
        return While(cond, body, kw.offset)

    # -- expressions -----------------------------------------------------

    def _expression(self) -> object:
        return self._or()

    def _or(self) -> object:
        node = self._and()
        while (tok := self._peek()) and tok.kind == "KEYWORD" and tok.text == "or":
            self.pos += 1
            node = BinOp("or", node, self._and(), tok.offset)
        return node

    def _and(self) -> object:
        node = self._not()
        while (tok := self._peek()) and tok.kind == "KEYWORD" and tok.text == "and":
            self.pos += 1
            node = BinOp("and", node, self._not(), tok.offset)
        return node

    def _not(self) -> object:
        tok = self._peek()
        if tok is not None and tok.kind == "KEYWORD" and tok.text == "not":
            self.pos += 1
            return UnaryOp("not", self._not(), tok.offset)
        return self._comparison()

    def _comparison(self) -> object:
        node = self._additive()
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.text in _COMPARISONS:
            self.pos += 1
            return BinOp(tok.text, node, self._additive(), tok.offset)
        return node

    def _additive(self) -> object:
        node = self._multiplicative()
        while (tok := self._peek()) and tok.kind == "OP" and tok.text in ("+", "-"):
            self.pos += 1
            node = BinOp(tok.text, node, self._multiplicative(), tok.offset)
        return node

    def _multiplicative(self) -> object:
        node = self._unary()
        while (tok := self._peek()) and tok.kind == "OP" and tok.text in ("*", "/", "%"):
            self.pos += 1
            node = BinOp(tok.text, node, self._unary(), tok.offset)
        return node

    def _unary(self) -> object:
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.text == "-":
            self.pos += 1
            return UnaryOp("-", self._unary(), tok.offset)
        return self._primary()

    def _primary(self) -> object:
        tok = self._advance()
        if tok.kind in ("INT", "FLOAT", "STRING"):
            return Literal(tok.value, tok.offset)
        if tok.kind == "KEYWORD" and tok.text in ("true", "false"):
            return Literal(tok.text == "true", tok.offset)
        if tok.kind == "IDENT":
            return Var(tok.text, tok.offset)
        if tok.kind == "OP" and tok.text == "(":
            node = self._expression()
            self._expect_op(")")
            return node
        raise ParseError(f"unexpected token {tok.text!r}", tok.offset)


def parse(src: str) -> object:
    """Parse ``src`` into an AST (a list of statement nodes)."""
    return _Parser(src).parse_program()
