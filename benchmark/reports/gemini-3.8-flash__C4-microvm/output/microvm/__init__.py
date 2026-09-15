"""microvm: A Bytecode Compiler and Stack Virtual Machine."""

from microvm.compiler import Instr, Program, compile_source
from microvm.disassembler import disassemble
from microvm.errors import (
    CompileError,
    LexError,
    MicroVMError,
    ParseError,
    SerializationError,
    VMRuntimeError,
)
from microvm.lexer import Token, tokenize
from microvm.opcodes import OPCODE_NUMBERS, OPCODES
from microvm.optimizer import fold_constants
from microvm.parser import parse
from microvm.serializer import dumps, loads
from microvm.vm import execute

__all__: list[str] = [
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
