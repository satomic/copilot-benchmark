import sys
import argparse
import io

from microvm.errors import MicroVMError
from microvm.compiler import compile_source
from microvm.serializer import dumps, loads
from microvm.disassembler import disassemble
from microvm.vm import execute


def _read_src(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _read_bin(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _check_step_limit(val: int) -> None:
    if isinstance(val, bool) or val <= 0:
        print("Error: --step-limit must be a positive integer", file=sys.stderr)
        sys.exit(2)


def _print_output(output: list[str]) -> None:
    sys.stdout.write("\n".join(output))
    if output:
        sys.stdout.write("\n")


def cmd_run(args: argparse.Namespace) -> int:
    try:
        src = _read_src(args.file)
    except (FileNotFoundError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    _check_step_limit(args.step_limit)
    program = compile_source(src, optimize=args.optimize)
    output = execute(program, step_limit=args.step_limit)
    _print_output(output)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    try:
        src = _read_src(args.file)
    except (FileNotFoundError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    program = compile_source(src, optimize=args.optimize)
    data = dumps(program)
    try:
        with open(args.out, "wb") as f:
            f.write(data)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    try:
        data = _read_bin(args.file)
    except (FileNotFoundError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    _check_step_limit(args.step_limit)
    program = loads(data)
    output = execute(program, step_limit=args.step_limit)
    _print_output(output)
    return 0


def cmd_disasm(args: argparse.Namespace) -> int:
    try:
        data = _read_bin(args.file)
    except (FileNotFoundError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    program = loads(data)
    sys.stdout.write(disassemble(program))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m microvm")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    run_p = sub.add_parser("run")
    run_p.add_argument("file")
    run_p.add_argument("--optimize", action="store_true")
    run_p.add_argument("--step-limit", type=int, default=100_000)

    build_p = sub.add_parser("build")
    build_p.add_argument("file")
    build_p.add_argument("out")
    build_p.add_argument("--optimize", action="store_true")

    exec_p = sub.add_parser("exec")
    exec_p.add_argument("file")
    exec_p.add_argument("--step-limit", type=int, default=100_000)

    disasm_p = sub.add_parser("disasm")
    disasm_p.add_argument("file")

    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            return cmd_run(args)
        elif args.command == "build":
            return cmd_build(args)
        elif args.command == "exec":
            return cmd_exec(args)
        elif args.command == "disasm":
            return cmd_disasm(args)
        return 0
    except MicroVMError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    except (FileNotFoundError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())