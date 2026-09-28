"""Recursive-descent parser for minilang expressions."""

from minilang.errors import ParseError
from minilang.lexer import tokenize

_COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})


class Number:
    def __init__(self, value: float, position: int):
        self.value = value
        self.position = position


class StringLit:
    def __init__(self, value: str, position: int):
        self.value = value
        self.position = position


class BoolLit:
    def __init__(self, value: bool, position: int):
        self.value = value
        self.position = position


class Name:
    def __init__(self, name: str, position: int):
        self.name = name
        self.position = position


class UnaryOp:
    def __init__(self, op: str, operand, position: int):
        self.op = op
        self.operand = operand
        self.position = position


class BinaryOp:
    def __init__(self, op: str, left, right, position: int):
        self.op = op
        self.left = left
        self.right = right
        self.position = position


class Call:
    def __init__(self, name: str, args: list, position: int):
        self.name = name
        self.args = args
        self.position = position


class Parser:
    def __init__(self, tokens: list, source: str):
        self.tokens = tokens
        self.source = source
        self.index = 0

    def _current(self):
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def _advance(self):
        token = self._current()
        if token is not None:
            self.index += 1
        return token

    def _error_pos(self) -> int:
        token = self._current()
        if token is not None:
            return token.position
        return len(self.source)

    def _expect_op(self, value: str) -> None:
        token = self._current()
        if token is None or token.kind != "OP" or token.value != value:
            raise ParseError(f"expected {value!r}", self._error_pos())
        self._advance()

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while True:
            token = self._current()
            if token is None or token.kind != "KEYWORD" or token.value != "or":
                return left
            self._advance()
            right = self.parse_and()
            left = BinaryOp("or", left, right, token.position)

    def parse_and(self):
        left = self.parse_not()
        while True:
            token = self._current()
            if token is None or token.kind != "KEYWORD" or token.value != "and":
                return left
            self._advance()
            right = self.parse_not()
            left = BinaryOp("and", left, right, token.position)

    def parse_not(self):
        token = self._current()
        if token is not None and token.kind == "KEYWORD" and token.value == "not":
            self._advance()
            return UnaryOp("not", self.parse_not(), token.position)
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        token = self._current()
        if token is None or token.kind != "OP" or token.value not in _COMPARISONS:
            return left
        self._advance()
        right = self.parse_additive()
        nxt = self._current()
        if nxt is not None and nxt.kind == "OP" and nxt.value in _COMPARISONS:
            raise ParseError("comparison operators are non-associative", nxt.position)
        return BinaryOp(token.value, left, right, token.position)

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            token = self._current()
            if token is None or token.kind != "OP" or token.value not in "+-":
                return left
            self._advance()
            right = self.parse_multiplicative()
            left = BinaryOp(token.value, left, right, token.position)

    def parse_multiplicative(self):
        left = self.parse_unary()
        while True:
            token = self._current()
            if token is None or token.kind != "OP" or token.value not in "*/%":
                return left
            self._advance()
            right = self.parse_unary()
            left = BinaryOp(token.value, left, right, token.position)

    def parse_unary(self):
        token = self._current()
        if token is not None and token.kind == "OP" and token.value == "-":
            self._advance()
            return UnaryOp("-", self.parse_unary(), token.position)
        return self.parse_power()

    def parse_power(self):
        left = self.parse_primary()
        token = self._current()
        if token is not None and token.kind == "OP" and token.value == "^":
            self._advance()
            # Right operand is a unary, so ^ is right-associative and
            # binds tighter than unary minus: -2 ^ 2 == -(2 ^ 2).
            right = self.parse_unary()
            return BinaryOp("^", left, right, token.position)
        return left

    def parse_primary(self):
        token = self._current()
        if token is None:
            raise ParseError("unexpected end of input", len(self.source))
        if token.kind == "NUMBER":
            self._advance()
            return Number(token.value, token.position)
        if token.kind == "STRING":
            self._advance()
            return StringLit(token.value, token.position)
        if token.kind == "KEYWORD" and token.value in ("true", "false"):
            self._advance()
            return BoolLit(token.value == "true", token.position)
        if token.kind == "IDENT":
            self._advance()
            nxt = self._current()
            if nxt is not None and nxt.kind == "OP" and nxt.value == "(":
                self._advance()
                args: list = []
                nxt = self._current()
                if not (nxt is not None and nxt.kind == "OP" and nxt.value == ")"):
                    args.append(self.parse_expr())
                    while True:
                        nxt = self._current()
                        if nxt is None or nxt.kind != "OP" or nxt.value != ",":
                            break
                        self._advance()
                        args.append(self.parse_expr())
                self._expect_op(")")
                return Call(token.value, args, token.position)
            return Name(token.value, token.position)
        if token.kind == "OP" and token.value == "(":
            self._advance()
            expr = self.parse_expr()
            self._expect_op(")")
            return expr
        raise ParseError("unexpected token", token.position)


def parse(source: str):
    """Parse ``source`` into an AST. Does not evaluate the expression."""
    tokens = tokenize(source)
    if not tokens:
        raise ParseError("unexpected end of input", 0)
    parser = Parser(tokens, source)
    expr = parser.parse_expr()
    if parser._current() is not None:
        raise ParseError("unexpected token", parser._error_pos())
    return expr
