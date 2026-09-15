import argparse
import sys

from kvstore.compact import compact
from kvstore.errors import CorruptSegmentError
from kvstore.store import KVStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kvstore",
        description="Append-only key-value store CLI",
    )
    parser.add_argument("root", help="Root directory of the store")
    parser.add_argument(
        "--max-segment-bytes",
        type=int,
        default=4096,
        help="Maximum segment size in bytes (default: 4096)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_set = subparsers.add_parser("set", help="Set a key-value pair")
    p_set.add_argument("key", help="Key to set")
    p_set.add_argument("value", help="Value to set")

    p_get = subparsers.add_parser("get", help="Get a value by key")
    p_get.add_argument("key", help="Key to look up")

    p_delete = subparsers.add_parser("delete", help="Delete a key")
    p_delete.add_argument("key", help="Key to delete")

    subparsers.add_parser("list", help="List all live keys")
    subparsers.add_parser("compact", help="Compact the store")
    subparsers.add_parser("stats", help="Show store statistics")

    return parser


def _run_command(store: KVStore, args: argparse.Namespace) -> int:
    cmd = args.command
    if cmd == "set":
        store.set(args.key, args.value)
        return 0
    if cmd == "get":
        val = store.get(args.key)
        if val is None:
            return 1
        sys.stdout.write(val + "\n")
        return 0
    if cmd == "delete":
        if not store.delete(args.key):
            return 1
        return 0
    if cmd == "list":
        for k in store.keys():
            sys.stdout.write(k + "\n")
        return 0
    if cmd == "compact":
        res = compact(store)
        sys.stdout.write(
            f"removed={res.segments_removed} written={res.records_written} "
            f"dropped={res.records_dropped} reclaimed={res.bytes_reclaimed}\n"
        )
        return 0
    if cmd == "stats":
        st = store.stats()
        sys.stdout.write(
            f"live_keys={st.live_keys} tombstones={st.tombstones} "
            f"total_records={st.total_records} dead_records={st.dead_records} "
            f"segment_count={st.segment_count} bytes_on_disk={st.bytes_on_disk}\n"
        )
        return 0
    sys.stderr.write(f"Unknown command: {cmd}\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 2

    if args.max_segment_bytes <= 0:
        sys.stderr.write("error: max_segment_bytes must be a positive integer\n")
        return 2

    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            return _run_command(store, args)
    except CorruptSegmentError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 3
    except (ValueError, TypeError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"Unexpected error: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
