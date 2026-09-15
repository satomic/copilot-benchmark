import io
import os
import pathlib
import struct
import sys
import zlib
import pytest

from kvstore import (
    CompactionResult,
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    Index,
    KVStore,
    Location,
    Segment,
    Stats,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main


def test_record_codec_roundtrip() -> None:
    blob = encode_record("greeting", "hello world")
    key, val, size = decode_record(blob)
    assert key == "greeting"
    assert val == "hello world"
    assert size == len(blob)


def test_record_tombstone_vs_empty_value() -> None:
    tomb_blob = encode_record("k", None)
    assert tomb_blob[4] == 0x01
    assert struct.unpack_from(">I", tomb_blob, 7)[0] == 0
    t_key, t_val, t_size = decode_record(tomb_blob)
    assert t_key == "k"
    assert t_val is None
    assert t_size == len(tomb_blob)

    empty_blob = encode_record("k", "")
    assert empty_blob[4] == 0x00
    assert struct.unpack_from(">I", empty_blob, 7)[0] == 0
    e_key, e_val, e_size = decode_record(empty_blob)
    assert e_key == "k"
    assert e_val == ""
    assert e_size == len(empty_blob)
    assert tomb_blob != empty_blob


def test_record_encode_type_and_value_validation() -> None:
    with pytest.raises(TypeError):
        encode_record(123, "val")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        encode_record(b"k", "val")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        encode_record("k", 123)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        encode_record("k", b"val")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        encode_record("", "val")
    oversized_key = "x" * 65536
    with pytest.raises(ValueError):
        encode_record(oversized_key, "val")
    cjk_key = "\u4e00" * 22000
    with pytest.raises(ValueError):
        encode_record(cjk_key, "val")


def test_record_decode_structural_and_crc_errors() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(b"KVR1\x00")

    bad_magic = b"ABCD" + b"\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00k"
    with pytest.raises(CorruptRecordError):
        decode_record(bad_magic)

    bad_flags = b"KVR1\x05\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00k"
    with pytest.raises(CorruptRecordError):
        decode_record(bad_flags)

    zero_key_len = b"KVR1\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    with pytest.raises(CorruptRecordError):
        decode_record(zero_key_len)

    tomb_with_val = b"KVR1\x01\x00\x01\x00\x00\x00\x05\x00\x00\x00\x00khello"
    with pytest.raises(CorruptRecordError):
        decode_record(tomb_with_val)

    valid = encode_record("abc", "def")
    with pytest.raises(IncompleteRecordError):
        decode_record(valid[:-1])

    corrupt_payload = bytearray(valid)
    corrupt_payload[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(corrupt_payload))


def test_record_decode_invalid_utf8() -> None:
    raw_key = b"\xff\xfe"
    flags = 0x00
    key_len = len(raw_key)
    val_bytes = b"ok"
    val_len = len(val_bytes)
    payload = raw_key + val_bytes
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    header = struct.pack(">4sBHII", b"KVR1", flags, key_len, val_len, crc)
    with pytest.raises(CorruptRecordError):
        decode_record(header + payload)


def test_segment_append_and_size(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "000001.seg"
    seg = Segment(p, 1)
    assert seg.size == 0
    rec = encode_record("a", "1")
    offset1 = seg.append(rec)
    assert offset1 == 0
    assert seg.size == len(rec)
    offset2 = seg.append(rec)
    assert offset2 == len(rec)
    assert seg.size == 2 * len(rec)
    seg.close()


def test_segment_scan_clean(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "000001.seg"
    seg = Segment(p, 1)
    seg.append(encode_record("k1", "v1"))
    seg.append(encode_record("k2", None))
    seg.append(encode_record("k3", "v3"))
    records = list(seg.scan())
    assert len(records) == 3
    assert records[0][:2] == ("k1", "v1")
    assert records[1][:2] == ("k2", None)
    assert records[2][:2] == ("k3", "v3")
    seg.close()


def test_segment_scan_truncated_tail_partial_header(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "000001.seg"
    seg = Segment(p, 1)
    seg.append(encode_record("k1", "v1"))
    seg.append(b"KVR1\x00\x00")
    records = list(seg.scan())
    assert len(records) == 1
    assert records[0][:2] == ("k1", "v1")
    seg.close()


def test_segment_scan_truncated_tail_partial_payload(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "000001.seg"
    seg = Segment(p, 1)
    seg.append(encode_record("k1", "v1"))
    rec2 = encode_record("k2", "a very long value string")
    seg.append(rec2[:20])
    records = list(seg.scan())
    assert len(records) == 1
    assert records[0][:2] == ("k1", "v1")
    seg.close()


def test_segment_scan_crc_mismatch_at_end_is_corruption(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "000001.seg"
    seg = Segment(p, 1)
    seg.append(encode_record("k1", "v1"))
    rec2 = bytearray(encode_record("k2", "v2"))
    rec2[-1] ^= 0xFF
    seg.append(bytes(rec2))
    with pytest.raises(CorruptSegmentError) as exc_info:
        list(seg.scan())
    err = exc_info.value
    assert err.path == p
    assert err.offset == len(encode_record("k1", "v1"))
    assert p.name in str(err)
    assert str(err.offset) in str(err)
    seg.close()


def test_index_operations() -> None:
    idx = Index()
    assert len(idx) == 0
    assert idx.tombstone_count() == 0
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 20), tombstone=False)
    assert idx.get("a") == Location(1, 0)
    assert idx.get("b") == Location(1, 20)
    assert idx.get("c") is None
    assert len(idx) == 2

    idx.put("a", Location(2, 5), tombstone=True)
    assert idx.get("a") is None
    assert idx.tombstone_count() == 1
    assert len(idx) == 1
    assert idx.live_keys() == ["b"]


def test_index_live_keys_ordering() -> None:
    idx = Index()
    idx.put("x", Location(1, 10), tombstone=False)
    idx.put("y", Location(1, 30), tombstone=False)
    idx.put("z", Location(1, 50), tombstone=False)
    assert idx.live_keys() == ["x", "y", "z"]

    idx.put("x", Location(2, 0), tombstone=False)
    assert idx.live_keys() == ["y", "z", "x"]


def test_kvstore_set_and_get(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("user", "alice")
        store.set("role", "admin")
        assert store.get("user") == "alice"
        assert store.get("role") == "admin"
        assert store.get("missing") is None


def test_kvstore_empty_string_value(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("blank", "")
        res = store.get("blank")
        assert res == ""
        assert res is not None


def test_kvstore_delete_behavior(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("k1", "v1")
        assert store.delete("k1") is True
        assert store.get("k1") is None
        assert store.delete("k1") is False
        assert store.delete("never_existed") is False


def test_kvstore_delete_does_not_grow_log_on_noop(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("k1", "v1")
        st_before = store.stats()
        assert store.delete("nonexistent") is False
        st_after = store.stats()
        assert st_before.bytes_on_disk == st_after.bytes_on_disk
        assert st_before.total_records == st_after.total_records


def test_kvstore_persistence_after_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("alpha", "1")
        store.set("beta", "2")
        store.delete("alpha")

    with KVStore(tmp_path) as reopened:
        assert reopened.get("alpha") is None
        assert reopened.get("beta") == "2"
        assert reopened.keys() == ["beta"]
        st = reopened.stats()
        assert st.live_keys == 1
        assert st.tombstones == 1
        assert st.total_records == 3


def test_kvstore_rollover_on_size_limit(tmp_path: pathlib.Path) -> None:
    rec_size = len(encode_record("k1", "v"))
    with KVStore(tmp_path, max_segment_bytes=rec_size * 2) as store:
        store.set("k1", "v")
        store.set("k2", "v")
        assert store.stats().segment_count == 1
        store.set("k3", "v")
        assert store.stats().segment_count == 2
        assert store.get("k1") == "v"
        assert store.get("k2") == "v"
        assert store.get("k3") == "v"


def test_kvstore_oversized_record_fits_empty_segment(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=20) as store:
        large_val = "x" * 100
        store.set("large", large_val)
        assert store.get("large") == large_val
        assert store.stats().segment_count == 1
        store.set("next", "val")
        assert store.stats().segment_count == 2
        assert store.get("next") == "val"


def test_kvstore_ignores_non_matching_files(tmp_path: pathlib.Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "000001.seg.tmp").write_bytes(b"garbage")
    (tmp_path / "notes.txt").write_text("hello")
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.stats().segment_count == 1
        assert store.get("a") == "1"


def test_kvstore_truncated_tail_recovery(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")

    seg1 = tmp_path / "000001.seg"
    with open(seg1, "ab") as f:
        f.write(b"KVR1\x00\x00\x01\x00\x00\x00\x05")

    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"
        assert store.get("b") == "2"
        store.set("c", "3")
        assert store.get("c") == "3"


def test_kvstore_corrupt_segment_detection(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")

    seg1 = tmp_path / "000001.seg"
    data = bytearray(seg1.read_bytes())
    data[1] = 0xFF
    seg1.write_bytes(bytes(data))

    with pytest.raises(CorruptSegmentError) as exc_info:
        KVStore(tmp_path)
    assert "000001.seg" in str(exc_info.value)


def test_kvstore_closed_operations_raise_value_error(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.close()
    store.close()  # idempotent
    with pytest.raises(ValueError):
        store.set("b", "2")
    with pytest.raises(ValueError):
        store.get("a")
    with pytest.raises(ValueError):
        store.delete("a")
    with pytest.raises(ValueError):
        store.keys()
    with pytest.raises(ValueError):
        store.stats()
    with pytest.raises(ValueError):
        compact(store)


def test_kvstore_invalid_max_segment_bytes(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=15)
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=0)
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=-1)
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes="4096")  # type: ignore[arg-type]


def test_kvstore_stats_calculation(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "updated")
        store.delete("b")
        st = store.stats()
        assert st.live_keys == 1
        assert st.tombstones == 1
        assert st.total_records == 4
        assert st.dead_records == 2
        assert st.segment_count == 1
        assert st.bytes_on_disk > 0


def test_compact_removes_old_and_drops_tombstones(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=50) as store:
        store.set("k1", "v1")
        store.set("k2", "v2")
        store.delete("k1")
        store.set("k3", "v3")
        assert store.stats().segment_count >= 2
        res = compact(store)
        assert res.segments_removed >= 2
        assert res.records_written == 2
        assert res.records_dropped >= 2
        assert res.bytes_reclaimed > 0
        assert store.keys() == ["k2", "k3"]
        assert store.get("k2") == "v2"
        assert store.get("k3") == "v3"
        assert store.get("k1") is None
        st = store.stats()
        assert st.segment_count == 1
        assert st.live_keys == 2
        assert st.tombstones == 0
        assert st.dead_records == 0


def test_compact_preserves_keys_ordering(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("c", "3")
        store.set("a", "1")
        store.set("b", "2")
        store.set("c", "updated")
        order_before = store.keys()
        assert order_before == ["a", "b", "c"]
        compact(store)
        assert store.keys() == ["a", "b", "c"]
        assert store.get("a") == "1"
        assert store.get("b") == "2"
        assert store.get("c") == "updated"


def test_compact_empty_store(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        res = compact(store)
        assert res.records_written == 0
        assert store.keys() == []
        store.set("first", "val")
        assert store.get("first") == "val"


def test_cli_set_get_and_list(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    assert main([root, "set", "k1", "hello"]) == 0
    assert main([root, "get", "k1"]) == 0
    out, err = capsys.readouterr()
    assert out == "hello\n"
    assert err == ""

    assert main([root, "set", "k2", "world"]) == 0
    assert main([root, "list"]) == 0
    out, err = capsys.readouterr()
    assert out == "k1\nk2\n"
    assert err == ""


def test_cli_get_absent_exits_1(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    ret = main([root, "get", "missing"])
    assert ret == 1
    out, err = capsys.readouterr()
    assert out == ""


def test_cli_delete_exit_codes(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    main([root, "set", "target", "value"])
    capsys.readouterr()
    assert main([root, "delete", "target"]) == 0
    assert main([root, "delete", "target"]) == 1
    assert main([root, "delete", "absent"]) == 1
    out, err = capsys.readouterr()
    assert out == ""


def test_cli_stats_and_compact(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    main([root, "set", "a", "1"])
    capsys.readouterr()
    assert main([root, "stats"]) == 0
    out, err = capsys.readouterr()
    assert "live_keys=1 tombstones=0 total_records=1 dead_records=0 segment_count=1" in out
    assert main([root, "compact"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("removed=1 written=1 dropped=0")


def test_cli_usage_error_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    ret = main(["--unknown-flag"])
    assert ret == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""


def test_cli_invalid_max_segment_bytes_exits_2(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    ret = main([root, "--max-segment-bytes", "0", "list"])
    assert ret == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "positive integer" in err


def test_cli_corrupt_segment_exits_3(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    main([root, "set", "x", "y"])
    capsys.readouterr()
    seg = tmp_path / "000001.seg"
    seg.write_bytes(b"BADMAGIC" + b"\x00" * 30)
    ret = main([root, "get", "x"])
    assert ret == 3
    out, err = capsys.readouterr()
    assert out == ""
    assert "Error:" in err


def test_cli_store_value_error_exits_2(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    ret = main([root, "set", "", "value"])
    assert ret == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "Error:" in err


def test_corrupt_segment_error_details(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000002.seg"
    err = CorruptSegmentError(path, 42, "Bad CRC")
    assert isinstance(err.path, pathlib.Path)
    assert err.path == path
    assert isinstance(err.offset, int)
    assert err.offset == 42
    assert err.reason == "Bad CRC"
    assert "000002.seg" in str(err)
    assert "42" in str(err)


def test_segment_close_idempotent(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "000001.seg"
    seg = Segment(p, 1)
    seg.close()
    seg.close()
    with pytest.raises(ValueError):
        seg.append(b"test")
    with pytest.raises(ValueError):
        list(seg.scan())


def test_kvstore_exact_max_segment_bytes_boundary(tmp_path: pathlib.Path) -> None:
    # Header is 15 bytes. Key "a" (1) + Val "1" (1) = 17 bytes.
    # Total record size = 17 bytes.
    rec = encode_record("a", "1")
    rec_len = len(rec)
    with KVStore(tmp_path, max_segment_bytes=rec_len) as store:
        store.set("a", "1")
        # Exact match: size == max_segment_bytes
        assert store.stats().bytes_on_disk == rec_len
        assert store.stats().segment_count == 1
        # Next append must roll over because size(17) + n(17) = 34 > 17
        store.set("b", "2")
        assert store.stats().segment_count == 2
        assert store.get("a") == "1"
        assert store.get("b") == "2"


def test_cli_utf8_roundtrip(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    key = "clé"
    val = "valeur_€_🚀"
    assert main([root, "set", key, val]) == 0
    assert main([root, "get", key]) == 0
    out, err = capsys.readouterr()
    assert out == val + "\n"
    assert err == ""


def test_cli_no_stdout_on_failure_path(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    # 1. get non-existent key
    code = main([root, "get", "no_such_key"])
    assert code == 1
    out, _ = capsys.readouterr()
    assert out == ""

    # 2. delete non-existent key
    code = main([root, "delete", "no_such_key"])
    assert code == 1
    out, _ = capsys.readouterr()
    assert out == ""

    # 3. bad max-segment-bytes
    code = main([root, "--max-segment-bytes", "-10", "list"])
    assert code == 2
    out, _ = capsys.readouterr()
    assert out == ""

