#!/usr/bin/env python3
"""Analyze long steady-state iostat.log for GC drift.

Reads iostat.log (per-second samples), extracts nvme1n1 stats, and produces:
- time-series CSV (1 row per second)
- time-series plot (4 panels: BW, IOPS, %util, await)
- 5-minute windowed statistics showing drift

Parser is robust to iostat output format: it locates column indices by
matching the header row, so it works with various iostat -dx -m layouts.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# Known column names we want. We match against the iostat header line.
DESIRED_COLS = [
    "r/s",
    "rMB/s",
    "rkB/s",
    "w/s",
    "wMB/s",
    "wkB/s",
    "rareq-sz",
    "wareq-sz",
    "r_await",
    "w_await",
    "aqu-sz",
    "%util",
    "await",
]


@dataclass
class IOStatSample:
    second: int
    r_mb_s: float
    w_mb_s: float
    r_iops: float
    w_iops: float
    util_pct: float
    await_ms: float
    rareq_sz_kb: float
    wareq_sz_kb: float


def find_header_columns(header_line: str) -> dict[str, int] | None:
    """Locate column indices by matching header tokens."""
    tokens = header_line.split()
    if tokens[0] != "Device":
        return None
    found: dict[str, int] = {}
    for i, tok in enumerate(tokens):
        if tok in DESIRED_COLS:
            found[tok] = i
    return found if found else None


def parse_iostat_log(path: Path) -> list[IOStatSample]:
    """Parse iostat.log. Find header line, then parse device rows for nvme1n1."""
    samples: list[IOStatSample] = []
    cols: dict[str, int] | None = None
    with path.open() as f:
        for line in f:
            line = line.rstrip()
            # Header lines start with "Device"
            if line.lstrip().startswith("Device"):
                cols = find_header_columns(line)
                if not cols or "r/s" not in cols or "%util" not in cols:
                    return []  # unsupported layout
                continue
            if not cols:
                continue
            if not line.startswith("nvme1n1"):
                continue
            tokens = line.split()
            # Need at least the right number of columns
            if len(tokens) < max(cols.values()) + 1:
                continue
            try:
                r_iops = float(tokens[cols["r/s"]])
                w_iops = float(tokens[cols["w/s"]])
                # Prefer MB/s columns; fall back to kB/s if missing
                if "rMB/s" in cols:
                    r_mb = float(tokens[cols["rMB/s"]])
                elif "rkB/s" in cols:
                    r_mb = float(tokens[cols["rkB/s"]]) / 1024.0
                else:
                    r_mb = 0.0
                if "wMB/s" in cols:
                    w_mb = float(tokens[cols["wMB/s"]])
                elif "wkB/s" in cols:
                    w_mb = float(tokens[cols["wkB/s"]]) / 1024.0
                else:
                    w_mb = 0.0
                util = float(tokens[cols["%util"]])
                # r_await + w_await = avg await (need weighted, but simpler to use whichever is available)
                if "r_await" in cols and "w_await" in cols:
                    r_await = float(tokens[cols["r_await"]])
                    w_await = float(tokens[cols["w_await"]])
                    if (r_iops + w_iops) > 0:
                        await_ms = (r_await * r_iops + w_await * w_iops) / (r_iops + w_iops)
                    else:
                        await_ms = 0.0
                elif "await" in cols:
                    await_ms = float(tokens[cols["await"]])
                else:
                    await_ms = 0.0
                rareq_sz_kb = float(tokens[cols["rareq-sz"]]) if "rareq-sz" in cols else 0.0
                wareq_sz_kb = float(tokens[cols["wareq-sz"]]) if "wareq-sz" in cols else 0.0
            except (ValueError, IndexError):
                continue

            samples.append(
                IOStatSample(
                    second=len(samples),
                    r_mb_s=r_mb,
                    w_mb_s=w_mb,
                    r_iops=r_iops,
                    w_iops=w_iops,
                    util_pct=util,
                    await_ms=await_ms,
                    rareq_sz_kb=rareq_sz_kb,
                    wareq_sz_kb=wareq_sz_kb,
                )
            )
    return samples


def write_csv(samples: list[IOStatSample], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["second", "r_mb_s", "w_mb_s", "r_iops", "w_iops", "util_pct", "await_ms", "rareq_sz_kb", "wareq_sz_kb"])
        for s in samples:
            w.writerow([s.second, f"{s.r_mb_s:.2f}", f"{s.w_mb_s:.2f}",
                        f"{s.r_iops:.2f}", f"{s.w_iops:.2f}",
                        f"{s.util_pct:.2f}", f"{s.await_ms:.2f}",
                        f"{s.rareq_sz_kb:.2f}", f"{s.wareq_sz_kb:.2f}"])


def plot_timeseries(samples: list[IOStatSample], path: Path) -> None:
    secs = [s.second for s in samples]
    r_mb = [s.r_mb_s for s in samples]
    w_mb = [s.w_mb_s for s in samples]
    r_iops = [s.r_iops for s in samples]
    w_iops = [s.w_iops for s in samples]
    util = [s.util_pct for s in samples]
    await_vals = [s.await_ms for s in samples]

    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)

    axes[0].plot(secs, r_mb, label="Read MB/s", color="tab:blue", alpha=0.7)
    axes[0].plot(secs, w_mb, label="Write MB/s", color="tab:orange", alpha=0.7)
    axes[0].set_ylabel("Bandwidth (MB/s)")
    axes[0].set_title(f"Long steady-state run — {len(samples)}s of nvme1n1 I/O")
    axes[0].legend(loc="upper right")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(secs, r_iops, label="Read IOPS", color="tab:blue", alpha=0.7)
    axes[1].plot(secs, w_iops, label="Write IOPS", color="tab:orange", alpha=0.7)
    axes[1].set_ylabel("IOPS")
    axes[1].legend(loc="upper right")
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(secs, util, label="%util", color="tab:green")
    axes[2].set_ylabel("%util")
    axes[2].set_ylim(0, 105)
    axes[2].legend(loc="upper right")
    axes[2].grid(True, alpha=0.3)

    axes[3].plot(secs, await_vals, label="await (ms)", color="tab:red", alpha=0.7)
    axes[3].set_ylabel("await (ms)")
    axes[3].set_xlabel("Time (s)")
    axes[3].legend(loc="upper right")
    axes[3].grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def windowed_stats(samples: list[IOStatSample], window_s: int = 300) -> list[dict]:
    """Compute mean stats for each window_s-second bucket."""
    if not samples:
        return []
    out = []
    max_sec = max(s.second for s in samples)
    for wstart in range(0, max_sec, window_s):
        wend = min(wstart + window_s, max_sec + 1)
        bucket = [s for s in samples if wstart <= s.second < wend]
        if not bucket:
            continue
        out.append({
            "window_start_s": wstart,
            "window_end_s": wend - 1,
            "samples": len(bucket),
            "r_mb_s_mean": sum(s.r_mb_s for s in bucket) / len(bucket),
            "w_mb_s_mean": sum(s.w_mb_s for s in bucket) / len(bucket),
            "r_iops_mean": sum(s.r_iops for s in bucket) / len(bucket),
            "w_iops_mean": sum(s.w_iops for s in bucket) / len(bucket),
            "util_mean": sum(s.util_pct for s in bucket) / len(bucket),
            "await_mean": sum(s.await_ms for s in bucket) / len(bucket),
            "await_p95": sorted(s.await_ms for s in bucket)[int(len(bucket) * 0.95)] if bucket else 0,
            "await_max": max(s.await_ms for s in bucket) if bucket else 0,
        })
    return out


def write_window_csv(stats: list[dict], path: Path) -> None:
    if not stats:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=stats[0].keys())
        w.writeheader()
        w.writerows(stats)


def write_report_md(samples: list[IOStatSample], stats: list[dict], path: Path) -> None:
    total_runtime_s = max(s.second for s in samples) + 1 if samples else 0
    avg_r = sum(s.r_mb_s for s in samples) / len(samples) if samples else 0
    avg_w = sum(s.w_mb_s for s in samples) / len(samples) if samples else 0
    avg_util = sum(s.util_pct for s in samples) / len(samples) if samples else 0
    avg_await = sum(s.await_ms for s in samples) / len(samples) if samples else 0
    max_util = max(s.util_pct for s in samples) if samples else 0
    max_await = max(s.await_ms for s in samples) if samples else 0
    avg_riops = sum(s.r_iops for s in samples) / len(samples) if samples else 0
    avg_wiops = sum(s.w_iops for s in samples) / len(samples) if samples else 0

    lines = [
        "# Long Steady-State Run — GC Drift Analysis",
        "",
        f"Total runtime: {total_runtime_s} s ({total_runtime_s / 60:.1f} min)",
        f"Total iostat samples: {len(samples)}",
        "",
        "## Overall Statistics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Avg Read BW | {avg_r:.2f} MB/s |",
        f"| Avg Write BW | {avg_w:.2f} MB/s |",
        f"| Avg Read IOPS | {avg_riops:.1f} |",
        f"| Avg Write IOPS | {avg_wiops:.1f} |",
        f"| Avg %util | {avg_util:.2f} % |",
        f"| Avg await | {avg_await:.2f} ms |",
        f"| Peak %util | {max_util:.2f} % |",
        f"| Peak await | {max_await:.2f} ms |",
        "",
        "## GC Drift — 5-minute Window Comparison",
        "",
        "This shows whether SSD behavior changes over a long run",
        "(early vs middle vs late).",
        "",
        "| Window | R MB/s | W MB/s | R IOPS | W IOPS | %util | await | await P95 | await max |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in stats:
        lines.append(
            f"| {s['window_start_s']}-{s['window_end_s']}s "
            f"| {s['r_mb_s_mean']:.2f} | {s['w_mb_s_mean']:.2f} "
            f"| {s['r_iops_mean']:.1f} | {s['w_iops_mean']:.1f} "
            f"| {s['util_mean']:.2f} | {s['await_mean']:.2f} "
            f"| {s['await_p95']:.2f} | {s['await_max']:.2f} |"
        )

    if len(stats) >= 2:
        first = stats[0]
        last = stats[-1]
        drift_util = last["util_mean"] - first["util_mean"]
        drift_await = last["await_mean"] - first["await_mean"]
        lines.extend([
            "",
            "## Drift Detection",
            "",
            f"- First window %util: {first['util_mean']:.2f} %",
            f"- Last window %util:  {last['util_mean']:.2f} %",
            f"- Drift: {drift_util:+.2f} % (positive = SSD busier)",
            f"- First window await: {first['await_mean']:.2f} ms",
            f"- Last window await:  {last['await_mean']:.2f} ms",
            f"- Drift: {drift_await:+.2f} ms (positive = slower)",
            "",
        ])
        if abs(drift_util) < 5 and abs(drift_await) < 10:
            lines.append("**Conclusion**: No significant GC drift detected.")
            lines.append("SSD reaches steady state quickly and remains stable.")
        elif drift_util > 5 or drift_await > 10:
            lines.append("**Conclusion**: GC drift detected — late-window has more pressure.")
            lines.append("This suggests background GC activity increases over time.")
        else:
            lines.append("**Conclusion**: Mixed signal — investigate further.")

    lines.append("")
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iostat-log", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    in_path = Path(args.iostat_log)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = parse_iostat_log(in_path)
    if not samples:
        print(f"ERROR: no nvme1n1 samples parsed from {in_path}", file=sys.stderr)
        return 1

    csv_path = out_dir / "iostat_timeseries.csv"
    png_path = out_dir / "iostat_timeseries.png"
    win_csv_path = out_dir / "iostat_window_5min.csv"
    md_path = out_dir / "gc_drift_report.md"

    write_csv(samples, csv_path)
    plot_timeseries(samples, png_path)
    stats = windowed_stats(samples, window_s=300)
    write_window_csv(stats, win_csv_path)
    write_report_md(samples, stats, md_path)

    print(f"Parsed {len(samples)} samples ({max(s.second for s in samples) + 1}s)")
    print(f"  csv:      {csv_path}")
    print(f"  plot:     {png_path}")
    print(f"  windows:  {win_csv_path}")
    print(f"  report:   {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())