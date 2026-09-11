"""Disassembler: Program -> human readable text."""

from .compiler import Program
from .opcodes import OPCODES_WITH_ARG


def _escape_string(value: str) -> str:
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _render_const(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, str):
        return _escape_string(value)
    return str(value)


def disassemble(program: Program) -> str:
    lines = []
    for index, instr in enumerate(program.instructions):
        line = f"{index:04d} {instr.op}"
        if instr.op in OPCODES_WITH_ARG:
            line += f" {instr.arg}"
        if instr.op == "CONST":
            line += f"  ; {_render_const(program.constants[instr.arg])}"
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")
