import sys
from minilang import evaluate, parse, tokenize
from minilang.errors import MiniLangError, LexError, ParseError, EvalError


def _format_value(val: object) -> str:
    """Format a value for REPL output following rule 33."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float):
        if val == float("inf") or val == float("-inf") or val != val:
            return repr(val)
        if val == int(val) and abs(val) < 2 ** 53:
            # Integral number, no decimal part
            return str(int(val))
        s = repr(val)
        # Remove trailing zeros and possible trailing dot
        if "." in s:
            s = s.rstrip("0")
            if s.endswith("."):
                s = s[:-1]
        return s
    if isinstance(val, str):
        # Re-escape: wrap in double quotes, escape special chars
        escaped = (
            val.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\r", "\\r")
            .replace('"', '\\"')
        )
        return f'"{escaped}"'
    return repr(val)


def _repl():
    env: dict = {}
    for line_raw in sys.stdin:
        line = line_raw.rstrip("\n\r")

        # Blank or whitespace-only
        if not line.strip():
            continue

        # :quit
        if line.strip() == ":quit":
            sys.exit(0)

        # :vars
        if line.strip() == ":vars":
            if env:
                for name in sorted(env):
                    print(f"{name} = {_format_value(env[name])}")
            continue

        # <ident> = <expr> (a single '=' not followed by '=')
        stripped = line.strip()
        eq_pos = _find_assignment_eq(stripped)
        if eq_pos is not None:
            ident = stripped[:eq_pos].strip()
            expr_src = stripped[eq_pos + 1:].strip()
            if not ident:
                # Try to evaluate the whole line
                try:
                    result = evaluate(line, env)
                    print(_format_value(result))
                except MiniLangError as e:
                    print(f"error: {e}")
                continue
            # Validate identifier
            if not ident.isidentifier():
                print(f"error: invalid identifier: {ident!r}")
                continue
            try:
                result = evaluate(expr_src, env)
                env[ident] = result
            except MiniLangError as e:
                print(f"error: {e}")
            continue

        # Evaluate as expression
        try:
            result = evaluate(line, env)
            print(_format_value(result))
        except MiniLangError as e:
            print(f"error: {e}")


def _find_assignment_eq(s: str) -> int | None:
    """Find a single '=' that is not '==' and not inside parens at top level.
    
    We look for '=' that is not part of '==', and there's exactly one top-level '='.
    """
    depth = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '=' and depth == 0:
            # Check if this is '==' 
            if i + 1 < len(s) and s[i + 1] == '=':
                i += 2
                continue
            return i
        i += 1
    return None


if __name__ == "__main__":
    _repl()