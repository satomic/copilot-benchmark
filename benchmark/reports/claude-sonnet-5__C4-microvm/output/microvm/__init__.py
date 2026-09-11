"""microvm: a small imperative language compiler, optimizer and stack VM."""

from .compiler import Instr, Program, compile_source
from .disassembler import disassemble
from .errors import (
    CompileError,
    LexError,
    MicroVMError,
    ParseError,
    SerializationError,
    VMRuntimeError,
)
from .lexer import Token, tokenize
from .opcodes import OPCODE_NUMBERS, OPCODES
from .optimizer import fold_constants
from .parser import parse
from .serializer import dumps, loads
from .vm import execute

__all__ = [
    "tokenize",
    "Token",
    "parse",
    "compile_source",
    "Program",
    "Instr",
    "fold_constants",
    "execute",
    "dumps",
    "loads",
    "disassemble",
    "OPCODES",
    "OPCODE_NUMBERS",
    "MicroVMError",
    "LexError",
    "ParseError",
    "CompileError",
    "SerializationError",
    "VMRuntimeError",
]
