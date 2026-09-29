from microvm.compiler import Program


def _escape_str(s: str) -> str:
    """Escape a string for disassembly: \n, \t, \", \\."""
    result = s.replace("\\", "\\\\")
    result = result.replace("\n", "\\n")
    result = result.replace("\t", "\\t")
    result = result.replace('"', '\\"')
    return result


def _format_const(val: object) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float):
        return str(val)
    if isinstance(val, str):
        return f'"{_escape_str(val)}"'
    return str(val)


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for idx, instr in enumerate(program.instructions):
        op = instr.op
        arg = instr.arg
        prefix = f"{idx:04d} {op}"
        if arg is not None:
            if op == "CONST":
                val = program.constants[arg]
                lines.append(f"{prefix} {arg}  ; {_format_const(val)}\n")
            else:
                lines.append(f"{prefix} {arg}\n")
        else:
            lines.append(f"{prefix}\n")
    return "".join(lines)