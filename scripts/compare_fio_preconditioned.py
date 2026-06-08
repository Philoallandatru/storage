#!/usr/bin/env python3
"""Compare fio iodepth sweep results: fresh SSD vs preconditioned SSD.

Reads both:
  - results/kvcache-profile/fio_sweep/sweep_summary.csv       (fresh)
  - results/kvcache-profile/fio_sweep_precond/sweep_precond_summary.csv  (preconditioned)

Produces:
  - results/kvcache-profile/fio_sweep_precond/sweep_precond_analysis.md
  - results/kvcache-profile/fio_sweep_precond/sweep_precond_comparison.png
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

FRESH = "/home/ficus/llm/storage/results/kvcache-profile/fio_sweep/sweep_summary.csv"
PRECOND = "/home/ficus/llm/storage/results/kvcache-profile/fio_sweep_precond/sweep_precond_summary.csv"
MD = "/home/ficus/llm/storage/results/kvcache-profile/fio_sweep_precond/sweep_precond_analysis.md"
PNG = "/home/ficus/llm/storage/results/kvcache-profile/fio_sweep_precond/sweep_precond_comparison.png"
PRECOND_JSON = "/home/ficus/llm/storage/results/kvcache-profile/fio_sweep_precond/precondition_clean.json"


def load(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
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


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:.1f}"
    return str(v)


def pct_change(new, old):
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old * 100


def arrow_pct(pct):
    if pct is None:
        return "n/a"
    if pct > 5:
        return f"+{pct:.0f}% (worse)"
    if pct < -5:
        return f"{pct:.0f}% (better)"
    return "~0% (same)"


def fmt_pct(pct):
    """Just format the percentage, no semantic annotation."""
    if pct is None:
        return "n/a"
    if pct > 0:
        return f"+{pct:.0f}%"
    if pct < 0:
        return f"{pct:.0f}%"
    return "~0%"


def md_table(fresh, precond):
    """Build a markdown comparison table."""
    fresh_by = {(r["workload"], r["iodepth"]): r for r in fresh}
    precond_by = {(r["workload"], r["iodepth"]): r for r in precond}

    keys = sorted(set(fresh_by.keys()) | set(precond_by.keys()),
                  key=lambda k: (str(k[0]), k[1] or 0))

    parts = []
    parts.append("# Preconditioned SSD fio sweep — comparison\n")
    parts.append("Compare the original fio iodepth sweep (fresh SSD) against the same")
    parts.append("sweep run after 100 GB of sequential preconditioning writes.\n")
    parts.append("## Preconditioning summary\n")

    if os.path.exists(PRECOND_JSON):
        import json
        d = json.load(open(PRECOND_JSON))
        j = d["jobs"][0]
        w = j["write"]
        parts.append(f"- Sequential writes: `{w['io_bytes']/1024**3:.1f} GiB`")
        parts.append(f"- Sustained BW: `{w['bw']/1024:.1f} MiB/s`")
        parts.append(f"- Avg IOPS: `{w['iops']:.0f}`")
        parts.append(f"- Time: `{w['runtime']/1e9:.1f} s`\n")

    parts.append("## Side-by-side comparison\n")
    parts.append("| Workload | qd | | R IOPS | W IOPS | R P99 (us) | W P99 (us) |")
    parts.append("|---|---:|---|---:|---:|---:|---:|")
    for k in keys:
        wl, qd = k
        f = fresh_by.get(k)
        p = precond_by.get(k)
        for label, r in [("fresh", f), ("precond", p)]:
            if r is None:
                parts.append(f"| {wl} | {qd} | {label} | - | - | - | - |")
            else:
                parts.append(
                    f"| {wl} | {qd} | {label} | "
                    f"{fmt(r['read_iops'])} | {fmt(r['write_iops'])} | "
                    f"{fmt(r['lat_read_p99_us'])} | {fmt(r['lat_write_p99_us'])} |"
                )

    parts.append("\n## Percent change (preconditioned vs fresh)\n")
    parts.append("Positive % on IOPS = better (more throughput). Negative % on P99 = better (lower latency).\n")
    parts.append("| Workload | qd | R IOPS Δ | R P99 Δ | W IOPS Δ | W P99 Δ |")
    parts.append("|---|---:|---:|---:|---:|---:|")
    for k in keys:
        wl, qd = k
        f = fresh_by.get(k)
        p = precond_by.get(k)
        if f is None or p is None:
            continue
        riops = pct_change(p["read_iops"], f["read_iops"])
        rlat = pct_change(p["lat_read_p99_us"], f["lat_read_p99_us"])
        wiops = pct_change(p["write_iops"], f["write_iops"])
        wlat = pct_change(p["lat_write_p99_us"], f["lat_write_p99_us"])
        parts.append(
            f"| {wl} | {qd} | {fmt_pct(riops)} | {fmt_pct(rlat)} | "
            f"{fmt_pct(wiops)} | {fmt_pct(wlat)} |"
        )
    parts.append("")
    return "\n".join(parts)


def plot(fresh, precond):
    if not HAVE_MPL:
        return
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    fresh_by = {(r["workload"], r["iodepth"]): r for r in fresh}
    precond_by = {(r["workload"], r["iodepth"]): r for r in precond}

    workloads = sorted(set(r["workload"] for r in fresh + precond))

    # Panel 1: R IOPS
    ax = axes[0, 0]
    for wl in workloads:
        f_iops = [fresh_by.get((wl, q), {}).get("read_iops") for q in [32, 1024]]
        p_iops = [precond_by.get((wl, q), {}).get("read_iops") for q in [32, 1024]]
        ax.plot([32, 1024], f_iops, "-o", label=f"{wl} (fresh)", alpha=0.6)
        ax.plot([32, 1024], p_iops, "--s", label=f"{wl} (precond)", alpha=0.9)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks([32, 1024])
    ax.set_xticklabels(["32", "1024"])
    ax.set_xlabel("iodepth")
    ax.set_ylabel("Read IOPS")
    ax.set_title("Read IOPS — fresh vs preconditioned")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)

    # Panel 2: W IOPS
    ax = axes[0, 1]
    for wl in workloads:
        f_iops = [fresh_by.get((wl, q), {}).get("write_iops") for q in [32, 1024]]
        p_iops = [precond_by.get((wl, q), {}).get("write_iops") for q in [32, 1024]]
        ax.plot([32, 1024], f_iops, "-o", label=f"{wl} (fresh)", alpha=0.6)
        ax.plot([32, 1024], p_iops, "--s", label=f"{wl} (precond)", alpha=0.9)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks([32, 1024])
    ax.set_xticklabels(["32", "1024"])
    ax.set_xlabel("iodepth")
    ax.set_ylabel("Write IOPS")
    ax.set_title("Write IOPS — fresh vs preconditioned")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)

    # Panel 3: R P99 latency
    ax = axes[1, 0]
    for wl in workloads:
        f_lat = [fresh_by.get((wl, q), {}).get("lat_read_p99_us") for q in [32, 1024]]
        p_lat = [precond_by.get((wl, q), {}).get("lat_read_p99_us") for q in [32, 1024]]
        ax.plot([32, 1024], f_lat, "-o", label=f"{wl} (fresh)", alpha=0.6)
        ax.plot([32, 1024], p_lat, "--s", label=f"{wl} (precond)", alpha=0.9)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks([32, 1024])
    ax.set_xticklabels(["32", "1024"])
    ax.set_xlabel("iodepth")
    ax.set_ylabel("R P99 latency (us)")
    ax.set_title("Read P99 latency — fresh vs preconditioned")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)

    # Panel 4: W P99 latency
    ax = axes[1, 1]
    for wl in workloads:
        f_lat = [fresh_by.get((wl, q), {}).get("lat_write_p99_us") for q in [32, 1024]]
        p_lat = [precond_by.get((wl, q), {}).get("lat_write_p99_us") for q in [32, 1024]]
        ax.plot([32, 1024], f_lat, "-o", label=f"{wl} (fresh)", alpha=0.6)
        ax.plot([32, 1024], p_lat, "--s", label=f"{wl} (precond)", alpha=0.9)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks([32, 1024])
    ax.set_xticklabels(["32", "1024"])
    ax.set_xlabel("iodepth")
    ax.set_ylabel("W P99 latency (us)")
    ax.set_title("Write P99 latency — fresh vs preconditioned")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)

    fig.suptitle("Preconditioned SSD fio sweep — fresh vs 100GB preconditioned", fontsize=14)
    fig.tight_layout()
    fig.savefig(PNG, dpi=110)
    print(f"saved {PNG}")


def main():
    fresh = load(FRESH)
    precond = load(PRECOND)
    if not precond:
        print(f"no preconditioned data; check {PRECOND}")
        return 1
    md = md_table(fresh, precond)
    with open(MD, "w") as f:
        f.write(md)
    print(f"saved {MD}")
    print()
    print(md)
    print()
    plot(fresh, precond)
    return 0


if __name__ == "__main__":
    sys.exit(main())