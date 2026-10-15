from __future__ import annotations

import argparse
import sys
from microvm.compiler import compile_source
from microvm.disassembler import disassemble
from microvm.errors import MicroVMError
from microvm.serializer import dumps, loads
from microvm.vm import execute


class _CLIArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _positive_int(val: str) -> int:
    try:
        n = int(val)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("step-limit must be an integer") from exc
    if n <= 0:
        raise argparse.ArgumentTypeError("step-limit must be positive")
    return n


def _build_parser() -> argparse.ArgumentParser:
    parser = _CLIArgumentParser(prog="microvm", add_help=False)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", add_help=False)
    p_run.add_argument("file")
    p_run.add_argument("--optimize", action="store_true")
    p_run.add_argument("--step-limit", type=_positive_int, default=100_000)

    p_build = sub.add_parser("build", add_help=False)
    p_build.add_argument("file")
    p_build.add_argument("out")
    p_build.add_argument("--optimize", action="store_true")

    p_exec = sub.add_parser("exec", add_help=False)
    p_exec.add_argument("file")
    p_exec.add_argument("--step-limit", type=_positive_int, default=100_000)

    p_disasm = sub.add_parser("disasm", add_help=False)
    p_disasm.add_argument("file")

    return parser


def _run_cmd(ns: argparse.Namespace) -> int:
    try:
        with open(ns.file, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        return 2
    prog = compile_source(src, optimize=ns.optimize)
    lines = execute(prog, step_limit=ns.step_limit)
    for line in lines:
        print(line)
    return 0


def _build_cmd(ns: argparse.Namespace) -> int:
    try:
        with open(ns.file, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        return 2
    prog = compile_source(src, optimize=ns.optimize)
    data = dumps(prog)
    try:
        with open(ns.out, "wb") as f:
            f.write(data)
    except OSError as exc:
        print(f"Error writing file: {exc}", file=sys.stderr)
        return 2
    return 0


def _exec_cmd(ns: argparse.Namespace) -> int:
    try:
        with open(ns.file, "rb") as f:
            data = f.read()
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        return 2
    prog = loads(data)
    lines = execute(prog, step_limit=ns.step_limit)
    for line in lines:
        print(line)
    return 0


def _disasm_cmd(ns: argparse.Namespace) -> int:
    try:
        with open(ns.file, "rb") as f:
            data = f.read()
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        return 2
    prog = loads(data)
    sys.stdout.write(disassemble(prog))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        ns = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except (ValueError, SystemExit) as exc:
        print(f"Usage error: {exc}", file=sys.stderr)
        return 2

    try:
        if ns.command == "run":
            return _run_cmd(ns)
        if ns.command == "build":
            return _build_cmd(ns)
        if ns.command == "exec":
            return _exec_cmd(ns)
        if ns.command == "disasm":
            return _disasm_cmd(ns)
    except MicroVMError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
