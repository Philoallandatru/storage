#!/usr/bin/env python3
"""Analyze fio iodepth sweep results and produce:
  - Markdown table summary
  - CSV pivot (one row per (workload, iodepth))
  - PNG plots: 4-panel latency vs iodepth + IOPS curve
"""
import csv
import os
import sys
from collections import defaultdict

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False

BASE = "/home/ficus/llm/storage/results/kvcache-profile/fio_sweep"
CSV = f"{BASE}/sweep_summary.csv"
MD = f"{BASE}/sweep_analysis.md"
PNG = f"{BASE}/sweep_curves.png"


def load():
    rows = []
    with open(CSV) as f:
        r = csv.DictReader(f)
        for row in r:
            # numeric coercion
            for k in (
                "iodepth",
                "read_iops", "write_iops",
                "read_bw_MiBs", "write_bw_MiBs",
                "lat_read_p50_us", "lat_read_p95_us", "lat_read_p99_us", "lat_read_p99_9_us",
                "lat_write_p50_us", "lat_write_p95_us", "lat_write_p99_us", "lat_write_p99_9_us",
            ):
                try:
                    v = row[k]
                    if v in (None, "", "None"):
                        row[k] = None
                    else:
                        row[k] = float(v) if k != "iodepth" else int(v)
                except (KeyError, ValueError):
                    row[k] = None
            rows.append(row)
    return rows


def fmt(v, unit=""):
    if v is None:
        return "-"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:.1f}"
    return str(v)


def pct_curve(rows):
    """For each workload, find the iodepth at which P99 latency first crosses
    the 10000us (10ms) and 100000us (100ms) thresholds."""
    out = []
    by_wl = defaultdict(list)
    for row in rows:
        by_wl[row["workload"]].append(row)
    for wl, lst in by_wl.items():
        lst.sort(key=lambda r: r["iodepth"] or 0)
        knee10 = None
        knee100 = None
        for r in lst:
            rp99 = r["lat_read_p99_us"]
            if rp99 is None:
                continue
            if knee10 is None and rp99 >= 10000:
                knee10 = r["iodepth"]
            if knee100 is None and rp99 >= 100000:
                knee100 = r["iodepth"]
        out.append({
            "workload": wl,
            "knee10_ms_iodepth": knee10,
            "knee100_ms_iodepth": knee100,
            "max_read_iops": max((r["read_iops"] or 0) for r in lst),
            "max_write_iops": max((r["write_iops"] or 0) for r in lst),
        })
    return out


def md_table(rows):
    by_wl = defaultdict(list)
    for r in rows:
        by_wl[r["workload"]].append(r)
    for k in by_wl:
        by_wl[k].sort(key=lambda r: r["iodepth"] or 0)
    parts = []
    parts.append("# fio iodepth sweep — results\n")
    parts.append("## Data Table\n")
    parts.append("| Workload | rwmix% | iodepth | R IOPS | R BW(MiB/s) | W IOPS | W BW(MiB/s) | R P50(us) | R P95(us) | R P99(us) | R P99.9(us) | W P50(us) | W P95(us) | W P99(us) | W P99.9(us) |")
    parts.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for wl, lst in by_wl.items():
        for r in lst:
            parts.append("| {wl} | {mix} | {qd} | {r_iops} | {r_bw} | {w_iops} | {w_bw} | {r_p50} | {r_p95} | {r_p99} | {r_p99_9} | {w_p50} | {w_p95} | {w_p99} | {w_p99_9} |".format(
                wl=wl,
                mix=r["rwmixread_pct"],
                qd=r["iodepth"],
                r_iops=fmt(r["read_iops"]),
                r_bw=fmt(r["read_bw_MiBs"]),
                w_iops=fmt(r["write_iops"]),
                w_bw=fmt(r["write_bw_MiBs"]),
                r_p50=fmt(r["lat_read_p50_us"]),
                r_p95=fmt(r["lat_read_p95_us"]),
                r_p99=fmt(r["lat_read_p99_us"]),
                r_p99_9=fmt(r["lat_read_p99_9_us"]),
                w_p50=fmt(r["lat_write_p50_us"]),
                w_p95=fmt(r["lat_write_p95_us"]),
                w_p99=fmt(r["lat_write_p99_us"]),
                w_p99_9=fmt(r["lat_write_p99_9_us"]),
            ))
    parts.append("\n## Saturation Point Analysis\n")
    parts.append("| Workload | First iodepth where R P99 ≥ 10ms | First iodepth where R P99 ≥ 100ms | Max R IOPS achieved | Max W IOPS achieved |")
    parts.append("|---|---|---|---:|---:|")
    for s in pct_curve(rows):
        parts.append("| {wl} | {k10} | {k100} | {mr} | {mw} |".format(
            wl=s["workload"],
            k10=s["knee10_ms_iodepth"] if s["knee10_ms_iodepth"] else "-",
            k100=s["knee100_ms_iodepth"] if s["knee100_ms_iodepth"] else "-",
            mr=fmt(s["max_read_iops"]),
            mw=fmt(s["max_write_iops"]),
        ))
    parts.append("")
    return "\n".join(parts)


def plot(rows):
    if not HAVE_MPL:
        print("matplotlib not available; skipping plots")
        return
    by_wl = defaultdict(list)
    for r in rows:
        by_wl[r["workload"]].append(r)
    for lst in by_wl.values():
        lst.sort(key=lambda r: r["iodepth"] or 0)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    # Panel 1: R P50/P95/P99 vs iodepth
    ax = axes[0, 0]
    for wl, lst in by_wl.items():
        qd = [r["iodepth"] for r in lst]
        p50 = [r["lat_read_p50_us"] or 0 for r in lst]
        p95 = [r["lat_read_p95_us"] or 0 for r in lst]
        p99 = [r["lat_read_p99_us"] or 0 for r in lst]
        ax.plot(qd, p50, "-o", label=f"{wl} P50", alpha=0.6)
        ax.plot(qd, p95, "--s", label=f"{wl} P95", alpha=0.6)
        ax.plot(qd, p99, ":^", label=f"{wl} P99", alpha=0.9, linewidth=2)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("iodepth (log2)")
    ax.set_ylabel("Read latency (us, log)")
    ax.set_title("Read latency vs iodepth (log-log)")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, which="both", alpha=0.3)

    # Panel 2: W P50/P95/P99 vs iodepth
    ax = axes[0, 1]
    for wl, lst in by_wl.items():
        qd = [r["iodepth"] for r in lst]
        p50 = [r["lat_write_p50_us"] or 0.01 for r in lst]
        p95 = [r["lat_write_p95_us"] or 0.01 for r in lst]
        p99 = [r["lat_write_p99_us"] or 0.01 for r in lst]
        ax.plot(qd, p50, "-o", label=f"{wl} P50", alpha=0.6)
        ax.plot(qd, p95, "--s", label=f"{wl} P95", alpha=0.6)
        ax.plot(qd, p99, ":^", label=f"{wl} P99", alpha=0.9, linewidth=2)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("iodepth (log2)")
    ax.set_ylabel("Write latency (us, log)")
    ax.set_title("Write latency vs iodepth (log-log)")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, which="both", alpha=0.3)

    # Panel 3: IOPS vs iodepth
    ax = axes[1, 0]
    for wl, lst in by_wl.items():
        qd = [r["iodepth"] for r in lst]
        r_iops = [r["read_iops"] or 0 for r in lst]
        w_iops = [r["write_iops"] or 0 for r in lst]
        ax.plot(qd, r_iops, "-o", label=f"{wl} R IOPS")
        ax.plot(qd, w_iops, "--s", label=f"{wl} W IOPS")
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("iodepth (log2)")
    ax.set_ylabel("IOPS (log)")
    ax.set_title("IOPS vs iodepth")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, which="both", alpha=0.3)

    # Panel 4: BW vs iodepth
    ax = axes[1, 1]
    for wl, lst in by_wl.items():
        qd = [r["iodepth"] for r in lst]
        r_bw = [r["read_bw_MiBs"] or 0 for r in lst]
        w_bw = [r["write_bw_MiBs"] or 0 for r in lst]
        ax.plot(qd, r_bw, "-o", label=f"{wl} R BW")
        ax.plot(qd, w_bw, "--s", label=f"{wl} W BW")
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("iodepth (log2)")
    ax.set_ylabel("BW (MiB/s, log)")
    ax.set_title("Bandwidth vs iodepth")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, which="both", alpha=0.3)

    fig.suptitle("fio iodepth sweep — KV-Cache AI SSD pre-study", fontsize=14)
    fig.tight_layout()
    fig.savefig(PNG, dpi=110)
    print(f"saved {PNG}")


def main():
    rows = load()
    if not rows:
        print("no rows loaded; check", CSV)
        return 1
    md = md_table(rows)
    with open(MD, "w") as f:
        f.write(md)
    print(f"saved {MD}")
    print()
    print(md)
    print()
    plot(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())