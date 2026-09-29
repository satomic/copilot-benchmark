import argparse
import sys
from collections.abc import Callable

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kvstore")
    parser.add_argument("--max-segment-bytes", type=_positive_int, default=4096)
    parser.add_argument("root")
    subparsers = parser.add_subparsers(dest="command", required=True)
    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("key")
    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("key")
    subparsers.add_parser("list")
    subparsers.add_parser("compact")
    subparsers.add_parser("stats")
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
        for key in store.keys():
            print(key)
    elif args.command == "compact":
        result = compact(store)
        print(
            f"removed={result.segments_removed} written={result.records_written} "
            f"dropped={result.records_dropped} reclaimed={result.bytes_reclaimed}"
        )
    elif args.command == "stats":
        stats = store.stats()
        print(
            f"live_keys={stats.live_keys} tombstones={stats.tombstones} "
            f"total_records={stats.total_records} dead_records={stats.dead_records} "
            f"segment_count={stats.segment_count} bytes_on_disk={stats.bytes_on_disk}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            return _run(store, args)
    except CorruptSegmentError as exc:
        print(exc, file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
