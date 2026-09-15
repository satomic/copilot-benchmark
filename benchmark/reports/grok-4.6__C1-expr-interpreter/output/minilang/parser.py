from minilang.errors import ParseError
from minilang.lexer import tokenize


class NumberLit:
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


class Variable:
    def __init__(self, name: str, position: int):
        self.name = name
        self.position = position


class Call:
    def __init__(self, name: str, args: list, position: int):
        self.name = name
        self.args = args
        self.position = position


class Unary:
    def __init__(self, op: str, operand, position: int):
        self.op = op
        self.operand = operand
        self.position = position


class Binary:
    def __init__(self, op: str, left, right, position: int):
        self.op = op
        self.left = left
        self.right = right
        self.position = position


_CMP_OPS = frozenset({"==", "!=", "<", "<=", ">", ">="})


def parse(source: str):
    tokens = tokenize(source)
    parser = _Parser(tokens, source)
    expr = parser.parse_expr()
    if parser.peek() is not None:
        tok = parser.peek()
        raise ParseError("unexpected trailing input", tok.position)
    return expr


class _Parser:
    def __init__(self, tokens, source: str):
        self.tokens = tokens
        self.source = source
        self.i = 0

    def peek(self):
        if self.i < len(self.tokens):
            return self.tokens[self.i]
        return None

    def advance(self):
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", len(self.source))
        self.i += 1
        return tok

    def _eof_pos(self):
        return len(self.source)

    def parse_expr(self):
        if self.peek() is None:
            raise ParseError("empty expression", 0)
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while True:
            tok = self.peek()
            if tok and tok.kind == "KEYWORD" and tok.value == "or":
                self.advance()
                right = self.parse_and()
                left = Binary("or", left, right, tok.position)
            else:
                return left

    def parse_and(self):
        left = self.parse_not()
        while True:
            tok = self.peek()
            if tok and tok.kind == "KEYWORD" and tok.value == "and":
                self.advance()
                right = self.parse_not()
                left = Binary("and", left, right, tok.position)
            else:
                return left

    def parse_not(self):
        tok = self.peek()
        if tok and tok.kind == "KEYWORD" and tok.value == "not":
            self.advance()
            return Unary("not", self.parse_not(), tok.position)
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        tok = self.peek()
        if tok and tok.kind == "OP" and tok.value in _CMP_OPS:
            op = tok.value
            self.advance()
            right = self.parse_additive()
            nxt = self.peek()
            if nxt and nxt.kind == "OP" and nxt.value in _CMP_OPS:
                raise ParseError("comparison is non-associative", nxt.position)
            return Binary(op, left, right, tok.position)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            tok = self.peek()
            if tok and tok.kind == "OP" and tok.value in ("+", "-"):
                self.advance()
                right = self.parse_multiplicative()
                left = Binary(tok.value, left, right, tok.position)
            else:
                return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if tok and tok.kind == "OP" and tok.value in ("*", "/", "%"):
                self.advance()
                right = self.parse_unary()
                left = Binary(tok.value, left, right, tok.position)
            else:
                return left

    def parse_unary(self):
        tok = self.peek()
        if tok and tok.kind == "OP" and tok.value == "-":
            self.advance()
            return Unary("-", self.parse_unary(), tok.position)
        return self.parse_power()

    def parse_power(self):
        left = self.parse_primary()
        tok = self.peek()
        if tok and tok.kind == "OP" and tok.value == "^":
            self.advance()
            right = self.parse_unary()
            return Binary("^", left, right, tok.position)
        return left

    def parse_primary(self):
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", self._eof_pos())
        if tok.kind == "NUMBER":
            self.advance()
            return NumberLit(tok.value, tok.position)
        if tok.kind == "STRING":
            self.advance()
            return StringLit(tok.value, tok.position)
        if tok.kind == "KEYWORD" and tok.value in ("true", "false"):
            self.advance()
            return BoolLit(tok.value == "true", tok.position)
        if tok.kind == "IDENT":
            self.advance()
            nxt = self.peek()
            if nxt and nxt.kind == "OP" and nxt.value == "(":
                self.advance()
                args = []
                if not (self.peek() and self.peek().kind == "OP" and self.peek().value == ")"):
                    args.append(self.parse_expr())
                    while self.peek() and self.peek().kind == "OP" and self.peek().value == ",":
                        self.advance()
                        args.append(self.parse_expr())
                close = self.peek()
                if not (close and close.kind == "OP" and close.value == ")"):
                    pos = close.position if close else self._eof_pos()
                    raise ParseError("expected ')'", pos)
                self.advance()
                return Call(tok.value, args, tok.position)
            return Variable(tok.value, tok.position)
        if tok.kind == "OP" and tok.value == "(":
            self.advance()
            expr = self.parse_expr()
            close = self.peek()
            if not (close and close.kind == "OP" and close.value == ")"):
                pos = close.position if close else self._eof_pos()
                raise ParseError("expected ')'", pos)
            self.advance()
            return expr
        raise ParseError(f"unexpected token: {tok.value!r}", tok.position)
