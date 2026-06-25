#!/usr/bin/env python3
"""Plot raw KV-cache iostat samples to show IO randomness.

This script reads the original 1 Hz iostat logs from the K4 GC-drift run and
renders:
  1. Raw time-series small multiples per disk.
  2. Distribution boxplots across disks.
  3. A compact markdown summary of the randomness indicators.

The intent is to visualize the original samples directly, not just the already
summarized tables.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from analyze_kv_cache_iostat import DEV_FOR_DISK, detect_cliff, parse_iostat, quartile_stats  # noqa: E402


DISKS = ["biwin_x570", "seagate_fc530", "zhitai_ti600", "wd_sn570"]
DISK_LABEL = {
    "biwin_x570": "Biwin X570",
    "seagate_fc530": "Seagate FC530",
    "zhitai_ti600": "ZhiTai Ti600",
    "wd_sn570": "WD SN570",
}
COLOR = {
    "biwin_x570": "#2ca02c",
    "seagate_fc530": "#ffbb33",
    "zhitai_ti600": "#d62728",
    "wd_sn570": "#1f77b4",
}


def rolling_mean(values: list[float], window: int = 30) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(arr.shape, np.nan, dtype=float)
    if len(arr) < window:
        return out
    csum = np.cumsum(np.insert(arr, 0, 0.0))
    out[window - 1 :] = (csum[window:] - csum[:-window]) / window
    return out


def finite_stats(values: list[float], prefix: str) -> dict[str, Any]:
    vals = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    if not vals:
        return {}
    stats = quartile_stats(vals, prefix)
    stats[f"{prefix}mean"] = float(np.mean(vals))
    return stats


def load_samples(base: Path) -> dict[str, list[dict[str, float]]]:
    out: dict[str, list[dict[str, float]]] = {}
    for disk in DISKS:
        path = base / disk / "K4_16u_llama3.1-8b_1200s" / "iostat.txt"
        if not path.exists():
            continue
        raw = parse_iostat(path, DEV_FOR_DISK[disk])
        samples = []
        for idx, row in enumerate(raw):
            samples.append(
                {
                    "t": float(idx),
                    "r_mbs": float(row["r_mbs"]),
                    "w_mbs": float(row["w_mbs"]),
                    "rareq_sz": float(row["rareq_sz"]),
                    "wareq_sz": float(row["wareq_sz"]),
                    "pct_rrqm": float(row["pct_rrqm"]),
                    "pct_wrqm": float(row["pct_wrqm"]),
                    "r_await": float(row["r_await"]),
                    "w_await": float(row["w_await"]),
                    "aqu_sz": float(row["aqu_sz"]),
                }
            )
        out[disk] = samples
    return out


def summarize(samples_by_disk: dict[str, list[dict[str, float]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for disk, samples in samples_by_disk.items():
        cliff_s = detect_cliff(samples, key="r_mbs", warmup_s=120, window=30, drop_pct=20)
        rows.append(
            {
                "disk": DISK_LABEL[disk],
                "samples": len(samples),
                "cliff_s": cliff_s if cliff_s is not None else "",
                "cliff_min": f"{cliff_s / 60:.1f}" if cliff_s is not None else "",
                "read_req_median_kb": quartile_stats([s["rareq_sz"] for s in samples if s["rareq_sz"] > 0], "x_").get("x_median", ""),
                "read_req_p99_kb": quartile_stats([s["rareq_sz"] for s in samples if s["rareq_sz"] > 0], "x_").get("x_p99", ""),
                "write_req_median_kb": quartile_stats([s["wareq_sz"] for s in samples if s["wareq_sz"] > 0], "x_").get("x_median", ""),
                "write_req_p99_kb": quartile_stats([s["wareq_sz"] for s in samples if s["wareq_sz"] > 0], "x_").get("x_p99", ""),
                "rrqm_median_pct": quartile_stats([s["pct_rrqm"] for s in samples], "x_").get("x_median", ""),
                "rrqm_p99_pct": quartile_stats([s["pct_rrqm"] for s in samples], "x_").get("x_p99", ""),
                "wrqm_median_pct": quartile_stats([s["pct_wrqm"] for s in samples], "x_").get("x_median", ""),
                "wrqm_p99_pct": quartile_stats([s["pct_wrqm"] for s in samples], "x_").get("x_p99", ""),
                "r_await_median_ms": quartile_stats([s["r_await"] for s in samples if s["r_await"] > 0], "x_").get("x_median", ""),
                "r_await_p99_ms": quartile_stats([s["r_await"] for s in samples if s["r_await"] > 0], "x_").get("x_p99", ""),
                "w_await_median_ms": quartile_stats([s["w_await"] for s in samples if s["w_await"] > 0], "x_").get("x_median", ""),
                "w_await_p99_ms": quartile_stats([s["w_await"] for s in samples if s["w_await"] > 0], "x_").get("x_p99", ""),
                "aqu_median": quartile_stats([s["aqu_sz"] for s in samples], "x_").get("x_median", ""),
                "aqu_p95": quartile_stats([s["aqu_sz"] for s in samples], "x_").get("x_p95", ""),
                "aqu_p99": quartile_stats([s["aqu_sz"] for s in samples], "x_").get("x_p99", ""),
            }
        )
    return rows


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "disk",
        "samples",
        "cliff_s",
        "cliff_min",
        "read_req_median_kb",
        "read_req_p99_kb",
        "write_req_median_kb",
        "write_req_p99_kb",
        "rrqm_median_pct",
        "rrqm_p99_pct",
        "wrqm_median_pct",
        "wrqm_p99_pct",
        "r_await_median_ms",
        "r_await_p99_ms",
        "w_await_median_ms",
        "w_await_p99_ms",
        "aqu_median",
        "aqu_p95",
        "aqu_p99",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


def plot_timeseries(samples_by_disk: dict[str, list[dict[str, float]]], out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(DISKS), 4, figsize=(20, 16), sharex="col")
    fig.suptitle("KV cache raw iostat samples — K4 GC drift", fontsize=15, fontweight="bold")

    for row_idx, disk in enumerate(DISKS):
        samples = samples_by_disk.get(disk)
        if not samples:
            continue
        t = np.asarray([s["t"] for s in samples], dtype=float) / 60.0
        color = COLOR[disk]
        cliff_s = detect_cliff(samples, key="r_mbs", warmup_s=120, window=30, drop_pct=20)
        cliff_min = cliff_s / 60.0 if cliff_s is not None else None

        # 1) Throughput
        ax = axes[row_idx, 0]
        r_bw = np.asarray([s["r_mbs"] for s in samples], dtype=float)
        w_bw = np.asarray([s["w_mbs"] for s in samples], dtype=float)
        ax.plot(t, r_bw, color=color, alpha=0.28, linewidth=0.8)
        ax.plot(t, rolling_mean(r_bw.tolist(), 30), color=color, linewidth=2.0, label="read")
        ax.plot(t, w_bw, color="#555555", alpha=0.20, linewidth=0.8)
        ax.plot(t, rolling_mean(w_bw.tolist(), 30), color="#555555", linewidth=1.7, label="write")
        if cliff_min is not None:
            ax.axvline(cliff_min, color="red", linestyle="--", linewidth=1.2)
        ax.set_ylabel(f"{DISK_LABEL[disk]}\nMB/s")
        ax.set_title("Throughput")
        ax.legend(loc="upper right", fontsize=8)

        # 2) Request size
        ax = axes[row_idx, 1]
        rareq = np.asarray([s["rareq_sz"] for s in samples], dtype=float)
        wareq = np.asarray([s["wareq_sz"] for s in samples], dtype=float)
        ax.plot(t, rareq, color=color, alpha=0.28, linewidth=0.8)
        ax.plot(t, rolling_mean(rareq.tolist(), 30), color=color, linewidth=2.0, label="read")
        ax.plot(t, wareq, color="#555555", alpha=0.20, linewidth=0.8)
        ax.plot(t, rolling_mean(wareq.tolist(), 30), color="#555555", linewidth=1.7, label="write")
        ax.set_title("Request size (kB)")
        ax.legend(loc="upper right", fontsize=8)

        # 3) Merge ratio
        ax = axes[row_idx, 2]
        rrqm = np.asarray([s["pct_rrqm"] for s in samples], dtype=float)
        wrqm = np.asarray([s["pct_wrqm"] for s in samples], dtype=float)
        ax.plot(t, rrqm, color=color, alpha=0.30, linewidth=0.8)
        ax.plot(t, rolling_mean(rrqm.tolist(), 30), color=color, linewidth=2.0, label="%rrqm")
        ax.plot(t, wrqm, color="#555555", alpha=0.24, linewidth=0.8)
        ax.plot(t, rolling_mean(wrqm.tolist(), 30), color="#555555", linewidth=1.7, label="%wrqm")
        ax.set_title("Merge ratio (%)")
        ax.legend(loc="upper right", fontsize=8)

        # 4) Await and queue depth
        ax = axes[row_idx, 3]
        r_await = np.asarray([s["r_await"] for s in samples], dtype=float)
        w_await = np.asarray([s["w_await"] for s in samples], dtype=float)
        aqu = np.asarray([s["aqu_sz"] for s in samples], dtype=float)
        ax.plot(t, r_await, color=color, alpha=0.30, linewidth=0.8)
        ax.plot(t, rolling_mean(r_await.tolist(), 30), color=color, linewidth=2.0, label="r_await")
        ax.plot(t, w_await, color="#555555", alpha=0.24, linewidth=0.8)
        ax.plot(t, rolling_mean(w_await.tolist(), 30), color="#555555", linewidth=1.7, label="w_await")
        ax.set_yscale("log")
        ax.set_title("Service time (ms)")
        ax2 = ax.twinx()
        ax2.plot(t, aqu, color="#9467bd", alpha=0.22, linewidth=0.8)
        ax2.plot(t, rolling_mean(aqu.tolist(), 30), color="#9467bd", linewidth=1.5, label="aqu-sz")
        ax2.set_ylabel("aqu-sz")
        if row_idx == 0:
            ax.legend(loc="upper left", fontsize=8)
            ax2.legend(loc="upper right", fontsize=8)

        if row_idx < len(DISKS) - 1:
            for col in range(4):
                axes[row_idx, col].tick_params(labelbottom=False)

    for col in range(4):
        axes[-1, col].set_xlabel("Time (min)")

    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(out, dpi=160)
    plt.close(fig)


def plot_boxplots(samples_by_disk: dict[str, list[dict[str, float]]], out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metrics = [
        ("rareq_sz", "Read req size (kB)", False),
        ("wareq_sz", "Write req size (kB)", False),
        ("pct_rrqm", "%rrqm", False),
        ("pct_wrqm", "%wrqm", False),
        ("r_await", "Read await (ms)", False),
        ("w_await", "Write await (ms)", True),
        ("aqu_sz", "Queue depth (aqu-sz)", False),
    ]
    fig, axes = plt.subplots(2, 4, figsize=(18, 9))
    axes = axes.flatten()
    fig.suptitle("KV cache raw iostat distributions — K4 GC drift", fontsize=15, fontweight="bold")

    labels = [DISK_LABEL[d] for d in DISKS]
    for idx, (key, title, logy) in enumerate(metrics):
        ax = axes[idx]
        data = []
        for disk in DISKS:
            vals = [float(s[key]) for s in samples_by_disk.get(disk, []) if float(s[key]) >= 0]
            data.append(vals)
        bp = ax.boxplot(data, patch_artist=True, showfliers=False, medianprops={"color": "black", "linewidth": 2})
        for patch, disk in zip(bp["boxes"], DISKS):
            patch.set_facecolor(COLOR[disk])
            patch.set_alpha(0.65)
        ax.set_title(title)
        ax.set_xticks(range(1, len(labels) + 1))
        ax.set_xticklabels(labels, rotation=18)
        if logy:
            ax.set_yscale("log")

    axes[-1].axis("off")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out, dpi=160)
    plt.close(fig)


def render_md(rows: list[dict[str, Any]], out: Path, data_root: Path) -> None:
    lines = [
        "# KV Cache IO Randomness Raw Data",
        "",
        f"Source: `{data_root}`",
        "",
        "## Conclusion",
        "",
        "The raw iostat samples show an application-locked large-block random workload:",
        "- read request size is tightly clustered around 124-125 kB across all disks",
        "- write request size is tightly clustered around 113-116 kB",
        "- `%rrqm` stays at 0 for all four disks",
        "- `%wrqm` is near zero in median, with occasional write merge spikes on some disks",
        "- the real separation is in `r_await`, `w_await`, and `aqu-sz`, not in request shape",
        "",
        "## Raw summary",
        "",
        "| Disk | Samples | Cliff (min) | Read req p50 (kB) | Read req p99 (kB) | Write req p50 (kB) | Write req p99 (kB) | %rrqm p50 | %wrqm p50 | r_await p99 (ms) | w_await p99 (ms) | aqu p99 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['disk']} | {r['samples']} | {r['cliff_min']} | "
            f"{r['read_req_median_kb']:.2f} | {r['read_req_p99_kb']:.2f} | "
            f"{r['write_req_median_kb']:.2f} | {r['write_req_p99_kb']:.2f} | "
            f"{r['rrqm_median_pct']:.2f} | {r['wrqm_median_pct']:.2f} | "
            f"{r['r_await_p99_ms']:.2f} | {r['w_await_p99_ms']:.2f} | {r['aqu_p99']:.2f} |"
        )
    lines += [
        "",
        "## Files",
        "",
        "- `kvcache_io_randomness_timeseries.png`",
        "- `kvcache_io_randomness_boxplots.png`",
        "- `kvcache_io_randomness_summary.csv`",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", type=Path, default=REPO / "results/cross_vendor/kv_cache_k4_gc_drift")
    ap.add_argument("--out-dir", type=Path, default=REPO / "results/cross_vendor/kv_cache_k4_gc_drift/_analysis")
    args = ap.parse_args()

    samples_by_disk = load_samples(args.input_dir)
    if not samples_by_disk:
        raise SystemExit(f"no iostat samples found under {args.input_dir}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = summarize(samples_by_disk)
    save_csv(args.out_dir / "kvcache_io_randomness_summary.csv", rows)
    plot_timeseries(samples_by_disk, args.out_dir / "kvcache_io_randomness_timeseries.png")
    plot_boxplots(samples_by_disk, args.out_dir / "kvcache_io_randomness_boxplots.png")
    render_md(rows, args.out_dir / "kvcache_io_randomness.md", args.input_dir)

    print(f"wrote {args.out_dir / 'kvcache_io_randomness_timeseries.png'}")
    print(f"wrote {args.out_dir / 'kvcache_io_randomness_boxplots.png'}")
    print(f"wrote {args.out_dir / 'kvcache_io_randomness_summary.csv'}")
    print(f"wrote {args.out_dir / 'kvcache_io_randomness.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
