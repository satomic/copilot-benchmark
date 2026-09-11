from .lexer import tokenize
from .errors import ParseError, LexError


class ASTNode:
    pass


class Program(ASTNode):
    def __init__(self, statements):
        self.statements = statements


class Let(ASTNode):
    def __init__(self, name, value):
        self.name = name
        self.value = value


class Assign(ASTNode):
    def __init__(self, name, value):
        self.name = name
        self.value = value


class Print(ASTNode):
    def __init__(self, expr):
        self.expr = expr


class If(ASTNode):
    def __init__(self, cond, then_branch, else_branch=None):
        self.cond = cond
        self.then_branch = then_branch
        self.else_branch = else_branch


class While(ASTNode):
    def __init__(self, cond, body):
        self.cond = cond
        self.body = body


class Block(ASTNode):
    def __init__(self, statements):
        self.statements = statements


class BinOp(ASTNode):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right


class UnaryOp(ASTNode):
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand


class Literal(ASTNode):
    def __init__(self, value):
        self.value = value


class Var(ASTNode):
    def __init__(self, name):
        self.name = name


def parse(src: str) -> Program:
    try:
        tokens = tokenize(src)
    except LexError:
        raise
    parser = Parser(tokens)
    return parser.parse_program()


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self):
        token = self.peek()
        self.pos += 1
        return token

    def expect(self, kind, value=None):
        token = self.peek()
        if not token or token.kind != kind or (value and token.value != value):
            offset = token.offset if token else len(self.src)
            raise ParseError(f"Expected {kind}", token.offset if token else 0)
        return self.consume()

    def parse_program(self):
        statements = []
        while self.peek():
            statements.append(self.parse_statement())
        return Program(statements)

    def parse_statement(self):
        token = self.peek()
        if not token:
            raise ParseError("Unexpected EOF", 0)
        if token.kind == "KEYWORD" and token.value == "let":
            return self.parse_let()
        elif token.kind == "KEYWORD" and token.value == "print":
            return self.parse_print()
        elif token.kind == "KEYWORD" and token.value == "if":
            return self.parse_if()
        elif token.kind == "KEYWORD" and token.value == "while":
            return self.parse_while()
        elif token.kind == "OP" and token.value == "{":
            return self.parse_block()
        elif token.kind == "IDENT":
            return self.parse_assign()
        else:
            raise ParseError("Expected statement", token.offset)

    def parse_let(self):
        let_token = self.expect("KEYWORD", "let")
        name_token = self.expect("IDENT")
        self.expect("OP", "=")
        value = self.parse_expr()
        self.expect("OP", ";")
        return Let(name_token.value, value)

    def parse_assign(self):
        name_token = self.consume()
        self.expect("OP", "=")
        value = self.parse_expr()
        self.expect("OP", ";")
        return Assign(name_token.value, value)

    def parse_print(self):
        self.expect("KEYWORD", "print")
        expr = self.parse_expr()
        self.expect("OP", ";")
        return Print(expr)

    def parse_if(self):
        self.expect("KEYWORD", "if")
        self.expect("OP", "(")
        cond = self.parse_expr()
        self.expect("OP", ")")
        then_branch = self.parse_statement()
        else_branch = None
        if self.peek() and self.peek().kind == "KEYWORD" and self.peek().value == "else":
            self.consume()
            else_branch = self.parse_statement()
        return If(cond, then_branch, else_branch)

    def parse_while(self):
        self.expect("KEYWORD", "while")
        self.expect("OP", "(")
        cond = self.parse_expr()
        self.expect("OP", ")")
        body = self.parse_statement()
        return While(cond, body)

    def parse_block(self):
        self.expect("OP", "{")
        statements = []
        while self.peek() and not (self.peek().kind == "OP" and self.peek().value == "}"):
            statements.append(self.parse_statement())
        self.expect("OP", "}")
        return Block(statements)

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.peek() and self.peek().kind == "KEYWORD" and self.peek().value == "or":
            self.consume()
            right = self.parse_and()
            left = BinOp(left, "or", right)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.peek() and self.peek().kind == "KEYWORD" and self.peek().value == "and":
            self.consume()
            right = self.parse_not()
            left = BinOp(left, "and", right)
        return left

    def parse_not(self):
        if self.peek() and self.peek().kind == "KEYWORD" and self.peek().value == "not":
            self.consume()
            return UnaryOp("not", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        token = self.peek()
        if token and token.kind == "OP" and token.value in ["==", "!=", "<", "<=", ">", ">="]:
            op_token = self.consume()
            right = self.parse_additive()
            left = BinOp(left, op_token.value, right)
            if self.peek() and self.peek().kind == "OP" and self.peek().value in ["==", "!=", "<", "<=", ">", ">="]:
                raise ParseError("Comparison is not associative", self.peek().offset)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.peek() and self.peek().kind == "OP" and self.peek().value in ["+", "-"]:
            op_token = self.consume()
            right = self.parse_multiplicative()
            left = BinOp(left, op_token.value, right)
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.peek() and self.peek().kind == "OP" and self.peek().value in ["*", "/", "%"]:
            op_token = self.consume()
            right = self.parse_unary()
            left = BinOp(left, op_token.value, right)
        return left

    def parse_unary(self):
        if self.peek() and self.peek().kind == "OP" and self.peek().value == "-":
            self.consume()
            return UnaryOp("-", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        token = self.peek()
        if not token:
            raise ParseError("Unexpected EOF", 0)
        if token.kind == "INT":
            self.consume()
            return Literal(token.value)
        elif token.kind == "FLOAT":
            self.consume()
            return Literal(token.value)
        elif token.kind == "STRING":
            self.consume()
            return Literal(token.value)
        elif token.kind == "KEYWORD" and token.value == "true":
            self.consume()
            return Literal(True)
        elif token.kind == "KEYWORD" and token.value == "false":
            self.consume()
            return Literal(False)
        elif token.kind == "IDENT":
            self.consume()
            return Var(token.value)
        elif token.kind == "OP" and token.value == "(":
            self.consume()
            expr = self.parse_expr()
            self.expect("OP", ")")
            return expr
        else:
            raise ParseError("Expected primary", token.offset)
