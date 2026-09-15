"""MiniLang parser and AST definitions."""

from dataclasses import dataclass
from typing import Any
from .errors import ParseError
from .lexer import Token, tokenize


@dataclass
class Literal:
    value: Any
    position: int


@dataclass
class Variable:
    name: str
    position: int


@dataclass
class UnaryOp:
    op: str
    operand: Any
    position: int


@dataclass
class BinaryOp:
    op: str
    left: Any
    right: Any
    position: int


@dataclass
class FunctionCall:
    name: str
    args: list[Any]
    position: int


class Parser:
    """Recursive-descent parser for MiniLang grammar."""

    def __init__(self, tokens: list[Token], source_len: int) -> None:
        self.tokens = tokens
        self.source_len = source_len
        self.pos = 0

    def peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def current_position(self) -> int:
        tok = self.peek()
        if tok is not None:
            return tok.position
        return self.source_len

    def consume(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", position=self.source_len)
        self.pos += 1
        return tok

    def is_at_end(self) -> bool:
        return self.pos >= len(self.tokens)

    def parse(self) -> Any:
        return self.or_expr()

    def or_expr(self) -> Any:
        node = self.and_expr()
        while self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().value == "or":
            op_tok = self.consume()
            right = self.and_expr()
            node = BinaryOp(op="or", left=node, right=right, position=op_tok.position)
        return node

    def and_expr(self) -> Any:
        node = self.not_expr()
        while self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().value == "and":
            op_tok = self.consume()
            right = self.not_expr()
            node = BinaryOp(op="and", left=node, right=right, position=op_tok.position)
        return node

    def not_expr(self) -> Any:
        if self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().value == "not":
            op_tok = self.consume()
            operand = self.not_expr()
            return UnaryOp(op="not", operand=operand, position=op_tok.position)
        return self.comparison()

    def comparison(self) -> Any:
        node = self.additive()
        comp_ops = ("==", "!=", "<", "<=", ">", ">=")
        if self.peek() is not None and self.peek().kind == "OP" and self.peek().value in comp_ops:
            op_tok = self.consume()
            right = self.additive()
            if self.peek() is not None and self.peek().kind == "OP" and self.peek().value in comp_ops:
                offending = self.peek()
                raise ParseError(
                    f"comparison operator '{offending.value}' is non-associative",
                    position=offending.position,
                )
            node = BinaryOp(op=op_tok.value, left=node, right=right, position=op_tok.position)
        return node

    def additive(self) -> Any:
        node = self.multiplicative()
        while self.peek() is not None and self.peek().kind == "OP" and self.peek().value in ("+", "-"):
            op_tok = self.consume()
            right = self.multiplicative()
            node = BinaryOp(op=op_tok.value, left=node, right=right, position=op_tok.position)
        return node

    def multiplicative(self) -> Any:
        node = self.unary()
        while self.peek() is not None and self.peek().kind == "OP" and self.peek().value in ("*", "/", "%"):
            op_tok = self.consume()
            right = self.unary()
            node = BinaryOp(op=op_tok.value, left=node, right=right, position=op_tok.position)
        return node

    def unary(self) -> Any:
        if self.peek() is not None and self.peek().kind == "OP" and self.peek().value == "-":
            op_tok = self.consume()
            operand = self.unary()
            return UnaryOp(op="-", operand=operand, position=op_tok.position)
        return self.power()

    def power(self) -> Any:
        node = self.primary()
        if self.peek() is not None and self.peek().kind == "OP" and self.peek().value == "^":
            op_tok = self.consume()
            right = self.unary()
            node = BinaryOp(op="^", left=node, right=right, position=op_tok.position)
        return node

    def primary(self) -> Any:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", position=self.source_len)

        if tok.kind == "NUMBER":
            self.consume()
            return Literal(value=tok.value, position=tok.position)

        if tok.kind == "STRING":
            self.consume()
            return Literal(value=tok.value, position=tok.position)

        if tok.kind == "KEYWORD":
            if tok.value == "true":
                self.consume()
                return Literal(value=True, position=tok.position)
            elif tok.value == "false":
                self.consume()
                return Literal(value=False, position=tok.position)
            else:
                raise ParseError(f"unexpected keyword '{tok.value}'", position=tok.position)

        if tok.kind == "IDENT":
            ident_tok = self.consume()
            if self.peek() is not None and self.peek().kind == "OP" and self.peek().value == "(":
                self.consume()  # consume '('
                args: list[Any] = []
                if self.peek() is not None and not (self.peek().kind == "OP" and self.peek().value == ")"):
                    args.append(self.or_expr())
                    while self.peek() is not None and self.peek().kind == "OP" and self.peek().value == ",":
                        self.consume()  # consume ','
                        args.append(self.or_expr())
                if self.peek() is None or not (self.peek().kind == "OP" and self.peek().value == ")"):
                    raise ParseError("expected ')' after function arguments", position=self.current_position())
                self.consume()  # consume ')'
                return FunctionCall(name=ident_tok.value, args=args, position=ident_tok.position)
            return Variable(name=ident_tok.value, position=ident_tok.position)

        if tok.kind == "OP" and tok.value == "(":
            self.consume()
            expr_node = self.or_expr()
            if self.peek() is None or not (self.peek().kind == "OP" and self.peek().value == ")"):
                raise ParseError("expected ')'", position=self.current_position())
            self.consume()
            return expr_node

        raise ParseError(f"unexpected token '{tok.value}'", position=tok.position)


def parse(source: str) -> object:
    """Parse source string into an AST root node."""
    tokens = tokenize(source)
    if not tokens:
        raise ParseError("empty source", position=0)
    parser = Parser(tokens, len(source))
    ast = parser.parse()
    if not parser.is_at_end():
        trailing = parser.peek()
        raise ParseError(f"unexpected trailing token: {trailing.value!r}", position=trailing.position)
    return ast
