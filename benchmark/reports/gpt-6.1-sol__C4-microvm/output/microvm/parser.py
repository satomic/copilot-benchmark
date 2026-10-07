from collections.abc import Callable
from dataclasses import dataclass

from .errors import ParseError
from .lexer import Token, tokenize


Value = int | float | str | bool


@dataclass(frozen=True)
class Node:
    kind: str
    value: Value | None = None
    children: tuple["Node", ...] = ()


class _Parser:
    def __init__(self, src: str) -> None:
        self.tokens = tokenize(src)
        self.index = 0
        self.end = len(src)

    def peek(self, text: str) -> bool:
        if self.index == len(self.tokens):
            return False
        token = self.tokens[self.index]
        return token.kind in ("KEYWORD", "OP") and token.text == text

    def error(self, message: str) -> ParseError:
        offset = self.tokens[self.index].offset if self.index < len(self.tokens) else self.end
        return ParseError(message, offset)

    def accept(self, text: str) -> bool:
        if not self.peek(text):
            return False
        self.index += 1
        return True

    def expect(self, text: str) -> None:
        if not self.accept(text):
            raise self.error(f"Expected {text!r}")

    def identifier(self) -> str:
        if self.index == len(self.tokens) or self.tokens[self.index].kind != "IDENT":
            raise self.error("Expected identifier")
        text = self.tokens[self.index].text
        self.index += 1
        return text

    def block(self) -> Node:
        self.expect("{")
        children: list[Node] = []
        while not self.accept("}"):
            if self.index == len(self.tokens):
                raise self.error("Unterminated block")
            children.append(self.statement())
        return Node("block", children=tuple(children))

    def statement(self) -> Node:
        if self.peek("{"):
            return self.block()
        if self.accept("let"):
            name = self.identifier()
            self.expect("=")
            expression = self.expression()
            self.expect(";")
            return Node("let", name, (expression,))
        if self.accept("print"):
            expression = self.expression()
            self.expect(";")
            return Node("print", children=(expression,))
        if self.accept("if"):
            self.expect("(")
            condition = self.expression()
            self.expect(")")
            then = self.block()
            children = (condition, then)
            if self.accept("else"):
                otherwise = self.statement() if self.peek("if") else self.block()
                children += (otherwise,)
            return Node("if", children=children)
        if self.accept("while"):
            self.expect("(")
            condition = self.expression()
            self.expect(")")
            return Node("while", children=(condition, self.block()))
        name = self.identifier()
        self.expect("=")
        expression = self.expression()
        self.expect(";")
        return Node("assign", name, (expression,))

    def expression(self) -> Node:
        return self.chain(self.and_expr, ("or",))

    def and_expr(self) -> Node:
        return self.chain(self.not_expr, ("and",))

    def not_expr(self) -> Node:
        if self.accept("not"):
            return Node("unary", "not", (self.not_expr(),))
        return self.comparison()

    def comparison(self) -> Node:
        node = self.additive()
        operators = ("==", "!=", "<", "<=", ">", ">=")
        for op in operators:
            if self.accept(op):
                node = Node("binary", op, (node, self.additive()))
                if any(self.peek(next_op) for next_op in operators):
                    raise self.error("Chained comparison")
                break
        return node

    def additive(self) -> Node:
        return self.chain(self.multiplicative, ("+", "-"))

    def multiplicative(self) -> Node:
        return self.chain(self.unary, ("*", "/", "%"))

    def unary(self) -> Node:
        if self.accept("-"):
            return Node("unary", "-", (self.unary(),))
        return self.primary()

    def chain(self, operand: Callable[[], Node], operators: tuple[str, ...]) -> Node:
        node = operand()
        while True:
            op = next((op for op in operators if self.peek(op)), None)
            if op is None:
                return node
            self.index += 1
            node = Node("binary", op, (node, operand()))

    def primary(self) -> Node:
        if self.accept("("):
            node = self.expression()
            self.expect(")")
            return node
        if self.index == len(self.tokens):
            raise self.error("Expected expression")
        token: Token = self.tokens[self.index]
        if token.kind in ("INT", "FLOAT", "STRING"):
            self.index += 1
            assert type(token.value) in (int, float, str)
            assert isinstance(token.value, (int, float, str))
            return Node("literal", token.value)
        if token.kind == "IDENT":
            self.index += 1
            return Node("name", token.text)
        if token.kind == "KEYWORD" and token.text in ("true", "false"):
            self.index += 1
            return Node("literal", token.text == "true")
        raise self.error("Expected expression")


def parse(src: str) -> object:
    parser = _Parser(src)
    children: list[Node] = []
    while parser.index < len(parser.tokens):
        children.append(parser.statement())
    return Node("block", children=tuple(children))
