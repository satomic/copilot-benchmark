"""Human-readable listing of compiled Programs."""

from __future__ import annotations

from .compiler import Instr, Program


def disassemble(program: Program) -> str:
    """Return one line per instruction, each terminated by a newline."""
    return "".join(
        _format_line(index, instr, program)
        for index, instr in enumerate(program.instructions)
    )


def _format_line(index: int, instr: Instr, program: Program) -> str:
    text = f"{index:04d} {instr.op}"
    if instr.arg is None:
        return text + "\n"
    text += f" {instr.arg}"
    if instr.op == "CONST":
        text += "  ; " + _render_constant(program, instr.arg)
    return text + "\n"


def _render_constant(program: Program, index: int) -> str:
    if not 0 <= index < len(program.constants):
        return "<invalid constant>"
    value = program.constants[index]
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        return '"' + _escape(value) + '"'
    return str(value)


def _escape(text: str) -> str:
    replacements = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t"}
    return "".join(replacements.get(ch, ch) for ch in text)
