import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kvstore")
    parser.add_argument("--max-segment-bytes", type=int, default=4096)
    parser.add_argument("root")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, args in (("set", ("KEY", "VALUE")), ("get", ("KEY",)),
                       ("delete", ("KEY",))):
        command = sub.add_parser(name)
        for arg in args:
            command.add_argument(arg)
    sub.add_parser("list")
    sub.add_parser("compact")
    sub.add_parser("stats")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            if args.command == "set":
                store.set(args.KEY, args.VALUE)
            elif args.command == "get":
                value = store.get(args.KEY)
                if value is None:
                    return 1
                print(value)
            elif args.command == "delete":
                return 0 if store.delete(args.KEY) else 1
            elif args.command == "list":
                print("\n".join(store.keys()))
            elif args.command == "compact":
                result = compact(store)
                print(f"removed={result.segments_removed} written={result.records_written} "
                      f"dropped={result.records_dropped} reclaimed={result.bytes_reclaimed}")
            else:
                stats = store.stats()
                fields = ("live_keys", "tombstones", "total_records", "dead_records",
                          "segment_count", "bytes_on_disk")
                print(" ".join(f"{name}={getattr(stats, name)}" for name in fields))
        return 0
    except CorruptSegmentError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
