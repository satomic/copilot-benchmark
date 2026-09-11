"""Opcode definitions for the microvm bytecode."""

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

# Opcodes that carry an integer argument; all others take no argument.
OPCODES_WITH_ARG: frozenset[str] = frozenset({"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"})
