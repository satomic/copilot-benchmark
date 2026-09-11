import dataclasses
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib

import pytest

import kvstore
from kvstore import (
    CompactionResult, CorruptRecordError, CorruptSegmentError, IncompleteRecordError,
    Index, KVStore, KVStoreError, Location, RecordError, Segment, Stats, compact,
    decode_record, encode_record,
)
from kvstore.__main__ import main


def _raw(
    key: bytes = b"k", value: bytes = b"v", *, magic: bytes = b"KVR1",
    flags: int = 0, crc: int | None = None,
) -> bytes:
    checksum = zlib.crc32(key + value) if crc is None else crc
    return struct.pack(">4sBHII", magic, flags, len(key), len(value), checksum) + key + value


def test_public_exports() -> None:
    expected = {
        "KVStore", "Stats", "Index", "Location", "Segment", "CompactionResult",
        "compact", "encode_record", "decode_record", "KVStoreError", "RecordError",
        "IncompleteRecordError", "CorruptRecordError", "CorruptSegmentError",
    }
    assert set(kvstore.__all__) == expected
    assert len(kvstore.__all__) == len(expected)
    assert all(hasattr(kvstore, name) for name in expected)


def test_error_hierarchy() -> None:
    assert issubclass(RecordError, KVStoreError)
    assert issubclass(IncompleteRecordError, RecordError)
    assert issubclass(CorruptRecordError, RecordError)
    assert issubclass(CorruptSegmentError, KVStoreError)
    assert not issubclass(CorruptSegmentError, RecordError)


def test_record_exact_layout() -> None:
    blob = encode_record("a", "bc")
    assert blob == b"KVR1\x00\x00\x01\x00\x00\x00\x02" + struct.pack(">I", zlib.crc32(b"abc")) + b"abc"
    assert len(blob) == 18


@pytest.mark.parametrize("key,value", [("a", "1"), ("key", ""), ("key", None), ("\u4e2d", "\U0001f600")])
def test_record_round_trip(key: str, value: str | None) -> None:
    blob = encode_record(key, value)
    assert decode_record(blob) == (key, value, len(blob))


def test_record_offset_and_trailing_bytes() -> None:
    first = encode_record("first", "1")
    second = encode_record("second", "2")
    assert decode_record(first + second + b"junk", len(first)) == ("second", "2", len(second))


def test_tombstone_is_not_empty_value() -> None:
    empty, tombstone = encode_record("a", ""), encode_record("a", None)
    assert len(empty) == len(tombstone) == 16
    assert empty[4] == 0 and tombstone[4] == 1
    assert empty[:4] + empty[5:] == tombstone[:4] + tombstone[5:]
    assert decode_record(empty)[1] == ""
    assert decode_record(tombstone)[1] is None


@pytest.mark.parametrize("cut", range(18))
def test_record_incomplete(cut: int) -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("a", "bc")[:cut])


@pytest.mark.parametrize("blob", [
    _raw(magic=b"BAD!"), _raw(flags=2), _raw(key=b""), _raw(flags=1),
])
def test_record_structural_corruption(blob: bytes) -> None:
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_structure_precedes_incomplete_payload_and_crc() -> None:
    blob = struct.pack(">4sBHII", b"BAD!", 0, 1, 1000, 0)
    with pytest.raises(CorruptRecordError, match="magic"):
        decode_record(blob)


def test_crc_precedes_utf8() -> None:
    with pytest.raises(CorruptRecordError, match="CRC"):
        decode_record(_raw(key=b"\xff", crc=0))


@pytest.mark.parametrize("key,value", [(b"\xff", b"v"), (b"k", b"\xff")])
def test_record_invalid_utf8(key: bytes, value: bytes) -> None:
    with pytest.raises(CorruptRecordError, match="UTF-8"):
        decode_record(_raw(key, value))


def test_record_crc_mismatch() -> None:
    blob = bytearray(encode_record("key", "value"))
    blob[-1] ^= 1
    with pytest.raises(CorruptRecordError, match="CRC"):
        decode_record(bytes(blob))


@pytest.mark.parametrize("offset", [-1, 0.5])
def test_record_invalid_offset(offset: int | float) -> None:
    with pytest.raises(CorruptRecordError):
        decode_record(encode_record("k", "v"), offset)  # type: ignore[arg-type]


@pytest.mark.parametrize("key", [b"key", 42, None])
def test_encode_rejects_non_string_key(key: object) -> None:
    with pytest.raises(TypeError):
        encode_record(key, "v")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [b"value", 42, [], True])
def test_encode_rejects_non_string_value(value: object) -> None:
    with pytest.raises(TypeError):
        encode_record("key", value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "key", ["", "a" * 65536, "\u4e2d" * 40000],
    ids=["empty", "ascii-too-long", "utf8-too-long"],
)
def test_encode_key_byte_length(key: str) -> None:
    with pytest.raises(ValueError):
        encode_record(key, "v")


def test_encode_maximum_key_length() -> None:
    key = "\u4e2d" * 21845
    blob = encode_record(key, "")
    assert len(key.encode("utf-8")) == 65535
    assert decode_record(blob) == (key, "", len(blob))


def test_segment_append_scan_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    segment = Segment(path, 1)
    first = encode_record("a", "")
    assert segment.seg_id == 1 and segment.size == 0
    assert segment.append(first) == 0
    assert segment.append(encode_record("b", None)) == len(first)
    assert path.read_bytes() == first + encode_record("b", None)
    assert list(segment.scan()) == [("a", "", 0), ("b", None, len(first))]
    segment.close()
    segment.close()
    reopened = Segment(path, 1)
    try:
        assert reopened.size == 32
        assert list(reopened.scan()) == [("a", "", 0), ("b", None, 16)]
    finally:
        reopened.close()


@pytest.mark.parametrize("tail", [b"KVR", encode_record("other", "value")[:-1]])
def test_segment_truncated_tail(tmp_path: Path, tail: bytes) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "b") + tail)
    segment = Segment(path, 1)
    try:
        assert list(segment.scan()) == [("a", "b", 0)]
        assert segment.size == 17 + len(tail)
    finally:
        segment.close()


@pytest.mark.parametrize("bad", [
    _raw(magic=b"NOPE"), _raw(flags=3), _raw(key=b""), _raw(flags=1),
    _raw(crc=0), _raw(key=b"\xff"), _raw(value=b"\xff"),
])
def test_segment_reports_corrupt_final_record(tmp_path: Path, bad: bytes) -> None:
    path = tmp_path / "000042.seg"
    path.write_bytes(encode_record("a", "1") + bad)
    segment = Segment(path, 42)
    try:
        with pytest.raises(CorruptSegmentError) as caught:
            list(segment.scan())
        assert caught.value.path == path
        assert caught.value.offset == 17
        assert path.name in str(caught.value) and "17" in str(caught.value)
        assert caught.value.reason
    finally:
        segment.close()


def test_segment_corruption_in_middle(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(_raw(crc=0) + encode_record("later", "value"))
    segment = Segment(path, 1)
    try:
        with pytest.raises(CorruptSegmentError) as caught:
            list(segment.scan())
        assert caught.value.offset == 0
    finally:
        segment.close()


def test_index_latest_put_wins() -> None:
    index = Index()
    assert index.get("a") is None and len(index) == 0
    index.put("a", Location(2, 10), tombstone=False)
    index.put("a", Location(1, 0), tombstone=True)
    assert index.get("a") is None
    assert len(index) == 0 and index.tombstone_count() == 1
    index.put("a", Location(3, 0), tombstone=False)
    assert index.get("a") == Location(3, 0)
    assert len(index) == 1 and index.tombstone_count() == 0


def test_index_order_is_location_not_insertion_order() -> None:
    index = Index()
    index.put("c", Location(3, 0), tombstone=False)
    index.put("b", Location(2, 10), tombstone=False)
    index.put("a", Location(2, 0), tombstone=False)
    index.put("dead", Location(1, 0), tombstone=True)
    index.put("dead", Location(4, 0), tombstone=True)
    assert index.live_keys() == ["a", "b", "c"]
    assert index.tombstone_count() == 1
    index.put("a", Location(5, 0), tombstone=False)
    assert index.live_keys() == ["b", "c", "a"]


def test_location_and_stats_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        Location(1, 0).offset = 5  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        Stats(0, 0, 0, 0, 1, 0).live_keys = 5  # type: ignore[misc]
    assert [field.name for field in dataclasses.fields(Stats)] == [
        "live_keys", "tombstones", "total_records", "dead_records", "segment_count", "bytes_on_disk",
    ]


def test_store_creates_missing_root(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "data"
    with KVStore(root) as store:
        assert store.stats() == Stats(0, 0, 0, 0, 1, 0)
        assert store.keys() == [] and store.get("absent") is None
    assert [path.name for path in root.iterdir()] == ["000001.seg"]


def test_store_persists_values_and_deletions(tmp_path: Path) -> None:
    with KVStore(str(tmp_path)) as store:
        store.set("a", "1")
        store.set("b", "")
        store.set("a", "2")
        assert store.delete("a")
        assert store.get("a") is None and store.get("b") == ""
    with KVStore(tmp_path) as store:
        assert store.keys() == ["b"]
        assert store.get("a") is None and store.get("b") == ""
        assert store.stats().total_records == 4


def test_noop_delete_does_not_write_or_rollover(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        before = store.stats()
        assert not store.delete("missing")
        assert store.stats() == before
        store.set("a", "")
        assert store.delete("a")
        before = store.stats()
        assert not store.delete("a") and not store.delete("missing")
        assert store.stats() == before


@pytest.mark.parametrize("method", ["set", "get", "delete"])
@pytest.mark.parametrize(
    "key", [b"k", 1, None, "", "\u4e2d" * 40000],
    ids=["bytes", "integer", "none", "empty", "utf8-too-long"],
)
def test_store_validates_keys_without_writes(tmp_path: Path, method: str, key: object) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("k", "")
        before = store.stats()
        args = (key, "value") if method == "set" else (key,)
        error = ValueError if isinstance(key, str) else TypeError
        with pytest.raises(error):
            getattr(store, method)(*args)
        assert store.stats() == before
        assert store.get("k") == ""


@pytest.mark.parametrize("value", [None, b"v", 1, False, []])
def test_store_validates_values_without_writes(tmp_path: Path, value: object) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("k", "")
        before = store.stats()
        with pytest.raises(TypeError):
            store.set("k", value)  # type: ignore[arg-type]
        assert store.stats() == before


@pytest.mark.parametrize("limit", [0, -1, 15, 16.0, "16", None, True])
def test_invalid_segment_limit(tmp_path: Path, limit: object) -> None:
    root = tmp_path / "not-created"
    with pytest.raises(ValueError):
        KVStore(root, max_segment_bytes=limit)  # type: ignore[arg-type]
    assert not root.exists()


def test_rollover_strict_boundary(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        store.set("a", "")
        store.set("b", "")
        assert store.stats().segment_count == 1
        assert (tmp_path / "000001.seg").stat().st_size == 32
        store.set("c", "")
        assert store.stats().segment_count == 2
        assert (tmp_path / "000002.seg").stat().st_size == 16
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b", "c"]


def test_oversized_record_uses_empty_segment(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("a", "x" * 100)
        assert store.stats().segment_count == 1
        assert store.stats().bytes_on_disk == 116
        store.set("b", "")
        assert store.stats().segment_count == 2
        assert store.get("a") == "x" * 100


def test_store_keys_follow_newest_record(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        store.set("a", "")
        store.set("b", "")
        store.set("c", "")
        store.set("a", "updated")
        assert store.keys() == ["b", "c", "a"]
        assert store.delete("c")
        store.set("b", "updated")
        store.set("c", "revived")
        assert store.keys() == ["a", "b", "c"]
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b", "c"]


def test_recovery_sorts_segment_ids_and_uses_highest(tmp_path: Path) -> None:
    (tmp_path / "000010.seg").write_bytes(encode_record("a", "latest"))
    (tmp_path / "000002.seg").write_bytes(encode_record("a", "old") + encode_record("b", "2"))
    with KVStore(tmp_path) as store:
        assert store.get("a") == "latest"
        assert store.keys() == ["b", "a"]
        size = (tmp_path / "000010.seg").stat().st_size
        store.set("c", "3")
        assert (tmp_path / "000010.seg").stat().st_size > size


@pytest.mark.parametrize("name", ["000003.seg.tmp", "1.seg", "0000001.seg", "notes", "123456.seg.bak"])
def test_recovery_ignores_unmatched_files(tmp_path: Path, name: str) -> None:
    ignored = tmp_path / name
    ignored.write_bytes(b"not a valid record" * 2)
    with KVStore(tmp_path) as store:
        assert store.stats() == Stats(0, 0, 0, 0, 1, 0)
        store.set("a", "1")
        compact(store)
    assert ignored.read_bytes() == b"not a valid record" * 2


@pytest.mark.parametrize("tail", [b"K", encode_record("partial", "value")[:-1]])
def test_recovery_tail_stats_and_subsequent_writes(tmp_path: Path, tail: bytes) -> None:
    path = tmp_path / "000001.seg"
    original = encode_record("a", "old") + tail
    path.write_bytes(original)
    with KVStore(tmp_path) as store:
        assert store.stats() == Stats(1, 0, 1, 0, 1, len(original))
        store.set("a", "new")
        store.set("b", "")
        assert path.read_bytes() == original
    with KVStore(tmp_path) as store:
        assert store.get("a") == "new" and store.get("b") == ""
        assert store.stats().total_records == 3


def test_recovery_continues_after_older_truncated_tail(tmp_path: Path) -> None:
    (tmp_path / "000001.seg").write_bytes(encode_record("a", "1") + b"KV")
    (tmp_path / "000002.seg").write_bytes(encode_record("b", "2"))
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b"]
        assert store.stats().total_records == 2
        assert store.stats().bytes_on_disk == 36


def test_store_reports_corruption_and_closes_files(tmp_path: Path) -> None:
    (tmp_path / "000001.seg").write_bytes(encode_record("a", "1"))
    bad = tmp_path / "000002.seg"
    bad.write_bytes(_raw(crc=0))
    with pytest.raises(CorruptSegmentError) as caught:
        KVStore(tmp_path)
    assert caught.value.path == bad and caught.value.offset == 0
    for path in tmp_path.iterdir():
        path.unlink()


def test_stats_count_superseded_records_and_latest_tombstones(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "")
        store.delete("a")
        assert store.stats() == Stats(1, 1, 4, 2, 1, 66)
        store.set("a", "")
        assert store.stats() == Stats(2, 0, 5, 3, 1, 82)


@pytest.mark.parametrize("operation", [
    lambda store: store.set("a", "1"), lambda store: store.get("a"),
    lambda store: store.delete("a"), lambda store: store.keys(),
    lambda store: store.stats(), lambda store: store.__enter__(),
    lambda store: compact(store),
])
def test_closed_store_rejects_operations(tmp_path: Path, operation: object) -> None:
    store = KVStore(tmp_path)
    store.close()
    store.close()
    with pytest.raises(ValueError, match="closed"):
        operation(store)  # type: ignore[operator]


def test_context_manager_closes_after_exception(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    with pytest.raises(RuntimeError):
        with store:
            raise RuntimeError("test")
    with pytest.raises(ValueError, match="closed"):
        store.keys()


def test_compaction_drops_dead_records_and_tombstones(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        store.set("a", "")
        store.set("b", "")
        store.set("a", "new")
        store.delete("b")
        store.set("c", "")
        before = store.stats()
        keys = store.keys()
        result = compact(store)
        assert isinstance(result, CompactionResult)
        assert result == CompactionResult(before.segment_count, 2, 3, before.bytes_on_disk - 35)
        assert store.keys() == keys == ["a", "c"]
        assert store.get("a") == "new" and store.get("c") == ""
        assert store.get("b") is None
        assert store.stats() == Stats(2, 0, 2, 0, 1, 35)
        assert [path.name for path in tmp_path.iterdir()] == ["000004.seg"]
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "c"] and store.get("b") is None


def test_compaction_preserves_rewrite_order(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        for key in ("a", "b", "c", "a", "b"):
            store.set(key, key)
        compact(store)
        assert store.keys() == ["c", "a", "b"]
        assert store.stats().dead_records == 0
        store.set("c", "updated")
        assert store.keys() == ["a", "b", "c"]


def test_compaction_empty_store_creates_next_segment(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        assert compact(store) == CompactionResult(1, 0, 0, 0)
        assert store.stats() == Stats(0, 0, 0, 0, 1, 0)
        assert (tmp_path / "000002.seg").exists()
        store.set("a", "")
        assert (tmp_path / "000002.seg").stat().st_size == 16


def test_compaction_all_deleted(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "")
        store.delete("a")
        assert compact(store) == CompactionResult(1, 0, 2, 32)
        assert store.keys() == []
        assert store.stats() == Stats(0, 0, 0, 0, 1, 0)
    with KVStore(tmp_path) as store:
        assert store.get("a") is None


def test_compaction_reclaims_truncated_tail(tmp_path: Path) -> None:
    (tmp_path / "000001.seg").write_bytes(encode_record("a", "") + b"KVR")
    with KVStore(tmp_path) as store:
        assert compact(store) == CompactionResult(1, 1, 0, 3)
        assert store.stats().bytes_on_disk == 16


def test_writes_after_compaction_obey_rollover(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        store.set("a", "")
        compact(store)
        store.set("b", "")
        assert store.stats().segment_count == 1
        store.set("c", "")
        assert store.stats().segment_count == 2
        assert (tmp_path / "000003.seg").exists()
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b", "c"]


def test_compaction_ignores_rollover_limit(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        for key in ("a", "b", "c"):
            store.set(key, "")
        assert compact(store) == CompactionResult(3, 3, 0, 0)
        assert store.stats().segment_count == 1
        assert (tmp_path / "000004.seg").stat().st_size == 48
        store.set("d", "")
        assert (tmp_path / "000005.seg").exists()


def test_failed_compaction_replace_preserves_old_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_replace(source: Path, destination: Path) -> None:
        assert source.name == "000002.seg.tmp"
        assert destination.name == "000002.seg"
        assert (tmp_path / "000001.seg").exists()
        raise OSError("simulated replace failure")

    with KVStore(tmp_path) as store:
        store.set("a", "old")
        store.set("a", "new")
        before = store.stats()
        with monkeypatch.context() as patch:
            patch.setattr(os, "replace", fail_replace)
            with pytest.raises(OSError, match="simulated"):
                compact(store)
        assert store.stats() == before and store.get("a") == "new"
    with KVStore(tmp_path) as store:
        assert store.stats() == before
        assert compact(store).records_written == 1
        assert store.get("a") == "new"
        assert not (tmp_path / "000002.seg.tmp").exists()


def test_compaction_partial_cleanup_preserves_deletion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_unlink = Path.unlink

    def fail_second(path: Path, missing_ok: bool = False) -> None:
        if path.name == "000002.seg":
            raise OSError("simulated deletion failure")
        original_unlink(path, missing_ok=missing_ok)

    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("deleted", "value")
        store.delete("deleted")
        store.set("live", "")
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", fail_second)
            with pytest.raises(OSError, match="simulated"):
                compact(store)
        assert store.get("deleted") is None and store.get("live") == ""
        assert store.stats().total_records == 3
    with KVStore(tmp_path) as store:
        assert store.keys() == ["live"]
        compact(store)
        assert store.stats().tombstones == 0


def test_cli_set_get_list_stats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "a", "bc"]) == 0
    assert capsys.readouterr().out == ""
    assert main([str(tmp_path), "get", "a"]) == 0
    assert capsys.readouterr().out == "bc\n"
    assert main([str(tmp_path), "list"]) == 0
    assert capsys.readouterr().out == "a\n"
    assert main([str(tmp_path), "stats"]) == 0
    output = capsys.readouterr()
    assert output.out == "live_keys=1 tombstones=0 total_records=1 dead_records=0 segment_count=1 bytes_on_disk=18\n"
    assert output.err == ""


def test_cli_empty_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "empty", ""]) == 0
    assert main([str(tmp_path), "get", "empty"]) == 0
    assert capsys.readouterr().out == "\n"


def test_cli_missing_and_delete_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "get", "missing"]) == 1
    assert main([str(tmp_path), "delete", "missing"]) == 1
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert main([str(tmp_path), "delete", "a"]) == 0
    assert main([str(tmp_path), "delete", "a"]) == 1
    assert main([str(tmp_path), "get", "a"]) == 1
    assert main([str(tmp_path), "list"]) == 0
    output = capsys.readouterr()
    assert output.out == output.err == ""


@pytest.mark.parametrize("args", [
    [], ["unknown"], ["get"], ["set", "a"], ["get", "a", "extra"], ["list", "extra"],
    ["--max-segment-bytes", "no", "stats"], ["--max-segment-bytes", "0", "stats"],
    ["--max-segment-bytes", "15", "stats"], ["--max-segment-bytes", "-2", "stats"],
])
def test_cli_usage_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]) -> None:
    assert main([str(tmp_path), *args]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err
    assert not list(tmp_path.iterdir())


def test_cli_store_validation_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "k" * 65536, "v"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "UTF-8" in output.err


def test_cli_corruption_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("ok", "v") + _raw(crc=0))
    assert main([str(tmp_path), "list"]) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert path.name in output.err and "18" in output.err


def test_cli_compaction_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert main([str(tmp_path), "set", "a", "2"]) == 0
    assert main([str(tmp_path), "compact"]) == 0
    output = capsys.readouterr()
    assert output.out == "removed=1 written=1 dropped=1 reclaimed=17\n"
    assert output.err == ""


def test_cli_global_segment_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for key in ("a", "b"):
        assert main(["--max-segment-bytes", "16", str(tmp_path), "set", key, ""]) == 0
    assert len(list(tmp_path.glob("*.seg"))) == 2
    assert capsys.readouterr().out == ""


def test_cli_module_entry_point(tmp_path: Path) -> None:
    prefix = [sys.executable, "-B", "-m", "kvstore", str(tmp_path)]
    for args, code, output in [
        (["set", "a", "1"], 0, ""), (["get", "a"], 0, "1\n"),
        (["get", "zz"], 1, ""), (["list"], 0, "a\n"),
        (["get"], 2, ""),
    ]:
        result = subprocess.run(prefix + args, capture_output=True, text=True, check=False)
        assert result.returncode == code
        assert result.stdout == output
        assert bool(result.stderr) == (code == 2)
    (tmp_path / "000001.seg").write_bytes(_raw(crc=0))
    result = subprocess.run(prefix + ["stats"], capture_output=True, text=True, check=False)
    assert result.returncode == 3 and result.stdout == "" and result.stderr
