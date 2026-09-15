from __future__ import annotations

from microvm.compiler import Program


def disassemble(program: Program) -> str:
    lines = [_format_instr(program, index, instr) for index, instr in enumerate(program.instructions)]
    return "".join(lines)


def _format_instr(program: Program, index: int, instr: object) -> str:
    op = instr.op  # type: ignore[attr-defined]
    arg = instr.arg  # type: ignore[attr-defined]
    if arg is None:
        return f"{index:04d} {op}\n"
    line = f"{index:04d} {op} {arg}"
    if op == "CONST":
        line += f"  ; {_render_const(program.constants[arg])}"
    return line + "\n"


def _render_const(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        return '"' + _escape_string(value) + '"'
    return str(value)


def _escape_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )
