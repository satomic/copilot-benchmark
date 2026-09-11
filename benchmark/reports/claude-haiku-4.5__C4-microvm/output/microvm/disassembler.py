from .compiler import Program


def disassemble(program: Program) -> str:
    lines = []
    for idx, instr in enumerate(program.instructions):
        line = f"{idx:04d} {instr.op}"
        if instr.arg is not None:
            line += f" {instr.arg}"
        if instr.op == "CONST":
            const = program.constants[instr.arg]
            const_str = format_const(const)
            line += f"  ; {const_str}"
        line += "\n"
        lines.append(line)
    return "".join(lines)


def format_const(val):
    if isinstance(val, bool):
        return "true" if val else "false"
    elif isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')
        return f'"{escaped}"'
    else:
        return str(val)
