#!/usr/bin/env python3
"""Cross-vendor T4 GC drift analysis.

Compares first 60s vs last 60s of each disk's iostat trace to detect
GC-induced throughput collapse over 15 minutes of sustained random read.

Usage:
    python3 scripts/cross_vendor_t4_analyze.py
"""
import json
import os
import sys
from pathlib import Path

PROFILE_DIR = Path(os.environ.get("PROFILE_DIR", Path(__file__).resolve().parent.parent))
RESULTS_DIR = PROFILE_DIR / "results" / "cross_vendor" / "t4_gc_drift"
WINDOW_S = 60  # compare first/last 60s windows


def parse_iostat(path):
    """Parse iostat -dx -m output, return per-disk sample lists."""
    rows_by_disk: dict[str, list[dict]] = {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts or not parts[0].startswith("nvme"):
                continue
            if len(parts) < 18:
                continue
            try:
                disk = parts[0]
                # zh_CN format: Device r/s rMB/s rrqm/s %rrqm r_await rareq-sz w/s wMB/s ...
                rows_by_disk.setdefault(disk, []).append({
                    "r_mbs": float(parts[2]),
                    "w_mbs": float(parts[8]),
                    "r_await": float(parts[5]),
                    "w_await": float(parts[11]),
                })
            except (ValueError, IndexError):
                continue
    return rows_by_disk


def drift_for_disk(samples, window=WINDOW_S):
    """Compute BW drift between first/last window."""
    if len(samples) < 2 * window:
        return None
    first = samples[:window]
    last = samples[-window:]
    bw_first = sum(s["r_mbs"] + s["w_mbs"] for s in first) / window
    bw_last = sum(s["r_mbs"] + s["w_mbs"] for s in last) / window
    r_await_first = sum(s["r_await"] for s in first) / window
    r_await_last = sum(s["r_await"] for s in last) / window
    drift_pct = ((bw_last - bw_first) / bw_first * 100) if bw_first > 0 else 0.0
    await_ratio = (r_await_last / r_await_first) if r_await_first > 0 else 0.0
    return {
        "samples": len(samples),
        "duration_s": len(samples),  # 1Hz sampling
        "bw_first_mbs": bw_first,
        "bw_last_mbs": bw_last,
        "bw_drift_pct": drift_pct,
        "r_await_first_us": r_await_first,
        "r_await_last_us": r_await_last,
        "await_ratio": await_ratio,
    }


def main():
    if not RESULTS_DIR.exists():
        print(f"❌ {RESULTS_DIR} does not exist")
        sys.exit(1)

    # Group results by disk model (strip timestamp suffix)
    summary: dict[str, dict] = {}
    for result_dir in sorted(RESULTS_DIR.iterdir()):
        if not result_dir.is_dir():
            continue
        # name format: vendor_model_YYYYMMDD_HHMMSS
        name = result_dir.name
        parts = name.rsplit("_", 2)
        if len(parts) != 3:
            continue
        vendor_model = parts[0]
        iostat_path = result_dir / "iostat.txt"
        if not iostat_path.exists():
            continue
        rows_by_disk = parse_iostat(iostat_path)
        # Only care about the disk being tested
        vendor_disk_map = {
            "wd_sn570": "nvme0n1",
            "biwin_x570": "nvme1n1",
            "zhitai_ti600": "nvme2n1",
            "seagate_fc530": "nvme3n1",
        }
        target_disk = vendor_disk_map.get(vendor_model)
        if not target_disk:
            continue
        samples = rows_by_disk.get(target_disk, [])
        if not samples:
            continue
        drift = drift_for_disk(samples)
        if not drift:
            continue
        summary[vendor_model] = drift

    if not summary:
        print("❌ No T4 results found")
        sys.exit(1)

    # Print comparison table
    print(f"\n=== T4 GC Drift Summary ({WINDOW_S}s windows) ===\n")
    print(f"{'Disk':<20} {'Start BW':>10} {'End BW':>10} {'Drift':>8} {'R_Await':>10} {'Await':>8}")
    print("-" * 75)
    for vendor, d in summary.items():
        await_str = f"{d['r_await_first_us']:.0f}us→{d['r_await_last_us']:.0f}us"
        drift_color = "🟢" if d["bw_drift_pct"] > -10 else ("🟡" if d["bw_drift_pct"] > -25 else "🔴")
        print(
            f"{vendor:<20} "
            f"{d['bw_first_mbs']:>9.0f}M "
            f"{d['bw_last_mbs']:>9.0f}M "
            f"{drift_color}{d['bw_drift_pct']:>+6.1f}% "
            f"{await_str:>20} "
            f"{d['await_ratio']:>6.2f}x"
        )

    # Save as JSON for later report aggregation
    out_path = PROFILE_DIR / "results" / "cross_vendor" / "t4_gc_drift_summary.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n💾 Saved → {out_path}")


if __name__ == "__main__":
    main()