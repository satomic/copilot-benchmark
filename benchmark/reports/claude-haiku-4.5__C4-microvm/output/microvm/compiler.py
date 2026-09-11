import dataclasses
from .parser import parse, Let, Assign, Print, If, While, Block, BinOp, UnaryOp, Literal, Var
from .errors import CompileError
from .opcodes import OPCODE_NUMBERS


@dataclasses.dataclass
class Instr:
    op: str
    arg: int | None


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


class Compiler:
    def __init__(self):
        self.constants = {}
        self.const_list = []
        self.names = {}
        self.declared_names = {}
        self.name_list = []
        self.instructions = []

    def const_index(self, val):
        key = (type(val).__name__, val)
        if key not in self.constants:
            self.constants[key] = len(self.const_list)
            self.const_list.append(val)
        return self.constants[key]

    def add_instr(self, op: str, arg: int | None = None) -> int:
        self.instructions.append(Instr(op, arg))
        return len(self.instructions) - 1

    def compile_source(self, src: str, optimize: bool = False) -> Program:
        ast = parse(src)
        if optimize:
            from .optimizer import fold_constants
            ast = fold_constants(ast)
        self.compile_program(ast)
        self.add_instr("HALT")
        return Program(self.const_list, self.name_list, self.instructions)

    def compile_program(self, node):
        for stmt in node.statements:
            self.compile_statement(stmt)

    def compile_statement(self, node):
        if isinstance(node, Let):
            if node.name in self.declared_names:
                raise CompileError(f"Variable '{node.name}' already declared")
            self.declared_names[node.name] = len(self.name_list)
            self.name_list.append(node.name)
            self.names[node.name] = len(self.name_list) - 1
            self.compile_expr(node.value)
            self.add_instr("STORE", self.names[node.name])
        elif isinstance(node, Assign):
            if node.name not in self.declared_names:
                raise CompileError(f"Variable '{node.name}' not declared")
            self.compile_expr(node.value)
            self.add_instr("STORE", self.names[node.name])
        elif isinstance(node, Print):
            self.compile_expr(node.expr)
            self.add_instr("PRINT")
        elif isinstance(node, If):
            self.compile_expr(node.cond)
            jump_false = self.add_instr("JUMP_IF_FALSE", 0)
            self.compile_statement(node.then_branch)
            if node.else_branch:
                jump_end = self.add_instr("JUMP", 0)
                self.instructions[jump_false].arg = len(self.instructions)
                self.compile_statement(node.else_branch)
                self.instructions[jump_end].arg = len(self.instructions)
            else:
                self.instructions[jump_false].arg = len(self.instructions)
        elif isinstance(node, While):
            loop_start = len(self.instructions)
            self.compile_expr(node.cond)
            jump_exit = self.add_instr("JUMP_IF_FALSE", 0)
            self.compile_statement(node.body)
            self.add_instr("JUMP", loop_start)
            self.instructions[jump_exit].arg = len(self.instructions)
        elif isinstance(node, Block):
            for stmt in node.statements:
                self.compile_statement(stmt)

    def compile_expr(self, node):
        if isinstance(node, Literal):
            idx = self.const_index(node.value)
            self.add_instr("CONST", idx)
        elif isinstance(node, Var):
            if node.name not in self.declared_names:
                raise CompileError(f"Variable '{node.name}' not declared")
            self.add_instr("LOAD", self.names[node.name])
        elif isinstance(node, BinOp):
            if node.op == "and":
                self.compile_expr(node.left)
                jump_false = self.add_instr("JUMP_IF_FALSE", 0)
                self.compile_expr(node.right)
                self.add_instr("NOT")
                self.add_instr("NOT")
                jump_end = self.add_instr("JUMP", 0)
                self.instructions[jump_false].arg = len(self.instructions)
                self.add_instr("CONST", self.const_index(False))
                self.instructions[jump_end].arg = len(self.instructions)
            elif node.op == "or":
                self.compile_expr(node.left)
                jump_false = self.add_instr("JUMP_IF_FALSE", 0)
                self.add_instr("CONST", self.const_index(True))
                jump_end = self.add_instr("JUMP", 0)
                self.instructions[jump_false].arg = len(self.instructions)
                self.compile_expr(node.right)
                self.add_instr("NOT")
                self.add_instr("NOT")
                self.instructions[jump_end].arg = len(self.instructions)
            else:
                self.compile_expr(node.left)
                self.compile_expr(node.right)
                op_map = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
                          "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE"}
                self.add_instr(op_map[node.op])
        elif isinstance(node, UnaryOp):
            self.compile_expr(node.operand)
            if node.op == "-":
                self.add_instr("NEG")
            elif node.op == "not":
                self.add_instr("NOT")


def compile_source(src: str, *, optimize: bool = False) -> Program:
    return Compiler().compile_source(src, optimize)
