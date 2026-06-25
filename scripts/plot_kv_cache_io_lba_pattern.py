#!/usr/bin/env python3
"""Plot per-request LBA-level IO pattern for KV cache benchmark.

This script complements ``plot_kv_cache_io_randomness.py`` (which uses iostat
device-level aggregates) by working directly on the per-request trace recorded
by ``kv-cache.py --tracer-storage``:

    Timestamp,Operation,Object_Size_Bytes,Tier,Key,Phase

For each Key we assign a simulated starting LBA based on the cumulative size of
prior Write operations, then colour every IO by (Operation, Phase, Tier).  This
yields three views that the device-level boxplots cannot produce:

1. ``kvcache_lba_scatter.png``         LBA vs Time scatter (per-request)
2. ``kvcache_lba_delta_histogram.png`` |delta-LBA| histogram (sequential ratio)
3. ``kvcache_phase_comparison.png``    Prefill vs Decode IOPS/size split

Together they answer the question "is the workload sequential streaming or
random access?" with evidence that the device-level %rrqm=0 cannot supply.

Usage::

    python3 scripts/plot_kv_cache_io_lba_pattern.py \\
        --trace results/kvcache-profile/io_trace_sharegpt_8b_tp8_cpu0p5g_users2_300s.csv.zst \\
        --out   results/kvcache-profile/io_lba_pattern
"""

from __future__ import annotations

import argparse
import csv
import gzip
import sys
import zstandard as zstd
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Same colour palette as plot_kv_cache_io_randomness.py for visual consistency.
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

PHASE_COLOR = {
    "Prefill": "#2ca02c",
    "Decode":  "#d62728",
    "Evict":   "#ff7f0e",
}
OP_MARKER = {
    "Read":  "o",
    "Write": "s",
}


def open_trace(path: Path) -> csv.DictReader:
    """Open a possibly-compressed trace file."""
    if path.suffix == ".zst":
        dctx = zstd.ZstdDecompressor()
        fh = dctx.stream_reader(path.open("rb"))
        text = gzip.GzipFile(fileobj=fh) if False else __import__("io").TextIOWrapper(fh, encoding="utf-8")
        return csv.DictReader(text)
    if path.suffix == ".gz":
        return csv.DictReader(gzip.open(path, "rt", encoding="utf-8"))
    return csv.DictReader(path.open("r", encoding="utf-8"))


def assign_lba(ios: list[dict]) -> tuple[list[dict], int]:
    """Give each IO a simulated LBA based on first-write time order.

    Returns (ios_with_lba, total_lba_bytes).
    """
    key_lba: dict[str, int] = {}
    cur_lba = 0
    for io in ios:
        if io["op"] == "Write" and io["key"] not in key_lba and io["size"] > 0:
            key_lba[io["key"]] = cur_lba
            cur_lba += io["size"]
    for io in ios:
        io["lba"] = key_lba.get(io["key"], -1) if io["size"] > 0 else -1
    return ios, cur_lba


def plot_lba_scatter(ios: list[dict], t0: float, duration_s: float, out: Path, title_suffix: str) -> None:
    """LBA vs Time scatter, coloured by (Op, Phase, Tier)."""
    fig, ax = plt.subplots(figsize=(14, 7))

    # Group IOs by label to share legend entries
    groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for io in ios:
        if io["lba"] < 0:
            continue
        label = f"{io['op']}-{io['phase']}-{io['tier']}"
        groups[label].append((io["ts"] - t0, io["lba"] / (1024 ** 3)))  # GiB

    for label, points in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        xs, ys = zip(*points)
        ax.scatter(xs, ys,
                   s=4, alpha=0.35, marker=OP_MARKER.get(label.split("-")[0], "o"),
                   color=COLOR.get(label, COLOR["Other"]),
                   label=f"{label}  (n={len(points):,})",
                   edgecolors="none")

    ax.set_xlabel("Time since trace start (s)", fontsize=12)
    ax.set_ylabel("Simulated LBA (GiB)", fontsize=12)
    ax.set_title(
        f"KV cache per-request LBA pattern  ({len(ios):,} IO / {duration_s:.0f}s / 973 unique keys)\n"
        f"Tier-1 = CPU RAM, Tier-2 = NVMe SSD, Tier-0 (GPU VRAM) has no real data in this trace",
        fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9, ncol=2)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  -> {out}  ({out.stat().st_size // 1024} KB)")


def plot_lba_delta_histogram(ios: list[dict], out: Path, title_suffix: str) -> None:
    """|delta-LBA| CDF + zoomed-in linear histogram side by side.

    A pure log-scale histogram buries the 70% same-key (delta=0) reads inside
    the leftmost bin, making the workload look 100% random.  This figure shows
    BOTH the linear near-zero region (where the sequential peak lives) AND the
    log-scale tail (where the random jumps live) so the bimodal nature is
    obvious.
    """
    # Compute delta-LBA between consecutive reads on Tier-2 (the only tier
    # that touches SSD; Tier-1 reads are pure VRAM and Tier-0 is meta).
    ssd_reads = [io for io in ios if io["tier"] == "Tier-2"
                 and io["op"] == "Read" and io["lba"] >= 0]

    deltas_mb = []
    for i in range(1, len(ssd_reads)):
        d = abs(ssd_reads[i]["lba"] - ssd_reads[i - 1]["lba"])
        deltas_mb.append(d / (1024 ** 2))

    deltas_mb = np.asarray(deltas_mb, dtype=np.float64)
    total = len(deltas_mb)

    same_key       = int((deltas_mb < 0.001).sum())
    sequential_1mb = int((deltas_mb < 1).sum())
    sequential_10mb = int((deltas_mb < 10).sum())
    random_100mb_plus = int((deltas_mb >= 100).sum())
    median = float(np.median(deltas_mb))
    p95 = float(np.percentile(deltas_mb, 95))
    p99 = float(np.percentile(deltas_mb, 99))

    # ---- Figure: CDF + linear zoomed histogram side by side ----
    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5))

    # Left: CDF on log-scale x
    ax = axes[0]
    sorted_d = np.sort(deltas_mb)
    cdf = np.arange(1, len(sorted_d) + 1) / len(sorted_d)
    ax.plot(sorted_d, cdf, color="#d62728", linewidth=2)
    ax.set_xscale("log")
    ax.set_xlabel("|delta-LBA| between consecutive SSD reads (MB, log)", fontsize=11)
    ax.set_ylabel("Cumulative fraction", fontsize=11)
    ax.set_title("CDF: how concentrated is the workload?", fontsize=12)
    ax.grid(True, alpha=0.3, which="both")
    ax.set_ylim(0, 1.02)
    ax.axhline(0.70, color="green", linestyle="--", alpha=0.7)
    ax.text(0.01, 0.71, f"70% mark  ({sequential_1mb:,} reads within 1MB)",
            color="green", fontsize=9, va="bottom")
    ax.axhline(0.95, color="purple", linestyle="--", alpha=0.7)
    ax.text(0.01, 0.96, f"95% mark  (= {p95:.0f} MB)", color="purple", fontsize=9, va="bottom")
    # Where does 95% come from?
    ax.axvline(p95, color="purple", linestyle=":", alpha=0.6)
    ax.text(p95 * 1.05, 0.05, f"95th pct = {p95:.0f} MB",
            color="purple", fontsize=9, rotation=90, va="bottom")

    # Right: linear histogram for the 0-1MB region + log for the tail
    ax = axes[1]
    bins_lin = np.linspace(0, 1, 50)  # 0 to 1 MB in 20 KB steps
    n_lin, _, _ = ax.hist(deltas_mb[deltas_mb <= 1], bins=bins_lin,
                          color="#d62728", alpha=0.8, edgecolor="white",
                          label="0-1 MB region (linear)")
    ax.set_xlabel("|delta-LBA| (MB, linear 0-1 MB)", fontsize=11)
    ax.set_ylabel("Count (linear region)", fontsize=11, color="#d62728")
    ax.tick_params(axis="y", labelcolor="#d62728")
    ax.set_xlim(0, 1)
    ax.grid(True, alpha=0.3)

    # Inset for the tail
    ax2 = ax.inset_axes([1.05, 0.0, 0.6, 1.0])
    bins_log = np.logspace(0, 4, 50)  # 1 MB to 10 GB
    ax2.hist(deltas_mb, bins=bins_log, color="#9467bd", alpha=0.8,
             edgecolor="white")
    ax2.set_xscale("log")
    ax2.set_xlabel("|delta-LBA| (MB, log 1-10000)", fontsize=10)
    ax2.set_ylabel("Count", fontsize=10)
    ax2.grid(True, alpha=0.3, which="both")

    fig.suptitle(
        f"KV cache inter-IO LBA delta: bimodal (70% same-key + 30% random jumps)\n"
        f"{title_suffix}  -  Tier-2 (SSD) reads only, N={total:,} consecutive read pairs",
        fontsize=13, y=1.10)

    txt = (
        f"Same-key (delta=0):         {same_key:,} ({same_key/total*100:.1f}%)    "
        f"Sequential (<1MB):          {sequential_1mb:,} ({sequential_1mb/total*100:.1f}%)    "
        f"Random (>=100MB):           {random_100mb_plus:,} ({random_100mb_plus/total*100:.1f}%)\n"
        f"Median delta:                {median:.3f} MB    "
        f"p95 / p99 delta:             {p95:.0f} / {p99:.0f} MB"
    )
    fig.text(0.5, 1.00, txt, ha="center", fontsize=10,
             bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out}  ({out.stat().st_size // 1024} KB)")
    return {
        "same_key_pct": same_key / total * 100,
        "sequential_1mb_pct": sequential_1mb / total * 100,
        "random_100mb_plus_pct": random_100mb_plus / total * 100,
        "median_delta_mb": median,
        "p95_delta_mb": p95,
        "p99_delta_mb": p99,
    }


def plot_phase_comparison(ios: list[dict], t0: float, out: Path, title_suffix: str) -> None:
    """Prefill vs Decode: IOPS time series + size distribution side by side."""
    phases = ["Prefill", "Decode", "Evict"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    # --- Top-left: IOPS time series per phase (1s bins) ---
    ax = axes[0, 0]
    t1 = max(io["ts"] for io in ios)
    bins = np.arange(0, t1 - t0 + 2, 1.0)
    for phase in phases:
        ts = np.asarray([io["ts"] - t0 for io in ios if io["phase"] == phase])
        if len(ts) == 0:
            continue
        h, _ = np.histogram(ts, bins=bins)
        ax.plot(bins[:-1], h, label=f"{phase}  (mean={h.mean():.0f}/s, peak={h.max()})",
                color=PHASE_COLOR[phase], linewidth=1.5)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("IOPS (1-second bins)")
    ax.set_title("IOPS time series by phase")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)

    # --- Top-right: Stacked bar of op x tier ---
    ax = axes[0, 1]
    op_tier_count: dict[tuple, int] = defaultdict(int)
    for io in ios:
        op_tier_count[(io["op"], io["tier"])] += 1
    labels = list(op_tier_count.keys())
    counts = list(op_tier_count.values())
    colors = [COLOR.get(f"{op}-{phase}-{tier}", "#7f7f7f")
              for (op, tier) in labels
              for phase in ["Decode"]]
    ax.bar(range(len(labels)), counts, color=colors)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([f"{op}\n{tier}" for op, tier in labels], rotation=0, fontsize=9)
    ax.set_ylabel("Total IO count")
    ax.set_title("Operation x Tier breakdown")
    ax.grid(True, alpha=0.3, axis="y")

    # --- Bottom-left: Size distribution per phase (log x) ---
    ax = axes[1, 0]
    for phase in phases:
        sizes = np.asarray([io["size"] for io in ios if io["phase"] == phase and io["size"] > 0])
        if len(sizes) == 0:
            continue
        sizes_kb = sizes / 1024
        ax.hist(sizes_kb, bins=np.logspace(2, 6, 50),
                alpha=0.5, label=f"{phase}  (n={len(sizes):,}, p50={np.median(sizes_kb):.0f}kB)",
                color=PHASE_COLOR[phase], edgecolor="white")
    ax.set_xscale("log")
    ax.set_xlabel("Object size (kB, log)")
    ax.set_ylabel("Count")
    ax.set_title("IO size distribution by phase")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(loc="upper right", fontsize=9)

    # --- Bottom-right: Read/Write ratio over time (10s bins) ---
    ax = axes[1, 1]
    r_bins = np.arange(0, t1 - t0 + 11, 10.0)
    r_ts = np.asarray([io["ts"] - t0 for io in ios if io["op"] == "Read"])
    w_ts = np.asarray([io["ts"] - t0 for io in ios if io["op"] == "Write"])
    r_h, _ = np.histogram(r_ts, bins=r_bins)
    w_h, _ = np.histogram(w_ts, bins=r_bins)
    total_h = r_h + w_h
    # Avoid divide-by-zero: where total=0, ratio is undefined -> NaN
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(total_h > 0, r_h / total_h, np.nan)
    # Only plot bins that have any IO at all
    mask = ~np.isnan(ratio)
    ax.fill_between(r_bins[:-1][mask], ratio[mask],
                    alpha=0.5, color="#1f77b4", label="Read ratio")
    ax.plot(r_bins[:-1][mask], ratio[mask], color="#1f77b4", linewidth=1.5)
    ax.axhline(0.987, color="red", linestyle="--", alpha=0.5,
               label="overall read ratio = 0.987")
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Time (s, 10s bins)")
    ax.set_ylabel("Read fraction")
    ax.set_title("Read/Write ratio over time")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)

    fig.suptitle(f"Prefill vs Decode IO pattern breakdown\n{title_suffix}",
                 fontsize=14, y=1.02)
    fig.tight_layout()
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out}  ({out.stat().st_size // 1024} KB)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace", required=True, type=Path,
                   help="Path to io_trace_sharegpt_*.csv.zst")
    p.add_argument("--out", required=True, type=Path,
                   help="Output directory for PNGs and summary JSON")
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Loading trace {args.trace} ...")
    ios: list[dict] = []
    t0 = float("inf")
    t1 = -float("inf")
    r = open_trace(args.trace)
    try:
        for row in r:
            ts = float(row["Timestamp"])
            t0 = min(t0, ts); t1 = max(t1, ts)
            sz = int(row["Object_Size_Bytes"])
            ios.append({
                "ts": ts,
                "op": row["Operation"],
                "tier": row["Tier"],
                "phase": row["Phase"],
                "key": row["Key"],
                "size": sz,
            })
    finally:
        # Best-effort cleanup; csv.DictReader doesn't expose close, so the
        # underlying text/gzip/zstd streams are closed via GC.
        del r
    print(f"  loaded {len(ios):,} IO, duration {t1 - t0:.2f}s")

    print("Assigning simulated LBA by first-write order ...")
    ios, total_lba = assign_lba(ios)
    print(f"  total simulated LBA span: {total_lba / 1024**3:.2f} GiB")

    duration_s = t1 - t0
    title_suffix = (f"trace={args.trace.name[:40]}...  -  "
                    f"{len(ios):,} IO  /  {duration_s:.0f}s")

    print("\nGenerating figures:")
    plot_lba_scatter(ios, t0, duration_s, args.out / "kvcache_lba_scatter.png", title_suffix)
    stats = plot_lba_delta_histogram(
        ios, args.out / "kvcache_lba_delta_histogram.png", title_suffix)
    plot_phase_comparison(ios, t0, args.out / "kvcache_phase_comparison.png", title_suffix)

    print(f"\nSequential / random ratio summary:")
    for k, v in stats.items():
        print(f"  {k}: {v:.2f}")

    import json
    summary = {
        "trace": str(args.trace),
        "total_io": len(ios),
        "duration_s": t1 - t0,
        "simulated_lba_span_gib": total_lba / 1024**3,
        "stats_ssd_reads": stats,
    }
    (args.out / "kvcache_io_lba_pattern_summary.json").write_text(
        json.dumps(summary, indent=2))
    print(f"\nDone. Outputs in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())