"""Opcode table shared by the compiler, VM, serializer and disassembler."""

OPCODES: tuple[str, ...] = (
    "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
    "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
)

OPCODE_NUMBERS: dict[str, int] = {name: index + 1 for index, name in enumerate(OPCODES)}

OPCODES_WITH_ARG: frozenset[str] = frozenset({"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"})
