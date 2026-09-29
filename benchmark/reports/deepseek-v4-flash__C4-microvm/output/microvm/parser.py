from microvm.errors import ParseError, LexError
from microvm.lexer import tokenize, Token

# AST node types


class ASTNode:
    """Base class for all AST nodes."""
    pass


class ProgramNode(ASTNode):
    __slots__ = ("statements",)

    def __init__(self, statements: list) -> None:
        self.statements = statements


class LetNode(ASTNode):
    __slots__ = ("name", "value", "offset")

    def __init__(self, name: str, value: object, offset: int) -> None:
        self.name = name
        self.value = value
        self.offset = offset


class AssignNode(ASTNode):
    __slots__ = ("name", "value", "offset")

    def __init__(self, name: str, value: object, offset: int) -> None:
        self.name = name
        self.value = value
        self.offset = offset


class PrintNode(ASTNode):
    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value


class IfNode(ASTNode):
    __slots__ = ("condition", "then_branch", "else_branch")

    def __init__(self, condition: object, then_branch: object, else_branch: object | None) -> None:
        self.condition = condition
        self.then_branch = then_branch
        self.else_branch = else_branch


class WhileNode(ASTNode):
    __slots__ = ("condition", "body")

    def __init__(self, condition: object, body: object) -> None:
        self.condition = condition
        self.body = body


class BlockNode(ASTNode):
    __slots__ = ("statements",)

    def __init__(self, statements: list) -> None:
        self.statements = statements


class BinaryOpNode(ASTNode):
    __slots__ = ("op", "left", "right", "offset")

    def __init__(self, op: str, left: object, right: object, offset: int) -> None:
        self.op = op
        self.left = left
        self.right = right
        self.offset = offset


class UnaryOpNode(ASTNode):
    __slots__ = ("op", "operand", "offset")

    def __init__(self, op: str, operand: object, offset: int) -> None:
        self.op = op
        self.operand = operand
        self.offset = offset


class LiteralNode(ASTNode):
    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value


class IdentNode(ASTNode):
    __slots__ = ("name", "offset")

    def __init__(self, name: str, offset: int) -> None:
        self.name = name
        self.offset = offset


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str, text: str | None = None) -> Token:
        tok = self.peek()
        if tok is None:
            offset = self.tokens[-1].offset + len(self.tokens[-1].text) if self.tokens else 0
            raise ParseError(f"Expected {kind} '{text}', got end of input", offset)
        if tok.kind != kind or (text is not None and tok.text != text):
            raise ParseError(f"Expected {kind} '{text}', got {tok.kind} '{tok.text}'", tok.offset)
        return self.advance()

    def match(self, kind: str, text: str | None = None) -> bool:
        tok = self.peek()
        if tok is None:
            return False
        if tok.kind != kind:
            return False
        if text is not None and tok.text != text:
            return False
        return True

    def parse(self) -> ProgramNode:
        statements: list[object] = []
        while self.peek() is not None:
            stmt = self.parse_statement()
            if stmt is not None:
                statements.append(stmt)
        return ProgramNode(statements)

    def parse_statement(self) -> object | None:
        tok = self.peek()
        if tok is None:
            return None
        if tok.kind == "KEYWORD":
            if tok.text == "let":
                return self.parse_let()
            elif tok.text == "print":
                return self.parse_print()
            elif tok.text == "if":
                return self.parse_if()
            elif tok.text == "while":
                return self.parse_while()
        if tok.text == "{":
            return self.parse_block()
        return self.parse_assign()

    def parse_let(self) -> LetNode:
        self.expect("KEYWORD", "let")
        name_tok = self.expect("IDENT")
        self.expect("OP", "=")
        value = self.parse_expr()
        self.expect("OP", ";")
        return LetNode(name_tok.text, value, name_tok.offset)

    def parse_assign(self) -> AssignNode:
        name_tok = self.expect("IDENT")
        if self.match("OP", "="):
            self.advance()
            value = self.parse_expr()
            self.expect("OP", ";")
            return AssignNode(name_tok.text, value, name_tok.offset)
        # It might be a bare expression? The language only allows let/assign/print/if/while/block
        # But if we see IDENT not followed by =, it's a parse error at the IDENT
        # Actually the spec says statements are: let, assignment, print, if, while, block
        # So IDENT must be followed by =
        raise ParseError(f"Expected '=' after identifier '{name_tok.text}'", name_tok.offset)

    def parse_print(self) -> PrintNode:
        self.expect("KEYWORD", "print")
        value = self.parse_expr()
        self.expect("OP", ";")
        return PrintNode(value)

    def parse_if(self) -> IfNode:
        tok = self.expect("KEYWORD", "if")
        self.expect("OP", "(")
        condition = self.parse_expr()
        self.expect("OP", ")")
        then_branch = self.parse_statement() or BlockNode([])
        else_branch: object | None = None
        if self.match("KEYWORD", "else"):
            self.advance()
            else_branch = self.parse_statement() or BlockNode([])
        return IfNode(condition, then_branch, else_branch)

    def parse_while(self) -> WhileNode:
        self.expect("KEYWORD", "while")
        self.expect("OP", "(")
        condition = self.parse_expr()
        self.expect("OP", ")")
        body = self.parse_statement() or BlockNode([])
        return WhileNode(condition, body)

    def parse_block(self) -> BlockNode:
        self.expect("OP", "{")
        statements: list[object] = []
        while self.peek() is not None and not self.match("OP", "}"):
            stmt = self.parse_statement()
            if stmt is not None:
                statements.append(stmt)
        self.expect("OP", "}")
        return BlockNode(statements)

    # Expression parsing

    def parse_expr(self) -> object:
        return self.parse_or()

    def parse_or(self) -> object:
        left = self.parse_and()
        while self.match("KEYWORD", "or"):
            tok = self.advance()
            right = self.parse_and()
            left = BinaryOpNode("or", left, right, tok.offset)
        return left

    def parse_and(self) -> object:
        left = self.parse_not()
        while self.match("KEYWORD", "and"):
            tok = self.advance()
            right = self.parse_not()
            left = BinaryOpNode("and", left, right, tok.offset)
        return left

    def parse_not(self) -> object:
        if self.match("KEYWORD", "not"):
            tok = self.advance()
            operand = self.parse_not()
            return UnaryOpNode("not", operand, tok.offset)
        return self.parse_comparison()

    def parse_comparison(self) -> object:
        left = self.parse_additive()
        if self.match("OP") and self.peek() and self.peek().text in ("==", "!=", "<", "<=", ">", ">="):
            op_tok = self.advance()
            right = self.parse_additive()
            return BinaryOpNode(op_tok.text, left, right, op_tok.offset)
        return left

    def parse_additive(self) -> object:
        left = self.parse_multiplicative()
        while self.match("OP") and self.peek() and self.peek().text in ("+", "-"):
            op_tok = self.advance()
            right = self.parse_multiplicative()
            left = BinaryOpNode(op_tok.text, left, right, op_tok.offset)
        return left

    def parse_multiplicative(self) -> object:
        left = self.parse_unary()
        while self.match("OP") and self.peek() and self.peek().text in ("*", "/", "%"):
            op_tok = self.advance()
            right = self.parse_unary()
            left = BinaryOpNode(op_tok.text, left, right, op_tok.offset)
        return left

    def parse_unary(self) -> object:
        if self.match("OP") and self.peek() and self.peek().text == "-":
            tok = self.advance()
            operand = self.parse_unary()
            return UnaryOpNode("-", operand, tok.offset)
        return self.parse_primary()

    def parse_primary(self) -> object:
        tok = self.peek()
        if tok is None:
            raise ParseError("Expected expression, got end of input",
                             self.tokens[-1].offset + len(self.tokens[-1].text))
        if tok.kind == "INT":
            self.advance()
            return LiteralNode(tok.value)
        if tok.kind == "FLOAT":
            self.advance()
            return LiteralNode(tok.value)
        if tok.kind == "STRING":
            self.advance()
            return LiteralNode(tok.value)
        if tok.kind == "KEYWORD" and tok.text == "true":
            self.advance()
            return LiteralNode(True)
        if tok.kind == "KEYWORD" and tok.text == "false":
            self.advance()
            return LiteralNode(False)
        if tok.kind == "IDENT":
            self.advance()
            return IdentNode(tok.text, tok.offset)
        if tok.text == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect("OP", ")")
            return expr
        raise ParseError(f"Unexpected token: {tok.kind} '{tok.text}'", tok.offset)


def parse(src: str) -> object:
    try:
        tokens = tokenize(src)
    except LexError:
        raise
    parser = Parser(tokens)
    return parser.parse()