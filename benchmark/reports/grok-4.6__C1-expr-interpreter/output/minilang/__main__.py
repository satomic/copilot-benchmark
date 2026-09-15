import sys

from minilang.errors import MiniLangError
from minilang.evaluator import evaluate
from minilang.builtins import format_value
from minilang.lexer import KEYWORDS


def _assignment(line: str):
    i = 0
    n = len(line)
    while i < n and line[i] in " \t":
        i += 1
    if i >= n or not (line[i].isalpha() or line[i] == "_"):
        return None
    start = i
    i += 1
    while i < n and (line[i].isalnum() or line[i] == "_"):
        i += 1
    name = line[start:i]
    if name in KEYWORDS:
        return None
    while i < n and line[i] in " \t":
        i += 1
    if i < n and line[i] == "=" and (i + 1 >= n or line[i + 1] != "="):
        return name, line[i + 1 :]
    return None


def main(argv=None) -> int:
    env = {}
    for line in sys.stdin:
        if line.endswith("\n"):
            line = line[:-1]
        if line.endswith("\r"):
            line = line[:-1]
        stripped = line.strip()
        if stripped == "":
            continue
        if stripped == ":quit":
            return 0
        if stripped == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue
        assign = _assignment(line)
        try:
            if assign is not None:
                name, expr_src = assign
                value = evaluate(expr_src, env)
                env[name] = value
            else:
                value = evaluate(line, env)
                print(format_value(value))
        except MiniLangError as exc:
            print(f"error: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
