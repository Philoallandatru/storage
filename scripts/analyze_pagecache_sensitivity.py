#!/usr/bin/env python3
"""Analyze page cache sensitivity sweep results.

Generates a comparison table of:
  - fio R/W throughput (READ BW, WRITE BW, IOPS)
  - fio latency (clat P50/P95/P99/P99.9)
  - iostat device-level (r/s, w/s, rMB/s, wMB/s, await, %util)
  - cgroup memory.peak (mostly the fio process footprint)
  - system-wide Cached (the real DRAM cache footprint)

Usage:
  python3 scripts/analyze_pagecache_sensitivity.py <results_dir>
  e.g. python3 scripts/analyze_pagecache_sensitivity.py \\
       results/kvcache-profile/pagecache_sweep
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def parse_fio_log(fio_log: Path) -> dict:
    """Extract key metrics from fio text log."""
    if not fio_log.exists():
        return {}
    text = fio_log.read_text()

    out: dict = {}

    # READ: bw=1601MiB/s ... clat percentiles (usec): ...
    read_m = re.search(r"READ:\s*bw=([\d.]+)(MiB|MB)/s.*?io=([\d.]+)(GiB|GB|MiB|MB)", text)
    write_m = re.search(r"WRITE:\s*bw=([\d.]+)(MiB|MB)/s.*?io=([\d.]+)(GiB|GB|MiB|MB)", text)
    if read_m:
        out["read_bw_mib_s"] = float(read_m.group(1))
        out["read_io_str"] = read_m.group(3) + read_m.group(4)
    if write_m:
        out["write_bw_mib_s"] = float(write_m.group(1))
        out["write_io_str"] = write_m.group(3) + write_m.group(4)

    # IOPS — look for "read: IOPS=..." pattern
    read_iops_m = re.search(r"\s+read:\s+IOPS=([\d.]+)k?\s", text)
    write_iops_m = re.search(r"\s+write:\s+IOPS=([\d.]+)k?\s", text)
    if read_iops_m:
        out["read_iops"] = float(read_iops_m.group(1))
    if write_iops_m:
        out["write_iops"] = float(write_iops_m.group(1))

    # clat percentiles (read)
    clat_section = re.search(
        r"\s+read:.*?clat percentiles \(usec\):\s*\n.*?\|\s*50\.00th=\[\s*(\d+)\].*?95\.00th=\[\s*(\d+)\].*?99\.00th=\[\s*(\d+)\].*?99\.90th=\[\s*(\d+)\].*?99\.99th=\[\s*(\d+)\]",
        text, re.DOTALL)
    if clat_section:
        out["read_p50_us"] = int(clat_section.group(1))
        out["read_p95_us"] = int(clat_section.group(2))
        out["read_p99_us"] = int(clat_section.group(3))
        out["read_p999_us"] = int(clat_section.group(4))
        out["read_p9999_us"] = int(clat_section.group(5))

    return out


def parse_cgroup_memory(cgroup_log: Path) -> dict:
    """Extract cgroup memory stats."""
    if not cgroup_log.exists():
        return {}
    text = cgroup_log.read_text()
    out: dict = {}

    peak_m = re.search(r"memory\.peak\s+=\s+(\d+)\s+bytes\s+\(([\d.]+)\s+GiB\)", text)
    cur_m = re.search(r"memory\.current\s+=\s+(\d+)\s+bytes\s+\(([\d.]+)\s+GiB\)", text)
    if peak_m:
        out["cgroup_peak_gib"] = float(peak_m.group(2))
    if cur_m:
        out["cgroup_current_gib"] = float(cur_m.group(2))

    # meminfo
    cached_m = re.search(r"Cached:\s+(\d+)\s+kB", text)
    memfree_m = re.search(r"MemFree:\s+(\d+)\s+kB", text)
    if cached_m:
        out["system_cached_mib"] = int(cached_m.group(1)) / 1024
    if memfree_m:
        out["system_memfree_mib"] = int(memfree_m.group(1)) / 1024

    return out


def parse_iostat(iostat_log: Path) -> dict:
    """Extract average device-level stats from iostat log."""
    if not iostat_log.exists():
        return {}
    # Skip header lines, take the device row (nvme1n1)
    text = iostat_log.read_text()
    out: dict = {}
    sums = {"r_s": 0.0, "w_s": 0.0, "rkB_s": 0.0, "wkB_s": 0.0,
            "await": 0.0, "r_await": 0.0, "w_await": 0.0, "util": 0.0}
    n = 0
    for line in text.split("\n"):
        if line.startswith("nvme"):
            parts = line.split()
            if len(parts) >= 14:
                try:
                    sums["r_s"] += float(parts[3])
                    sums["w_s"] += float(parts[4])
                    sums["rkB_s"] += float(parts[5])
                    sums["wkB_s"] += float(parts[6])
                    sums["await"] += float(parts[9])
                    sums["r_await"] += float(parts[11])
                    sums["w_await"] += float(parts[12])
                    sums["util"] += float(parts[13])
                    n += 1
                except (ValueError, IndexError):
                    pass
    if n > 0:
        for k in sums:
            out[f"avg_{k}"] = sums[k] / n
        out["n_samples"] = n
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    results_dir = Path(sys.argv[1])

    # find all cell subdirs in the most recent timestamp
    subdirs = sorted(results_dir.iterdir())
    # group by timestamp (cellname_TIMESTAMP)
    by_ts: dict = {}
    for d in subdirs:
        if not d.is_dir() or d.name.startswith("."):
            continue
        # parse name like dram_unlimited_20260609_142850
        m = re.match(r"(.+)_(\d{8}_\d{6})$", d.name)
        if not m:
            continue
        cell = m.group(1)
        ts = m.group(2)
        by_ts.setdefault(ts, {})[cell] = d

    if not by_ts:
        print(f"No cell subdirs found in {results_dir}")
        sys.exit(1)

    # Use the most recent timestamp
    ts = sorted(by_ts.keys())[-1]
    cells = by_ts[ts]

    print(f"\n=== Page Cache Sensitivity Sweep — {ts} ===\n")
    print(f"{'Cell':<20} | {'R BW (MiB/s)':>13} | {'W BW (MiB/s)':>13} | "
          f"{'R IOPS':>10} | {'R P50':>8} | {'R P99':>8} | "
          f"{'Sys Cached (MiB)':>17}")
    print("-" * 110)

    summary = {}
    for cell in sorted(cells.keys()):
        d = cells[cell]
        fio = parse_fio_log(d / "fio.log")
        cgroup = parse_cgroup_memory(d / "meminfo_end.log")
        iostat = parse_iostat(d / "iostat.log")

        print(f"{cell:<20} | "
              f"{fio.get('read_bw_mib_s', 0):>13.1f} | "
              f"{fio.get('write_bw_mib_s', 0):>13.1f} | "
              f"{fio.get('read_iops', 0):>10.0f} | "
              f"{fio.get('read_p50_us', 0):>8} | "
              f"{fio.get('read_p99_us', 0):>8} | "
              f"{cgroup.get('system_cached_mib', 0):>17.1f}")

        summary[cell] = {
            "fio": fio,
            "cgroup": cgroup,
            "iostat": iostat,
        }

    print("\n=== iostat device-level (avg over run) ===\n")
    print(f"{'Cell':<20} | {'r/s':>8} | {'w/s':>8} | "
          f"{'rMB/s':>8} | {'wMB/s':>8} | {'await':>8} | {'%util':>6}")
    print("-" * 95)
    for cell in sorted(cells.keys()):
        s = summary[cell]["iostat"]
        print(f"{cell:<20} | "
              f"{s.get('avg_r_s', 0):>8.0f} | "
              f"{s.get('avg_w_s', 0):>8.0f} | "
              f"{s.get('avg_rkB_s', 0)/1024:>8.1f} | "
              f"{s.get('avg_wkB_s', 0)/1024:>8.1f} | "
              f"{s.get('avg_await', 0):>8.2f} | "
              f"{s.get('avg_util', 0):>6.1f}")

    # delta vs dram_unlimited
    if "dram_unlimited" in summary:
        base = summary["dram_unlimited"]["fio"].get("read_bw_mib_s", 0)
        if base > 0:
            print(f"\n=== READ BW delta vs dram_unlimited ({base:.0f} MiB/s) ===")
            for cell in sorted(cells.keys()):
                bw = summary[cell]["fio"].get("read_bw_mib_s", 0)
                delta = (bw - base) / base * 100
                print(f"  {cell:<20}: {bw:>7.1f} MiB/s ({delta:+.1f}%)")


if __name__ == "__main__":
    main()