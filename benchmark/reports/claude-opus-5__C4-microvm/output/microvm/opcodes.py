"""The fixed opcode table of the micro virtual machine."""

from __future__ import annotations

OPCODES: tuple[str, ...] = (
    "CONST",
    "LOAD",
    "STORE",
    "ADD",
    "SUB",
    "MUL",
    "DIV",
    "MOD",
    "NEG",
    "NOT",
    "EQ",
    "NE",
    "LT",
    "LE",
    "GT",
    "GE",
    "JUMP",
    "JUMP_IF_FALSE",
    "PRINT",
    "POP",
    "HALT",
)

OPCODE_NUMBERS: dict[str, int] = {name: index + 1 for index, name in enumerate(OPCODES)}

#: Opcodes that carry an integer argument; every other opcode has ``arg is None``.
ARGUMENT_OPCODES: frozenset[str] = frozenset(
    {"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"}
)


def has_argument(op: str) -> bool:
    """Return whether *op* takes an argument."""
    return op in ARGUMENT_OPCODES
