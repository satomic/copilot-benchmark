from .lexer import tokenize, Token
from .parser import parse
from .compiler import compile_source, Program, Instr
from .optimizer import fold_constants
from .vm import execute
from .serializer import dumps, loads
from .disassembler import disassemble
from .opcodes import OPCODES, OPCODE_NUMBERS
from .errors import (
    MicroVMError, LexError, ParseError, CompileError,
    SerializationError, VMRuntimeError
)

__all__ = [
    "tokenize", "Token", "parse", "compile_source", "Program", "Instr",
    "fold_constants", "execute", "dumps", "loads", "disassemble",
    "OPCODES", "OPCODE_NUMBERS",
    "MicroVMError", "LexError", "ParseError", "CompileError",
    "SerializationError", "VMRuntimeError"
]
