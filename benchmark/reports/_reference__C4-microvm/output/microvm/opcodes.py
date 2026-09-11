"""The instruction set. Exactly these opcodes, numbered from 1 in this order."""

from __future__ import annotations

__all__ = ["OPCODES", "OPCODE_NUMBERS", "HAS_ARG"]

OPCODES: tuple[str, ...] = (
    "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
    "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
)

OPCODE_NUMBERS: dict[str, int] = {name: index + 1 for index, name in enumerate(OPCODES)}

#: The opcodes that carry an argument. Everything else must have arg None.
HAS_ARG: frozenset[str] = frozenset({"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"})
