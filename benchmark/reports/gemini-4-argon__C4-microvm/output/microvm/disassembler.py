from __future__ import annotations

from microvm.compiler import Program


def _format_const(val: object) -> str:
    if type(val) is bool:
        return "true" if val else "false"
    if type(val) in (int, float):
        return str(val)
    if type(val) is str:
        escaped = (
            val.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    return str(val)


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for idx, ins in enumerate(program.instructions):
        if ins.arg is None:
            lines.append(f"{idx:04d} {ins.op}\n")
        elif ins.op == "CONST":
            c_str = _format_const(program.constants[ins.arg])
            lines.append(f"{idx:04d} {ins.op} {ins.arg}  ; {c_str}\n")
        else:
            lines.append(f"{idx:04d} {ins.op} {ins.arg}\n")
    return "".join(lines)
