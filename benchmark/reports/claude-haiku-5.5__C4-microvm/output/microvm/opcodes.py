"""Opcode table for the MicroVM bytecode."""

OPCODES: tuple[str, ...] = (
    "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
    "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
)

OPCODE_NUMBERS: dict[str, int] = {name: index + 1 for index, name in enumerate(OPCODES)}

# Opcodes whose instruction carries an argument; all others carry none.
ARGUMENT_OPCODES: frozenset[str] = frozenset({"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"})
