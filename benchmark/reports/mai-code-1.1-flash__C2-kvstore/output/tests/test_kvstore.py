import os
import struct
import sys
from pathlib import Path

import pytest

from kvstore import (
    CompactionResult,
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    KVStore,
    Location,
    Segment,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main
from kvstore.index import Index


def test_record_round_trip_value() -> None:
    blob = encode_record("a", "1")
    key, value, size = decode_record(blob)
    assert (key, value, size) == ("a", "1", len(blob))


def test_record_round_trip_empty_value() -> None:
    blob = encode_record("empty", "")
    key, value, size = decode_record(blob)
    assert (key, value, size) == ("empty", "", len(blob))


def test_record_round_trip_tombstone() -> None:
    blob = encode_record("gone", None)
    key, value, size = decode_record(blob)
    assert (key, value, size) == ("gone", None, len(blob))


def test_record_bad_magic_raises() -> None:
    blob = b"BAD!" + b"\x00" + b"\x00\x01" + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00"
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_record_unknown_flag_raises() -> None:
    blob = encode_record("a", "b")
    blob = blob[:4] + b"\x02" + blob[5:]
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_record_zero_key_len_raises() -> None:
    blob = encode_record("a", "b")
    blob = blob[:5] + b"\x00\x00" + blob[7:]
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_record_tombstone_value_len_raises() -> None:
    blob = encode_record("a", None)
    blob = blob[:7] + struct.pack(">I", 3) + blob[11:]
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_record_crc_mismatch_raises() -> None:
    blob = bytearray(encode_record("a", "1"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_invalid_utf8_key_raises() -> None:
    key_bytes = b"\xff"
    value_bytes = b"x"
    crc = struct.pack(">I", (0xFFFFFFFF & __import__('zlib').crc32(key_bytes + value_bytes)))
    blob = b"KVR1\x00" + struct.pack(">H", len(key_bytes)) + struct.pack(">I", len(value_bytes)) + crc + key_bytes + value_bytes
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_record_invalid_utf8_value_raises() -> None:
    key_bytes = b"a"
    value_bytes = b"\xff"
    crc = struct.pack(">I", (0xFFFFFFFF & __import__('zlib').crc32(key_bytes + value_bytes)))
    blob = b"KVR1\x00" + struct.pack(">H", len(key_bytes)) + struct.pack(">I", len(value_bytes)) + crc + key_bytes + value_bytes
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_record_incomplete_raises() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(b"KVR1")


def test_segment_append_and_scan(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    blob = encode_record("hello", "world")
    offset = seg.append(blob)
    assert offset == 0
    assert list(seg.scan()) == [("hello", "world", 0)]
    seg.close()


def test_segment_truncated_tail_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    seg.append(encode_record("a", "b"))
    with open(path, "ab") as handle:
        handle.write(b"\x00\x01\x02")
    assert list(seg.scan()) == [("a", "b", 0)]
    seg.close()


def test_segment_corrupt_last_record_raises(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    seg.append(b"KVR1\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    with pytest.raises(CorruptSegmentError):
        list(seg.scan())
    seg.close()


def test_index_put_and_get() -> None:
    idx = Index()
    loc = Location(1, 7)
    idx.put("a", loc, tombstone=False)
    assert idx.get("a") == loc
    assert idx.get("x") is None


def test_index_live_keys_order() -> None:
    idx = Index()
    idx.put("b", Location(2, 5), tombstone=False)
    idx.put("a", Location(1, 2), tombstone=False)
    idx.put("c", Location(1, 1), tombstone=False)
    assert idx.live_keys() == ["c", "a", "b"]


def test_index_tombstone_count() -> None:
    idx = Index()
    idx.put("a", Location(1, 1), tombstone=True)
    idx.put("b", Location(2, 2), tombstone=False)
    idx.put("c", Location(2, 3), tombstone=True)
    assert idx.tombstone_count() == 2
    assert len(idx) == 1


def test_store_set_and_get(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    assert store.get("a") == "1"
    assert store.keys() == ["a"]
    store.close()


def test_store_empty_string_value_is_live(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("empty", "")
    assert store.get("empty") == ""
    assert store.keys() == ["empty"]
    store.close()


def test_store_delete_missing_is_false(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    assert store.delete("missing") is False
    store.close()


def test_store_delete_noop_writes_nothing(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    assert store.delete("missing") is False
    assert store.stats().total_records == 0
    store.close()


def test_store_delete_live_key(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    assert store.delete("a") is True
    assert store.get("a") is None
    assert store.keys() == []
    store.close()


def test_store_delete_already_tombstoned_false(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.delete("a")
    assert store.delete("a") is False
    store.close()


def test_store_rollover(tmp_path: Path) -> None:
    store = KVStore(tmp_path, max_segment_bytes=32)
    store.set("a", "1111111111111111")
    store.set("b", "2222222222222222")
    assert store.stats().segment_count == 2
    assert store.keys() == ["a", "b"]
    store.close()


def test_store_exact_fit_does_not_rollover(tmp_path: Path) -> None:
    store = KVStore(tmp_path, max_segment_bytes=64)
    store.set("a", "1234567890")
    store.set("b", "123456")
    assert store.stats().segment_count == 1
    store.close()


def test_store_recovery_on_reopen(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("b", "2")
    store.close()
    reopened = KVStore(tmp_path)
    assert reopened.get("a") == "1"
    assert reopened.get("b") == "2"
    assert reopened.keys() == ["a", "b"]
    reopened.close()


def test_store_recovery_ignores_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "z"))
    (tmp_path / "000003.seg.tmp").write_bytes(b"junk")
    store = KVStore(tmp_path)
    assert store.get("a") == "z"
    store.close()


def test_store_stats_counts_dead_records(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("a", "2")
    store.delete("a")
    stats = store.stats()
    assert stats.live_keys == 0
    assert stats.tombstones == 1
    assert stats.total_records == 3
    assert stats.dead_records == 2
    store.close()


def test_store_stats_bytes_on_disk(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "b")
    assert store.stats().bytes_on_disk >= 15 + 1 + 1
    store.close()


def test_store_closed_raises_value_error(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.close()
    with pytest.raises(ValueError):
        store.get("a")


def test_compaction_rewrites_live_keys(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("b", "2")
    store.set("b", "3")
    store.delete("a")
    result = compact(store)
    assert isinstance(result, CompactionResult)
    assert result.records_written == 1
    assert result.records_dropped == 3
    assert store.keys() == ["b"]
    store.close()


def test_compaction_preserves_key_order(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("b", "2")
    store.set("a", "1")
    store.set("c", "3")
    compact(store)
    assert store.keys() == ["b", "a", "c"]
    store.close()


def test_cli_set_get_list_stats_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([str(tmp_path), "set", "a", "1"])
    assert rc == 0
    assert capsys.readouterr().out == ""
    rc = main([str(tmp_path), "get", "a"])
    assert rc == 0
    assert capsys.readouterr().out == "1\n"
    rc = main([str(tmp_path), "list"])
    assert rc == 0
    assert capsys.readouterr().out == "a\n"
    rc = main([str(tmp_path), "stats"])
    assert rc == 0
    assert "live_keys=1 tombstones=0 total_records=1 dead_records=0" in capsys.readouterr().out


def test_cli_get_missing_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([str(tmp_path), "get", "missing"])
    assert rc == 1
    assert capsys.readouterr().out == ""


def test_cli_delete_missing_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([str(tmp_path), "delete", "missing"])
    assert rc == 1
    assert capsys.readouterr().out == ""


def test_cli_usage_error_returns_2(tmp_path: Path) -> None:
    assert main([str(tmp_path), "bogus"]) == 2


def test_cli_overlong_key_returns_2(tmp_path: Path) -> None:
    assert main([str(tmp_path), "set", "x" * 70000, "v"]) == 2


def test_cli_corrupt_segment_returns_3(tmp_path: Path) -> None:
    segment = tmp_path / "000001.seg"
    segment.write_bytes(b"BAD!\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    assert main([str(tmp_path), "list"]) == 3


def test_cli_max_segment_bytes_flag(tmp_path: Path) -> None:
    rc = main(["--max-segment-bytes", "16", str(tmp_path), "set", "a", "1"])
    assert rc == 0


def test_cli_compact_outputs_result(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([str(tmp_path), "set", "a", "1"])
    rc = main([str(tmp_path), "compact"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "removed=" in out and "written=" in out and "reclaimed=" in out


def test_segment_path_name_str_contains_offset() -> None:
    err = CorruptSegmentError(Path("000001.seg"), 42, "bad magic")
    text = str(err)
    assert "000001.seg" in text
    assert "42" in text


def test_store_keys_order_after_rewrite(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("b", "2")
    store.set("a", "1")
    store.set("b", "3")
    assert store.keys() == ["a", "b"]
    store.close()


def test_store_get_with_missing_key_is_none(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    assert store.get("x") is None
    store.close()


def test_store_ignores_non_matching_segment_files(tmp_path: Path) -> None:
    (tmp_path / "000001.seg").write_bytes(encode_record("a", "1"))
    (tmp_path / "000002.seg.tmp").write_bytes(encode_record("b", "2"))
    (tmp_path / "notes.txt").write_text("ignore me")
    store = KVStore(tmp_path)
    assert store.keys() == ["a"]
    store.close()
