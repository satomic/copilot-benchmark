import dataclasses

from .errors import ParseError
from .lexer import Token


@dataclasses.dataclass(frozen=True)
class Literal:
    value: object


@dataclasses.dataclass(frozen=True)
class Name:
    name: str


@dataclasses.dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclasses.dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclasses.dataclass(frozen=True)
class LetStmt:
    name: str
    value: object


@dataclasses.dataclass(frozen=True)
class AssignStmt:
    name: str
    value: object


@dataclasses.dataclass(frozen=True)
class PrintStmt:
    value: object


@dataclasses.dataclass(frozen=True)
class IfStmt:
    condition: object
    then_branch: object
    else_branch: object | None


@dataclasses.dataclass(frozen=True)
class WhileStmt:
    condition: object
    body: object


@dataclasses.dataclass(frozen=True)
class BlockStmt:
    statements: list[object]


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    def peek(self) -> Token | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.peek()
        if token is None:
            raise ParseError("Unexpected end of input", 0)
        self.index += 1
        return token

    def match(self, kind: str, text: str | None = None) -> Token | None:
        token = self.peek()
        if token is None:
            return None
        if token.kind != kind:
            return None
        if text is not None and token.text != text:
            return None
        self.index += 1
        return token

    def expect(self, kind: str, text: str | None = None) -> Token:
        token = self.peek()
        if token is None:
            raise ParseError("Unexpected end of input", 0)
        if token.kind != kind or (text is not None and token.text != text):
            raise ParseError(f"Expected {text or kind}", token.offset)
        self.index += 1
        return token

    def parse_program(self) -> list[object]:
        statements: list[object] = []
        while self.peek() is not None:
            statements.append(self.parse_statement())
        return statements

    def parse_statement(self) -> object:
        token = self.peek()
        if token is None:
            raise ParseError("Unexpected end of input", 0)
        if token.kind == "KEYWORD" and token.text == "let":
            return self.parse_let()
        if token.kind == "KEYWORD" and token.text == "print":
            return self.parse_print()
        if token.kind == "KEYWORD" and token.text == "if":
            return self.parse_if()
        if token.kind == "KEYWORD" and token.text == "while":
            return self.parse_while()
        if token.kind == "OP" and token.text == "{":
            return self.parse_block()
        if token.kind == "IDENT":
            return self.parse_assignment()
        raise ParseError(f"Unexpected token {token.text!r}", token.offset)

    def parse_block(self) -> BlockStmt:
        self.expect("OP", "{")
        statements: list[object] = []
        while self.peek() is not None and not (self.peek().kind == "OP" and self.peek().text == "}"):
            statements.append(self.parse_statement())
        self.expect("OP", "}")
        return BlockStmt(statements)

    def parse_let(self) -> LetStmt:
        self.expect("KEYWORD", "let")
        name = self.expect("IDENT").text
        self.expect("OP", "=")
        value = self.parse_expression()
        self.expect("OP", ";")
        return LetStmt(name, value)

    def parse_assignment(self) -> AssignStmt:
        name = self.expect("IDENT").text
        self.expect("OP", "=")
        value = self.parse_expression()
        self.expect("OP", ";")
        return AssignStmt(name, value)

    def parse_print(self) -> PrintStmt:
        self.expect("KEYWORD", "print")
        value = self.parse_expression()
        self.expect("OP", ";")
        return PrintStmt(value)

    def parse_if(self) -> IfStmt:
        self.expect("KEYWORD", "if")
        self.expect("OP", "(")
        condition = self.parse_expression()
        self.expect("OP", ")")
        then_branch = self.parse_statement()
        else_branch: object | None = None
        if self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().text == "else":
            self.advance()
            if self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().text == "if":
                else_branch = self.parse_if()
            else:
                else_branch = self.parse_statement()
        return IfStmt(condition, then_branch, else_branch)

    def parse_while(self) -> WhileStmt:
        self.expect("KEYWORD", "while")
        self.expect("OP", "(")
        condition = self.parse_expression()
        self.expect("OP", ")")
        body = self.parse_statement()
        return WhileStmt(condition, body)

    def parse_expression(self) -> object:
        return self.parse_or()

    def parse_or(self) -> object:
        node = self.parse_and()
        while self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().text == "or":
            self.advance()
            node = Binary("or", node, self.parse_and())
        return node

    def parse_and(self) -> object:
        node = self.parse_not()
        while self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().text == "and":
            self.advance()
            node = Binary("and", node, self.parse_not())
        return node

    def parse_not(self) -> object:
        if self.peek() is not None and self.peek().kind == "KEYWORD" and self.peek().text == "not":
            self.advance()
            return Unary("not", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> object:
        node = self.parse_additive()
        if self.peek() is not None and self.peek().kind == "OP" and self.peek().text in {"==", "!=", "<", "<=", ">", ">="}:
            op = self.advance().text
            right = self.parse_additive()
            if self.peek() is not None and self.peek().kind == "OP" and self.peek().text in {"==", "!=", "<", "<=", ">", ">="}:
                raise ParseError("Chained comparison is not allowed", self.peek().offset)
            return Binary(op, node, right)
        return node

    def parse_additive(self) -> object:
        node = self.parse_multiplicative()
        while self.peek() is not None and self.peek().kind == "OP" and self.peek().text in {"+", "-"}:
            op = self.advance().text
            node = Binary(op, node, self.parse_multiplicative())
        return node

    def parse_multiplicative(self) -> object:
        node = self.parse_unary()
        while self.peek() is not None and self.peek().kind == "OP" and self.peek().text in {"*", "/", "%"}:
            op = self.advance().text
            node = Binary(op, node, self.parse_unary())
        return node

    def parse_unary(self) -> object:
        if self.peek() is not None and self.peek().kind == "OP" and self.peek().text == "-":
            self.advance()
            return Unary("neg", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> object:
        token = self.peek()
        if token is None:
            raise ParseError("Unexpected end of input", 0)
        if token.kind == "INT":
            self.advance()
            return Literal(token.value)
        if token.kind == "FLOAT":
            self.advance()
            return Literal(token.value)
        if token.kind == "STRING":
            self.advance()
            return Literal(token.value)
        if token.kind == "KEYWORD" and token.text in {"true", "false"}:
            self.advance()
            return Literal(token.text == "true")
        if token.kind == "IDENT":
            self.advance()
            return Name(token.text)
        if token.kind == "OP" and token.text == "(":
            self.advance()
            expr = self.parse_expression()
            self.expect("OP", ")")
            return expr
        raise ParseError(f"Unexpected token {token.text!r}", token.offset)


def parse(src: str) -> list[object]:
    tokens = []
    from .lexer import tokenize

    tokens = tokenize(src)
    parser = Parser(tokens)
    return parser.parse_program()
