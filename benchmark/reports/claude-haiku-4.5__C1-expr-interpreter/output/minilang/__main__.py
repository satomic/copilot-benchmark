import sys
from . import evaluate, MiniLangError


def format_value(value):
    """Format a value for display in the REPL."""
    if isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return repr(value)
    elif isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
        return f'"{escaped}"'
    return str(value)


def main():
    """Run the minilang REPL."""
    env = {}
    
    while True:
        try:
            line = input()
        except EOFError:
            break
        
        if not line or line.isspace():
            continue
        
        if line == ":quit":
            break
        
        if line == ":vars":
            for name in sorted(env.keys()):
                print(f"{name} = {format_value(env[name])}")
            continue
        
        if "=" in line and not "==" in line:
            parts = line.split("=", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                if name.isidentifier():
                    expr_str = parts[1].strip()
                    try:
                        result = evaluate(expr_str, env)
                        env = dict(env)
                        env[name] = result
                        continue
                    except MiniLangError as e:
                        print(f"error: {e}")
                        continue
        
        try:
            result = evaluate(line, env)
            print(format_value(result))
        except MiniLangError as e:
            print(f"error: {e}")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
