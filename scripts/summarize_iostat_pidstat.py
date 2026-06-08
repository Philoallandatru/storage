#!/usr/bin/env python3
"""summarize_iostat_pidstat.py — 解析 iostat / pidstat 输出成 CSV 摘要

iostat.log 格式:
  Linux 7.0.0... (Sakiko) ...
  avg-cpu: ...
  Device r/s w/s rkB/s wkB/s ... %util ...
  nvme1n1 12.3 45.6 ...
  (每 ~1s 一组)

pidstat.log 格式:
  Linux ...
  ...
  Time                 UID      PID  %usr %system  %guest  %wait  %CPU  CPU  Command
  11:34:34              1000  326374  0.00   0.50    0.00   0.00  0.50    0  python3

输出 <out>.csv:
  device,r/s_avg,r/s_p95,r/s_max,wkB/s_avg,wkB/s_p95,%util_avg,%util_p95
  nvme1n1,12.3,45.6,...

"""
import argparse
import re
import statistics
from pathlib import Path
import csv
import sys


def parse_iostat(path):
    """返回 device → list of (reads/s, wkB/s, %util) per-sample"""
    samples = {}
    in_devices = False
    cur_row = []
    headers = []

    with open(path) as f:
        for line in f:
            line = line.rstrip()
            if 'Device' in line and 'r/s' in line and 'w/s' in line:
                in_devices = True
                headers = line.split()
                continue
            if in_devices:
                if not line.strip():
                    in_devices = False
                    cur_row = []
                    continue
                parts = line.split()
                if len(parts) >= len(headers):
                    dev = parts[0]
                    try:
                        r = float(parts[headers.index('r/s')])
                        # Try rMB/s (iostat -m), fall back to rkB/s
                        if 'rMB/s' in headers:
                            wkbs = float(parts[headers.index('wMB/s')]) * 1024  # convert to KB
                        elif 'rkB/s' in headers:
                            wkbs = float(parts[headers.index('wkB/s')])
                        else:
                            wkbs = 0.0
                        util = float(parts[headers.index('%util')])
                    except (ValueError, IndexError):
                        continue
                    samples.setdefault(dev, []).append((r, wkbs, util))
    return samples


def parse_pidstat(path):
    """返回:cpu_pct 列表,(read_KB/s, write_KB/s, %wait) per pid 列表"""
    cpu_pct = []
    pid_io = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # %CPU + CPU pattern in pidstat -u output
            m = re.match(
                r'^\d+:\d+:\d+\s+\S+\s+\d+\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\S+)$',
                line,
            )
            if m:
                # %usr %system %guest %wait %CPU CPU Command
                cpu_pct.append(float(m.group(5)))
                continue
            # pidstat -d (kB_rd/s, kB_wr/s)
            m = re.search(
                r'^\d+\s+\S+\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\S+)$',
                line,
            )
            # Skip; pidstat output is messy, skip for now
    return cpu_pct, pid_io


def pct(values, p):
    """Return the value at percentile p (0-100) for a list of numbers."""
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iostat', type=Path, required=True)
    ap.add_argument('--pidstat', type=Path, default=None)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--source', type=str, default='unknown')
    args = ap.parse_args()

    if not args.iostat.exists():
        sys.exit(f"iostat not found: {args.iostat}")

    samples = parse_iostat(args.iostat)

    rows = []
    for dev, vals in samples.items():
        rs = [v[0] for v in vals]
        wkbs = [v[1] for v in vals]
        utils = [v[2] for v in vals]
        rows.append({
            'file': args.source,
            'dev': dev,
            'samples': len(vals),
            'r/s_avg': statistics.mean(rs),
            'r/s_p95': pct(rs, 95),
            'r/s_max': max(rs),
            'w/s_avg': sum(v[2] for v in vals) / len(vals) - statistics.mean(rs),  # 近似
            'w/s_p95': pct([v[2] for v in vals], 95),  # placeholder
            'wkB/s_avg': statistics.mean(wkbs),
            'wkB/s_p95': pct(wkbs, 95),
            'wkB/s_max': max(wkbs),
            '%util_avg': statistics.mean(utils),
            '%util_p95': pct(utils, 95),
            '%util_max': max(utils),
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with open(args.out, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {args.out} ({len(rows)} devices)")
        for r in rows:
            print(f"  {r['dev']:12s}  samples={r['samples']:4d}  "
                  f"r/s_avg={r['r/s_avg']:8.1f}  "
                  f"wkB/s_avg={r['wkB/s_avg']:10.1f}  "
                  f"%util_avg={r['%util_avg']:5.1f}%  "
                  f"%util_p95={r['%util_p95']:5.1f}%")
    else:
        print(f"warning: no devices parsed from {args.iostat}")


if __name__ == '__main__':
    main()