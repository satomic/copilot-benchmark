"""Opcode table for microvm bytecode."""

OPCODES: tuple[str, ...] = (
    "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
    "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
)

OPCODE_NUMBERS: dict[str, int] = {name: index + 1 for index, name in enumerate(OPCODES)}

# Opcodes that carry an argument; every other opcode has ``arg is None``.
ARG_OPCODES: frozenset[str] = frozenset({"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"})

# Source-level binary operators and the opcode implementing each one.
BINARY_OPCODES: dict[str, str] = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}

# Source-level unary operators and their opcodes.
UNARY_OPCODES: dict[str, str] = {"-": "NEG", "not": "NOT"}
