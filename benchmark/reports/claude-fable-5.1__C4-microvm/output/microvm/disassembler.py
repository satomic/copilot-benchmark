"""Human-readable listing of a compiled program."""

from __future__ import annotations

from .compiler import Program
from .vm import render

_STRING_ESCAPES: dict[str, str] = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t"}


def render_constant(value: object) -> str:
    if isinstance(value, str):
        return '"' + "".join(_STRING_ESCAPES.get(ch, ch) for ch in value) + '"'
    return render(value)


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for index, instr in enumerate(program.instructions):
        line = f"{index:04d} {instr.op}"
        if instr.arg is not None:
            line += f" {instr.arg}"
        if instr.op == "CONST":
            line += f"  ; {render_constant(program.constants[instr.arg])}"
        lines.append(line + "\n")
    return "".join(lines)
