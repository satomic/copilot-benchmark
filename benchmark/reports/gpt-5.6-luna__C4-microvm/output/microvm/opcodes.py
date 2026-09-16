OPCODES = ("CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD",
           "NEG", "NOT", "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP",
           "JUMP_IF_FALSE", "PRINT", "POP", "HALT")
OPCODE_NUMBERS = {name: index + 1 for index, name in enumerate(OPCODES)}
