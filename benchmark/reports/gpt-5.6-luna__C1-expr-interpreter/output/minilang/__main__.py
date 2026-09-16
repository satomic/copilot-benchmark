import re
import sys
from . import evaluate
from .builtins import format_number
from .errors import MiniLangError


def format_value(value):
    if type(value) is float: return format_number(value)
    if type(value) is bool: return "true" if value else "false"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    escaped = escaped.replace("\t", "\\t").replace("\r", "\\r")
    return '"' + escaped + '"'


def main():
    env = {}
    for line in sys.stdin:
        text = line.rstrip("\r\n")
        if not text.strip(): continue
        if text.strip() == ":quit": return 0
        if text.strip() == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue
        assignment = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$", text)
        old = dict(env)
        try:
            if assignment:
                env[assignment.group(1)] = evaluate(assignment.group(2), env)
            else:
                print(format_value(evaluate(text, env)))
        except MiniLangError as error:
            env = old
            print(f"error: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
