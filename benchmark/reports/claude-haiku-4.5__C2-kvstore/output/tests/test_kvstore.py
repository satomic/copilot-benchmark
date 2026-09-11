import pytest
import pathlib
import tempfile
import kvstore
from kvstore import (
    KVStore, encode_record, decode_record,
    IncompleteRecordError, CorruptRecordError, CorruptSegmentError,
    compact
)


class TestRecordCodec:
    def test_encode_decode_roundtrip(self):
        record = encode_record("key", "value")
        key, value, size = decode_record(record)
        assert key == "key"
        assert value == "value"
        assert size == len(record)
    
    def test_empty_value(self):
        record = encode_record("key", "")
        key, value, size = decode_record(record)
        assert key == "key"
        assert value == ""
        assert size == 15 + 3
    
    def test_tombstone(self):
        record = encode_record("key", None)
        key, value, size = decode_record(record)
        assert key == "key"
        assert value is None
        assert size == 15 + 3
    
    def test_tombstone_vs_empty_value(self):
        tombstone = encode_record("key", None)
        empty = encode_record("key", "")
        assert tombstone != empty
        
        k1, v1, _ = decode_record(tombstone)
        k2, v2, _ = decode_record(empty)
        assert v1 is None
        assert v2 == ""
    
    def test_unicode_key(self):
        record = encode_record("你好", "world")
        key, value, _ = decode_record(record)
        assert key == "你好"
        assert value == "world"
    
    def test_unicode_value(self):
        record = encode_record("key", "你好世界")
        key, value, _ = decode_record(record)
        assert key == "key"
        assert value == "你好世界"
    
    def test_offset_parameter(self):
        record = encode_record("a", "1")
        record2 = encode_record("b", "2")
        combined = record + record2
        
        k1, v1, size1 = decode_record(combined, 0)
        k2, v2, size2 = decode_record(combined, size1)
        
        assert k1 == "a" and v1 == "1"
        assert k2 == "b" and v2 == "2"
    
    def test_incomplete_header(self):
        partial = b"KVR1"
        with pytest.raises(IncompleteRecordError):
            decode_record(partial)
    
    def test_incomplete_data(self):
        record = encode_record("hello", "world")
        with pytest.raises(IncompleteRecordError):
            decode_record(record[:20])
    
    def test_bad_magic(self):
        record = encode_record("key", "value")
        bad = b"XXXX" + record[4:]
        with pytest.raises(CorruptRecordError):
            decode_record(bad)
    
    def test_bad_flags(self):
        record = encode_record("key", "value")
        bad = record[:4] + b"\x99" + record[5:]
        with pytest.raises(CorruptRecordError):
            decode_record(bad)
    
    def test_zero_key_len(self):
        record = encode_record("key", "value")
        bad = record[:5] + b"\x00\x00" + record[7:]
        with pytest.raises(CorruptRecordError):
            decode_record(bad)
    
    def test_tombstone_with_value_len(self):
        record = encode_record("key", None)
        bad = record[:4] + b"\x01" + record[5:7] + b"\x00\x05" + record[9:]
        with pytest.raises(CorruptRecordError):
            decode_record(bad)
    
    def test_crc_mismatch(self):
        record = encode_record("key", "value")
        bad = record[:11] + b"\xff\xff\xff\xff" + record[15:]
        with pytest.raises(CorruptRecordError):
            decode_record(bad)
    
    def test_invalid_utf8_key(self):
        record = encode_record("key", "value")
        bad = record[:15] + b"\xff\xfe" + record[17:]
        with pytest.raises(CorruptRecordError):
            decode_record(bad)


class TestKVStore:
    def test_set_get_basic(self, tmp_path):
        store = KVStore(tmp_path)
        store.set("key", "value")
        assert store.get("key") == "value"
        store.close()
    
    def test_get_missing(self, tmp_path):
        store = KVStore(tmp_path)
        assert store.get("missing") is None
        store.close()
    
    def test_delete_present(self, tmp_path):
        store = KVStore(tmp_path)
        store.set("key", "value")
        assert store.delete("key") is True
        assert store.get("key") is None
        store.close()
    
    def test_delete_missing(self, tmp_path):
        store = KVStore(tmp_path)
        assert store.delete("missing") is False
        store.close()
    
    def test_delete_no_write_on_missing(self, tmp_path):
        store = KVStore(tmp_path)
        before = store.stats().bytes_on_disk
        store.delete("missing")
        after = store.stats().bytes_on_disk
        assert before == after
        store.close()
    
    def test_keys_ordering(self, tmp_path):
        store = KVStore(tmp_path)
        store.set("a", "1")
        store.set("b", "2")
        store.set("c", "3")
        assert store.keys() == ["a", "b", "c"]
        store.close()
    
    def test_keys_after_update(self, tmp_path):
        store = KVStore(tmp_path)
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        assert store.keys() == ["b", "a"]
        store.close()
    
    def test_context_manager(self, tmp_path):
        with KVStore(tmp_path) as store:
            store.set("key", "value")
            assert store.get("key") == "value"
        
        with pytest.raises(ValueError):
            store.set("key2", "value2")
    
    def test_persistence(self, tmp_path):
        with KVStore(tmp_path) as store:
            store.set("a", "1")
            store.set("b", "2")
        
        with KVStore(tmp_path) as store:
            assert store.get("a") == "1"
            assert store.get("b") == "2"
    
    def test_segment_rollover(self, tmp_path):
        store = KVStore(tmp_path, max_segment_bytes=100)
        for i in range(10):
            store.set(f"key{i}", f"value{i}")
        
        assert len(store._segments) > 1
        store.close()
    
    def test_stats(self, tmp_path):
        store = KVStore(tmp_path)
        store.set("a", "1")
        store.set("b", "2")
        store.delete("a")
        
        stats = store.stats()
        assert stats.live_keys == 1
        assert stats.tombstones == 1
        assert stats.total_records == 3
        assert stats.dead_records == 1
        store.close()
    
    def test_type_validation_key(self, tmp_path):
        store = KVStore(tmp_path)
        with pytest.raises(TypeError):
            store.set(123, "value")
        with pytest.raises(TypeError):
            store.get(123)
        store.close()
    
    def test_type_validation_value(self, tmp_path):
        store = KVStore(tmp_path)
        with pytest.raises(TypeError):
            store.set("key", 123)
        store.close()
    
    def test_key_length_validation(self, tmp_path):
        store = KVStore(tmp_path)
        
        with pytest.raises(ValueError):
            store.set("", "value")
        
        big_key = "x" * 100000
        with pytest.raises(ValueError):
            store.set(big_key, "value")
        
        store.close()
    
    def test_empty_string_value(self, tmp_path):
        store = KVStore(tmp_path)
        store.set("key", "")
        assert store.get("key") == ""
        store.close()
    
    def test_max_segment_bytes_validation(self, tmp_path):
        with pytest.raises(ValueError):
            KVStore(tmp_path, max_segment_bytes=15)
        
        with pytest.raises(ValueError):
            KVStore(tmp_path, max_segment_bytes="not_an_int")
    
    def test_closed_store_raises(self, tmp_path):
        store = KVStore(tmp_path)
        store.set("key", "value")
        store.close()
        
        with pytest.raises(ValueError):
            store.set("key2", "value2")
    
    def test_close_idempotent(self, tmp_path):
        store = KVStore(tmp_path)
        store.close()
        store.close()


class TestCompaction:
    def test_compact_basic(self, tmp_path):
        with KVStore(tmp_path, max_segment_bytes=50) as store:
            for i in range(5):
                store.set(f"key{i}", f"value{i}")
            
            before_stats = store.stats()
            result = compact(store)
            after_stats = store.stats()
            
            assert result.segments_removed > 0
            assert result.records_written == 5
            assert len(store._segments) == 1
            assert after_stats.segment_count == 1
    
    def test_compact_preserves_data(self, tmp_path):
        with KVStore(tmp_path, max_segment_bytes=50) as store:
            store.set("a", "1")
            store.set("b", "2")
            store.set("c", "3")
            
            compact(store)
            
            assert store.get("a") == "1"
            assert store.get("b") == "2"
            assert store.get("c") == "3"
    
    def test_compact_removes_tombstones(self, tmp_path):
        with KVStore(tmp_path, max_segment_bytes=50) as store:
            store.set("a", "1")
            store.set("b", "2")
            store.delete("a")
            
            result = compact(store)
            
            assert result.records_written == 1
            assert store.get("a") is None
            assert store.get("b") == "2"
    
    def test_compact_drops_dead_records(self, tmp_path):
        with KVStore(tmp_path, max_segment_bytes=50) as store:
            store.set("key", "v1")
            store.set("key", "v2")
            store.set("key", "v3")
            
            before_stats = store.stats()
            result = compact(store)
            
            assert result.records_dropped == 2
            assert store.get("key") == "v3"
    
    def test_compact_preserves_key_order(self, tmp_path):
        with KVStore(tmp_path, max_segment_bytes=50) as store:
            store.set("a", "1")
            store.set("b", "2")
            store.set("c", "3")
            
            compact(store)
            assert store.keys() == ["a", "b", "c"]


class TestRecovery:
    def test_recover_from_clean_close(self, tmp_path):
        with KVStore(tmp_path) as store:
            store.set("a", "1")
            store.set("b", "2")
        
        with KVStore(tmp_path) as store:
            assert store.get("a") == "1"
            assert store.get("b") == "2"
    
    def test_recover_truncated_tail(self, tmp_path):
        with KVStore(tmp_path) as store:
            store.set("a", "1")
        
        seg_path = tmp_path / "000001.seg"
        with open(seg_path, "a+b") as f:
            f.write(b"TRUNCATED")
        
        with KVStore(tmp_path) as store:
            assert store.get("a") == "1"
    
    def test_corrupt_magic(self, tmp_path):
        with KVStore(tmp_path) as store:
            store.set("a", "1")
        
        seg_path = tmp_path / "000001.seg"
        with open(seg_path, "r+b") as f:
            f.write(b"XXXX")
        
        with pytest.raises(CorruptSegmentError):
            KVStore(tmp_path)
    
    def test_multiple_segments_recovery(self, tmp_path):
        with KVStore(tmp_path, max_segment_bytes=50) as store:
            store.set("a", "1")
            store.set("b", "2")
            store.set("c", "3")
        
        with KVStore(tmp_path) as store:
            assert store.get("a") == "1"
            assert store.get("b") == "2"
            assert store.get("c") == "3"


class TestCLI:
    def test_cli_set_get(self, tmp_path):
        from kvstore.__main__ import main
        
        root = str(tmp_path)
        assert main([root, "set", "key", "value"]) == 0
        import io
        import sys
        
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        result = main([root, "get", "key"])
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        
        assert result == 0
        assert output == "value\n"
    
    def test_cli_get_missing(self, tmp_path):
        from kvstore.__main__ import main
        
        root = str(tmp_path)
        import io
        import sys
        
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        result = main([root, "get", "missing"])
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        
        assert result == 1
        assert output == ""
    
    def test_cli_delete(self, tmp_path):
        from kvstore.__main__ import main
        
        root = str(tmp_path)
        assert main([root, "set", "key", "value"]) == 0
        assert main([root, "delete", "key"]) == 0
        
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        result = main([root, "get", "key"])
        sys.stdout = old_stdout
        assert result == 1
    
    def test_cli_list(self, tmp_path):
        from kvstore.__main__ import main
        
        root = str(tmp_path)
        main([root, "set", "a", "1"])
        main([root, "set", "b", "2"])
        
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        result = main([root, "list"])
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        
        assert result == 0
        assert output == "a\nb\n"
    
    def test_cli_stats(self, tmp_path):
        from kvstore.__main__ import main
        
        root = str(tmp_path)
        main([root, "set", "a", "1"])
        
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        result = main([root, "stats"])
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        
        assert result == 0
        assert "live_keys=" in output
    
    def test_cli_exit_codes(self, tmp_path):
        from kvstore.__main__ import main
        
        root = str(tmp_path)
        
        assert main([root, "set", "k", "v"]) == 0
        
        import io, sys
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        result = main(["bad", "command", "args", "extra"])
        sys.stderr = old_stderr
        assert result == 2
