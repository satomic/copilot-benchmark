"""Recursive-descent parser for the microvm language."""

import dataclasses

from .errors import ParseError
from .lexer import Token, tokenize


# ---------------------------------------------------------------------------
# AST node definitions. The shape is internal; only parse()'s error behaviour
# is part of the observable contract.
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Module:
    body: list


@dataclasses.dataclass
class LetStmt:
    name: str
    expr: object
    offset: int


@dataclasses.dataclass
class AssignStmt:
    name: str
    expr: object
    offset: int


@dataclasses.dataclass
class PrintStmt:
    expr: object


@dataclasses.dataclass
class IfStmt:
    cond: object
    then_body: list
    else_body: list | None


@dataclasses.dataclass
class WhileStmt:
    cond: object
    body: list


@dataclasses.dataclass
class IntLit:
    value: int


@dataclasses.dataclass
class FloatLit:
    value: float


@dataclasses.dataclass
class StrLit:
    value: str


@dataclasses.dataclass
class BoolLit:
    value: bool


@dataclasses.dataclass
class VarRef:
    name: str
    offset: int


@dataclasses.dataclass
class Neg:
    expr: object


@dataclasses.dataclass
class NotOp:
    expr: object


@dataclasses.dataclass
class BinOp:
    op: str
    left: object
    right: object
    offset: int


@dataclasses.dataclass
class LogicOp:
    op: str
    left: object
    right: object


class _Parser:
    def __init__(self, tokens: list[Token], src_len: int) -> None:
        self.tokens = tokens
        self.pos = 0
        self.src_len = src_len

    def _offset(self) -> int:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos].offset
        return self.src_len

    def _peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _advance(self) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.src_len)
        self.pos += 1
        return tok

    def _check_kw(self, kw: str) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == "KEYWORD" and tok.text == kw

    def _check_op(self, op: str) -> bool:
        tok = self._peek()
        return tok is not None and tok.kind == "OP" and tok.text == op

    def _expect_op(self, op: str) -> Token:
        if not self._check_op(op):
            raise ParseError(f"expected {op!r}", self._offset())
        return self._advance()

    def _expect_kw(self, kw: str) -> Token:
        if not self._check_kw(kw):
            raise ParseError(f"expected {kw!r}", self._offset())
        return self._advance()

    def parse_module(self) -> Module:
        body = []
        while self._peek() is not None:
            body.append(self.parse_stmt())
        return Module(body)

    def parse_stmt(self) -> object:
        if self._check_kw("let"):
            return self._parse_let()
        if self._check_kw("print"):
            return self._parse_print()
        if self._check_kw("if"):
            return self._parse_if()
        if self._check_kw("while"):
            return self._parse_while()
        if self._check_op("{"):
            return Module(self._parse_block())
        return self._parse_assign()

    def _parse_let(self) -> LetStmt:
        offset = self._advance().offset
        name_tok = self._peek()
        if name_tok is None or name_tok.kind != "IDENT":
            raise ParseError("expected identifier after 'let'", self._offset())
        self._advance()
        self._expect_op("=")
        expr = self.parse_expr()
        self._expect_op(";")
        return LetStmt(name_tok.text, expr, offset)

    def _parse_assign(self) -> AssignStmt:
        name_tok = self._peek()
        if name_tok is None or name_tok.kind != "IDENT":
            raise ParseError("expected statement", self._offset())
        offset = name_tok.offset
        self._advance()
        self._expect_op("=")
        expr = self.parse_expr()
        self._expect_op(";")
        return AssignStmt(name_tok.text, expr, offset)

    def _parse_print(self) -> PrintStmt:
        self._advance()
        expr = self.parse_expr()
        self._expect_op(";")
        return PrintStmt(expr)

    def _parse_block(self) -> list:
        self._expect_op("{")
        stmts = []
        while not self._check_op("}"):
            if self._peek() is None:
                raise ParseError("unterminated block", self._offset())
            stmts.append(self.parse_stmt())
        self._advance()
        return stmts

    def _parse_if(self) -> IfStmt:
        self._advance()
        self._expect_op("(")
        cond = self.parse_expr()
        self._expect_op(")")
        then_body = self._parse_block()
        else_body = None
        if self._check_kw("else"):
            self._advance()
            if self._check_kw("if"):
                else_body = [self._parse_if()]
            else:
                else_body = self._parse_block()
        return IfStmt(cond, then_body, else_body)

    def _parse_while(self) -> WhileStmt:
        self._advance()
        self._expect_op("(")
        cond = self.parse_expr()
        self._expect_op(")")
        body = self._parse_block()
        return WhileStmt(cond, body)

    # -- expressions --------------------------------------------------

    def parse_expr(self) -> object:
        return self._parse_or()

    def _parse_or(self) -> object:
        left = self._parse_and()
        while self._check_kw("or"):
            self._advance()
            right = self._parse_and()
            left = LogicOp("or", left, right)
        return left

    def _parse_and(self) -> object:
        left = self._parse_not()
        while self._check_kw("and"):
            self._advance()
            right = self._parse_not()
            left = LogicOp("and", left, right)
        return left

    def _parse_not(self) -> object:
        if self._check_kw("not"):
            self._advance()
            return NotOp(self._parse_not())
        return self._parse_comparison()

    _COMPARE_OPS = ("==", "!=", "<=", ">=", "<", ">")

    def _parse_comparison(self) -> object:
        left = self._parse_additive()
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.text in self._COMPARE_OPS:
            op = tok.text
            offset = tok.offset
            self._advance()
            right = self._parse_additive()
            left = BinOp(op, left, right, offset)
            tok2 = self._peek()
            if tok2 is not None and tok2.kind == "OP" and tok2.text in self._COMPARE_OPS:
                raise ParseError("comparison is not associative", tok2.offset)
        return left

    def _parse_additive(self) -> object:
        left = self._parse_multiplicative()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "OP" and tok.text in ("+", "-"):
                self._advance()
                right = self._parse_multiplicative()
                left = BinOp(tok.text, left, right, tok.offset)
            else:
                break
        return left

    def _parse_multiplicative(self) -> object:
        left = self._parse_unary()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "OP" and tok.text in ("*", "/", "%"):
                self._advance()
                right = self._parse_unary()
                left = BinOp(tok.text, left, right, tok.offset)
            else:
                break
        return left

    def _parse_unary(self) -> object:
        if self._check_op("-"):
            self._advance()
            return Neg(self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> object:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input", self.src_len)
        if tok.kind == "INT":
            self._advance()
            return IntLit(tok.value)
        if tok.kind == "FLOAT":
            self._advance()
            return FloatLit(tok.value)
        if tok.kind == "STRING":
            self._advance()
            return StrLit(tok.value)
        if tok.kind == "KEYWORD" and tok.text == "true":
            self._advance()
            return BoolLit(True)
        if tok.kind == "KEYWORD" and tok.text == "false":
            self._advance()
            return BoolLit(False)
        if tok.kind == "IDENT":
            self._advance()
            return VarRef(tok.text, tok.offset)
        if tok.kind == "OP" and tok.text == "(":
            self._advance()
            expr = self.parse_expr()
            self._expect_op(")")
            return expr
        raise ParseError("expected expression", tok.offset)


def parse(src: str) -> object:
    tokens = tokenize(src)
    parser = _Parser(tokens, len(src))
    module = parser.parse_module()
    if parser.pos != len(tokens):
        raise ParseError("trailing tokens", parser._offset())
    return module
