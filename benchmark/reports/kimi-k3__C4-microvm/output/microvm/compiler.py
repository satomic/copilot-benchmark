"""Compile the AST into a Program of stack-machine instructions."""

import dataclasses

from .errors import CompileError
from .parser import Assign, BinOp, If, Let, Literal, Print, UnaryOp, Var, While, parse


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str            # one of OPCODES
    arg: int | None    # None exactly when the opcode takes no argument


@dataclasses.dataclass
class Program:
    constants: list        # the constant pool
    names: list[str]       # variable names, slot order = declaration order
    instructions: list     # list[Instr]


_BIN_OPS = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}


class _Compiler:
    """Single-pass code generator with a global name table."""

    def __init__(self) -> None:
        self.constants: list = []
        self._const_index: dict[tuple[type, object], int] = {}
        self.names: list[str] = []
        self._slots: dict[str, int] = {}
        self.code: list[Instr] = []

    def _emit(self, op: str, arg: int | None = None) -> int:
        self.code.append(Instr(op, arg))
        return len(self.code) - 1

    def _patch(self, at: int, target: int) -> None:
        self.code[at] = Instr(self.code[at].op, target)

    def _const(self, value: object) -> int:
        key = (type(value), value)
        if key not in self._const_index:
            self._const_index[key] = len(self.constants)
            self.constants.append(value)
        return self._const_index[key]

    def _slot(self, name: str, offset: int) -> int:
        if name not in self._slots:
            raise CompileError(f"name {name!r} is not declared")
        return self._slots[name]

    # -- statements ------------------------------------------------------

    def _stmt(self, node: object) -> None:
        if isinstance(node, Let):
            if node.name in self._slots:
                raise CompileError(f"name {node.name!r} declared twice")
            self._slots[node.name] = len(self.names)
            self.names.append(node.name)
            self._expr(node.value)
            self._emit("STORE", self._slots[node.name])
        elif isinstance(node, Assign):
            self._expr(node.value)
            self._emit("STORE", self._slot(node.name, node.offset))
        elif isinstance(node, Print):
            self._expr(node.value)
            self._emit("PRINT")
        elif isinstance(node, If):
            self._if(node)
        elif isinstance(node, While):
            self._while(node)
        elif isinstance(node, list):
            for sub in node:
                self._stmt(sub)
        else:  # pragma: no cover - defensive
            raise CompileError(f"unknown statement {node!r}")

    def _if(self, node: If) -> None:
        self._expr(node.cond)
        jf = self._emit("JUMP_IF_FALSE")
        self._stmt(node.then)
        if node.otherwise:
            j = self._emit("JUMP")
            self._patch(jf, len(self.code))
            self._stmt(node.otherwise)
            self._patch(j, len(self.code))
        else:
            self._patch(jf, len(self.code))

    def _while(self, node: While) -> None:
        top = len(self.code)
        self._expr(node.cond)
        jf = self._emit("JUMP_IF_FALSE")
        self._stmt(node.body)
        self._emit("JUMP", top)
        self._patch(jf, len(self.code))

    # -- expressions -----------------------------------------------------

    def _expr(self, node: object) -> None:
        if isinstance(node, Literal):
            self._emit("CONST", self._const(node.value))
        elif isinstance(node, Var):
            self._emit("LOAD", self._slot(node.name, node.offset))
        elif isinstance(node, UnaryOp):
            self._expr(node.operand)
            self._emit("NEG" if node.op == "-" else "NOT")
        elif isinstance(node, BinOp):
            if node.op == "and":
                self._logic(node, is_and=True)
            elif node.op == "or":
                self._logic(node, is_and=False)
            else:
                self._expr(node.left)
                self._expr(node.right)
                self._emit(_BIN_OPS[node.op])
        else:  # pragma: no cover - defensive
            raise CompileError(f"unknown expression {node!r}")

    def _logic(self, node: BinOp, *, is_and: bool) -> None:
        # JUMP_IF_FALSE type-checks each evaluated operand, preserving the
        # strict-bool rule for both sides of a short-circuit operator.
        true_k = self._const(True)
        false_k = self._const(False)
        self._expr(node.left)
        jf1 = self._emit("JUMP_IF_FALSE")
        if not is_and:
            self._emit("CONST", true_k)
            j_true = self._emit("JUMP")
            self._patch(jf1, len(self.code))
        self._expr(node.right)
        jf2 = self._emit("JUMP_IF_FALSE")
        self._emit("CONST", true_k)
        j_end = self._emit("JUMP")
        l_false = len(self.code)
        self._emit("CONST", false_k)
        self._patch(jf2, l_false)
        if is_and:
            self._patch(jf1, l_false)
        else:
            self._patch(j_true, len(self.code))
        self._patch(j_end, len(self.code))


def compile_source(src: str, *, optimize: bool = False) -> Program:
    """Compile ``src`` into a Program; optionally constant-fold the AST first."""
    tree = parse(src)
    if optimize:
        from .optimizer import fold_constants

        tree = fold_constants(tree)
    gen = _Compiler()
    gen._stmt(tree)
    gen._emit("HALT")
    return Program(gen.constants, gen.names, gen.code)
