import re
import sys

from .builtins import format_number
from .errors import MiniLangError
from .evaluator import evaluate


_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$")


def _format(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return format_number(value)
    if type(value) is str:
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\r", "\\r")
        )
        return f'"{escaped}"'
    raise TypeError("unsupported value")


def main() -> int:
    environment: dict[str, object] = {}
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == ":quit":
            return 0
        if stripped == ":vars":
            for name in sorted(environment):
                print(f"{name} = {_format(environment[name])}")
            continue
        try:
            assignment = _ASSIGNMENT.match(line)
            if assignment is not None:
                name, source = assignment.groups()
                value = evaluate(source, environment)
                environment[name] = value
            else:
                print(_format(evaluate(line, environment)))
        except MiniLangError as error:
            print(f"error: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
