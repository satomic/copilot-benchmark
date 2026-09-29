"""Human-readable listing of compiled programs."""

from __future__ import annotations

from .compiler import Program

_STRING_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t"}


def render_constant(value: object) -> str:
    """Render a constant as it appears in a disassembly listing."""
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        return '"' + "".join(_STRING_ESCAPES.get(ch, ch) for ch in value) + '"'
    return str(value)


def disassemble(program: Program) -> str:
    """Return one ``NNNN OP [arg]`` line per instruction."""
    lines = []
    for index, instr in enumerate(program.instructions):
        if instr.arg is None:
            line = f"{index:04d} {instr.op}"
        else:
            line = f"{index:04d} {instr.op} {instr.arg}"
        if instr.op == "CONST":
            if type(instr.arg) is int and 0 <= instr.arg < len(program.constants):
                line += "  ; " + render_constant(program.constants[instr.arg])
            else:
                line += "  ; <invalid constant>"
        lines.append(line + "\n")
    return "".join(lines)
