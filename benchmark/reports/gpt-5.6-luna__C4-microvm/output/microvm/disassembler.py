from .compiler import Program


def _render(value: object) -> str:
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"') + '"'
    return str(value)


def disassemble(program: Program) -> str:
    lines = []
    takes = {"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"}
    for i, ins in enumerate(program.instructions):
        line = f"{i:04d} {ins.op}"
        if ins.op in takes:
            line += f" {ins.arg}"
            if ins.op == "CONST": line += "  ; " + _render(program.constants[ins.arg])
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")
