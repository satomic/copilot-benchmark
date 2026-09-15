"""MiniLang REPL."""

import re
import sys
from .errors import MiniLangError
from .evaluator import evaluate

ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)\s*(.*)$")
KEYWORDS = {"true", "false", "and", "or", "not"}


def format_repl_string(s: str) -> str:
    """Format a string with double quotes and re-escaped contents."""
    out: list[str] = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def format_repl_value(val: object) -> str:
    """Format any MiniLang value for REPL output."""
    if type(val) is bool:
        return "true" if val else "false"
    elif type(val) is float:
        if val.is_integer():
            return str(int(val))
        return repr(val)
    elif type(val) is str:
        return format_repl_string(val)
    else:
        return repr(val)


def main() -> None:
    env: dict[str, object] = {}
    for line in sys.stdin:
        line = line.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == ":quit":
            sys.exit(0)
        if stripped == ":vars":
            for k in sorted(env.keys()):
                print(f"{k} = {format_repl_value(env[k])}")
            continue

        # Check variable assignment
        m = ASSIGN_RE.match(line)
        if m and m.group(1) not in KEYWORDS:
            ident = m.group(1)
            expr_str = m.group(2)
            try:
                val = evaluate(expr_str, env)
                env[ident] = val
            except MiniLangError as e:
                print(f"error: {e}")
            continue

        # Evaluate expression
        try:
            val = evaluate(line, env)
            print(format_repl_value(val))
        except MiniLangError as e:
            print(f"error: {e}")

    sys.exit(0)


if __name__ == "__main__":
    main()
