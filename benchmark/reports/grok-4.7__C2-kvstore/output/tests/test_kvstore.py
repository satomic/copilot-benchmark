"""Tests for the append-only key-value store."""

from __future__ import annotations

import inspect
import pathlib
import struct
import subprocess
import sys
import zlib

import pytest

import kvstore
from kvstore import (
    CompactionResult,
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    Index,
    KVStore,
    KVStoreError,
    Location,
    RecordError,
    Segment,
    Stats,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _record(flags: int, key: bytes, value: bytes, crc: int | None = None) -> bytes:
    if crc is None:
        crc = zlib.crc32(key + value) & 0xFFFFFFFF
    header = struct.pack(">4sBHII", b"KVR1", flags, len(key), len(value), crc)
    return header + key + value


def _seg_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for path in root.iterdir() if path.name.endswith(".seg"))


def test_encode_decode_round_trip() -> None:
    samples = [("a", "1"), ("hello", ""), ("k", "x" * 100), ("雪", "値")]
    for key, value in samples:
        blob = encode_record(key, value)
        assert decode_record(blob) == (key, value, len(blob))


def test_tombstone_differs_from_empty_value() -> None:
    empty = encode_record("k", "")
    tomb = encode_record("k", None)
    assert empty != tomb
    assert empty[4] == 0x00
    assert tomb[4] == 0x01
    assert len(empty) == len(tomb) == 16
    assert decode_record(empty) == ("k", "", 16)
    assert decode_record(tomb) == ("k", None, 16)


def test_record_layout_is_big_endian() -> None:
    blob = encode_record("ab", "xyz")
    assert blob[:4] == b"KVR1"
    assert blob[4] == 0
    assert blob[5:7] == b"\x00\x02"
    assert blob[7:11] == b"\x00\x00\x00\x03"
    assert blob[15:17] == b"ab"
    assert blob[17:] == b"xyz"
    crc = zlib.crc32(b"abxyz") & 0xFFFFFFFF
    assert blob[11:15] == struct.pack(">I", crc)


def test_crc_does_not_cover_header() -> None:
    blob = encode_record("ab", "xyz")
    assert blob[11:15] == struct.pack(">I", zlib.crc32(b"abxyz") & 0xFFFFFFFF)
    assert blob[11:15] != struct.pack(">I", zlib.crc32(blob[:11] + b"abxyz") & 0xFFFFFFFF)


def test_decode_incomplete_header() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(b"KVR1")


def test_decode_incomplete_body_before_structural_checks() -> None:
    short = b"XXXX" + struct.pack(">BHII", 0, 10, 0, 0)
    assert len(short) == 15
    with pytest.raises(IncompleteRecordError):
        decode_record(short)


def test_decode_bad_magic() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[0] = ord("X")
    with pytest.raises(CorruptRecordError, match="bad magic"):
        decode_record(bytes(blob))


def test_decode_unknown_flags_before_zero_key_len() -> None:
    blob = _record(0x02, b"", b"")
    with pytest.raises(CorruptRecordError, match="unknown flags"):
        decode_record(blob)


def test_decode_zero_key_len() -> None:
    blob = _record(0x00, b"", b"")
    with pytest.raises(CorruptRecordError, match="key length is zero"):
        decode_record(blob)


def test_decode_tombstone_with_value_before_crc() -> None:
    blob = _record(0x01, b"a", b"b", crc=0)
    with pytest.raises(CorruptRecordError, match="tombstone"):
        decode_record(blob)


def test_decode_crc_mismatch_before_utf8() -> None:
    blob = _record(0x00, b"\xff", b"", crc=0)
    with pytest.raises(CorruptRecordError, match="crc mismatch"):
        decode_record(blob)


def test_decode_invalid_utf8() -> None:
    blob = _record(0x00, b"\xff", b"")
    with pytest.raises(CorruptRecordError, match="invalid utf-8"):
        decode_record(blob)


def test_decode_uses_offset_and_reports_total_size() -> None:
    first = encode_record("a", "1")
    second = encode_record("bb", None)
    buf = b"prefix" + first + second + b"tail"
    key, value, size = decode_record(buf, 6)
    assert (key, value, size) == ("a", "1", len(first))
    assert decode_record(buf, 6 + size) == ("bb", None, len(second))


def test_exception_hierarchy() -> None:
    assert issubclass(IncompleteRecordError, RecordError)
    assert issubclass(CorruptRecordError, RecordError)
    assert issubclass(RecordError, KVStoreError)
    assert issubclass(CorruptSegmentError, KVStoreError)
    assert not issubclass(CorruptSegmentError, RecordError)


def test_segment_append_scan_and_size(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    segment = Segment(path, 1)
    first = encode_record("a", "1")
    second = encode_record("b", "2")
    assert segment.append(first) == 0
    assert segment.append(second) == len(first)
    assert segment.size == len(first) + len(second)
    assert list(segment.scan()) == [("a", "1", 0), ("b", "2", len(first))]
    segment.close()
    segment.close()
    assert path.stat().st_size == len(first) + len(second)


def test_scan_stops_on_truncated_tail(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    blob = encode_record("hello", "world")
    path.write_bytes(blob + b"PARTIAL")
    segment = Segment(path, 1)
    assert list(segment.scan()) == [("hello", "world", 0)]
    assert segment.size == len(blob) + 7
    segment.close()


def test_scan_header_only_tail_is_not_corruption(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    good = encode_record("a", "1")
    tail = b"XXXX" + struct.pack(">BHII", 0x02, 50, 0, 0)
    path.write_bytes(good + tail)
    segment = Segment(path, 1)
    assert list(segment.scan()) == [("a", "1", 0)]
    segment.close()


def test_scan_crc_mismatch_at_end_is_corruption(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000009.seg"
    blob = bytearray(encode_record("a", "1"))
    blob[-1] ^= 0xFF
    path.write_bytes(blob)
    segment = Segment(path, 9)
    with pytest.raises(CorruptSegmentError) as caught:
        list(segment.scan())
    segment.close()
    err = caught.value
    assert err.offset == 0
    assert err.path == path
    assert "000009.seg" in str(err)
    assert "0" in str(err)


def test_scan_corrupt_offset_after_good_record(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    good = encode_record("a", "1")
    bad = bytearray(encode_record("b", "2"))
    bad[-1] ^= 0xFF
    path.write_bytes(good + bad)
    segment = Segment(path, 1)
    seen: list[str] = []
    with pytest.raises(CorruptSegmentError) as caught:
        for key, _, _ in segment.scan():
            seen.append(key)
    segment.close()
    assert seen == ["a"]
    assert caught.value.offset == len(good)
    assert str(caught.value.offset) in str(caught.value)


def test_index_order_tombstones_and_len() -> None:
    index = Index()
    index.put("a", Location(1, 0), tombstone=False)
    index.put("b", Location(1, 20), tombstone=False)
    index.put("c", Location(1, 40), tombstone=False)
    assert index.live_keys() == ["a", "b", "c"]
    index.put("a", Location(2, 0), tombstone=False)
    assert index.live_keys() == ["b", "c", "a"]
    assert index.get("a") == Location(2, 0)
    index.put("b", Location(2, 10), tombstone=True)
    assert index.get("b") is None
    assert index.live_keys() == ["c", "a"]
    assert index.tombstone_count() == 1
    assert len(index) == 2
    assert index.get("missing") is None


def test_set_get_delete_and_empty_value(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("empty", "")
        assert store.get("a") == "1"
        assert store.get("empty") == ""
        assert store.get("missing") is None
        assert store.delete("a") is True
        assert store.get("a") is None
        assert store.delete("a") is False
        assert store.delete("missing") is False
        assert store.keys() == ["empty"]


def test_noop_delete_does_not_grow_log(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        store.set("a", "1")
        before = store.stats()
        assert store.delete("gone") is False
        assert store.stats() == before


def test_persistence_across_reopen(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.delete("a")
    with KVStore(root) as store:
        assert store.get("a") is None
        assert store.get("b") == "2"
        assert store.keys() == ["b"]
        assert store.stats().total_records == 3


def test_truncated_tail_is_recovered_and_counted(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        store.set("a", "1")
    seg = _seg_files(root)[0]
    before = seg.stat().st_size
    with seg.open("ab") as handle:
        handle.write(b"TORN")
    with KVStore(root) as store:
        assert store.get("a") == "1"
        assert store.stats().bytes_on_disk == before + 4
        assert store.stats().total_records == 1
        store.set("b", "2")
    with KVStore(root) as store:
        assert store.get("a") == "1"
        assert store.get("b") == "2"


def test_crc_mismatch_on_reopen_is_corruption(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        store.set("a", "1")
        store.set("b", "2")
    seg = _seg_files(root)[0]
    data = bytearray(seg.read_bytes())
    data[-1] ^= 0xFF
    seg.write_bytes(data)
    with pytest.raises(CorruptSegmentError) as caught:
        KVStore(root)
    assert caught.value.path.name == seg.name
    assert caught.value.offset == len(encode_record("a", "1"))


def test_rollover_exact_fit_and_oversized_record(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root, max_segment_bytes=32) as store:
        store.set("k", "")
        store.set("m", "")
        assert store.stats().segment_count == 1
        assert _seg_files(root)[0].stat().st_size == 32
        store.set("n", "")
        assert store.stats().segment_count == 2
    wide = tmp_path / "wide"
    with KVStore(wide, max_segment_bytes=16) as store:
        store.set("k", "v")
        assert store.get("k") == "v"
        assert store.stats().segment_count == 1
        store.set("m", "")
        assert store.stats().segment_count == 2
        assert store.keys() == ["k", "m"]


def test_keys_order_moves_rewritten_key_to_end(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "db") as store:
        store.set("c", "1")
        store.set("a", "1")
        store.set("b", "1")
        assert store.keys() == ["c", "a", "b"]
        store.set("a", "2")
        assert store.keys() == ["c", "b", "a"]
        assert store.get("a") == "2"
        store.delete("c")
        store.set("c", "3")
        assert store.keys() == ["b", "a", "c"]


def test_validation_rejects_bad_types_and_long_keys(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        before = store.stats()
        with pytest.raises(TypeError):
            store.set(b"a", "1")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.set("a", b"1")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.get(b"a")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.delete(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            store.set("", "1")
        with pytest.raises(ValueError):
            store.set("你" * 21846, "1")
        store.set("你" * 21845, "ok")
        assert store.get("你" * 21845) == "ok"
        assert store.stats().total_records == before.total_records + 1


def test_max_segment_bytes_must_be_int_at_least_16(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path / "a", max_segment_bytes=15)
    with pytest.raises(ValueError):
        KVStore(tmp_path / "b", max_segment_bytes=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        KVStore(tmp_path / "c", max_segment_bytes=16.0)  # type: ignore[arg-type]
    with KVStore(tmp_path / "d", max_segment_bytes=16) as store:
        store.set("k", "")
        assert store.get("k") == ""


def test_closed_store_and_context_manager(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    store = KVStore(root)
    store.set("a", "1")
    store.close()
    store.close()
    with pytest.raises(ValueError):
        store.get("a")
    with pytest.raises(RuntimeError):
        with KVStore(root) as again:
            again.set("b", "2")
            raise RuntimeError("boom")
    with KVStore(root) as reopened:
        assert reopened.get("a") == "1"
        assert reopened.get("b") == "2"


def test_stats_counts_dead_records(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "3")
        store.delete("a")
        stats = store.stats()
    assert stats == Stats(1, 1, 4, 2, 1, stats.bytes_on_disk)
    assert stats.dead_records == stats.total_records - stats.live_keys - stats.tombstones


def test_ignored_files_are_not_recovered(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        store.set("a", "1")
    (root / "000003.seg.tmp").write_bytes(encode_record("hidden", "no"))
    (root / "notes.txt").write_bytes(b"not a segment")
    (root / "00001.seg").write_bytes(encode_record("short", "name"))
    with KVStore(root) as store:
        assert store.get("a") == "1"
        assert store.get("hidden") is None
        assert store.stats().segment_count == 1


def test_later_segment_wins_and_gaps_are_allowed(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    root.mkdir()
    (root / "000003.seg").write_bytes(encode_record("k", "old") + encode_record("k", "new"))
    (root / "000005.seg").write_bytes(encode_record("k", "newest") + encode_record("z", "1"))
    with KVStore(root, max_segment_bytes=16) as store:
        assert store.get("k") == "newest"
        assert store.keys() == ["k", "z"]
        store.set("m", "2")
        names = [path.name for path in _seg_files(root)]
        assert names == ["000003.seg", "000005.seg", "000006.seg"]


def test_compaction_preserves_order_and_drops_tombstones(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root, max_segment_bytes=32) as store:
        store.set("c", "1")
        store.set("a", "1")
        store.set("b", "1")
        store.set("a", "9")
        store.delete("c")
        order = store.keys()
        result = compact(store)
        assert order == ["b", "a"]
        assert store.keys() == ["b", "a"]
        assert store.get("a") == "9"
        assert store.get("c") is None
        assert result.records_written == 2
        assert result.records_dropped == 3
        assert result.segments_removed >= 1
        assert store.stats().tombstones == 0
        assert store.stats().dead_records == 0
        assert store.stats().segment_count == 1
        assert store.stats().total_records == 2
    with KVStore(root) as store:
        assert store.keys() == ["b", "a"]
        assert store.get("b") == "1"


def test_compaction_reclaims_truncated_tail(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        store.set("a", "1")
        store.set("a", "2")
    seg = _seg_files(root)[0]
    with seg.open("ab") as handle:
        handle.write(b"TAIL!!")
    with KVStore(root) as store:
        before = store.stats().bytes_on_disk
        result = compact(store)
        assert result == CompactionResult(1, 1, 1, before - len(encode_record("a", "2")))
        assert store.stats().bytes_on_disk == len(encode_record("a", "2"))
        assert not list(root.glob("*.tmp"))


def test_compaction_of_empty_store_keeps_an_active_segment(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        result = compact(store)
        assert result == CompactionResult(1, 0, 0, 0)
        assert _seg_files(root) == [root / "000002.seg"]
        assert store.stats().segment_count == 1
        store.set("a", "1")
        assert store.get("a") == "1"


def test_writes_after_compaction_obey_rollover(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root, max_segment_bytes=16) as store:
        store.set("a", "1")
        compact(store)
        store.set("b", "")
        store.set("c", "")
        assert store.keys() == ["a", "b", "c"]
        # Compacted "a"/"1" is 17 bytes, so each later 16-byte record rolls.
        assert store.stats().segment_count == 3


def test_unicode_value_survives_compaction(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root) as store:
        store.set("city", "東京")
        compact(store)
        assert store.get("city") == "東京"
    with KVStore(root) as store:
        assert store.get("city") == "東京"


def test_cli_round_trip_list_stats_and_compact(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path / "db")
    assert main([root, "set", "a", "1"]) == 0
    assert main([root, "get", "a"]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main([root, "get", "zz"]) == 1
    assert capsys.readouterr().out == ""
    assert main([root, "list"]) == 0
    assert capsys.readouterr().out == "a\n"
    assert main([root, "stats"]) == 0
    assert capsys.readouterr().out == (
        "live_keys=1 tombstones=0 total_records=1 dead_records=0 "
        "segment_count=1 bytes_on_disk=17\n"
    )
    assert main([root, "compact"]) == 0
    assert capsys.readouterr().out == "removed=1 written=1 dropped=0 reclaimed=0\n"


def test_cli_delete_and_missing_exit_codes(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path / "db")
    assert main([root, "delete", "a"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert main([root, "set", "a", ""]) == 0
    assert main([root, "get", "a"]) == 0
    assert capsys.readouterr().out == "\n"
    assert main([root, "delete", "a"]) == 0
    assert capsys.readouterr().out == ""
    assert main([root, "get", "a"]) == 1


def test_cli_usage_and_store_errors_use_stderr(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path / "db")
    assert main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""
    assert main([root, "nope"]) == 2
    assert capsys.readouterr().out == ""
    assert main([root, "get"]) == 2
    assert capsys.readouterr().out == ""
    assert main([root, "set", "a", "b", "c"]) == 2
    assert capsys.readouterr().out == ""
    assert main([root, "--max-segment-bytes", "0", "set", "a", "1"]) == 2
    assert capsys.readouterr().out == ""
    assert main([root, "--max-segment-bytes", "abc", "set", "a", "1"]) == 2
    assert capsys.readouterr().out == ""
    assert main([root, "set", "x" * 70000, "v"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""
    assert main([root, "--max-segment-bytes", "10", "set", "a", "1"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_corrupt_segment_exits_3(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "db"
    root.mkdir()
    blob = bytearray(encode_record("a", "1"))
    blob[-1] ^= 0xFF
    (root / "000001.seg").write_bytes(blob)
    assert main([str(root), "get", "a"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "000001.seg" in captured.err
    assert "0" in captured.err


def test_module_entrypoint(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    base = [sys.executable, "-m", "kvstore", str(root)]
    set_proc = subprocess.run(base + ["set", "a", "1"], cwd=ROOT, capture_output=True, check=False)
    get_proc = subprocess.run(base + ["get", "a"], cwd=ROOT, capture_output=True, check=False)
    miss = subprocess.run(base + ["get", "zz"], cwd=ROOT, capture_output=True, check=False)
    listed = subprocess.run(base + ["list"], cwd=ROOT, capture_output=True, check=False)
    assert set_proc.returncode == 0 and set_proc.stdout == b""
    assert get_proc.returncode == 0 and get_proc.stdout == b"1\n"
    assert miss.returncode == 1 and miss.stdout == b""
    assert listed.returncode == 0 and listed.stdout == b"a\n"


def test_public_exports_and_annotations() -> None:
    expected = [
        "CompactionResult",
        "CorruptRecordError",
        "CorruptSegmentError",
        "IncompleteRecordError",
        "Index",
        "KVStore",
        "KVStoreError",
        "Location",
        "RecordError",
        "Segment",
        "Stats",
        "compact",
        "decode_record",
        "encode_record",
    ]
    assert sorted(kvstore.__all__) == expected
    missing = _missing_annotations()
    assert missing == []


def test_compact_result_field_order() -> None:
    result = CompactionResult(1, 2, 3, 4)
    assert tuple(result) == (1, 2, 3, 4)
    stats = Stats(1, 2, 3, 4, 5, 6)
    assert tuple(stats) == (1, 2, 3, 4, 5, 6)


def test_delete_then_set_revives_key_at_end(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.delete("a") is True
        store.set("a", "")
        assert store.keys() == ["b", "a"]
        assert store.get("a") == ""
        assert store.stats().tombstones == 0


def test_superseded_tombstone_is_not_double_counted(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.delete("a")
        store.set("a", "2")
        store.delete("a")
        stats = store.stats()
    assert stats.live_keys == 0
    assert stats.tombstones == 1
    assert stats.total_records == 4
    assert stats.dead_records == 3


def test_torn_tail_in_earlier_segment_does_not_hide_later_one(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root, max_segment_bytes=16) as store:
        store.set("k", "v")
        store.set("m", "")
    first, second = _seg_files(root)
    with first.open("ab") as handle:
        handle.write(b"TORN")
    with KVStore(root) as store:
        assert store.get("k") == "v"
        assert store.get("m") == ""
        assert store.stats().bytes_on_disk == first.stat().st_size + second.stat().st_size


def test_corrupt_non_active_segment_reports_its_path(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "db"
    with KVStore(root, max_segment_bytes=16) as store:
        store.set("k", "v")
        store.set("m", "")
    first = _seg_files(root)[0]
    data = bytearray(first.read_bytes())
    data[-1] ^= 0xFF
    first.write_bytes(data)
    with pytest.raises(CorruptSegmentError) as caught:
        KVStore(root)
    assert caught.value.path == first
    assert caught.value.offset == 0


def _missing_annotations() -> list[str]:
    missing: list[str] = []
    for name in kvstore.__all__:
        obj = getattr(kvstore, name)
        if inspect.isfunction(obj):
            missing.extend(_missing_on_callable(name, obj))
        elif inspect.isclass(obj):
            missing.extend(_missing_on_class(obj))
    return missing


def _missing_on_class(cls: type) -> list[str]:
    missing: list[str] = []
    special = {"__init__", "__len__", "__enter__", "__exit__"}
    for attr, value in cls.__dict__.items():
        if attr.startswith("_") and attr not in special:
            continue
        func = value
        if isinstance(func, property):
            func = func.fget
        if isinstance(func, (staticmethod, classmethod)):
            func = func.__func__
        if inspect.isfunction(func):
            missing.extend(_missing_on_callable(f"{cls.__name__}.{attr}", func))
    return missing


def _missing_on_callable(name: str, func: object) -> list[str]:
    signature = inspect.signature(func)  # type: ignore[arg-type]
    missing: list[str] = []
    for param in signature.parameters.values():
        if param.name == "self":
            continue
        if param.annotation is inspect.Signature.empty:
            missing.append(f"{name}:{param.name}")
    if signature.return_annotation is inspect.Signature.empty:
        missing.append(f"{name}:return")
    return missing
