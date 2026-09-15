"""Parser and AST definition for microvm."""

import dataclasses
from microvm.errors import ParseError
from microvm.lexer import Token, tokenize


@dataclasses.dataclass(frozen=True)
class Literal:
    value: int | float | str | bool
    offset: int


@dataclasses.dataclass(frozen=True)
class Var:
    name: str
    offset: int


@dataclasses.dataclass(frozen=True)
class UnaryOp:
    op: str
    expr: object
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
    then_block: list[object]
    else_branch: object  # list[object] | IfStmt | None
    offset: int


@dataclasses.dataclass(frozen=True)
class WhileStmt:
    cond: object
    body: list[object]
    offset: int


@dataclasses.dataclass(frozen=True)
class BlockStmt:
    stmts: list[object]
    offset: int


@dataclasses.dataclass(frozen=True)
class ProgramNode:
    stmts: list[object]


class Parser:
    def __init__(self, src: str, tokens: list[Token]) -> None:
        self.src: str = src
        self.tokens: list[Token] = tokens
        self.pos: int = 0

    def peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def match(self, kind: str, text: str | None = None) -> bool:
        tok = self.peek()
        if not tok or tok.kind != kind:
            return False
        if text is not None and tok.text != text:
            return False
        return True

    def consume(self, kind: str, text: str | None = None) -> Token:
        tok = self.peek()
        if not tok:
            raise ParseError("Unexpected end of input", len(self.src))
        if tok.kind != kind or (text is not None and tok.text != text):
            expected = f"{kind} '{text}'" if text else kind
            raise ParseError(f"Expected {expected}, got {tok.kind} '{tok.text}'", tok.offset)
        self.pos += 1
        return tok

    def parse_statement(self) -> object:
        tok = self.peek()
        if not tok:
            raise ParseError("Unexpected end of input", len(self.src))
        if tok.kind == "KEYWORD":
            if tok.text == "let":
                return self.parse_let()
            if tok.text == "print":
                return self.parse_print()
            if tok.text == "if":
                return self.parse_if()
            if tok.text == "while":
                return self.parse_while()
        if tok.kind == "OP" and tok.text == "{":
            return self.parse_block_stmt()
        if tok.kind == "IDENT":
            return self.parse_assign()
        raise ParseError(f"Unexpected token {tok.text!r}", tok.offset)

    def parse_let(self) -> LetStmt:
        start_tok = self.consume("KEYWORD", "let")
        name_tok = self.consume("IDENT")
        self.consume("OP", "=")
        expr = self.parse_expr()
        self.consume("OP", ";")
        return LetStmt(name=name_tok.text, expr=expr, offset=start_tok.offset)

    def parse_assign(self) -> AssignStmt:
        name_tok = self.consume("IDENT")
        self.consume("OP", "=")
        expr = self.parse_expr()
        self.consume("OP", ";")
        return AssignStmt(name=name_tok.text, expr=expr, offset=name_tok.offset)

    def parse_print(self) -> PrintStmt:
        start_tok = self.consume("KEYWORD", "print")
        expr = self.parse_expr()
        self.consume("OP", ";")
        return PrintStmt(expr=expr, offset=start_tok.offset)

    def parse_block_stmts(self) -> list[object]:
        self.consume("OP", "{")
        stmts: list[object] = []
        while True:
            tok = self.peek()
            if not tok:
                raise ParseError("Unclosed block, expected '}'", len(self.src))
            if tok.kind == "OP" and tok.text == "}":
                self.consume("OP", "}")
                break
            stmts.append(self.parse_statement())
        return stmts

    def parse_block_stmt(self) -> BlockStmt:
        tok = self.peek()
        offset = tok.offset if tok else len(self.src)
        stmts = self.parse_block_stmts()
        return BlockStmt(stmts=stmts, offset=offset)

    def parse_if(self) -> IfStmt:
        start_tok = self.consume("KEYWORD", "if")
        self.consume("OP", "(")
        cond = self.parse_expr()
        self.consume("OP", ")")
        then_block = self.parse_block_stmts()
        else_branch: object = None
        if self.match("KEYWORD", "else"):
            self.consume("KEYWORD", "else")
            if self.match("KEYWORD", "if"):
                else_branch = self.parse_if()
            elif self.match("OP", "{"):
                else_branch = self.parse_block_stmts()
            else:
                tok = self.peek()
                offset = tok.offset if tok else len(self.src)
                raise ParseError("Expected '{' or 'if' after 'else'", offset)
        return IfStmt(cond=cond, then_block=then_block, else_branch=else_branch, offset=start_tok.offset)

    def parse_while(self) -> WhileStmt:
        start_tok = self.consume("KEYWORD", "while")
        self.consume("OP", "(")
        cond = self.parse_expr()
        self.consume("OP", ")")
        body = self.parse_block_stmts()
        return WhileStmt(cond=cond, body=body, offset=start_tok.offset)

    def parse_expr(self) -> object:
        return self.parse_or()

    def parse_or(self) -> object:
        node = self.parse_and()
        while self.match("KEYWORD", "or"):
            op = self.consume("KEYWORD", "or")
            right = self.parse_and()
            node = BinaryOp("or", node, right, op.offset)
        return node

    def parse_and(self) -> object:
        node = self.parse_not()
        while self.match("KEYWORD", "and"):
            op = self.consume("KEYWORD", "and")
            right = self.parse_not()
            node = BinaryOp("and", node, right, op.offset)
        return node

    def parse_not(self) -> object:
        if self.match("KEYWORD", "not"):
            op = self.consume("KEYWORD", "not")
            operand = self.parse_not()
            return UnaryOp("not", operand, op.offset)
        return self.parse_comparison()

    def parse_comparison(self) -> object:
        node = self.parse_additive()
        cmp_ops = ("==", "!=", "<", "<=", ">", ">=")
        tok = self.peek()
        if tok and tok.kind == "OP" and tok.text in cmp_ops:
            op = self.consume("OP")
            right = self.parse_additive()
            node = BinaryOp(op.text, node, right, op.offset)
            next_tok = self.peek()
            if next_tok and next_tok.kind == "OP" and next_tok.text in cmp_ops:
                raise ParseError("Comparison operators are not associative", next_tok.offset)
        return node

    def parse_additive(self) -> object:
        node = self.parse_multiplicative()
        while True:
            tok = self.peek()
            if tok and tok.kind == "OP" and tok.text in ("+", "-"):
                op = self.consume("OP")
                right = self.parse_multiplicative()
                node = BinaryOp(op.text, node, right, op.offset)
            else:
                break
        return node

    def parse_multiplicative(self) -> object:
        node = self.parse_unary()
        while True:
            tok = self.peek()
            if tok and tok.kind == "OP" and tok.text in ("*", "/", "%"):
                op = self.consume("OP")
                right = self.parse_unary()
                node = BinaryOp(op.text, node, right, op.offset)
            else:
                break
        return node

    def parse_unary(self) -> object:
        tok = self.peek()
        if tok and tok.kind == "OP" and tok.text == "-":
            op = self.consume("OP", "-")
            operand = self.parse_unary()
            return UnaryOp("-", operand, op.offset)
        return self.parse_primary()

    def parse_primary(self) -> object:
        tok = self.peek()
        if not tok:
            raise ParseError("Expected expression, got end of input", len(self.src))
        if tok.kind in ("INT", "FLOAT", "STRING"):
            self.consume(tok.kind)
            return Literal(tok.value, tok.offset)
        if tok.kind == "KEYWORD" and tok.text == "true":
            self.consume("KEYWORD", "true")
            return Literal(True, tok.offset)
        if tok.kind == "KEYWORD" and tok.text == "false":
            self.consume("KEYWORD", "false")
            return Literal(False, tok.offset)
        if tok.kind == "IDENT":
            self.consume("IDENT")
            return Var(tok.text, tok.offset)
        if tok.kind == "OP" and tok.text == "(":
            self.consume("OP", "(")
            expr = self.parse_expr()
            self.consume("OP", ")")
            return expr
        raise ParseError(f"Unexpected token in expression: {tok.text!r}", tok.offset)


def parse(src: str) -> object:
    tokens = tokenize(src)
    parser = Parser(src, tokens)
    stmts: list[object] = []
    while parser.peek() is not None:
        stmts.append(parser.parse_statement())
    return ProgramNode(stmts=stmts)
