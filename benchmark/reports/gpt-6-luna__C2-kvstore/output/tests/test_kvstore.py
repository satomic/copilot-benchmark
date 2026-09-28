import struct
import subprocess
import sys
import zlib

import pytest

from kvstore import (
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    Index,
    KVStore,
    Location,
    Segment,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main


def test_record_round_trip():
    blob = encode_record("key", "value")
    assert decode_record(blob) == ("key", "value", len(blob))


def test_record_empty_value():
    assert decode_record(encode_record("k", "")) == ("k", "", 16)


def test_record_tombstone():
    assert decode_record(encode_record("k", None)) == ("k", None, 16)


def test_empty_value_differs_from_tombstone():
    assert encode_record("k", "") != encode_record("k", None)


def test_record_utf8_round_trip():
    assert decode_record(encode_record("雪", "☃"))[:2] == ("雪", "☃")


def test_record_rejects_non_string_key():
    with pytest.raises(TypeError):
        encode_record(b"k", "v")


def test_record_rejects_non_string_value():
    with pytest.raises(TypeError):
        encode_record("k", 3)


def test_record_rejects_empty_key():
    with pytest.raises(ValueError):
        encode_record("", "v")


def test_record_rejects_oversized_key():
    with pytest.raises(ValueError):
        encode_record("x" * 65536, "v")


def test_record_incomplete_header():
    with pytest.raises(IncompleteRecordError):
        decode_record(b"KVR")


def test_record_incomplete_body():
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("k", "value")[:-1])


def test_record_bad_magic():
    blob = bytearray(encode_record("k", "v"))
    blob[0] = 0
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_unknown_flags():
    blob = bytearray(encode_record("k", "v"))
    blob[4] = 2
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_zero_key_length():
    blob = bytearray(encode_record("k", "v"))
    blob[5:7] = b"\0\0"
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_tombstone_with_value_length():
    blob = bytearray(encode_record("k", None))
    blob[7:11] = struct.pack(">I", 1)
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_crc_mismatch():
    blob = bytearray(encode_record("k", "v"))
    blob[-1] ^= 1
    with pytest.raises(CorruptRecordError, match="CRC"):
        decode_record(bytes(blob))


def test_record_invalid_utf8_after_crc():
    blob = bytearray(encode_record("k", "v"))
    blob[-1] = 255
    blob[11:15] = struct.pack(">I", zlib.crc32(blob[15:]))
    with pytest.raises(CorruptRecordError, match="UTF-8"):
        decode_record(bytes(blob))


def test_segment_appends_and_scans(tmp_path):
    segment = Segment(tmp_path / "000001.seg", 1)
    assert segment.append(encode_record("a", "1")) == 0
    assert list(segment.scan()) == [("a", "1", 0)]
    segment.close()


def test_segment_incomplete_tail_is_ignored(tmp_path):
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "1") + b"KVR")
    assert list(Segment(path, 1).scan()) == [("a", "1", 0)]


def test_segment_corruption_has_path_and_offset(tmp_path):
    path = tmp_path / "000001.seg"
    blob = bytearray(encode_record("a", "1"))
    blob[0] = 0
    path.write_bytes(bytes(blob))
    segment = Segment(path, 1)
    with pytest.raises(CorruptSegmentError) as error:
        list(segment.scan())
    assert error.value.path == path
    assert error.value.offset == 0
    assert path.name in str(error.value) and "0" in str(error.value)


def test_index_live_order_moves_updated_key():
    index = Index()
    index.put("a", Location(1, 0), tombstone=False)
    index.put("b", Location(1, 10), tombstone=False)
    index.put("a", Location(1, 20), tombstone=False)
    assert index.live_keys() == ["b", "a"]


def test_index_tombstone_hides_location():
    index = Index()
    index.put("a", Location(1, 0), tombstone=False)
    index.put("a", Location(1, 10), tombstone=True)
    assert index.get("a") is None
    assert index.tombstone_count() == 1
    assert len(index) == 0


def test_store_persists_after_reopen(tmp_path):
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.close()
    reopened = KVStore(tmp_path)
    assert reopened.get("a") == "1"


def test_store_empty_value_is_live(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "")
        assert store.get("a") == ""
        assert store.keys() == ["a"]


def test_store_delete_returns_true_once(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.delete("a") is True
        assert store.delete("a") is False


def test_store_noop_delete_does_not_grow_log(tmp_path):
    with KVStore(tmp_path) as store:
        before = store.stats().bytes_on_disk
        assert store.delete("absent") is False
        assert store.stats().bytes_on_disk == before


def test_store_recovers_truncated_tail_and_preserves_bytes(tmp_path):
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "1") + b"KVR")
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"
        assert store.stats().bytes_on_disk == path.stat().st_size
        store.set("b", "2")
        assert store.get("b") == "2"
        assert store.stats().segment_count == 2


def test_store_reports_crc_mismatch_at_tail(tmp_path):
    blob = bytearray(encode_record("a", "1"))
    blob[-1] ^= 1
    (tmp_path / "000001.seg").write_bytes(blob)
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)


def test_store_rolls_over_when_record_would_exceed_limit(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=20) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 2


def test_store_exact_limit_fits(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=17) as store:
        store.set("a", "1")
        assert store.stats().segment_count == 1
        assert store.stats().bytes_on_disk == 17


def test_store_oversized_record_fits_empty_segment(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("a", "large")
        assert store.get("a") == "large"
        assert store.stats().segment_count == 1


def test_store_keys_follow_latest_write_order(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        assert store.keys() == ["b", "a"]


def test_store_validates_key_type_before_write(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set(b"a", "1")
        assert store.stats().total_records == 0


def test_store_validates_value_type_before_write(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set("a", 1)
        assert store.stats().total_records == 0


def test_store_validates_encoded_key_length(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.set("雪" * 22000, "v")
        assert store.stats().total_records == 0


def test_store_rejects_small_segment_limit(tmp_path):
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=15)


def test_store_closed_operations_raise(tmp_path):
    store = KVStore(tmp_path)
    store.close()
    store.close()
    with pytest.raises(ValueError):
        store.get("a")


def test_store_stats_dead_records(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.delete("a")
        stats = store.stats()
        assert (stats.live_keys, stats.tombstones, stats.total_records, stats.dead_records) == (
            0, 1, 3, 2
        )


def test_store_ignores_nonsegment_files(tmp_path):
    (tmp_path / "000003.seg.tmp").write_bytes(b"ignored")
    (tmp_path / "notes.txt").write_bytes(b"ignored")
    with KVStore(tmp_path) as store:
        assert store.stats().segment_count == 1


def test_compaction_keeps_live_keys_in_order(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        store.delete("b")
        store.set("c", "4")
        assert store.keys() == ["a", "c"]
        result = compact(store)
        assert store.keys() == ["a", "c"]
        assert store.get("a") == "3"
        assert result.records_written == 2


def test_compaction_drops_tombstones_and_old_records(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.delete("a")
        result = compact(store)
        assert result.records_dropped == 3
        assert store.stats().tombstones == 0
        assert store.stats().total_records == 0


def test_compaction_creates_empty_segment(tmp_path):
    with KVStore(tmp_path) as store:
        result = compact(store)
        assert result.records_written == 0
        assert store.stats().segment_count == 1
        assert store.keys() == []


def test_compaction_replaces_stale_temporary_file(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        (tmp_path / "000002.seg.tmp").write_bytes(b"stale partial data")
        compact(store)
        assert store.get("a") == "1"
        rewritten = Segment(tmp_path / "000002.seg", 2)
        assert list(rewritten.scan()) == [("a", "1", 0)]
        rewritten.close()


def test_cli_set_get_and_missing(tmp_path, capsys):
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert main([str(tmp_path), "get", "a"]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main([str(tmp_path), "get", "missing"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_delete_exit_codes(tmp_path):
    assert main([str(tmp_path), "delete", "missing"]) == 1
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert main([str(tmp_path), "delete", "a"]) == 0


def test_cli_list_and_stats_format(tmp_path, capsys):
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert main([str(tmp_path), "set", "b", "2"]) == 0
    assert main([str(tmp_path), "list"]) == 0
    assert capsys.readouterr().out == "a\nb\n"
    assert main([str(tmp_path), "stats"]) == 0
    assert capsys.readouterr().out == (
        "live_keys=2 tombstones=0 total_records=2 dead_records=0 "
        "segment_count=1 bytes_on_disk=34\n"
    )


def test_cli_usage_error_exit_two(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path), "set", "a"])
    assert error.value.code == 2
    assert capsys.readouterr().err


def test_cli_store_validation_error_exit_two(tmp_path, capsys):
    assert main(["--max-segment-bytes", "15", str(tmp_path), "stats"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err


def test_cli_corruption_exit_three(tmp_path, capsys):
    blob = bytearray(encode_record("a", "1"))
    blob[-1] ^= 1
    (tmp_path / "000001.seg").write_bytes(blob)
    assert main([str(tmp_path), "stats"]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "000001.seg" in captured.err


def test_module_cli_round_trip(tmp_path):
    root = str(tmp_path)
    command = [sys.executable, "-m", "kvstore", root]
    set_result = subprocess.run(command + ["set", "a", "1"], capture_output=True, text=True)
    get_result = subprocess.run(command + ["get", "a"], capture_output=True, text=True)
    assert set_result.returncode == 0 and set_result.stdout == ""
    assert get_result.returncode == 0 and get_result.stdout == "1\n"
