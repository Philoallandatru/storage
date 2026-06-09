#!/usr/bin/env python3
"""
cross_vendor_slc_analyze.py
Detect SLC cache cliff from fio --write_bw_log output.

Fio emits bw logs in this format:
    time_ms, bandwidth_bytes_per_sec, ...

After collecting time series, we find:
- The first sustained drop > 30% from peak (SLC cache depleted)
- The cumulative bytes written at that point (= SLC size estimate)
- The "cached" mean BW (above the cliff) and "uncached" mean BW (below)
"""
import sys
from pathlib import Path

def parse_bw_log(path):
    """Read fio write_bw_log and return list of (cumulative_ms, bw_KiBps) tuples.

    fio bw log per-thread format: time_ms, bw_KiB_per_sec, num_threads, bytes_per_io, runtime_ms
    """
    rows = []
    if not Path(path).exists():
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('start'):
                continue
            parts = line.split(',')
            if len(parts) < 5:
                continue
            try:
                ts_ms = int(parts[0])
                bw_kib = int(parts[1])
                b_per_io = int(parts[3])
                rows.append((ts_ms, bw_kib * 1024))  # bytes per second
            except (ValueError, IndexError):
                continue
    return rows


def detect_cliff(rows, slice_bytes=10 * 2**30):
    """Given list of (cumulative_ms, bw_bytes_per_s) rows, find SLC cliff.

    Strategy:
      1. Find peak BW in first 200 samples (initial SLC cache region).
      2. Find first time a 200-sample window has avg BW < peak/2.
      3. Report cumulative bytes written up to that point as SLC size.
      4. If no sustained cliff (SLC > total written), report no cliff.
    """
    if len(rows) < 5:
        return {"_error": "too few samples"}

    bw_series = [r[1] for r in rows]

    # Build cumulative bytes
    cum_bytes = [0]
    for i in range(len(rows) - 1):
        dt_ms = max(0, rows[i+1][0] - rows[i][0])
        cum_bytes.append(cum_bytes[-1] + rows[i][1] * dt_ms / 1000)

    total_written_gb = cum_bytes[-1] / 2**30

    # Find peak in first 200 samples
    peak_bw = max(bw_series[:200])

    # Find first 200-sample window with avg BW < 50% of peak (after sample 200)
    window = 200
    threshold = peak_bw * 0.5
    cliff_idx = None
    for i in range(200, len(bw_series) - window):
        avg = sum(bw_series[i:i+window]) / window
        if avg < threshold:
            cliff_idx = i
            break

    if cliff_idx is None:
        return {
            "status": "no cliff detected (SLC cache ≥ total write volume)",
            "peak_bw_MBps": peak_bw / 2**20,
            "sustained_bw_MBps": (sum(bw_series) / len(bw_series)) / 2**20,
            "total_written_GB": total_written_gb,
        }

    # Bytes written up to cliff (use cum_bytes at end of cliff window)
    bytes_to_cliff = cum_bytes[max(0, cliff_idx - 1)] / 2**30

    pre_bw = sum(bw_series[:cliff_idx]) / max(1, cliff_idx)
    post_bw = sum(bw_series[cliff_idx:]) / max(1, len(bw_series) - cliff_idx)

    return {
        "status": "cliff detected",
        "slc_cache_GB": bytes_to_cliff,
        "peak_bw_MBps": peak_bw / 2**20,
        "cached_bw_MBps": pre_bw / 2**20,
        "uncached_bw_MBps": post_bw / 2**20,
        "cliff_at_time_ms": rows[cliff_idx][0],
        "samples": len(rows),
        "total_written_GB": total_written_gb,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: cross_vendor_slc_analyze.py <result_dir>")
        return 1
    result_dir = Path(sys.argv[1])
    print(f"Analyzing {result_dir}...")
    # Look for any *_bw*.log (fio bw logs)
    logs = sorted(result_dir.glob("*_bw*.log")) + sorted(result_dir.glob("*bw*.log"))
    if not logs:
        logs = sorted(result_dir.glob("*.log"))
    for bw_log in logs:
        rows = parse_bw_log(bw_log)
        if not rows:
            print(f"\n{bw_log.name}: (empty or unreadable)")
            continue
        result = detect_cliff(rows)
        print(f"\n{bw_log.name}:")
        for k, v in result.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.2f}")
            else:
                print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())