import dataclasses
from .lexer import tokenize, Token
from .errors import ParseError


@dataclasses.dataclass
class Literal:
    value: object


@dataclasses.dataclass
class Variable:
    name: str


@dataclasses.dataclass
class Unary:
    op: str
    expr: object


@dataclasses.dataclass
class Binary:
    op: str
    left: object
    right: object


@dataclasses.dataclass
class Let:
    name: str
    expr: object


@dataclasses.dataclass
class Assign:
    name: str
    expr: object


@dataclasses.dataclass
class Print:
    expr: object


@dataclasses.dataclass
class Block:
    statements: list


@dataclasses.dataclass
class If:
    cond: object
    then: object
    otherwise: object | None


@dataclasses.dataclass
class While:
    cond: object
    body: object


@dataclasses.dataclass
class ProgramNode:
    statements: list


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.t = tokens
        self.i = 0

    def current(self) -> Token | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def fail(self, message: str) -> None:
        tok = self.current()
        raise ParseError(message, tok.offset if tok else (self.t[-1].offset + len(self.t[-1].text) if self.t else 0))

    def take(self, text: str) -> Token:
        tok = self.current()
        if not tok or tok.text != text:
            self.fail("expected " + text)
        self.i += 1
        return tok

    def parse(self) -> ProgramNode:
        statements = []
        while self.current():
            statements.append(self.statement())
        return ProgramNode(statements)

    def statement(self) -> object:
        tok = self.current()
        if tok.text == "let":
            self.i += 1; name = self.current()
            if not name or name.kind != "IDENT": self.fail("expected identifier")
            self.i += 1; self.take("="); expr = self.expression(); self.take(";")
            return Let(name.text, expr)
        if tok.text == "print":
            self.i += 1; expr = self.expression(); self.take(";"); return Print(expr)
        if tok.text == "if":
            self.i += 1; self.take("("); cond = self.expression(); self.take(")")
            then = self.block()
            other = None
            if self.current() and self.current().text == "else":
                self.i += 1
                other = self.statement() if self.current() and self.current().text == "if" else self.block()
            return If(cond, then, other)
        if tok.text == "while":
            self.i += 1; self.take("("); cond = self.expression(); self.take(")"); return While(cond, self.block())
        if tok.text == "{":
            return self.block()
        if tok.kind == "IDENT":
            self.i += 1; name = tok.text; self.take("="); expr = self.expression(); self.take(";"); return Assign(name, expr)
        self.fail("expected statement")

    def block(self) -> Block:
        self.take("{"); items = []
        while self.current() and self.current().text != "}": items.append(self.statement())
        self.take("}"); return Block(items)

    def expression(self) -> object: return self.or_expr()
    def or_expr(self) -> object:
        node = self.and_expr()
        while self.current() and self.current().text == "or":
            self.i += 1; node = Binary("or", node, self.and_expr())
        return node
    def and_expr(self) -> object:
        node = self.not_expr()
        while self.current() and self.current().text == "and":
            self.i += 1; node = Binary("and", node, self.not_expr())
        return node
    def not_expr(self) -> object:
        if self.current() and self.current().text == "not":
            self.i += 1; return Unary("not", self.not_expr())
        return self.comparison()
    def comparison(self) -> object:
        node = self.additive()
        if self.current() and self.current().text in ("==", "!=", "<", "<=", ">", ">="):
            op = self.current().text; self.i += 1; node = Binary(op, node, self.additive())
            if self.current() and self.current().text in ("==", "!=", "<", "<=", ">", ">="): self.fail("comparison is not associative")
        return node
    def additive(self) -> object:
        node = self.multiplicative()
        while self.current() and self.current().text in ("+", "-"):
            op = self.current().text; self.i += 1; node = Binary(op, node, self.multiplicative())
        return node
    def multiplicative(self) -> object:
        node = self.unary()
        while self.current() and self.current().text in ("*", "/", "%"):
            op = self.current().text; self.i += 1; node = Binary(op, node, self.unary())
        return node
    def unary(self) -> object:
        if self.current() and self.current().text == "-":
            self.i += 1; return Unary("-", self.unary())
        return self.primary()
    def primary(self) -> object:
        tok = self.current()
        if not tok: self.fail("expected expression")
        if tok.kind in ("INT", "FLOAT", "STRING"): self.i += 1; return Literal(tok.value)
        if tok.text in ("true", "false"): self.i += 1; return Literal(tok.text == "true")
        if tok.kind == "IDENT": self.i += 1; return Variable(tok.text)
        if tok.text == "(":
            self.i += 1; n = self.expression(); self.take(")"); return n
        self.fail("expected expression")


def parse(src: str) -> object:
    return _Parser(tokenize(src)).parse()
