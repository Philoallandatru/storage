#!/usr/bin/env python3
"""Plot Key time-locality pattern for KV cache benchmark.

This figure replaces the previous LBA-vs-time scatter
(kvcache_lba_scatter.png) because the simulated LBA was an artefact,
not real hardware data.  The new Y-axis is "Key index sorted by access
count" - a real metric (973 unique Keys, ranked hot-to-cold) that maps
directly to how LMCache manages cache space.

Key insight: by sorting keys hot-to-cold, hot keys compress into the top
strip (heavy reuse = sequential pattern) while cold keys spread across
the bottom strip (sparse access = random pattern).

Source data: results/kvcache-profile/io_trace_sharegpt_*.csv.zst
"""

from __future__ import annotations

import argparse
import csv
import sys
import zstandard as zstd
from collections import defaultdict
from io import TextIOWrapper
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

COLOR = {
    "Read-Decode-Tier-2":  "#d62728",   # SSD  decode (red)
    "Read-Decode-Tier-1":  "#1f77b4",   # CPU  decode (blue)
    "Read-Decode-Tier-0":  "#9467bd",   # meta  decode (purple)
    "Read-Evict-Tier-1":   "#ff7f0e",   # CPU  evict read (orange)
    "Write-Prefill-Tier-1": "#2ca02c",  # CPU  prefill write (green)
    "Write-Evict-Tier-2":  "#8c564b",   # SSD  evict write (brown)
    "Write-Prefill-Tier-2": "#e377c2",  # SSD  prefill (rare, pink)
    "Other":               "#7f7f7f",
}

OP_MARKER = {"Read": "o", "Write": "s"}


def open_trace(path: Path) -> csv.DictReader:
    if path.suffix == ".zst":
        dctx = zstd.ZstdDecompressor()
        fh = dctx.stream_reader(path.open("rb"))
        text = TextIOWrapper(fh, encoding="utf-8")
        return csv.DictReader(text)
    if path.suffix == ".gz":
        import gzip
        return csv.DictReader(gzip.open(path, "rt", encoding="utf-8"))
    return csv.DictReader(path.open("r", encoding="utf-8"))


def plot_key_locality_scatter(ios: list[dict], t0: float,
                               duration_s: float, out: Path) -> None:
    """Main figure: 127K IO plotted as (time, hot-to-cold key index).

    Replaces the LBA scatter.  Y axis now shows Key rank (hot at top,
    cold at bottom), so hot Key IO concentrate in a horizontal band at
    the top and cold Key IO scatter sparsely at the bottom.
    """
    # Build hot-to-cold key ordering (most-accessed first)
    key_count: dict[str, int] = defaultdict(int)
    for io in ios:
        key_count[io["key"]] += 1
    sorted_keys = sorted(key_count.keys(), key=lambda k: -key_count[k])
    key_rank = {k: i for i, k in enumerate(sorted_keys)}

    fig, ax = plt.subplots(figsize=(14, 8))

    groups: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for io in ios:
        if io["size"] == 0:
            continue  # skip 0-byte metadata
        label = f"{io['op']}-{io['phase']}-{io['tier']}"
        groups[label].append((io["ts"] - t0, key_rank[io["key"]]))

    for label, points in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        xs, ys = zip(*points)
        ax.scatter(xs, ys,
                   s=4, alpha=0.35, marker=OP_MARKER.get(label.split("-")[0], "o"),
                   color=COLOR.get(label, COLOR["Other"]),
                   label=f"{label}  (n={len(points):,})",
                   edgecolors="none")

    ax.set_xlabel("Time since trace start (s)", fontsize=12)
    # Use percentile-based Y ticks so labels are key-rank indices
    yticks = [0, len(sorted_keys) // 4, len(sorted_keys) // 2,
              3 * len(sorted_keys) // 4, len(sorted_keys) - 1]
    ytick_labels = [f"#{r}\n({key_count[sorted_keys[r]]} IO)" for r in yticks]
    ax.set_yticks(yticks)
    ax.set_yticklabels(ytick_labels, fontsize=9)
    # Invert Y axis so hot Key (rank 0, most-accessed) appears at TOP
    ax.invert_yaxis()
    ax.set_ylabel("Key index (ranked hot to cold, hot at top)", fontsize=12)
    ax.set_title(
        f"KV cache Key time-locality pattern  ({len(ios):,} IO / {duration_s:.0f}s / {len(sorted_keys)} unique keys)\n"
        f"Each dot = one IO.  Top band = hot Keys (high reuse).  "
        f"Bottom band = cold Keys (single-use).",
        fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="center right", fontsize=9, framealpha=0.9, ncol=1)
    # mark hot/cold zones with shading:
    #   hot zone = TOP 20% keys  (y near 0)
    #   cold zone = BOTTOM 20% keys  (y near len-1)
    ax.axhspan(0, len(sorted_keys) * 0.2, alpha=0.10, color="red",
               label="_nolegend_")
    ax.axhspan(len(sorted_keys) * 0.8, len(sorted_keys), alpha=0.10, color="blue",
               label="_nolegend_")
    ax.text(duration_s * 0.02, len(sorted_keys) * 0.10,
            "HOT 20% keys\n(many accesses, dense IO)",
            fontsize=10, color="darkred", fontweight="bold", va="center")
    ax.text(duration_s * 0.02, len(sorted_keys) * 0.90,
            "COLD 20% keys\n(few accesses, sparse IO)",
            fontsize=10, color="darkblue", fontweight="bold", va="center")

    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  -> {out}  ({out.stat().st_size // 1024} KB)")


def plot_io_intervals(ios: list[dict], out: Path) -> dict:
    """Same-Key re-read interval histogram.

    Three populations distinguished:
      - intra-token   (<10 ms):   GPU reading same KV block within one decode step
      - inter-token   (10 ms - 1 s): same request's later tokens reading other blocks
      - inter-request (>1 s): a new request's prefill triggering fresh reads
    """
    key_read_ts: dict[str, list[float]] = defaultdict(list)
    for io in ios:
        if io["op"] == "Read" and io["phase"] == "Decode":
            key_read_ts[io["key"]].append(io["ts"])

    intra_ms, inter_token_ms, inter_req_ms = [], [], []
    for ts_list in key_read_ts.values():
        ts_list.sort()
        for i in range(1, len(ts_list)):
            dt_ms = (ts_list[i] - ts_list[i - 1]) * 1000
            if dt_ms < 10:
                intra_ms.append(dt_ms)
            elif dt_ms < 1000:
                inter_token_ms.append(dt_ms)
            else:
                inter_req_ms.append(dt_ms)

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # ---- Left: CDF on log scale, three populations ----
    ax = axes[0]
    for data, label, color in [
        (intra_ms,      f"intra-token  (<10ms)        n={len(intra_ms):,}",     "#d62728"),
        (inter_token_ms, f"inter-token  (10ms-1s)     n={len(inter_token_ms):,}", "#ff7f0e"),
        (inter_req_ms,   f"inter-request (>1s)         n={len(inter_req_ms):,}",   "#9467bd"),
    ]:
        if not data:
            continue
        sorted_d = np.sort(np.asarray(data, dtype=np.float64))
        cdf = np.arange(1, len(sorted_d) + 1) / len(sorted_d)
        ax.plot(sorted_d, cdf, label=label, color=color, linewidth=2)

    ax.set_xscale("log")
    ax.set_xlabel("Same-Key re-read interval (ms, log scale)", fontsize=12)
    ax.set_ylabel("Cumulative fraction", fontsize=12)
    ax.set_title("When is the same KV cache block re-read?", fontsize=13)
    ax.grid(True, alpha=0.3, which="both")
    ax.axvline(10, color="grey", linestyle="--", alpha=0.5)
    ax.axvline(1000, color="grey", linestyle="--", alpha=0.5)
    ax.text(10, 0.05, "10ms\n(intra-token boundary)", fontsize=8, color="grey")
    ax.text(1000, 0.05, "1s\n(inter-request boundary)", fontsize=8, color="grey")
    ax.legend(loc="lower right", fontsize=9)
    ax.set_ylim(0, 1.02)

    # ---- Right: bar chart of population sizes ----
    ax = axes[1]
    counts = [len(intra_ms), len(inter_token_ms), len(inter_req_ms)]
    labels = ["intra-token\n(<10 ms)", "inter-token\n(10 ms - 1 s)",
              "inter-request\n(> 1 s)"]
    colors = ["#d62728", "#ff7f0e", "#9467bd"]
    total = sum(counts)
    bars = ax.bar(range(len(counts)), counts, color=colors, edgecolor="white")
    for i, (c, lbl) in enumerate(zip(counts, labels)):
        pct = c / total * 100
        ax.text(i, c + total * 0.01, f"{c:,}\n({pct:.1f}%)",
                ha="center", fontsize=11, fontweight="bold")
    ax.set_xticks(range(len(counts)))
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Number of same-Key read intervals", fontsize=12)
    ax.set_title(
        "Breakdown of re-read population by time scale",
        fontsize=13)
    ax.grid(True, alpha=0.3, axis="y")
    ax.set_ylim(0, max(counts) * 1.15)

    # Add median annotations
    for i, data in enumerate([intra_ms, inter_token_ms, inter_req_ms]):
        if data:
            med = float(np.median(data))
            ax.text(i, total * 0.02, f"median {med:.2f} ms",
                    ha="center", fontsize=9, color="white")

    fig.suptitle(
        "Key time-locality: when does the same KV block get re-read?\n"
        "intra-token = LLM decode loop reading same block over and over",
        fontsize=14, y=1.02)
    fig.tight_layout()
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out}  ({out.stat().st_size // 1024} KB)")
    return {
        "intra_token_pct":      len(intra_ms) / total * 100,
        "inter_token_pct":      len(inter_token_ms) / total * 100,
        "inter_request_pct":    len(inter_req_ms) / total * 100,
        "intra_token_median_ms": float(np.median(intra_ms)) if intra_ms else 0,
        "inter_token_median_ms": float(np.median(inter_token_ms)) if inter_token_ms else 0,
        "inter_request_median_ms": float(np.median(inter_req_ms)) if inter_req_ms else 0,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Loading trace {args.trace} ...")
    ios: list[dict] = []
    t0 = float("inf"); t1 = -float("inf")
    r = open_trace(args.trace)
    try:
        for row in r:
            ts = float(row["Timestamp"])
            t0 = min(t0, ts); t1 = max(t1, ts)
            ios.append({
                "ts": ts,
                "op": row["Operation"],
                "tier": row["Tier"],
                "phase": row["Phase"],
                "key": row["Key"],
                "size": int(row["Object_Size_Bytes"]),
            })
    finally:
        del r
    print(f"  loaded {len(ios):,} IO, duration {t1 - t0:.2f}s")

    duration_s = t1 - t0
    print("\nGenerating figures:")
    plot_key_locality_scatter(
        ios, t0, duration_s,
        args.out / "kvcache_key_locality_scatter.png")
    stats = plot_io_intervals(
        ios, args.out / "kvcache_key_re_read_intervals.png")

    import json
    (args.out / "kvcache_key_locality_summary.json").write_text(
        json.dumps(stats, indent=2))
    print(f"\nKey-locality summary:")
    for k, v in stats.items():
        print(f"  {k}: {v:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())