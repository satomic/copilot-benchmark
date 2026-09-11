import sys
import argparse
from . import compile_source, execute, dumps, loads, disassemble
from .errors import MicroVMError


def main(argv=None):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("file")
    run_parser.add_argument("--optimize", action="store_true")
    run_parser.add_argument("--step-limit", type=int, default=100_000)
    
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("file")
    build_parser.add_argument("out")
    build_parser.add_argument("--optimize", action="store_true")
    
    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument("file")
    exec_parser.add_argument("--step-limit", type=int, default=100_000)
    
    disasm_parser = subparsers.add_parser("disasm")
    disasm_parser.add_argument("file")
    
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    
    if args.command is None:
        parser.print_help()
        return 2
    
    try:
        if args.command == "run":
            try:
                with open(args.file, "r") as f:
                    src = f.read()
            except Exception:
                return 2
            if args.step_limit <= 0 or not isinstance(args.step_limit, int):
                return 2
            try:
                prog = compile_source(src, optimize=args.optimize)
                output = execute(prog, step_limit=args.step_limit)
                for line in output:
                    print(line)
                return 0
            except MicroVMError as e:
                print(str(e), file=sys.stderr)
                return 3
        elif args.command == "build":
            try:
                with open(args.file, "r") as f:
                    src = f.read()
            except Exception:
                return 2
            try:
                prog = compile_source(src, optimize=args.optimize)
                data = dumps(prog)
                with open(args.out, "wb") as f:
                    f.write(data)
                return 0
            except MicroVMError as e:
                print(str(e), file=sys.stderr)
                return 3
        elif args.command == "exec":
            try:
                with open(args.file, "rb") as f:
                    data = f.read()
            except Exception:
                return 2
            if args.step_limit <= 0 or not isinstance(args.step_limit, int):
                return 2
            try:
                prog = loads(data)
                output = execute(prog, step_limit=args.step_limit)
                for line in output:
                    print(line)
                return 0
            except MicroVMError as e:
                print(str(e), file=sys.stderr)
                return 3
        elif args.command == "disasm":
            try:
                with open(args.file, "rb") as f:
                    data = f.read()
            except Exception:
                return 2
            try:
                prog = loads(data)
                output = disassemble(prog)
                print(output, end="")
                return 0
            except MicroVMError as e:
                print(str(e), file=sys.stderr)
                return 3
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 3
    
    return 2


if __name__ == "__main__":
    sys.exit(main())
