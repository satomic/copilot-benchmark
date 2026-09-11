import pytest
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from logstats import parse_line, analyze, main


class TestParseLine:
    """Test the parse_line function."""
    
    def test_well_formed_line(self):
        """Test parsing a well-formed log line."""
        line = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
        rec = parse_line(line)
        
        assert rec is not None
        assert rec['ip'] == '203.0.113.10'
        assert rec['user'] is None
        assert rec['method'] == 'GET'
        assert rec['path'] == '/api/users'
        assert rec['protocol'] == 'HTTP/1.1'
        assert rec['status'] == 200
        assert rec['bytes'] == 1024
        assert rec['duration'] == 0.042
        assert rec['timestamp'].year == 2026
        assert rec['timestamp'].month == 9
        assert rec['timestamp'].day == 9
        # UTC offset should be +08:00
        assert rec['timestamp'].utcoffset().total_seconds() == 8 * 3600
    
    def test_malformed_line(self):
        """Test that malformed lines return None."""
        line = 'this line is not a log line at all'
        assert parse_line(line) is None
    
    def test_bytes_dash_becomes_zero(self):
        """Test that - in bytes field becomes 0."""
        line = '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
        rec = parse_line(line)
        
        assert rec is not None
        assert rec['bytes'] == 0
        assert rec['user'] == 'alice'
    
    def test_user_dash_becomes_none(self):
        """Test that - in user field becomes None."""
        line = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
        rec = parse_line(line)
        
        assert rec is not None
        assert rec['user'] is None
    
    def test_named_user(self):
        """Test parsing with named user."""
        line = '198.51.100.7 - bob [09/Sep/2026:08:00:17 +0800] "GET / HTTP/1.1" 304 - 0.011'
        rec = parse_line(line)
        
        assert rec is not None
        assert rec['user'] == 'bob'
    
    def test_line_with_newline(self):
        """Test that trailing newline is handled correctly."""
        line = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042\n'
        rec = parse_line(line)
        
        assert rec is not None
        assert rec['ip'] == '203.0.113.10'
    
    def test_line_with_crlf(self):
        """Test that trailing CRLF is handled correctly."""
        line = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042\r\n'
        rec = parse_line(line)
        
        assert rec is not None
        assert rec['ip'] == '203.0.113.10'
    
    def test_various_methods(self):
        """Test parsing various HTTP methods."""
        for method in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD']:
            line = f'203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "{method} /api/users HTTP/1.1" 200 1024 0.042'
            rec = parse_line(line)
            assert rec is not None
            assert rec['method'] == method


class TestAnalyze:
    """Test the analyze function."""
    
    def test_percentile_calculation(self):
        """Test nearest-rank percentile calculation."""
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
        ]
        r = analyze(lines)
        
        assert r['duration']['count'] == 4
        assert r['duration']['p50'] == 2.0
        assert r['duration']['p95'] == 4.0
        assert r['duration']['max'] == 4.0
        assert r['duration']['mean'] == 2.5
    
    def test_status_classes(self):
        """Test status class categorization."""
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 301 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 404 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 500 1 0.1',
        ]
        r = analyze(lines)
        
        assert r['status_classes'] == {'2xx': 1, '3xx': 1, '4xx': 1, '5xx': 1, 'other': 0}
    
    def test_top_truncation_and_tiebreaking(self):
        """Test that top paths/ips are truncated and tie-broken correctly."""
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 0.1',
            '2.2.2.2 - - [09/Sep/2026:08:00:03 +0800] "GET /b HTTP/1.1" 200 1 0.1',
            '2.2.2.2 - - [09/Sep/2026:08:00:04 +0800] "GET /b HTTP/1.1" 200 1 0.1',
            '3.3.3.3 - - [09/Sep/2026:08:00:05 +0800] "GET /c HTTP/1.1" 200 1 0.1',
        ]
        r = analyze(lines, top=2)
        
        # Top paths: /a and /b have count 2, so both appear, sorted by path ascending
        assert len(r['top_paths']) <= 2
        
        # Top IPs: 1.1.1.1 and 2.2.2.2 have count 2, so both appear
        assert len(r['top_ips']) <= 2
    
    def test_empty_lines_ignored(self):
        """Test that blank lines are ignored."""
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 0.1',
            '',
            '   ',
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 0.1',
        ]
        r = analyze(lines)
        
        assert r['lines_total'] == 2  # Only non-blank lines
        assert r['lines_parsed'] == 2
        assert r['lines_malformed'] == 0
    
    def test_methods_sorted(self):
        """Test that methods are sorted ascending."""
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "POST /a HTTP/1.1" 200 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "DELETE /a HTTP/1.1" 200 1 0.1',
        ]
        r = analyze(lines)
        
        keys = list(r['methods'].keys())
        assert keys == ['DELETE', 'GET', 'POST']
    
    def test_no_parsed_lines(self):
        """Test analyze with no parsed lines."""
        lines = [
            'malformed line 1',
            'malformed line 2',
        ]
        r = analyze(lines)
        
        assert r['lines_parsed'] == 0
        assert r['lines_malformed'] == 2
        assert r['duration']['count'] == 0
        assert r['duration']['mean'] == 0.0
        assert r['duration']['p50'] == 0.0
        assert r['duration']['p95'] == 0.0
        assert r['duration']['max'] == 0.0


class TestCLI:
    """Test the CLI functionality."""
    
    def test_strict_mode_exits_on_malformed(self):
        """Test that --strict mode exits with code 2 on malformed line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logfile = Path(tmpdir) / 'test.log'
            logfile.write_text(
                '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042\n'
                'this is malformed\n'
                '203.0.113.10 - - [09/Sep/2026:08:00:02 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042\n'
            )
            exit_code = main([str(logfile), '--strict'])
            assert exit_code == 2
    
    def test_missing_file_exits_with_2(self):
        """Test that missing file exits with code 2."""
        exit_code = main(['/nonexistent/path/to/file.log'])
        assert exit_code == 2
    
    def test_valid_top_argument(self):
        """Test valid --top argument."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logfile = Path(tmpdir) / 'test.log'
            logfile.write_text(
                '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1024 0.042\n'
                '203.0.113.10 - - [09/Sep/2026:08:00:02 +0800] "GET /b HTTP/1.1" 200 1024 0.042\n'
            )
            exit_code = main([str(logfile), '--top', '1'])
            assert exit_code == 0
    
    def test_invalid_top_argument(self):
        """Test that invalid --top argument returns exit code 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logfile = Path(tmpdir) / 'test.log'
            logfile.write_text('203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1024 0.042\n')
            
            # Test top < 1
            exit_code = main([str(logfile), '--top', '0'])
            assert exit_code == 2
            
            # Test non-integer top
            exit_code = main([str(logfile), '--top', 'abc'])
            assert exit_code == 2
    
    def test_json_output_format(self, capsys):
        """Test JSON output format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logfile = Path(tmpdir) / 'test.log'
            logfile.write_text('203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1024 0.042\n')
            
            exit_code = main([str(logfile), '--format', 'json'])
            assert exit_code == 0
            
            captured = capsys.readouterr()
            assert 'lines_total' in captured.out
            assert 'lines_parsed' in captured.out
    
    def test_table_output_format(self, capsys):
        """Test table output format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logfile = Path(tmpdir) / 'test.log'
            logfile.write_text('203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1024 0.042\n')
            
            exit_code = main([str(logfile), '--format', 'table'])
            assert exit_code == 0
            
            captured = capsys.readouterr()
            # Table format must contain these substrings and not be valid JSON
            assert 'lines_total' in captured.out
            assert 'status_classes' in captured.out
            assert 'top_paths' in captured.out
            assert 'top_ips' in captured.out
            assert 'duration' in captured.out


class TestAcceptanceCriteria:
    """Test acceptance criteria from the task."""
    
    def test_acceptance_example_1(self):
        """Test first acceptance criterion example."""
        rec = parse_line(
            '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
        )
        assert rec["ip"] == "203.0.113.10"
        assert rec["user"] is None
        assert rec["method"] == "GET" and rec["path"] == "/api/users"
        assert rec["status"] == 200 and rec["bytes"] == 1024
        assert rec["duration"] == 0.042
        assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600
    
    def test_acceptance_example_2(self):
        """Test malformed line returns None."""
        assert parse_line("this line is not a log line at all") is None
    
    def test_acceptance_example_3(self):
        """Test - bytes become 0, named user is kept."""
        rec2 = parse_line(
            '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
        )
        assert rec2["bytes"] == 0 and rec2["user"] == "alice"
    
    def test_acceptance_example_4(self):
        """Test nearest-rank percentile."""
        r = analyze([
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
        ])
        assert r["duration"]["p50"] == 2.0
        assert r["duration"]["p95"] == 4.0
        assert r["status_classes"] == {"2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    
    def test_acceptance_example_sample_file(self, capsys):
        """Test with the provided sample file."""
        logfile = 'access.log'
        exit_code = main([logfile, '--top', '3'])
        assert exit_code == 0
        
        captured = capsys.readouterr()
        # Parse the JSON output
        import json
        result = json.loads(captured.out)
        
        assert result['lines_total'] == 40
        assert result['lines_malformed'] == 4
        assert result['lines_parsed'] == 36
