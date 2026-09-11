"""Canonical text rendering of a compiled program."""

from __future__ import annotations

from .compiler import Program
from .vm import render

__all__ = ["disassemble"]

_STRING_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t"}


def _constant_comment(value: object) -> str:
    if isinstance(value, str):
        escaped = "".join(_STRING_ESCAPES.get(ch, ch) for ch in value)
        return f'"{escaped}"'
    return render(value)


def disassemble(program: Program) -> str:
    """One line per instruction, each terminated by a newline."""
    lines = []
    for index, instr in enumerate(program.instructions):
        line = f"{index:04d} {instr.op}"
        if instr.arg is not None:
            line += f" {instr.arg}"
        if instr.op == "CONST":
            line += f"  ; {_constant_comment(program.constants[instr.arg])}"
        lines.append(line)
    return "".join(line + "\n" for line in lines)
