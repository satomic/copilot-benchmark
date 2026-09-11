from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .errors import ParseError
from .lexer import Token, tokenize


@dataclass(frozen=True)
class _Node:
    kind: str
    value: int | float | str | bool | None = None
    children: tuple[_Node, ...] = ()


class _Parser:
    def __init__(self, src: str) -> None:
        self.tokens = tokenize(src)
        self.end = len(src)
        self.pos = 0

    def _error(self, message: str) -> ParseError:
        offset = self.tokens[self.pos].offset if self.pos < len(self.tokens) else self.end
        return ParseError(message, offset)

    def _at(self, text: str) -> bool:
        if self.pos == len(self.tokens):
            return False
        token = self.tokens[self.pos]
        return token.kind in ("OP", "KEYWORD") and token.text == text

    def _match(self, text: str) -> bool:
        if not self._at(text):
            return False
        self.pos += 1
        return True

    def _expect(self, text: str) -> None:
        if not self._match(text):
            raise self._error(f"Expected {text!r}")

    def _identifier(self) -> str:
        if self.pos == len(self.tokens) or self.tokens[self.pos].kind != "IDENT":
            raise self._error("Expected identifier")
        token = self.tokens[self.pos]
        self.pos += 1
        return token.text

    def _program(self) -> _Node:
        statements: list[_Node] = []
        while self.pos < len(self.tokens):
            statements.append(self._statement())
        return _Node("block", children=tuple(statements))

    def _block(self) -> _Node:
        self._expect("{")
        statements: list[_Node] = []
        while not self._match("}"):
            if self.pos == len(self.tokens):
                raise self._error("Expected '}'")
            statements.append(self._statement())
        return _Node("block", children=tuple(statements))

    def _statement(self) -> _Node:
        if self._at("{"):
            return self._block()
        if self._match("let"):
            name = self._identifier()
            self._expect("=")
            value = self._expression()
            self._expect(";")
            return _Node("let", name, (value,))
        if self._match("print"):
            value = self._expression()
            self._expect(";")
            return _Node("print", children=(value,))
        if self._match("if"):
            return self._if()
        if self._match("while"):
            self._expect("(")
            condition = self._expression()
            self._expect(")")
            return _Node("while", children=(condition, self._block()))
        name = self._identifier()
        self._expect("=")
        value = self._expression()
        self._expect(";")
        return _Node("assign", name, (value,))

    def _if(self) -> _Node:
        self._expect("(")
        condition = self._expression()
        self._expect(")")
        children = (condition, self._block())
        if self._match("else"):
            other = self._if() if self._match("if") else self._block()
            children += (other,)
        return _Node("if", children=children)

    def _level(self, operand: Callable[[], _Node], operators: tuple[str, ...]) -> _Node:
        result = operand()
        while self.pos < len(self.tokens):
            op = self.tokens[self.pos].text
            if op not in operators or not self._match(op):
                break
            result = _Node("binary", op, (result, operand()))
        return result

    def _expression(self) -> _Node:
        return self._level(self._and, ("or",))

    def _and(self) -> _Node:
        return self._level(self._not, ("and",))

    def _not(self) -> _Node:
        if self._match("not"):
            return _Node("unary", "not", (self._not(),))
        return self._comparison()

    def _comparison(self) -> _Node:
        left = self._additive()
        operators = ("==", "!=", "<", "<=", ">", ">=")
        if self.pos < len(self.tokens) and self.tokens[self.pos].text in operators:
            op = self.tokens[self.pos].text
            if self._match(op):
                left = _Node("binary", op, (left, self._additive()))
                if any(self._at(other) for other in operators):
                    raise self._error("Comparisons cannot be chained")
        return left

    def _additive(self) -> _Node:
        return self._level(self._multiplicative, ("+", "-"))

    def _multiplicative(self) -> _Node:
        return self._level(self._unary, ("*", "/", "%"))

    def _unary(self) -> _Node:
        if self._match("-"):
            return _Node("unary", "-", (self._unary(),))
        return self._primary()

    def _primary(self) -> _Node:
        if self._match("("):
            value = self._expression()
            self._expect(")")
            return value
        if self.pos == len(self.tokens):
            raise self._error("Expected expression")
        token: Token = self.tokens[self.pos]
        if token.kind in ("INT", "FLOAT", "STRING"):
            self.pos += 1
            if not isinstance(token.value, (int, float, str)):
                raise self._error("Invalid literal")
            return _Node("literal", token.value)
        if self._at("true") or self._at("false"):
            self.pos += 1
            return _Node("literal", token.text == "true")
        if token.kind == "IDENT":
            self.pos += 1
            return _Node("variable", token.text)
        raise self._error("Expected expression")


def parse(src: str) -> object:
    return _Parser(src)._program()
