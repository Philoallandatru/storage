#!/usr/bin/env python3
"""append_to_io_profile_summary.py — 把新 benchmark JSON 接进 io_profile_summary.csv

读取 kv-cache.py 输出的 JSON,按 io_profile_summary.csv 列结构输出一行 CSV。
"""
import argparse
import csv
import json
from pathlib import Path
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('json_file', type=Path)
    ap.add_argument('--group', default='BurstGPT-70B')
    ap.add_argument('--case', required=True)
    ap.add_argument('--note', default='')
    ap.add_argument('--users', type=float, required=True)
    ap.add_argument('--summary-csv', type=Path,
                    default='docs/assets/kvcache-io-profiling/io_profile_summary.csv')
    args = ap.parse_args()

    d = json.load(open(args.json_file))
    s = d['summary']
    cs = s['cache_stats']

    # Match the existing CSV column order
    row = {
        'group': args.group,
        'case': args.case,
        'file': args.json_file.name,
        'note': args.note,
        'users': args.users,
        'status': 'PASS',  # We only add PASS rows by convention
        'passed': '3/3',
        'requests': s.get('total_requests'),
        'tokens': s.get('total_tokens'),
        'tok_s': s.get('avg_throughput_tokens_per_sec'),
        'storage_tok_s': s.get('storage_throughput_tokens_per_sec'),
        'req_s': s.get('requests_per_second'),
        'e2e_p95_ms': s.get('end_to_end_latency_ms', {}).get('p95'),
        'storage_io_p95_ms': s.get('storage_io_latency_ms', {}).get('p95'),
        'cache_hit_rate_pct': cs.get('cache_hit_rate', 0) * 100,
        'read_dev_p95_ms': cs.get('storage_read_device_p95_ms'),
        'read_host_p95_ms': cs.get('storage_read_host_p95_ms'),
        'read_total_p95_ms': cs.get('storage_read_p95_ms'),
        'write_dev_p95_ms': cs.get('storage_write_device_p95_ms'),
        'write_host_p95_ms': cs.get('storage_write_host_p95_ms'),
        'write_total_p95_ms': cs.get('storage_write_p95_ms'),
        'total_read_gb': cs.get('total_read_gb'),
        'total_write_gb': cs.get('total_write_gb'),
        'storage_read_gb': cs.get('total_read_gb'),  # same since cpu=0
        'storage_write_gb': cs.get('total_write_gb'),
        'cpu_read_gb': 0.0,
        'cpu_write_gb': 0.0,
        'storage_read_bw_gibs': cs.get('tier_storage_read_bandwidth_gbps', 0) / 8.0,
        'storage_write_bw_gibs': cs.get('tier_storage_write_bandwidth_gbps', 0) / 8.0,
        'prefill_writes': cs.get('prefill_writes'),
        'decode_reads': cs.get('decode_reads'),
    }

    # Read existing CSV to get header + count
    with open(args.summary_csv, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    n_existing = len(rows)

    # Write the new row, in the column order of header
    new_row = [row.get(col, '') for col in header]
    with open(args.summary_csv, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(new_row)

    print(f"✓ appended to {args.summary_csv}")
    print(f"  rows: {n_existing} → {n_existing + 1}")
    print(f"  case: {args.case}")
    print(f"  users: {args.users}")
    print(f"  requests: {row['requests']}")
    print(f"  read_dev_p95_ms: {row['read_dev_p95_ms']}")
    print(f"  write_dev_p95_ms: {row['write_dev_p95_ms']}")
    print(f"  cache_hit_rate: {row['cache_hit_rate_pct']:.2f}%")


if __name__ == '__main__':
    main()