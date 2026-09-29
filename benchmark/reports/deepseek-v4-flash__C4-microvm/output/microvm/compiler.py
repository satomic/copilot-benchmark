import dataclasses
from typing import Any

from microvm.parser import (
    parse, ProgramNode, LetNode, AssignNode, PrintNode, IfNode,
    WhileNode, BlockNode, BinaryOpNode, UnaryOpNode, LiteralNode, IdentNode,
)
from microvm.errors import CompileError


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


class Compiler:
    def __init__(self, optimize: bool = False) -> None:
        self.constants: list[Any] = []
        self.const_map: dict[tuple, int] = {}
        self.names: list[str] = []
        self.name_slots: dict[str, int] = {}
        self.declared: set[str] = set()
        self.instructions: list[Instr] = []
        self.pending_labels: dict[int, list[int]] = {}
        self.label_positions: dict[int, int] = {}
        self.next_label = 0
        self.optimize = optimize

    def add_constant(self, value: Any) -> int:
        key = (type(value).__name__, value)
        idx = self.const_map.get(key)
        if idx is not None:
            return idx
        idx = len(self.constants)
        self.constants.append(value)
        self.const_map[key] = idx
        return idx

    def get_name_slot(self, name: str) -> int:
        slot = self.name_slots.get(name)
        if slot is not None:
            return slot
        slot = len(self.names)
        self.names.append(name)
        self.name_slots[name] = slot
        return slot

    def declare_name(self, name: str, offset: int) -> int:
        if name in self.declared:
            raise CompileError(f"Duplicate declaration of '{name}'")
        self.declared.add(name)
        return self.get_name_slot(name)

    def fresh_label(self) -> int:
        lbl = self.next_label
        self.next_label += 1
        return lbl

    def emit(self, op: str, arg: int | None = None) -> None:
        self.instructions.append(Instr(op, arg))

    def emit_jump(self, op: str, label: int) -> None:
        idx = len(self.instructions)
        self.instructions.append(Instr(op, -label - 1))
        self.pending_labels.setdefault(label, []).append(idx)

    def mark_label(self, label: int) -> None:
        self.label_positions[label] = len(self.instructions)

    def compile_node(self, node: object) -> None:
            if isinstance(node, ProgramNode):
                for stmt in node.statements:
                    self.compile_node(stmt)
                self.emit("HALT")
            elif isinstance(node, LetNode):
                slot = self.declare_name(node.name, node.offset)
                self.compile_node(node.value)
                self.emit("STORE", slot)
            elif isinstance(node, AssignNode):
                if node.name not in self.declared:
                    raise CompileError(f"Undeclared variable '{node.name}'")
                slot = self.name_slots[node.name]
                self.compile_node(node.value)
                self.emit("STORE", slot)
            elif isinstance(node, PrintNode):
                self.compile_node(node.value)
                self.emit("PRINT")
            elif isinstance(node, IfNode):
                self._compile_if(node)
            elif isinstance(node, WhileNode):
                self._compile_while(node)
            elif isinstance(node, BlockNode):
                for stmt in node.statements:
                    self.compile_node(stmt)
            elif isinstance(node, BinaryOpNode):
                self._compile_binary(node)
            elif isinstance(node, UnaryOpNode):
                if node.op == "not":
                    self.compile_node(node.operand)
                    self.emit("NOT")
                elif node.op == "-":
                    self.compile_node(node.operand)
                    self.emit("NEG")
            elif isinstance(node, LiteralNode):
                idx = self.add_constant(node.value)
                self.emit("CONST", idx)
            elif isinstance(node, IdentNode):
                if node.name not in self.declared:
                    raise CompileError(f"Undeclared variable '{node.name}'")
                slot = self.name_slots[node.name]
                self.emit("LOAD", slot)

    def _compile_if(self, node: IfNode) -> None:
        else_label = self.fresh_label()
        end_label = self.fresh_label()
        self.compile_node(node.condition)
        self.emit_jump("JUMP_IF_FALSE", else_label)
        self.compile_node(node.then_branch)
        self.emit_jump("JUMP", end_label)
        self.mark_label(else_label)
        if node.else_branch is not None:
            self.compile_node(node.else_branch)
        self.mark_label(end_label)

    def _compile_while(self, node: WhileNode) -> None:
        cond_label = self.fresh_label()
        end_label = self.fresh_label()
        self.mark_label(cond_label)
        self.compile_node(node.condition)
        self.emit_jump("JUMP_IF_FALSE", end_label)
        self.compile_node(node.body)
        self.emit_jump("JUMP", cond_label)
        self.mark_label(end_label)

    def _compile_binary(self, node: BinaryOpNode) -> None:
        if node.op == "and":
            self._compile_and(node)
        elif node.op == "or":
            self._compile_or(node)
        else:
            self.compile_node(node.left)
            self.compile_node(node.right)
            op_map = {
                "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
                "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
            }
            self.emit(op_map[node.op])

    def _compile_and(self, node: BinaryOpNode) -> None:
        false_label = self.fresh_label()
        right_check = self.fresh_label()
        end_label = self.fresh_label()
        self.compile_node(node.left)
        self.emit_jump("JUMP_IF_FALSE", false_label)
        # stack empty, left was true -> eval right
        self.compile_node(node.right)
        # JUMP_IF_FALSE checks right is BOOL; if false -> right_check
        self.emit_jump("JUMP_IF_FALSE", right_check)
        # right was true, stack empty
        self.emit("CONST", self.add_constant(True))
        self.emit_jump("JUMP", end_label)
        self.mark_label(right_check)
        # right was false, stack empty
        self.emit("CONST", self.add_constant(False))
        self.emit_jump("JUMP", end_label)
        self.mark_label(false_label)
        # left was false, stack empty
        self.emit("CONST", self.add_constant(False))
        self.mark_label(end_label)

    def _compile_or(self, node: BinaryOpNode) -> None:
        right_label = self.fresh_label()
        right_check = self.fresh_label()
        end_label = self.fresh_label()
        self.compile_node(node.left)
        self.emit_jump("JUMP_IF_FALSE", right_label)
        # stack empty, left was true -> push true
        self.emit("CONST", self.add_constant(True))
        self.emit_jump("JUMP", end_label)
        self.mark_label(right_label)
        # stack empty, left was false -> eval right
        self.compile_node(node.right)
        # JUMP_IF_FALSE checks right is BOOL; if false -> right_check
        self.emit_jump("JUMP_IF_FALSE", right_check)
        self.emit("CONST", self.add_constant(True))
        self.emit_jump("JUMP", end_label)
        self.mark_label(right_check)
        self.emit("CONST", self.add_constant(False))
        self.mark_label(end_label)

    def resolve_labels(self) -> None:
        for label, instr_indices in self.pending_labels.items():
            target = self.label_positions.get(label)
            if target is None:
                continue
            for idx in instr_indices:
                instr = self.instructions[idx]
                self.instructions[idx] = Instr(instr.op, target)


def compile_source(src: str, *, optimize: bool = False) -> Program:
    from microvm.optimizer import fold_constants
    ast = parse(src)
    if optimize:
        ast = fold_constants(ast)
    compiler = Compiler()
    compiler.compile_node(ast)
    compiler.resolve_labels()
    return Program(
        constants=list(compiler.constants),
        names=list(compiler.names),
        instructions=list(compiler.instructions),
    )