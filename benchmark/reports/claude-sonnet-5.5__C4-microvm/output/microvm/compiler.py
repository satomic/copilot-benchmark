"""AST -> bytecode compiler."""

import dataclasses

from .errors import CompileError
from .optimizer import fold_constants
from .opcodes import BINARY_OPCODES
from .parser import parse


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


def _const_key(value: object) -> tuple:
    # Floats keyed by repr so 0.0 / -0.0 (and NaNs) stay distinct and stable.
    return (type(value), repr(value) if type(value) is float else value)


class _Generator:
    def __init__(self) -> None:
        self.constants: list = []
        self.const_index: dict[tuple, int] = {}
        self.names: list[str] = []
        self.slots: dict[str, int] = {}
        self.code: list[Instr] = []

    def emit(self, op: str, arg: int | None = None) -> int:
        self.code.append(Instr(op, arg))
        return len(self.code) - 1

    def patch(self, at: int, target: int) -> None:
        self.code[at] = Instr(self.code[at].op, target)

    def here(self) -> int:
        return len(self.code)

    def const(self, value: object) -> int:
        key = _const_key(value)
        if key not in self.const_index:
            self.const_index[key] = len(self.constants)
            self.constants.append(value)
        return self.const_index[key]

    def slot_of(self, name: str) -> int:
        if name not in self.slots:
            raise CompileError(f"undeclared variable {name!r}")
        return self.slots[name]

    # statements
    def stmt(self, node: tuple) -> None:
        getattr(self, "s_" + node[0])(node)

    def s_program(self, node: tuple) -> None:
        for child in node[1]:
            self.stmt(child)

    s_block = s_program

    def s_let(self, node: tuple) -> None:
        self.expr(node[2])
        if node[1] in self.slots:
            raise CompileError(f"variable {node[1]!r} already declared")
        self.slots[node[1]] = len(self.names)
        self.names.append(node[1])
        self.emit("STORE", self.slots[node[1]])

    def s_assign(self, node: tuple) -> None:
        slot = self.slot_of(node[1])
        self.expr(node[2])
        self.emit("STORE", slot)

    def s_print(self, node: tuple) -> None:
        self.expr(node[1])
        self.emit("PRINT")

    def s_if(self, node: tuple) -> None:
        self.expr(node[1])
        to_else = self.emit("JUMP_IF_FALSE", 0)
        self.stmt(node[2])
        if node[3] is None:
            self.patch(to_else, self.here())
            return
        to_end = self.emit("JUMP", 0)
        self.patch(to_else, self.here())
        self.stmt(node[3])
        self.patch(to_end, self.here())

    def s_while(self, node: tuple) -> None:
        start = self.here()
        self.expr(node[1])
        to_end = self.emit("JUMP_IF_FALSE", 0)
        self.stmt(node[2])
        self.emit("JUMP", start)
        self.patch(to_end, self.here())

    # expressions
    def expr(self, node: tuple) -> None:
        getattr(self, "e_" + node[0])(node)

    def e_lit(self, node: tuple) -> None:
        self.emit("CONST", self.const(node[1]))

    def e_var(self, node: tuple) -> None:
        self.emit("LOAD", self.slot_of(node[1]))

    def e_un(self, node: tuple) -> None:
        self.expr(node[2])
        self.emit("NEG")

    def e_not(self, node: tuple) -> None:
        self.expr(node[1])
        self.emit("NOT")

    def e_bin(self, node: tuple) -> None:
        self.expr(node[2])
        self.expr(node[3])
        self.emit(BINARY_OPCODES[node[1]])

    def e_and(self, node: tuple) -> None:
        # l; JIF F; r; JIF F; CONST true; JUMP end; F: CONST false; end:
        self.expr(node[1])
        first = self.emit("JUMP_IF_FALSE", 0)
        self.expr(node[2])
        second = self.emit("JUMP_IF_FALSE", 0)
        self.finish_logic([first, second])

    def e_or(self, node: tuple) -> None:
        # l; NOT; JIF T; r; JIF F; T: CONST true; JUMP end; F: CONST false; end:
        # NOT enforces that l is BOOL; JIF then enforces it for r.
        self.expr(node[1])
        self.emit("NOT")
        to_true = self.emit("JUMP_IF_FALSE", 0)
        self.expr(node[2])
        to_false = self.emit("JUMP_IF_FALSE", 0)
        self.patch(to_true, self.here())
        self.emit("CONST", self.const(True))
        to_end = self.emit("JUMP", 0)
        self.patch(to_false, self.here())
        self.emit("CONST", self.const(False))
        self.patch(to_end, self.here())

    def finish_logic(self, false_jumps: list[int]) -> None:
        self.emit("CONST", self.const(True))
        to_end = self.emit("JUMP", 0)
        for at in false_jumps:
            self.patch(at, self.here())
        self.emit("CONST", self.const(False))
        self.patch(to_end, self.here())


def compile_source(src: str, *, optimize: bool = False) -> Program:
    tree = parse(src)
    if optimize:
        tree = fold_constants(tree)
    gen = _Generator()
    try:
        gen.stmt(tree)  # type: ignore[arg-type]
    except RecursionError:
        raise CompileError("program nesting too deep") from None
    gen.emit("HALT")
    return Program(gen.constants, gen.names, gen.code)
