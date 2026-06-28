#!/usr/bin/env python3
"""
plot_kv_comparison.py — Compare token-rate timelines from multiple KV cache benchmarks.

Usage:
  python3 scripts/plot_kv_comparison.py <result1.json> [result2.json ...] \\
      --output compare.png \\
      --labels "label1" "label2" "label3"

Each input JSON must be a kv-cache.py result file with throughput_timeline.
Labels are matched positionally to result files (1st label → 1st file).

Use '|' inside a label name to draw a newline at that point (legend looks cleaner).
Use --labels=<lbl1>|<lbl2>|...  or  --labels <lbl1> <lbl2> ...  (recommended).
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("Install matplotlib: uv pip install matplotlib")
    sys.exit(1)


# Color palette (one per run)
COLORS = ["#2196F3", "#FF9800", "#4CAF50", "#9C27B0", "#E91E63", "#00BCD4"]


def extract_timeline(data: dict):
    """Return (timestamps, throughputs, label) from one result file."""
    tl = data.get("throughput_timeline", [])
    if not tl:
        return None, None, None
    timestamps = [t["timestamp"] for t in tl]
    throughputs = [t["throughput_tokens_per_sec"] for t in tl]

    sm = data.get("summary", {})
    autoscaling = sm.get("autoscaling_summary", {})
    initial_users = autoscaling.get("initial_users", "?")
    model = data.get("model") or sm.get("model", "?")
    elapsed = sm.get("elapsed_time", timestamps[-1] if timestamps else 0)
    requests = sm.get("total_requests", "?")
    tokens = sm.get("total_tokens", "?")
    hit_rate = sm.get("cache_stats", {}).get("cache_hit_rate", 0) * 100

    label = f"users={initial_users} | {model} | {elapsed:.0f}s | req={requests} | hit={hit_rate:.0f}%"
    return timestamps, throughputs, label


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Parse args: positional = result files, --output=PNG, --labels=LABEL1|LABEL2|...
    # --labels consumes ALL subsequent non-flag args as labels
    args = sys.argv[1:]
    output_path = "kv_comparison.png"
    labels_override = None

    files = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--output="):
            output_path = a.split("=", 1)[1]
        elif a == "--output":
            i += 1
            output_path = args[i]
        elif a.startswith("--labels="):
            labels_override = a.split("=", 1)[1].split("|")
        elif a == "--labels":
            i += 1
            # Consume all subsequent non-flag args as labels
            labels_override = []
            while i < len(args) and not args[i].startswith("--"):
                labels_override.append(args[i])
                i += 1
            continue
        elif a.startswith("--"):
            print(f"Unknown flag: {a}")
            sys.exit(1)
        else:
            files.append(a)
        i += 1

    if not files:
        print("No result files given.")
        sys.exit(1)

    fig, ax = plt.subplots(1, 1, figsize=(14, 7))

    for i, fp in enumerate(files):
        with open(fp) as f:
            data = json.load(f)
        ts, tputs, auto_label = extract_timeline(data)
        if not ts:
            print(f"⚠️  {fp}: no throughput_timeline, skipping")
            continue
        label = labels_override[i] if labels_override and i < len(labels_override) else auto_label
        color = COLORS[i % len(COLORS)]
        ax.plot(ts, tputs, color=color, linewidth=1.5, alpha=0.9, label=label)

        # Print per-file stats
        sm = data.get("summary", {})
        avg = sm.get("avg_throughput_tokens_per_sec", 0)
        peak = max(tputs)
        print(f"  [{i+1}] {Path(fp).name}")
        print(f"      label: {label}")
        print(f"      avg: {avg:.0f} tok/s, peak: {peak:.0f} tok/s, points: {len(ts)}")

    ax.set_xlabel("Elapsed Time (s)", fontsize=12)
    ax.set_ylabel("Throughput (tokens/sec)", fontsize=12)
    ax.set_title("KV Cache Benchmark — Token/s Comparison", fontsize=13, fontweight="bold")
    ax.legend(loc="best", fontsize=10)
    ax.grid(True, alpha=0.25)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\nChart saved: {output_path}")


if __name__ == "__main__":
    main()