from __future__ import annotations

import dataclasses
from microvm.errors import ParseError
from microvm.lexer import Token, tokenize


@dataclasses.dataclass(frozen=True)
class Literal:
    value: object
    offset: int


@dataclasses.dataclass(frozen=True)
class Var:
    name: str
    offset: int


@dataclasses.dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: Expr
    offset: int


@dataclasses.dataclass(frozen=True)
class BinOp:
    op: str
    left: Expr
    right: Expr
    offset: int


@dataclasses.dataclass(frozen=True)
class LogicOp:
    op: str  # "and" | "or"
    left: Expr
    right: Expr
    offset: int


Expr = Literal | Var | UnaryOp | BinOp | LogicOp


@dataclasses.dataclass(frozen=True)
class LetStmt:
    name: str
    expr: Expr
    offset: int


@dataclasses.dataclass(frozen=True)
class AssignStmt:
    name: str
    expr: Expr
    offset: int


@dataclasses.dataclass(frozen=True)
class PrintStmt:
    expr: Expr
    offset: int


@dataclasses.dataclass(frozen=True)
class BlockStmt:
    stmts: list[Stmt]
    offset: int


@dataclasses.dataclass(frozen=True)
class IfStmt:
    cond: Expr
    then_block: BlockStmt
    else_branch: BlockStmt | IfStmt | None
    offset: int


@dataclasses.dataclass(frozen=True)
class WhileStmt:
    cond: Expr
    body: BlockStmt
    offset: int


Stmt = LetStmt | AssignStmt | PrintStmt | BlockStmt | IfStmt | WhileStmt


@dataclasses.dataclass(frozen=True)
class ProgramAST:
    stmts: list[Stmt]


COMPARE_OPS: frozenset[str] = frozenset({"==", "!=", "<", "<=", ">", ">="})


class _Parser:
    def __init__(self, tokens: list[Token], eof_offset: int) -> None:
        self.tokens = tokens
        self.pos = 0
        self.eof_offset = eof_offset

    def _peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _offset(self) -> int:
        tok = self._peek()
        return tok.offset if tok is not None else self.eof_offset

    def _advance(self) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError("Unexpected end of input", self.eof_offset)
        self.pos += 1
        return tok

    def _expect(self, kind: str, text: str | None = None) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError(f"Expected {text or kind}, got EOF", self.eof_offset)
        if tok.kind != kind or (text is not None and tok.text != text):
            raise ParseError(f"Expected {text or kind}, got {tok.text!r}", tok.offset)
        self.pos += 1
        return tok

    def parse_program(self) -> ProgramAST:
        stmts: list[Stmt] = []
        while self._peek() is not None:
            stmts.append(self._parse_stmt())
        return ProgramAST(stmts)

    def _parse_stmt(self) -> Stmt:
        tok = self._peek()
        if tok is None:
            raise ParseError("Expected statement, got EOF", self.eof_offset)
        if tok.kind == "KEYWORD" and tok.text == "let":
            return self._parse_let()
        if tok.kind == "KEYWORD" and tok.text == "print":
            return self._parse_print()
        if tok.kind == "KEYWORD" and tok.text == "if":
            return self._parse_if()
        if tok.kind == "KEYWORD" and tok.text == "while":
            return self._parse_while()
        if tok.kind == "OP" and tok.text == "{":
            return self._parse_block()
        if tok.kind == "IDENT":
            return self._parse_assign()
        raise ParseError(f"Unexpected token {tok.text!r} in statement", tok.offset)

    def _parse_let(self) -> LetStmt:
        kw = self._expect("KEYWORD", "let")
        ident = self._expect("IDENT")
        self._expect("OP", "=")
        expr = self._parse_expr()
        self._expect("OP", ";")
        return LetStmt(ident.text, expr, kw.offset)

    def _parse_assign(self) -> AssignStmt:
        ident = self._expect("IDENT")
        self._expect("OP", "=")
        expr = self._parse_expr()
        self._expect("OP", ";")
        return AssignStmt(ident.text, expr, ident.offset)

    def _parse_print(self) -> PrintStmt:
        kw = self._expect("KEYWORD", "print")
        expr = self._parse_expr()
        self._expect("OP", ";")
        return PrintStmt(expr, kw.offset)

    def _parse_block(self) -> BlockStmt:
        lbrace = self._expect("OP", "{")
        stmts: list[Stmt] = []
        while True:
            tok = self._peek()
            if tok is None:
                raise ParseError("Unterminated block", self.eof_offset)
            if tok.kind == "OP" and tok.text == "}":
                self._advance()
                return BlockStmt(stmts, lbrace.offset)
            stmts.append(self._parse_stmt())

    def _parse_if(self) -> IfStmt:
        kw = self._expect("KEYWORD", "if")
        self._expect("OP", "(")
        cond = self._parse_expr()
        self._expect("OP", ")")
        then_block = self._parse_block()
        else_branch: BlockStmt | IfStmt | None = None
        tok = self._peek()
        if tok is not None and tok.kind == "KEYWORD" and tok.text == "else":
            self._advance()
            nxt = self._peek()
            if nxt is not None and nxt.kind == "KEYWORD" and nxt.text == "if":
                else_branch = self._parse_if()
            elif nxt is not None and nxt.kind == "OP" and nxt.text == "{":
                else_branch = self._parse_block()
            else:
                raise ParseError("Expected '{' or 'if' after 'else'", self._offset())
        return IfStmt(cond, then_block, else_branch, kw.offset)

    def _parse_while(self) -> WhileStmt:
        kw = self._expect("KEYWORD", "while")
        self._expect("OP", "(")
        cond = self._parse_expr()
        self._expect("OP", ")")
        body = self._parse_block()
        return WhileStmt(cond, body, kw.offset)

    def _parse_expr(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "KEYWORD" and tok.text == "or":
                self._advance()
                right = self._parse_and()
                left = LogicOp("or", left, right, tok.offset)
            else:
                return left

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "KEYWORD" and tok.text == "and":
                self._advance()
                right = self._parse_not()
                left = LogicOp("and", left, right, tok.offset)
            else:
                return left

    def _parse_not(self) -> Expr:
        tok = self._peek()
        if tok is not None and tok.kind == "KEYWORD" and tok.text == "not":
            self._advance()
            return UnaryOp("not", self._parse_not(), tok.offset)
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        left = self._parse_additive()
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.text in COMPARE_OPS:
            self._advance()
            right = self._parse_additive()
            nxt = self._peek()
            if nxt is not None and nxt.kind == "OP" and nxt.text in COMPARE_OPS:
                raise ParseError("Comparison operators cannot be chained", nxt.offset)
            return BinOp(tok.text, left, right, tok.offset)
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "OP" and tok.text in ("+", "-"):
                self._advance()
                right = self._parse_multiplicative()
                left = BinOp(tok.text, left, right, tok.offset)
            else:
                return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while True:
            tok = self._peek()
            if tok is not None and tok.kind == "OP" and tok.text in ("*", "/", "%"):
                self._advance()
                right = self._parse_unary()
                left = BinOp(tok.text, left, right, tok.offset)
            else:
                return left

    def _parse_unary(self) -> Expr:
        tok = self._peek()
        if tok is not None and tok.kind == "OP" and tok.text == "-":
            self._advance()
            return UnaryOp("-", self._parse_unary(), tok.offset)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        tok = self._peek()
        if tok is None:
            raise ParseError("Expected expression, got EOF", self.eof_offset)
        if tok.kind in ("INT", "FLOAT", "STRING"):
            self._advance()
            return Literal(tok.value, tok.offset)
        if tok.kind == "KEYWORD" and tok.text in ("true", "false"):
            self._advance()
            return Literal(tok.text == "true", tok.offset)
        if tok.kind == "IDENT":
            self._advance()
            return Var(tok.text, tok.offset)
        if tok.kind == "OP" and tok.text == "(":
            self._advance()
            expr = self._parse_expr()
            self._expect("OP", ")")
            return expr
        raise ParseError(f"Unexpected token {tok.text!r} in expression", tok.offset)


def parse(src: str) -> object:
    tokens = tokenize(src)
    return _Parser(tokens, len(src)).parse_program()
