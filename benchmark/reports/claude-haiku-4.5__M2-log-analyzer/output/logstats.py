import re
import sys
import json
import argparse
import math
from datetime import datetime
from typing import Iterable
from collections import defaultdict


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    line = line.rstrip('\n\r')
    
    # Regex pattern to match the log format:
    # <ip> - <user> [<timestamp>] "<method> <path> <protocol>" <status> <bytes> <duration>
    pattern = (
        r'^'
        r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+'  # IP
        r'-\s+'  # dash
        r'(-|\w+)\s+'  # user (- or word chars)
        r'\[([^\]]+)\]\s+'  # timestamp
        r'"(\w+)\s+(\S+)\s+(\S+)"\s+'  # method, path, protocol
        r'(\d{3})\s+'  # status
        r'(-|\d+)\s+'  # bytes
        r'([\d.]+)'  # duration
        r'$'
    )
    
    match = re.match(pattern, line)
    if not match:
        return None
    
    ip, user, timestamp_str, method, path, protocol, status, bytes_str, duration_str = match.groups()
    
    # Parse timestamp
    try:
        timestamp = datetime.strptime(timestamp_str, '%d/%b/%Y:%H:%M:%S %z')
    except ValueError:
        return None
    
    # Parse bytes (- means 0)
    bytes_val = 0 if bytes_str == '-' else int(bytes_str)
    
    # Parse duration
    try:
        duration_val = float(duration_str)
    except ValueError:
        return None
    
    return {
        'ip': ip,
        'user': None if user == '-' else user,
        'timestamp': timestamp,
        'method': method,
        'path': path,
        'protocol': protocol,
        'status': int(status),
        'bytes': bytes_val,
        'duration': duration_val,
    }


def _percentile(values: list, p: float) -> float:
    """Calculate percentile using nearest-rank method."""
    if not values:
        return 0.0
    n = len(values)
    index = math.ceil(p / 100 * n) - 1
    index = max(0, min(index, n - 1))
    return float(values[index])


def analyze(lines: Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    
    bytes_total = 0
    status_classes = {'2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0, 'other': 0}
    methods = defaultdict(int)
    paths = defaultdict(int)
    ips = defaultdict(int)
    durations = []
    
    for line in lines:
        # Skip blank lines
        if not line.strip():
            continue
        
        lines_total += 1
        record = parse_line(line)
        
        if record is None:
            lines_malformed += 1
            continue
        
        lines_parsed += 1
        bytes_total += record['bytes']
        
        # Status classes
        status = record['status']
        if 200 <= status < 300:
            status_classes['2xx'] += 1
        elif 300 <= status < 400:
            status_classes['3xx'] += 1
        elif 400 <= status < 500:
            status_classes['4xx'] += 1
        elif 500 <= status < 600:
            status_classes['5xx'] += 1
        else:
            status_classes['other'] += 1
        
        # Methods
        methods[record['method']] += 1
        
        # Paths and IPs
        paths[record['path']] += 1
        ips[record['ip']] += 1
        
        # Durations
        durations.append(record['duration'])
    
    # Sort methods by key
    methods_sorted = dict(sorted(methods.items()))
    
    # Top paths: sorted by count descending, then by path ascending
    top_paths_list = sorted(
        paths.items(),
        key=lambda x: (-x[1], x[0])
    )[:top]
    top_paths = [{'path': path, 'count': count} for path, count in top_paths_list]
    
    # Top IPs: sorted by count descending, then by IP ascending
    top_ips_list = sorted(
        ips.items(),
        key=lambda x: (-x[1], x[0])
    )[:top]
    top_ips = [{'ip': ip, 'count': count} for ip, count in top_ips_list]
    
    # Duration statistics
    if durations:
        sorted_durations = sorted(durations)
        mean = sum(sorted_durations) / len(sorted_durations)
        p50 = _percentile(sorted_durations, 50)
        p95 = _percentile(sorted_durations, 95)
        max_duration = max(sorted_durations)
        
        duration_stats = {
            'count': len(sorted_durations),
            'mean': round(mean, 3),
            'p50': round(p50, 3),
            'p95': round(p95, 3),
            'max': round(max_duration, 3),
        }
    else:
        duration_stats = {
            'count': 0,
            'mean': 0.0,
            'p50': 0.0,
            'p95': 0.0,
            'max': 0.0,
        }
    
    return {
        'lines_total': lines_total,
        'lines_parsed': lines_parsed,
        'lines_malformed': lines_malformed,
        'bytes_total': bytes_total,
        'status_classes': status_classes,
        'methods': methods_sorted,
        'top_paths': top_paths,
        'top_ips': top_ips,
        'duration': duration_stats,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description='Parse access logs and report statistics')
    parser.add_argument('logfile', help='Path to the log file')
    parser.add_argument('--top', type=int, default=5, help='Number of top items to report')
    parser.add_argument('--format', choices=['json', 'table'], default='json', help='Output format')
    parser.add_argument('--strict', action='store_true', help='Exit on first malformed line')
    
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    
    # Validate --top argument
    if args.top < 1:
        sys.stderr.write('Error: --top must be at least 1\n')
        return 2
    
    # Try to open the file
    try:
        with open(args.logfile, 'r') as f:
            if args.strict:
                lines_to_analyze = []
                for line_num, line in enumerate(f, 1):
                    # Skip blank lines but check them
                    if not line.strip():
                        continue
                    
                    record = parse_line(line)
                    if record is None:
                        sys.stderr.write(f'malformed line {line_num}: {line.rstrip()}\n')
                        return 2
                    lines_to_analyze.append(line)
                
                report = analyze(lines_to_analyze, top=args.top)
            else:
                with open(args.logfile, 'r') as f:
                    report = analyze(f, top=args.top)
    except FileNotFoundError:
        sys.stderr.write(f'Error: File not found: {args.logfile}\n')
        return 2
    except IOError as e:
        sys.stderr.write(f'Error: {e}\n')
        return 2
    
    # Output report
    if args.format == 'json':
        sys.stdout.write(json.dumps(report, indent=2))
        sys.stdout.write('\n')
    else:  # table format
        sys.stdout.write('=== Access Log Statistics ===\n\n')
        sys.stdout.write(f'lines_total: {report["lines_total"]}\n')
        sys.stdout.write(f'lines_parsed: {report["lines_parsed"]}\n')
        sys.stdout.write(f'lines_malformed: {report["lines_malformed"]}\n')
        sys.stdout.write(f'bytes_total: {report["bytes_total"]}\n\n')
        
        sys.stdout.write('status_classes:\n')
        for status_class, count in report['status_classes'].items():
            sys.stdout.write(f'  {status_class}: {count}\n')
        sys.stdout.write('\n')
        
        sys.stdout.write('methods:\n')
        for method, count in report['methods'].items():
            sys.stdout.write(f'  {method}: {count}\n')
        sys.stdout.write('\n')
        
        sys.stdout.write('top_paths:\n')
        for item in report['top_paths']:
            sys.stdout.write(f'  {item["path"]}: {item["count"]}\n')
        sys.stdout.write('\n')
        
        sys.stdout.write('top_ips:\n')
        for item in report['top_ips']:
            sys.stdout.write(f'  {item["ip"]}: {item["count"]}\n')
        sys.stdout.write('\n')
        
        sys.stdout.write('duration:\n')
        sys.stdout.write(f'  count: {report["duration"]["count"]}\n')
        sys.stdout.write(f'  mean: {report["duration"]["mean"]}\n')
        sys.stdout.write(f'  p50: {report["duration"]["p50"]}\n')
        sys.stdout.write(f'  p95: {report["duration"]["p95"]}\n')
        sys.stdout.write(f'  max: {report["duration"]["max"]}\n')
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
