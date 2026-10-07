import ast
import os
import struct
import subprocess
import sys
import zlib
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

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


def raw_record(flags: int, key: bytes, value: bytes) -> bytes:
    return struct.pack(
        ">4sBHII", b"KVR1", flags, len(key), len(value), zlib.crc32(key + value)
    ) + key + value


def test_public_exports() -> None:
    expected = {
        "KVStore", "Stats", "Index", "Location", "Segment", "CompactionResult",
        "compact", "encode_record", "decode_record", "KVStoreError", "RecordError",
        "IncompleteRecordError", "CorruptRecordError", "CorruptSegmentError",
    }
    assert set(kvstore.__all__) == expected
    assert all(hasattr(kvstore, name) for name in expected)


def test_exception_hierarchy() -> None:
    assert issubclass(RecordError, KVStoreError)
    assert issubclass(IncompleteRecordError, RecordError)
    assert issubclass(CorruptRecordError, RecordError)
    assert issubclass(CorruptSegmentError, KVStoreError)
    assert not issubclass(CorruptSegmentError, RecordError)


def test_record_exact_layout() -> None:
    blob = encode_record("a", "bc")
    assert blob == struct.pack(">4sBHII", b"KVR1", 0, 1, 2, zlib.crc32(b"abc")) + b"abc"
    assert len(blob) == 18


def test_record_unicode_roundtrip() -> None:
    blob = encode_record("hello\u4e16\u754c", "\u2603\U0001f600")
    assert decode_record(blob) == ("hello\u4e16\u754c", "\u2603\U0001f600", len(blob))


def test_record_empty_value_differs_from_tombstone() -> None:
    empty = encode_record("a", "")
    deleted = encode_record("a", None)
    assert empty[4] == 0 and deleted[4] == 1
    assert decode_record(empty) == ("a", "", 16)
    assert decode_record(deleted) == ("a", None, 16)


def test_record_offset_and_consumed_size() -> None:
    first, second = encode_record("a", "1"), encode_record("b", "22")
    assert decode_record(first + second, len(first)) == ("b", "22", len(second))
    assert decode_record(first + second) == ("a", "1", len(first))


def test_record_all_incomplete_prefixes() -> None:
    blob = encode_record("abc", "value")
    for end in range(len(blob)):
        with pytest.raises(IncompleteRecordError):
            decode_record(blob[:end])


def test_record_bad_magic() -> None:
    with pytest.raises(CorruptRecordError, match="magic"):
        decode_record(b"XXXX" + encode_record("a", "1")[4:])


def test_record_unknown_flags() -> None:
    with pytest.raises(CorruptRecordError, match="flags"):
        decode_record(raw_record(2, b"a", b""))


def test_record_zero_key_length() -> None:
    with pytest.raises(CorruptRecordError, match="key"):
        decode_record(raw_record(0, b"", b"value"))


def test_record_tombstone_with_payload() -> None:
    with pytest.raises(CorruptRecordError, match="tombstone"):
        decode_record(raw_record(1, b"a", b"x"))


def test_record_structural_errors_precede_incomplete_payload() -> None:
    header = struct.pack(">4sBHII", b"KVR1", 1, 1, 100, 0)
    with pytest.raises(CorruptRecordError, match="tombstone"):
        decode_record(header)


def test_record_crc_mismatch() -> None:
    blob = encode_record("a", "1")
    with pytest.raises(CorruptRecordError, match="CRC"):
        decode_record(blob[:-1] + b"2")


def test_record_crc_precedes_utf8() -> None:
    blob = bytearray(raw_record(0, b"\xff", b"x"))
    blob[11:15] = b"\x00" * 4
    with pytest.raises(CorruptRecordError, match="CRC"):
        decode_record(bytes(blob))


@pytest.mark.parametrize("key,value", [(b"\xff", b"x"), (b"x", b"\xff")])
def test_record_invalid_utf8(key: bytes, value: bytes) -> None:
    with pytest.raises(CorruptRecordError, match="UTF-8"):
        decode_record(raw_record(0, key, value))


@pytest.mark.parametrize("offset", [-1, "1", 1.5])
def test_record_invalid_offset(offset: object) -> None:
    with pytest.raises(CorruptRecordError):
        decode_record(encode_record("a", "1"), offset)


def test_record_key_limit_in_bytes() -> None:
    assert decode_record(encode_record("a" * 65535, ""))[0] == "a" * 65535
    for key in ("", "a" * 65536, "\u4e00" * 40000):
        with pytest.raises(ValueError):
            encode_record(key, "x")


@pytest.mark.parametrize("key,value", [(b"a", "v"), (1, "v"), ("a", b"v"), ("a", 1)])
def test_record_rejects_non_strings(key: object, value: object) -> None:
    with pytest.raises(TypeError):
        encode_record(key, value)


def test_segment_append_offsets_and_scan(tmp_path: Path) -> None:
    segment = Segment(tmp_path / "000001.seg", 1)
    try:
        first = encode_record("a", "")
        assert segment.seg_id == 1 and segment.size == 0
        assert segment.append(first) == 0
        assert segment.append(encode_record("b", None)) == len(first)
        assert list(segment.scan()) == [("a", "", 0), ("b", None, len(first))]
        assert segment.size == 32
        assert segment.path.read_bytes() == first + encode_record("b", None)
    finally:
        segment.close()


def test_segment_scan_repeatable(tmp_path: Path) -> None:
    segment = Segment(tmp_path / "000001.seg", 1)
    try:
        segment.append(encode_record("a", "v"))
        assert list(segment.scan()) == list(segment.scan()) == [("a", "v", 0)]
    finally:
        segment.close()


@pytest.mark.parametrize("tail_size", [1, 14, 15, 16, 18])
def test_segment_truncated_tail(tmp_path: Path, tail_size: int) -> None:
    first = encode_record("a", "1")
    path = tmp_path / "000001.seg"
    path.write_bytes(first + encode_record("tail", "value")[:tail_size])
    segment = Segment(path, 1)
    try:
        assert list(segment.scan()) == [("a", "1", 0)]
        assert segment.size == len(first) + tail_size
    finally:
        segment.close()


def test_segment_crc_corruption_at_last_record(tmp_path: Path) -> None:
    first = encode_record("a", "1")
    bad = encode_record("b", "2")[:-1] + b"3"
    path = tmp_path / "000007.seg"
    path.write_bytes(first + bad)
    segment = Segment(path, 7)
    try:
        with pytest.raises(CorruptSegmentError) as caught:
            list(segment.scan())
        error = caught.value
        assert error.path == path and error.offset == len(first)
        assert path.name in str(error) and str(len(first)) in str(error)
        assert "CRC" in error.reason
    finally:
        segment.close()


@pytest.mark.parametrize(
    "blob", [
        b"NOPE" + encode_record("a", "")[4:],
        raw_record(9, b"a", b""),
        raw_record(0, b"", b""),
        raw_record(1, b"a", b"x")[:15],
        raw_record(0, b"\xff", b""),
    ],
)
def test_segment_structural_and_utf8_corruption(tmp_path: Path, blob: bytes) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(blob)
    segment = Segment(path, 1)
    try:
        with pytest.raises(CorruptSegmentError):
            list(segment.scan())
    finally:
        segment.close()


def test_segment_close_idempotent(tmp_path: Path) -> None:
    segment = Segment(tmp_path / "000001.seg", 1)
    segment.close()
    segment.close()
    with pytest.raises(ValueError):
        segment.append(b"x")
    with pytest.raises(ValueError):
        list(segment.scan())


def test_index_order_by_location() -> None:
    index = Index()
    index.put("a", Location(2, 0), tombstone=False)
    index.put("b", Location(1, 30), tombstone=False)
    index.put("c", Location(1, 0), tombstone=False)
    assert index.live_keys() == ["c", "b", "a"]
    assert len(index) == 3 and index.tombstone_count() == 0


def test_index_rewrite_delete_and_resurrect() -> None:
    index = Index()
    index.put("a", Location(1, 0), tombstone=False)
    index.put("b", Location(1, 20), tombstone=False)
    index.put("a", Location(1, 40), tombstone=False)
    assert index.live_keys() == ["b", "a"]
    index.put("b", Location(2, 0), tombstone=True)
    index.put("b", Location(2, 20), tombstone=True)
    assert index.get("b") is None and index.get("missing") is None
    assert len(index) == 1 and index.tombstone_count() == 1
    index.put("b", Location(2, 40), tombstone=False)
    assert index.live_keys() == ["a", "b"] and index.tombstone_count() == 0


def test_location_and_stats_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        Location(1, 0).offset = 1
    with pytest.raises(FrozenInstanceError):
        Stats(0, 0, 0, 0, 1, 0).live_keys = 1
    assert [field.name for field in fields(Stats)] == [
        "live_keys", "tombstones", "total_records", "dead_records",
        "segment_count", "bytes_on_disk",
    ]


def test_store_creates_root_and_empty_segment(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "data"
    with KVStore(root) as store:
        assert store.stats() == Stats(0, 0, 0, 0, 1, 0)
        assert store.keys() == []
    assert (root / "000001.seg").exists()


def test_store_roundtrip_and_reopen(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("\u4e16\u754c", "\U0001f600")
        assert store.get("a") == "1"
        assert store.get("missing") is None
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"
        assert store.get("\u4e16\u754c") == "\U0001f600"
        assert store.stats().total_records == 2


def test_store_empty_value_and_delete(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "")
        assert store.get("a") == ""
        assert store.delete("a") is True
        assert store.get("a") is None
    with KVStore(tmp_path) as store:
        assert store.get("a") is None and store.stats().tombstones == 1


def test_store_noop_delete_writes_nothing(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        before = store.stats()
        assert store.delete("absent") is False
        assert store.stats() == before
        store.set("a", "")
        store.delete("a")
        before = store.stats()
        assert store.delete("a") is False
        assert store.stats() == before


def test_store_stats_superseded_and_tombstones(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "")
        store.delete("a")
        assert store.stats() == Stats(1, 1, 4, 2, 1, 66)
        store.set("a", "3")
        assert store.stats() == Stats(2, 0, 5, 3, 1, 83)


def test_store_keys_rewrites_move_to_end(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=34) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("c", "3")
        store.set("a", "4")
        assert store.keys() == ["b", "c", "a"]
        store.delete("c")
        store.set("b", "5")
        assert store.keys() == ["a", "b"]
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b"]


def test_store_recovery_ascending_segment_ids(tmp_path: Path) -> None:
    (tmp_path / "000003.seg").write_bytes(encode_record("a", "new"))
    (tmp_path / "000001.seg").write_bytes(
        encode_record("a", "old") + encode_record("b", "live")
    )
    (tmp_path / "000002.seg").write_bytes(encode_record("b", None))
    with KVStore(tmp_path) as store:
        assert store.get("a") == "new" and store.get("b") is None
        assert store.keys() == ["a"]
        assert store.stats().segment_count == 3
        store.set("c", "v")
    assert (tmp_path / "000003.seg").read_bytes().endswith(encode_record("c", "v"))


def test_store_ignores_unmatched_files(tmp_path: Path) -> None:
    names = ["000099.seg.tmp", "notes.seg", "1.seg", "0000001.seg", "other"]
    for name in names:
        (tmp_path / name).write_bytes(b"not a record")
    with KVStore(tmp_path) as store:
        assert store.stats() == Stats(0, 0, 0, 0, 1, 0)
        store.set("a", "1")
        compact(store)
    assert all((tmp_path / name).read_bytes() == b"not a record" for name in names)


def test_store_recovery_preserves_tail_bytes(tmp_path: Path) -> None:
    blob = encode_record("a", "1") + encode_record("bad", "tail")[:18]
    path = tmp_path / "000001.seg"
    path.write_bytes(blob)
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1" and store.get("bad") is None
        assert store.stats() == Stats(1, 0, 1, 0, 1, len(blob))
    assert path.read_bytes() == blob


def test_store_write_after_truncated_tail_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    original = encode_record("a", "1") + b"KVR"
    path.write_bytes(original)
    with KVStore(tmp_path) as store:
        store.set("b", "2")
        assert store.stats().segment_count == 2
        assert store.stats().bytes_on_disk == len(original) + 17
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b"] and store.get("b") == "2"
    assert path.read_bytes() == original


def test_store_truncated_older_segment(tmp_path: Path) -> None:
    (tmp_path / "000001.seg").write_bytes(encode_record("a", "old") + b"KVR")
    (tmp_path / "000002.seg").write_bytes(encode_record("a", "new"))
    with KVStore(tmp_path) as store:
        assert store.get("a") == "new"
        assert store.stats().total_records == 2


def test_store_reports_corruption_and_releases_handles(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "1")[:-1] + b"2")
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)
    path.unlink()
    with KVStore(tmp_path) as store:
        assert store.keys() == []


def test_store_rollover_exact_boundary(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=34) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 1 and store.stats().bytes_on_disk == 34
        store.set("c", "3")
        assert store.stats().segment_count == 2
    assert (tmp_path / "000001.seg").stat().st_size == 34
    assert (tmp_path / "000002.seg").stat().st_size == 17


def test_store_oversized_record_uses_empty_segment(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("a", "v" * 100)
        assert store.stats().segment_count == 1
        store.set("b", "")
        assert store.stats().segment_count == 2 and store.get("a") == "v" * 100


def test_store_tombstones_obey_rollover(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=17) as store:
        store.set("a", "1")
        store.delete("a")
        assert store.stats() == Stats(0, 1, 2, 1, 2, 33)


@pytest.mark.parametrize("limit", [0, -1, 15, 16.0, "4096", None, True])
def test_store_invalid_segment_limit(tmp_path: Path, limit: object) -> None:
    root = tmp_path / "not_created"
    with pytest.raises(ValueError):
        KVStore(root, max_segment_bytes=limit)
    assert not root.exists()


@pytest.mark.parametrize("key", [b"a", 1, None, [], ""])
def test_store_all_operations_validate_keys(tmp_path: Path, key: object) -> None:
    with KVStore(tmp_path) as store:
        before = store.stats()
        error = ValueError if key == "" else TypeError
        for operation in (lambda: store.set(key, "v"), lambda: store.get(key),
                          lambda: store.delete(key)):
            with pytest.raises(error):
                operation()
            assert store.stats() == before


def test_store_key_byte_limits_and_non_string_values(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        for key in ("a" * 65536, "\u4e00" * 40000):
            with pytest.raises(ValueError):
                store.set(key, "v")
        for value in (None, b"v", 1):
            with pytest.raises(TypeError):
                store.set("a", value)
        assert store.stats().bytes_on_disk == 0
        key = "a" * 65535
        store.set(key, "")
        assert store.get(key) == ""


def test_store_close_and_context_manager(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    assert store.__enter__() is store
    store.close()
    store.close()
    for operation in (lambda: store.set("a", "1"), lambda: store.get("a"),
                      lambda: store.delete("a"), store.keys, store.stats,
                      store.__enter__, lambda: compact(store)):
        with pytest.raises(ValueError, match="closed"):
            operation()


def test_store_context_closes_on_exception(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        with KVStore(tmp_path) as store:
            store.set("a", "1")
            raise RuntimeError("stop")
    with pytest.raises(ValueError):
        store.get("a")
    with KVStore(tmp_path) as reopened:
        assert reopened.get("a") == "1"


def test_compaction_result_and_order(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=34) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("c", "")
        store.set("a", "4")
        store.delete("b")
        before = store.stats()
        ids = [int(path.stem) for path in tmp_path.glob("*.seg")]
        result = compact(store)
        assert result == CompactionResult(
            before.segment_count, 2, 3, before.bytes_on_disk - 33
        )
        assert store.stats() == Stats(2, 0, 2, 0, 1, 33)
        assert store.keys() == ["c", "a"]
        assert store.get("c") == "" and store.get("a") == "4"
        assert store.get("b") is None
        assert [path.name for path in tmp_path.glob("*.seg")] == [
            f"{max(ids) + 1:06d}.seg"
        ]
    with KVStore(tmp_path) as store:
        assert store.keys() == ["c", "a"] and store.get("b") is None


def test_compaction_empty_store_creates_new_segment(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        assert compact(store) == CompactionResult(1, 0, 0, 0)
        assert store.stats() == Stats(0, 0, 0, 0, 1, 0)
        assert (tmp_path / "000002.seg").exists()


def test_compaction_all_deleted_drops_tombstones(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.delete("a")
        assert compact(store) == CompactionResult(1, 0, 2, 33)
        assert store.stats() == Stats(0, 0, 0, 0, 1, 0)
        store.set("b", "")
        assert store.stats().segment_count == 1
    with KVStore(tmp_path) as store:
        assert store.get("a") is None and store.get("b") == ""


def test_compaction_reclaims_truncated_tail(tmp_path: Path) -> None:
    (tmp_path / "000001.seg").write_bytes(encode_record("a", "1") + b"KVR")
    with KVStore(tmp_path) as store:
        assert compact(store) == CompactionResult(1, 1, 0, 3)
        assert store.stats().bytes_on_disk == 17


def test_compaction_then_append_and_rollover(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=34) as store:
        store.set("a", "1")
        compact(store)
        store.set("b", "2")
        assert store.stats().segment_count == 1
        store.set("c", "3")
        assert store.stats().segment_count == 2
        assert store.keys() == ["a", "b", "c"]
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b", "c"]


def test_compaction_ignores_rollover_limit(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        for key in ("a", "b", "c"):
            store.set(key, "1")
        assert compact(store).records_written == 3
        assert store.stats().segment_count == 1 and store.stats().bytes_on_disk == 51
        store.set("d", "")
        assert store.stats().segment_count == 2


def test_compaction_replace_failure_preserves_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(source: Path, destination: Path) -> None:
        assert source.suffix == ".tmp"
        raise OSError("simulated rename failure")

    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.delete("b")
        before = store.stats()
        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError, match="rename"):
            compact(store)
        assert store.stats() == before and store.keys() == ["a"]
        assert store.get("a") == "1" and store.get("b") is None
    with KVStore(tmp_path) as store:
        assert store.stats() == before and store.keys() == ["a"]
        store.set("c", "3")
        assert store.get("c") == "3"


def test_compaction_replaces_stale_temporary_file(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        (tmp_path / "000002.seg.tmp").write_bytes(b"stale")
        assert compact(store).records_written == 1
        assert not (tmp_path / "000002.seg.tmp").exists()
        assert store.get("a") == "1"


def test_cli_set_get_list_stats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert capsys.readouterr().out == ""
    assert main([str(tmp_path), "get", "a"]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main([str(tmp_path), "list"]) == 0
    assert capsys.readouterr().out == "a\n"
    assert main([str(tmp_path), "stats"]) == 0
    assert capsys.readouterr().out == (
        "live_keys=1 tombstones=0 total_records=1 dead_records=0 "
        "segment_count=1 bytes_on_disk=17\n"
    )


def test_cli_absent_get_and_delete(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "get", "missing"]) == 1
    assert main([str(tmp_path), "delete", "missing"]) == 1
    assert main([str(tmp_path), "list"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_cli_empty_value_and_delete(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "a", ""]) == 0
    assert main([str(tmp_path), "get", "a"]) == 0
    assert capsys.readouterr().out == "\n"
    assert main([str(tmp_path), "delete", "a"]) == 0
    assert main([str(tmp_path), "delete", "a"]) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "args", [
        [], ["unknown"], ["get"], ["get", "a", "extra"], ["set", "a"],
        ["list", "extra"], ["--max-segment-bytes", "no", "list"],
        ["--max-segment-bytes", "0", "list"],
        ["--max-segment-bytes", "15", "list"],
        ["--max-segment-bytes", "1.5", "list"],
    ],
)
def test_cli_usage_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    assert main([str(tmp_path), *args]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err
    assert not list(tmp_path.glob("*.seg"))


def test_cli_validation_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "\u4e00" * 40000, "v"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "length" in captured.err
    assert (tmp_path / "000001.seg").stat().st_size == 0


def test_cli_corruption_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "000001.seg").write_bytes(encode_record("a", "1")[:-1] + b"2")
    assert main([str(tmp_path), "get", "a"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "000001.seg" in captured.err and "offset 0" in captured.err


def test_cli_compact_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert main([str(tmp_path), "set", "a", "2"]) == 0
    assert main([str(tmp_path), "compact"]) == 0
    assert capsys.readouterr().out == "removed=1 written=1 dropped=1 reclaimed=17\n"


def test_cli_global_segment_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for key in ("a", "b"):
        assert main(["--max-segment-bytes", "17", str(tmp_path), "set", key, "v"]) == 0
    assert len(list(tmp_path.glob("*.seg"))) == 2
    assert capsys.readouterr().out == ""


def test_cli_module_roundtrip(tmp_path: Path) -> None:
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    commands = [
        (["set", "a", "1"], 0, ""),
        (["get", "a"], 0, "1\n"),
        (["get", "zz"], 1, ""),
        (["list"], 0, "a\n"),
        (["delete", "a"], 0, ""),
        (["delete", "a"], 1, ""),
    ]
    for args, code, output in commands:
        result = subprocess.run(
            [sys.executable, "-m", "kvstore", str(tmp_path), *args],
            capture_output=True, text=True, env=environment, check=False,
        )
        assert (result.returncode, result.stdout, result.stderr) == (code, output, "")


def test_source_function_lengths_and_annotations() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (root / "kvstore").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.body[0].lineno + 1 <= 60, (
                    path.name, node.name
                )
                assert node.returns is not None, (path.name, node.name)
                arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                arguments += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
                for argument in arguments:
                    if argument.arg not in ("self", "cls"):
                        assert argument.annotation is not None, (path.name, node.name)
