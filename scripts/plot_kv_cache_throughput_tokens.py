#!/usr/bin/env python3
"""Plot KV cache cross-vendor throughput in tokens/s.

Companion figure to ``docs/assets/test-history-io-summary/01_kvcache_read_bw_summary.png``
(GB/s) but with the throughput axis converted from GB/s to tokens/s.

Source data: ``results/history-summary/test_history_master.csv`` columns
``tok_s`` (throughput) and ``read_bw_gbps`` (bandwidth), one row per run.

Same scenarios and vendors as the bandwidth chart so the two figures can be
compared side-by-side:

  - K4 16u 8B 120s        (8B model, 16 concurrent users, 120 s)
  - K4 16u 8B 1200s       (8B model, 16 concurrent users, 1200 s long-steady)
  - K5 4u 70B 180s        (70B model, 4 concurrent users, 180 s)
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

VENDOR_ORDER = ["Biwin X570", "Seagate FC530", "ZhiTai Ti600", "WD SN570"]

SCENARIO_ORDER = ["K4 16u 8B 120s", "K4 16u 8B 1200s", "K5 4u 70B 180s"]

SCENARIO_TEST_IDS = {
    "K4 16u 8B 120s":   "K4_16u_llama3.1-8b_120s",
    "K4 16u 8B 1200s":  "K4_16u_llama3.1-8b_1200s",
    "K5 4u 70B 180s":   "K5_4u_llama3.1-70b-instruct_180s",
}

SCENARIO_COLOR = {
    "K4 16u 8B 120s":   "#1f77b4",   # blue  (matches original fig)
    "K4 16u 8B 1200s":  "#ff7f0e",   # orange (matches original fig)
    "K5 4u 70B 180s":   "#2ca02c",   # green  (matches original fig)
}


def load_history(csv_path: Path) -> dict[tuple[str, str], list[dict]]:
    """Group rows by (vendor, scenario) into a list of run dicts."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    test_id_to_scenario = {v: k for k, v in SCENARIO_TEST_IDS.items()}

    with csv_path.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            tid = row["test_id"]
            if tid not in test_id_to_scenario:
                continue
            scenario = test_id_to_scenario[tid]
            vendor = row["vendor"]
            grouped[(vendor, scenario)].append({
                "tok_s": float(row["tok_s"]),
                "read_bw_gbps": float(row["read_bw_gbps"]),
                "status": row["status"],
            })
    return grouped


def aggregate(grouped: dict) -> dict[tuple[str, str], dict]:
    """Average repeated runs to a single (mean, std, n) per (vendor, scenario)."""
    out = {}
    for k, runs in grouped.items():
        toks = [r["tok_s"] for r in runs]
        bws = [r["read_bw_gbps"] for r in runs]
        out[k] = {
            "tok_mean": float(np.mean(toks)),
            "tok_std":  float(np.std(toks)) if len(toks) > 1 else 0.0,
            "bw_mean":  float(np.mean(bws)),
            "bw_std":   float(np.std(bws)) if len(bws) > 1 else 0.0,
            "n":        len(runs),
        }
    return out


def plot_throughput(agg: dict, out: Path) -> None:
    """Same layout as the BW chart but with tok/s on Y axis."""
    fig, ax = plt.subplots(figsize=(12, 6.5))

    x = np.arange(len(VENDOR_ORDER))
    width = 0.27  # 3 bars per group

    for i, scenario in enumerate(SCENARIO_ORDER):
        offsets = x + (i - 1) * width  # -1, 0, +1
        means = []
        stds = []
        ns = []
        for vendor in VENDOR_ORDER:
            entry = agg.get((vendor, scenario))
            if entry is None:
                means.append(0.0); stds.append(0.0); ns.append(0)
            else:
                means.append(entry["tok_mean"])
                stds.append(entry["tok_std"])
                ns.append(entry["n"])

        bars = ax.bar(offsets, means, width,
                      color=SCENARIO_COLOR[scenario],
                      edgecolor="white",
                      label=scenario,
                      yerr=stds, ecolor="#444444", capsize=3)

        # Print mean value on top of each bar; if N>1 also show "±std"
        for xi, m, s, n in zip(offsets, means, stds, ns):
            label = f"{m:.0f}" if n == 1 else f"{m:.0f}\n±{s:.0f}"
            ax.text(xi, m + max(means) * 0.012, label,
                    ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(VENDOR_ORDER, rotation=15)
    ax.set_ylabel("Throughput (tokens/s)", fontsize=12)
    ax.set_title(
        "KV cache cross-vendor throughput (tokens/s)\n"
        "K4 16u 8B 120s  /  K4 16u 8B 1200s  /  K5 4u 70B 180s",
        fontsize=13)
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend(loc="upper right", fontsize=10, framealpha=0.9)
    ax.set_ylim(0, max(b["tok_mean"] for b in agg.values()) * 1.15)

    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  -> {out}  ({out.stat().st_size // 1024} KB)")


def plot_scatter_bw_vs_throughput(agg: dict, out: Path) -> None:
    """Scatter: read_bw vs tok_s, one dot per (vendor, scenario) — sanity check
    that the two metrics agree on the vendor ranking."""
    fig, ax = plt.subplots(figsize=(9, 7))
    vendor_marker = {
        "Biwin X570":   "o",
        "Seagate FC530": "s",
        "ZhiTai Ti600":  "^",
        "WD SN570":      "D",
    }
    for vendor in VENDOR_ORDER:
        xs, ys, labels = [], [], []
        for scenario in SCENARIO_ORDER:
            entry = agg.get((vendor, scenario))
            if entry is None:
                continue
            xs.append(entry["bw_mean"])
            ys.append(entry["tok_mean"])
            labels.append(scenario)
        ax.scatter(xs, ys,
                   s=120, marker=vendor_marker[vendor],
                   label=vendor, edgecolors="black", linewidths=0.8, alpha=0.85)
        for x, y, lbl in zip(xs, ys, labels):
            ax.annotate(lbl.replace("K4 ", "K4\n").replace("K5 ", "K5\n"),
                        (x, y), xytext=(6, 6), textcoords="offset points",
                        fontsize=8, alpha=0.7)

    ax.set_xlabel("Read bandwidth (GB/s)", fontsize=12)
    ax.set_ylabel("Throughput (tokens/s)", fontsize=12)
    ax.set_title(
        "BW vs throughput — is bandwidth a good predictor of token/s?\n"
        "(perfect agreement → all dots on a single line)",
        fontsize=13)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=10)

    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  -> {out}  ({out.stat().st_size // 1024} KB)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--history", required=True, type=Path,
                   help="Path to test_history_master.csv")
    p.add_argument("--out", required=True, type=Path,
                   help="Output directory for PNGs")
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Loading {args.history} ...")
    grouped = load_history(args.history)
    print(f"  -> {sum(len(v) for v in grouped.values())} runs across "
          f"{len(grouped)} (vendor, scenario) groups")
    agg = aggregate(grouped)

    print("\nAggregated averages:")
    print(f"  {'Vendor':<18} {'Scenario':<22} {'N':<3} {'tok/s':<12} {'GB/s':<10}")
    for vendor in VENDOR_ORDER:
        for scenario in SCENARIO_ORDER:
            e = agg.get((vendor, scenario))
            if e is None:
                continue
            print(f"  {vendor:<18} {scenario:<22} {e['n']:<3} "
                  f"{e['tok_mean']:<12.2f} {e['bw_mean']:<10.4f}")

    print("\nGenerating figures:")
    plot_throughput(agg, args.out / "01_kvcache_throughput_tokens_per_s.png")
    plot_scatter_bw_vs_throughput(
        agg, args.out / "01b_kvcache_bw_vs_tokens_scatter.png")

    return 0


if __name__ == "__main__":
    sys.exit(main())