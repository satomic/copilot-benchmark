import argparse
import sys
from . import compile_source, execute, dumps, loads, disassemble
from .errors import MicroVMError


def _positive(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("step limit must be positive") from exc
    if n <= 0:
        raise argparse.ArgumentTypeError("step limit must be positive")
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="microvm")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("file"); run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive, default=100000)
    build = sub.add_parser("build")
    build.add_argument("file"); build.add_argument("out"); build.add_argument("--optimize", action="store_true")
    ex = sub.add_parser("exec"); ex.add_argument("file"); ex.add_argument("--step-limit", type=_positive, default=100000)
    dis = sub.add_parser("disasm"); dis.add_argument("file")
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:
            return int(exc.code)
        if args.command == "run":
            with open(args.file, encoding="utf-8") as f:
                out = execute(compile_source(f.read(), optimize=args.optimize), step_limit=args.step_limit)
            print("\n".join(out))
        elif args.command == "build":
            with open(args.file, encoding="utf-8") as f:
                data = dumps(compile_source(f.read(), optimize=args.optimize))
            with open(args.out, "wb") as f: f.write(data)
        elif args.command == "exec":
            with open(args.file, "rb") as f: out = execute(loads(f.read()), step_limit=args.step_limit)
            print("\n".join(out))
        else:
            with open(args.file, "rb") as f: text = disassemble(loads(f.read()))
            sys.stdout.write(text)
        return 0
    except (OSError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr); return 2
    except MicroVMError as exc:
        print(str(exc), file=sys.stderr); return 3


if __name__ == "__main__":
    sys.exit(main())
