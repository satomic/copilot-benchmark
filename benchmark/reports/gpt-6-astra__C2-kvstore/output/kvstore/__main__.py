import argparse
import sys
from dataclasses import fields

from . import CorruptSegmentError, KVStore, compact


def _segment_limit(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer >= 16") from exc
    if value < 16:
        raise argparse.ArgumentTypeError("must be an integer >= 16")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore")
    parser.add_argument("--max-segment-bytes", type=_segment_limit, default=4096)
    parser.add_argument("root")
    commands = parser.add_subparsers(dest="command", required=True)
    setter = commands.add_parser("set")
    setter.add_argument("key")
    setter.add_argument("value")
    for name in ("get", "delete"):
        commands.add_parser(name).add_argument("key")
    for name in ("list", "compact", "stats"):
        commands.add_parser(name)
    return parser


def _run(store: KVStore, args: argparse.Namespace) -> int:
    if args.command == "set":
        store.set(args.key, args.value)
    elif args.command == "get":
        value = store.get(args.key)
        if value is None:
            return 1
        print(value)
    elif args.command == "delete":
        return 0 if store.delete(args.key) else 1
    elif args.command == "list":
        keys = store.keys()
        if keys:
            print("\n".join(keys))
    elif args.command == "compact":
        result = compact(store)
        print(
            f"removed={result.segments_removed} written={result.records_written} "
            f"dropped={result.records_dropped} reclaimed={result.bytes_reclaimed}"
        )
    elif args.command == "stats":
        stats = store.stats()
        print(" ".join(f"{field.name}={getattr(stats, field.name)}" for field in fields(stats)))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            return _run(store, args)
    except CorruptSegmentError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
