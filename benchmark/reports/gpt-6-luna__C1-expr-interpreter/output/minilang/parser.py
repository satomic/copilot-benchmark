from dataclasses import dataclass

from .errors import ParseError
from .lexer import Token, tokenize


@dataclass(frozen=True)
class Literal:
    value: object


@dataclass(frozen=True)
class Variable:
    name: str


@dataclass(frozen=True)
class Unary:
    operator: str
    operand: object


@dataclass(frozen=True)
class Binary:
    operator: str
    left: object
    right: object


@dataclass(frozen=True)
class Call:
    name: str
    arguments: list


class _Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = tokenize(source)
        self.index = 0

    def current(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _error(self, message: str, token: Token | None = None) -> ParseError:
        current = token if token is not None else self.current()
        position = current.position if current is not None else len(self.source)
        return ParseError(message, position)

    def _is(self, value: str) -> bool:
        token = self.current()
        return token is not None and token.value == value

    def _take(self, value: str) -> Token:
        token = self.current()
        if token is None or token.value != value:
            raise self._error(f"expected {value!r}")
        self.index += 1
        return token

    def parse(self):
        if not self.tokens:
            raise ParseError("expected expression", len(self.source))
        expression = self._or()
        if self.current() is not None:
            raise self._error("unexpected trailing input")
        return expression

    def _or(self):
        node = self._and()
        while self._is("or"):
            self.index += 1
            node = Binary("or", node, self._and())
        return node

    def _and(self):
        node = self._not()
        while self._is("and"):
            self.index += 1
            node = Binary("and", node, self._not())
        return node

    def _not(self):
        if self._is("not"):
            self.index += 1
            return Unary("not", self._not())
        return self._comparison()

    def _comparison(self):
        node = self._additive()
        if self.current() is not None and self.current().value in ("==", "!=", "<", "<=", ">", ">="):
            operator = self.current().value
            self.index += 1
            node = Binary(operator, node, self._additive())
            if self.current() is not None and self.current().value in ("==", "!=", "<", "<=", ">", ">="):
                raise self._error("comparisons are non-associative")
        return node

    def _additive(self):
        node = self._multiplicative()
        while self.current() is not None and self.current().value in ("+", "-"):
            operator = self.current().value
            self.index += 1
            node = Binary(operator, node, self._multiplicative())
        return node

    def _multiplicative(self):
        node = self._unary()
        while self.current() is not None and self.current().value in ("*", "/", "%"):
            operator = self.current().value
            self.index += 1
            node = Binary(operator, node, self._unary())
        return node

    def _unary(self):
        if self._is("-"):
            self.index += 1
            return Unary("-", self._unary())
        return self._power()

    def _power(self):
        node = self._primary()
        if self._is("^"):
            self.index += 1
            node = Binary("^", node, self._unary())
        return node

    def _primary(self):
        token = self.current()
        if token is None:
            raise self._error("expected expression")
        if token.kind == "NUMBER" or token.kind == "STRING":
            self.index += 1
            return Literal(token.value)
        if token.kind == "KEYWORD":
            if token.value in ("true", "false"):
                self.index += 1
                return Literal(token.value == "true")
            raise self._error("expected expression")
        if token.kind == "IDENT":
            self.index += 1
            if self._is("("):
                self.index += 1
                arguments = []
                if not self._is(")"):
                    arguments.append(self._or())
                    while self._is(","):
                        self.index += 1
                        arguments.append(self._or())
                self._take(")")
                return Call(token.value, arguments)
            return Variable(token.value)
        if token.value == "(":
            self.index += 1
            expression = self._or()
            self._take(")")
            return expression
        raise self._error("expected expression")


def parse(source: str):
    return _Parser(source).parse()
