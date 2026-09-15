"""Command-line interface for microvm."""

import argparse
import sys
from microvm.compiler import compile_source
from microvm.disassembler import disassemble
from microvm.errors import MicroVMError
from microvm.serializer import dumps, loads
from microvm.vm import execute


class UsageError(Exception):
    """Command-line usage error."""


class _CustomParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def _build_parser() -> _CustomParser:
    parser = _CustomParser(prog="microvm")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_p = subparsers.add_parser("run")
    run_p.add_argument("file", help="Source file path")
    run_p.add_argument("--optimize", action="store_true", help="Enable constant folding")
    run_p.add_argument("--step-limit", type=int, default=100_000, help="Step execution limit")

    build_p = subparsers.add_parser("build")
    build_p.add_argument("file", help="Source file path")
    build_p.add_argument("out", help="Output binary file path")
    build_p.add_argument("--optimize", action="store_true", help="Enable constant folding")

    exec_p = subparsers.add_parser("exec")
    exec_p.add_argument("file", help="Binary file path")
    exec_p.add_argument("--step-limit", type=int, default=100_000, help="Step execution limit")

    disasm_p = subparsers.add_parser("disasm")
    disasm_p.add_argument("file", help="Binary file path")

    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    if args.step_limit <= 0:
        raise UsageError("--step-limit must be a positive integer")
    try:
        with open(args.file, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as exc:
        raise UsageError(f"Cannot read file '{args.file}': {exc}") from exc
    prog = compile_source(src, optimize=args.optimize)
    output = execute(prog, step_limit=args.step_limit)
    for line in output:
        sys.stdout.write(line + "\n")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        with open(args.file, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as exc:
        raise UsageError(f"Cannot read file '{args.file}': {exc}") from exc
    prog = compile_source(src, optimize=args.optimize)
    data = dumps(prog)
    try:
        with open(args.out, "wb") as f:
            f.write(data)
    except OSError as exc:
        raise UsageError(f"Cannot write file '{args.out}': {exc}") from exc
    return 0


def _cmd_exec(args: argparse.Namespace) -> int:
    if args.step_limit <= 0:
        raise UsageError("--step-limit must be a positive integer")
    try:
        with open(args.file, "rb") as f:
            data = f.read()
    except OSError as exc:
        raise UsageError(f"Cannot read file '{args.file}': {exc}") from exc
    prog = loads(data)
    output = execute(prog, step_limit=args.step_limit)
    for line in output:
        sys.stdout.write(line + "\n")
    return 0


def _cmd_disasm(args: argparse.Namespace) -> int:
    try:
        with open(args.file, "rb") as f:
            data = f.read()
    except OSError as exc:
        raise UsageError(f"Cannot read file '{args.file}': {exc}") from exc
    prog = loads(data)
    text = disassemble(prog)
    sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "build":
            return _cmd_build(args)
        if args.command == "exec":
            return _cmd_exec(args)
        if args.command == "disasm":
            return _cmd_disasm(args)
        raise UsageError(f"Unknown command {args.command}")
    except UsageError as exc:
        sys.stderr.write(f"Usage error: {exc}\n")
        return 2
    except MicroVMError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 3


if __name__ == "__main__":
    sys.exit(main())
