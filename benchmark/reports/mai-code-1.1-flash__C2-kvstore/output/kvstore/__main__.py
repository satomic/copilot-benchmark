import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore")
    parser.add_argument("--max-segment-bytes", type=int, default=4096)
    parser.add_argument("root")
    sub = parser.add_subparsers(dest="command", required=True)
    set_parser = sub.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    get_parser = sub.add_parser("get")
    get_parser.add_argument("key")
    delete_parser = sub.add_parser("delete")
    delete_parser.add_argument("key")
    sub.add_parser("list")
    sub.add_parser("compact")
    sub.add_parser("stats")
    return parser


def _usage_error(parser: argparse.ArgumentParser, message: str) -> int:
    parser.print_usage(sys.stderr)
    print(message, file=sys.stderr)
    return 2


def _cmd_set(store: KVStore, key: str, value: str) -> int:
    store.set(key, value)
    return 0


def _cmd_get(store: KVStore, key: str) -> int:
    value = store.get(key)
    if value is None:
        return 1
    sys.stdout.write(f"{value}\n")
    return 0


def _cmd_delete(store: KVStore, key: str) -> int:
    return 0 if store.delete(key) else 1


def _cmd_list(store: KVStore) -> int:
    for key in store.keys():
        sys.stdout.write(f"{key}\n")
    return 0


def _cmd_compact(store: KVStore) -> int:
    result = compact(store)
    sys.stdout.write(
        f"removed={result.segments_removed} "
        f"written={result.records_written} "
        f"dropped={result.records_dropped} "
        f"reclaimed={result.bytes_reclaimed}\n"
    )
    return 0


def _cmd_stats(store: KVStore) -> int:
    stats = store.stats()
    sys.stdout.write(
        f"live_keys={stats.live_keys} tombstones={stats.tombstones} "
        f"total_records={stats.total_records} dead_records={stats.dead_records} "
        f"segment_count={stats.segment_count} bytes_on_disk={stats.bytes_on_disk}\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            if args.command == "set":
                return _cmd_set(store, args.key, args.value)
            if args.command == "get":
                return _cmd_get(store, args.key)
            if args.command == "delete":
                return _cmd_delete(store, args.key)
            if args.command == "list":
                return _cmd_list(store)
            if args.command == "compact":
                return _cmd_compact(store)
            if args.command == "stats":
                return _cmd_stats(store)
    except (TypeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    except CorruptSegmentError as exc:
        print(exc, file=sys.stderr)
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
