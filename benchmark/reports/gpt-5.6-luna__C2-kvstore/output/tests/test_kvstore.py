from pathlib import Path
import subprocess
import sys

import pytest

from kvstore import *


def test_encode_decode_value():
    blob = encode_record("a", "b")
    assert decode_record(blob) == ("a", "b", len(blob))


def test_empty_value_differs_from_tombstone():
    assert decode_record(encode_record("a", ""))[1] == ""
    assert decode_record(encode_record("a", None))[1] is None


def test_unicode_round_trip():
    assert decode_record(encode_record("键", "值"))[:2] == ("键", "值")


def test_bad_magic():
    with pytest.raises(CorruptRecordError):
        decode_record(b"BAD!" + encode_record("a", "b")[4:])


def test_incomplete_header():
    with pytest.raises(IncompleteRecordError):
        decode_record(b"KVR1")


def test_incomplete_payload():
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("a", "b")[:-1])


def test_crc_error():
    blob = bytearray(encode_record("a", "b"))
    blob[-1] ^= 1
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_key_validation():
    with pytest.raises(ValueError):
        encode_record("", "x")


def test_index_order():
    index = Index()
    index.put("a", Location(1, 2), tombstone=False)
    index.put("b", Location(1, 1), tombstone=False)
    assert index.live_keys() == ["b", "a"]


def test_index_rewrite_moves_key():
    index = Index()
    index.put("a", Location(1, 1), tombstone=False)
    index.put("b", Location(1, 2), tombstone=False)
    index.put("a", Location(1, 3), tombstone=False)
    assert index.live_keys() == ["b", "a"]


def test_index_tombstone():
    index = Index()
    index.put("a", Location(1, 1), tombstone=True)
    assert index.get("a") is None and index.tombstone_count() == 1


def test_new_store(tmp_path):
    store = KVStore(tmp_path)
    assert store.keys() == []
    store.close()


def test_set_get(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.get("a") == "1"


def test_empty_get(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "")
        assert store.get("a") == ""


def test_delete(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.delete("a") and store.get("a") is None


def test_delete_missing_does_not_grow(tmp_path):
    with KVStore(tmp_path) as store:
        before = store.stats().total_records
        assert not store.delete("a")
        assert store.stats().total_records == before


def test_delete_tombstone_does_not_grow(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.delete("a")
        before = store.stats().total_records
        assert not store.delete("a")
        assert store.stats().total_records == before


def test_reopen(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"


def test_recovery_truncated_tail(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    path = tmp_path / "000001.seg"
    path.write_bytes(path.read_bytes() + b"partial")
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"


def test_recovery_crc_corruption(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    path = tmp_path / "000001.seg"
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)


def test_rollover(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("a", "123")
        store.set("b", "456")
        assert store.stats().segment_count == 2


def test_exact_fit(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=18) as store:
        store.set("a", "123")
        assert store.stats().segment_count == 1


def test_keys_order(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        assert store.keys() == ["b", "a"]


def test_stats(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.delete("a")
        stats = store.stats()
        assert (stats.live_keys, stats.tombstones, stats.total_records, stats.dead_records) == (0, 1, 3, 2)


def test_close_idempotent(tmp_path):
    store = KVStore(tmp_path)
    store.close()
    store.close()
    with pytest.raises(ValueError):
        store.keys()


def test_context_manager(tmp_path):
    store = KVStore(tmp_path)
    with store:
        assert store.keys() == []
    with pytest.raises(ValueError):
        store.get("a")


def test_ignored_files(tmp_path):
    (tmp_path / "junk.seg").write_bytes(b"bad")
    (tmp_path / "000002.seg.tmp").write_bytes(b"bad")
    with KVStore(tmp_path) as store:
        assert store.keys() == []


def test_compaction(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.delete("a")
        result = compact(store)
        assert result.records_written == 1
        assert store.keys() == ["b"]


def test_compaction_empty(tmp_path):
    with KVStore(tmp_path) as store:
        result = compact(store)
        assert result.records_written == 0
        assert store.stats().segment_count == 1


def test_compaction_order(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        compact(store)
        assert store.keys() == ["b", "a"]


def test_cli_set_get(tmp_path):
    run = lambda *a: subprocess.run([sys.executable, "-m", "kvstore", str(tmp_path), *a],
                                    capture_output=True, text=True)
    assert run("set", "a", "1").returncode == 0
    result = run("get", "a")
    assert result.returncode == 0 and result.stdout == "1\n"


def test_cli_absent(tmp_path):
    result = subprocess.run([sys.executable, "-m", "kvstore", str(tmp_path), "get", "x"],
                            capture_output=True, text=True)
    assert result.returncode == 1 and result.stdout == ""


def test_cli_delete_exit(tmp_path):
    base = [sys.executable, "-m", "kvstore", str(tmp_path)]
    subprocess.run(base + ["set", "a", "1"], check=True)
    assert subprocess.run(base + ["delete", "a"]).returncode == 0
    assert subprocess.run(base + ["delete", "a"]).returncode == 1


def test_cli_list(tmp_path):
    base = [sys.executable, "-m", "kvstore", str(tmp_path)]
    subprocess.run(base + ["set", "a", "1"], check=True)
    result = subprocess.run(base + ["list"], capture_output=True, text=True)
    assert result.stdout == "a\n"


def test_cli_stats(tmp_path):
    base = [sys.executable, "-m", "kvstore", str(tmp_path)]
    result = subprocess.run(base + ["stats"], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.startswith("live_keys=0 ")


def test_cli_usage_error(tmp_path):
    result = subprocess.run([sys.executable, "-m", "kvstore", str(tmp_path), "set", "a"],
                            capture_output=True, text=True)
    assert result.returncode == 2 and result.stdout == ""


def test_cli_bad_max(tmp_path):
    result = subprocess.run([sys.executable, "-m", "kvstore", "--max-segment-bytes", "1",
                             str(tmp_path), "list"], capture_output=True, text=True)
    assert result.returncode == 2


def test_segment_append_scan(tmp_path):
    segment = Segment(tmp_path / "x.seg", 1)
    segment.append(encode_record("a", "b"))
    assert list(segment.scan())[0][:2] == ("a", "b")
    segment.close()


def test_invalid_types(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set(b"a", "b")
        with pytest.raises(TypeError):
            store.set("a", 1)


def test_long_utf8_key(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.set("界" * 22000, "x")
