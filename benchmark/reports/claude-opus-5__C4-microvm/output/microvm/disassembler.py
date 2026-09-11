"""Human readable rendering of compiled programs."""

from __future__ import annotations

from .compiler import Instr, Program

_STRING_ESCAPES: tuple[tuple[str, str], ...] = (
    ("\\", "\\\\"),
    ('"', '\\"'),
    ("\n", "\\n"),
    ("\t", "\\t"),
)


def render_constant(value: object) -> str:
    """Render a constant the way the disassembly listing shows it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        text = value
        for raw, escaped in _STRING_ESCAPES:
            text = text.replace(raw, escaped)
        return f'"{text}"'
    return str(value)


def _line(index: int, instr: Instr, constants: list) -> str:
    if instr.arg is None:
        return f"{index:04d} {instr.op}"
    head = f"{index:04d} {instr.op} {instr.arg}"
    if instr.op == "CONST" and 0 <= instr.arg < len(constants):
        return f"{head}  ; {render_constant(constants[instr.arg])}"
    return head


def disassemble(program: Program) -> str:
    """Return the full disassembly listing, one ``\\n`` terminated line each."""
    return "".join(
        _line(index, instr, program.constants) + "\n"
        for index, instr in enumerate(program.instructions)
    )
