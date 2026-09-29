from minilang.lexer import Token, tokenize
from minilang.errors import ParseError


# --- AST Node types ---

class NumberLiteral:
    __slots__ = ("value", "position")
    def __init__(self, value: float, position: int):
        self.value = value
        self.position = position

class StringLiteral:
    __slots__ = ("value", "position")
    def __init__(self, value: str, position: int):
        self.value = value
        self.position = position

class BooleanLiteral:
    __slots__ = ("value", "position")
    def __init__(self, value: bool, position: int):
        self.value = value
        self.position = position

class Identifier:
    __slots__ = ("name", "position")
    def __init__(self, name: str, position: int):
        self.name = name
        self.position = position

class UnaryOp:
    __slots__ = ("op", "operand", "position")
    def __init__(self, op: str, operand: object, position: int):
        self.op = op
        self.operand = operand
        self.position = position

class BinaryOp:
    __slots__ = ("op", "left", "right", "position")
    def __init__(self, op: str, left: object, right: object, position: int):
        self.op = op
        self.left = left
        self.right = right
        self.position = position

class FunctionCall:
    __slots__ = ("name", "args", "position")
    def __init__(self, name: str, args: list, position: int):
        self.name = name
        self.args = args
        self.position = position


class Parser:
    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, kind: str, value: str | None = None) -> Token:
        t = self.peek()
        if t is None:
            raise ParseError("unexpected end of input", -1)
        if t.kind != kind:
            raise ParseError(f"expected {kind}, got {t.kind}", t.position)
        if value is not None and t.value != value:
            raise ParseError(f"expected {value!r}, got {t.value!r}", t.position)
        return self.advance()

    def parse(self) -> object:
        if self.pos >= len(self.tokens):
            raise ParseError("empty expression", -1)
        node = self._expr()
        if self.pos < len(self.tokens):
            t = self.peek()
            raise ParseError(f"unexpected token: {t.value!r}", t.position)
        return node

    def _expr(self):
        return self._or_expr()

    def _or_expr(self):
        left = self._and_expr()
        while self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().value == "or":
            tok = self.advance()
            right = self._and_expr()
            left = BinaryOp("or", left, right, tok.position)
        return left

    def _and_expr(self):
        left = self._not_expr()
        while self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().value == "and":
            tok = self.advance()
            right = self._not_expr()
            left = BinaryOp("and", left, right, tok.position)
        return left

    def _not_expr(self):
        tok = self.peek()
        if tok is not None and tok.kind == "KEYWORD" and tok.value == "not":
            self.advance()
            operand = self._not_expr()
            return UnaryOp("not", operand, tok.position)
        return self._comparison()

    def _comparison(self):
        left = self._additive()
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.value in ("==", "!=", "<", "<=", ">", ">="):
            self.advance()
            right = self._additive()
            # Check that there isn't another comparison op (non-associative)
            next_tok = self.peek()
            if next_tok is not None and next_tok.kind == "OP" and next_tok.value in ("==", "!=", "<", "<=", ">", ">="):
                raise ParseError("chained comparison is not allowed", next_tok.position)
            return BinaryOp(tok.value, left, right, tok.position)
        return left

    def _additive(self):
        left = self._multiplicative()
        while self.peek() is not None and self.peek().kind == "OP" and self.peek().value in ("+", "-"):
            tok = self.advance()
            right = self._multiplicative()
            left = BinaryOp(tok.value, left, right, tok.position)
        return left

    def _multiplicative(self):
        left = self._unary()
        while self.peek() is not None and self.peek().kind == "OP" and self.peek().value in ("*", "/", "%"):
            tok = self.advance()
            right = self._unary()
            left = BinaryOp(tok.value, left, right, tok.position)
        return left

    def _unary(self):
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.value == "-":
            self.advance()
            operand = self._unary()
            return UnaryOp("-", operand, tok.position)
        return self._power()

    def _power(self):
        left = self._primary()
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.value == "^":
            self.advance()
            # Right-associative: right operand is unary
            right = self._unary()
            left = BinaryOp("^", left, right, tok.position)
        return left

    def _primary(self):
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of input", -1)

        if tok.kind == "NUMBER":
            self.advance()
            val = float(tok.value)
            return NumberLiteral(val, tok.position)
        elif tok.kind == "STRING":
            self.advance()
            return StringLiteral(tok.value, tok.position)
        elif tok.kind == "KEYWORD" and tok.value == "true":
            self.advance()
            return BooleanLiteral(True, tok.position)
        elif tok.kind == "KEYWORD" and tok.value == "false":
            self.advance()
            return BooleanLiteral(False, tok.position)
        elif tok.kind == "IDENT":
            self.advance()
            # Check if this is a function call
            if self.peek() is not None and self.peek().kind == "OP" and self.peek().value == "(":
                self.advance()  # consume (
                args = []
                if not (self.peek() is not None and self.peek().kind == "OP" and self.peek().value == ")"):
                    args.append(self._expr())
                    while self.peek() is not None and self.peek().kind == "OP" and self.peek().value == ",":
                        self.advance()  # consume ,
                        if self.peek() is None or (self.peek().kind == "OP" and self.peek().value == ")"):
                            raise ParseError("trailing comma not allowed", tok.position)
                        args.append(self._expr())
                self.expect("OP", ")")
                return FunctionCall(tok.value, args, tok.position)
            else:
                            return Identifier(tok.value, tok.position)
        elif tok.kind == "OP" and tok.value == "(":
            self.advance()
            node = self._expr()
            self.expect("OP", ")")
            return node
        else:
            raise ParseError(f"unexpected token: {tok.value!r}", tok.position)


def parse(source: str) -> object:
    tokens = tokenize(source)
    # Filter out any tokens that are just standalone '.' (shouldn't happen after lexer fix, but safety)
    parser = Parser(tokens)
    return parser.parse()