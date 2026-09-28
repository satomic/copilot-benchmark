import dataclasses
from typing import NoReturn, cast

from microvm.errors import ParseError
from microvm.lexer import Token, tokenize

_CMP_OPS = frozenset({"==", "!=", "<", "<=", ">", ">="})
_ADD_OPS = frozenset({"+", "-"})
_MUL_OPS = frozenset({"*", "/", "%"})


@dataclasses.dataclass(frozen=True)
class IntLit:
    value: int
    offset: int


@dataclasses.dataclass(frozen=True)
class FloatLit:
    value: float
    offset: int


@dataclasses.dataclass(frozen=True)
class StringLit:
    value: str
    offset: int


@dataclasses.dataclass(frozen=True)
class BoolLit:
    value: bool
    offset: int


@dataclasses.dataclass(frozen=True)
class Ident:
    name: str
    offset: int


@dataclasses.dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: object
    offset: int


@dataclasses.dataclass(frozen=True)
class BinaryOp:
    op: str
    left: object
    right: object
    offset: int


@dataclasses.dataclass(frozen=True)
class LetStmt:
    name: str
    expr: object
    offset: int


@dataclasses.dataclass(frozen=True)
class AssignStmt:
    name: str
    expr: object
    offset: int


@dataclasses.dataclass(frozen=True)
class PrintStmt:
    expr: object
    offset: int


@dataclasses.dataclass(frozen=True)
class IfStmt:
    cond: object
    then_body: object
    else_body: object | None
    offset: int


@dataclasses.dataclass(frozen=True)
class WhileStmt:
    cond: object
    body: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Block:
    statements: list[object]
    offset: int


@dataclasses.dataclass(frozen=True)
class ProgramNode:
    statements: list[object]


def parse(src: str) -> object:
    return _Parser(src, tokenize(src)).parse_program()


class _Parser:
    def __init__(self, src: str, tokens: list[Token]) -> None:
        self.src = src
        self.tokens = tokens
        self.pos = 0

    def parse_program(self) -> ProgramNode:
        statements: list[object] = []
        while not self._at_end():
            statements.append(self._statement())
        return ProgramNode(statements)

    def _statement(self) -> object:
        if self._check_keyword("let"):
            return self._let()
        if self._check_keyword("print"):
            return self._print()
        if self._check_keyword("if"):
            return self._if()
        if self._check_keyword("while"):
            return self._while()
        if self._check_op("{"):
            return self._block()
        if self._check_kind("IDENT"):
            return self._assign()
        self._fail("unexpected token")

    def _let(self) -> LetStmt:
        keyword = self._advance()
        name = self._expect_ident()
        self._expect_op("=")
        expr = self._expr()
        self._expect_op(";")
        return LetStmt(name.text, expr, keyword.offset)

    def _assign(self) -> AssignStmt:
        name = self._advance()
        self._expect_op("=")
        expr = self._expr()
        self._expect_op(";")
        return AssignStmt(name.text, expr, name.offset)

    def _print(self) -> PrintStmt:
        keyword = self._advance()
        expr = self._expr()
        self._expect_op(";")
        return PrintStmt(expr, keyword.offset)

    def _if(self) -> IfStmt:
        keyword = self._advance()
        self._expect_op("(")
        cond = self._expr()
        self._expect_op(")")
        then_body = self._block()
        else_body: object | None = None
        if self._match_keyword("else"):
            else_body = self._if() if self._check_keyword("if") else self._block()
        return IfStmt(cond, then_body, else_body, keyword.offset)

    def _while(self) -> WhileStmt:
        keyword = self._advance()
        self._expect_op("(")
        cond = self._expr()
        self._expect_op(")")
        return WhileStmt(cond, self._block(), keyword.offset)

    def _block(self) -> Block:
        brace = self._expect_op("{")
        statements: list[object] = []
        while not self._at_end() and not self._check_op("}"):
            statements.append(self._statement())
        self._expect_op("}")
        return Block(statements, brace.offset)

    def _expr(self) -> object:
        return self._or()

    def _or(self) -> object:
        left = self._and()
        while self._check_keyword("or"):
            op = self._advance()
            left = BinaryOp("or", left, self._and(), op.offset)
        return left

    def _and(self) -> object:
        left = self._not()
        while self._check_keyword("and"):
            op = self._advance()
            left = BinaryOp("and", left, self._not(), op.offset)
        return left

    def _not(self) -> object:
        # Grammar binds `not` outside comparison: `not a == b` is `not (a == b)`.
        if not self._check_keyword("not"):
            return self._comparison()
        op = self._advance()
        return UnaryOp("not", self._not(), op.offset)

    def _comparison(self) -> object:
        left = self._additive()
        if not self._check_op_set(_CMP_OPS):
            return left
        op = self._advance()
        right = self._additive()
        if self._check_op_set(_CMP_OPS):
            self._fail("comparison is not associative")
        return BinaryOp(op.text, left, right, op.offset)

    def _additive(self) -> object:
        left = self._multiplicative()
        while self._check_op_set(_ADD_OPS):
            op = self._advance()
            left = BinaryOp(op.text, left, self._multiplicative(), op.offset)
        return left

    def _multiplicative(self) -> object:
        left = self._unary()
        while self._check_op_set(_MUL_OPS):
            op = self._advance()
            left = BinaryOp(op.text, left, self._unary(), op.offset)
        return left

    def _unary(self) -> object:
        if not self._check_op("-"):
            return self._primary()
        op = self._advance()
        return UnaryOp("-", self._unary(), op.offset)

    def _primary(self) -> object:
        if self._at_end():
            self._fail("unexpected end of input")
        tok = self._peek()
        if tok.kind == "INT":
            self._advance()
            return IntLit(cast(int, tok.value), tok.offset)
        if tok.kind == "FLOAT":
            self._advance()
            return FloatLit(cast(float, tok.value), tok.offset)
        if tok.kind == "STRING":
            self._advance()
            return StringLit(cast(str, tok.value), tok.offset)
        if tok.kind == "KEYWORD" and tok.text in ("true", "false"):
            self._advance()
            return BoolLit(tok.text == "true", tok.offset)
        if tok.kind == "IDENT":
            self._advance()
            return Ident(tok.text, tok.offset)
        if tok.kind == "OP" and tok.text == "(":
            self._advance()
            expr = self._expr()
            self._expect_op(")")
            return expr
        self._fail("unexpected token")

    def _at_end(self) -> bool:
        return self.pos >= len(self.tokens)

    def _peek(self) -> Token:
        if self._at_end():
            raise ParseError("unexpected end of input", len(self.src))
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self._peek()
        self.pos += 1
        return tok

    def _check_kind(self, kind: str) -> bool:
        return not self._at_end() and self.tokens[self.pos].kind == kind

    def _check_keyword(self, text: str) -> bool:
        if self._at_end():
            return False
        tok = self.tokens[self.pos]
        return tok.kind == "KEYWORD" and tok.text == text

    def _check_op(self, text: str) -> bool:
        if self._at_end():
            return False
        tok = self.tokens[self.pos]
        return tok.kind == "OP" and tok.text == text

    def _check_op_set(self, ops: frozenset[str]) -> bool:
        if self._at_end():
            return False
        tok = self.tokens[self.pos]
        return tok.kind == "OP" and tok.text in ops

    def _match_keyword(self, text: str) -> bool:
        if not self._check_keyword(text):
            return False
        self.pos += 1
        return True

    def _expect_op(self, text: str) -> Token:
        if not self._check_op(text):
            self._fail(f"expected '{text}'")
        return self._advance()

    def _expect_ident(self) -> Token:
        if not self._check_kind("IDENT"):
            self._fail("expected identifier")
        return self._advance()

    def _fail(self, message: str) -> NoReturn:
        raise ParseError(message, self._error_offset())

    def _error_offset(self) -> int:
        if self._at_end():
            return len(self.src)
        return self.tokens[self.pos].offset
