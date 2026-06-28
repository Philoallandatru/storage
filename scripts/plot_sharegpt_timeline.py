#!/usr/bin/env python3
"""
plot_sharegpt_timeline.py — plot token/s over time from kv-cache benchmark result JSON.

Usage:
  python3 scripts/plot_sharegpt_timeline.py <result.json> [--output chart.png]
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("Install matplotlib: pip install matplotlib")
    sys.exit(1)


def plot_timeline(data: dict, output_path: str = "sharegpt_token_rate_timeline.png"):
    timeline = data.get("throughput_timeline", [])

    # Fallback: reconstruct timeline from end_to_end_latencies + total_tokens
    # when --enable-autoscaling was off (monitor thread never ran).
    if not timeline:
        e2e = data.get("end_to_end_latencies", [])
        total_tokens = data.get("total_tokens_generated", 0)
        summary = data.get("summary", {})
        if e2e and total_tokens and summary:
            print("  Note: throughput_timeline empty (no --enable-autoscaling).")
            print("  Reconstructing from end_to_end_latencies + total_tokens...")
            # Treat each completed request as a timestamp-ordered throughput point
            # Approximate elapsed = cumulative sum of end_to_end_latency / 1000 (seconds)
            cumulative_s = 0.0
            reconstructed = []
            avg_tok_per_req = total_tokens / max(len(e2e), 1)
            for i, lat in enumerate(e2e):
                cumulative_s += lat
                reconstructed.append({
                    "timestamp": cumulative_s,
                    "throughput_tokens_per_sec": avg_tok_per_req / max(lat, 0.001)
                })
            timeline = reconstructed
            # Cap to a reasonable time
            timeline = [t for t in timeline if t["timestamp"] <= 600]
            if not timeline:
                print("  Reconstruction produced no data.")
                sys.exit(1)

    if not timeline:
        print("ERROR: throughput_timeline is empty and could not be reconstructed.")
        sys.exit(1)

    timestamps = [t["timestamp"] for t in timeline]
    throughputs = [t["throughput_tokens_per_sec"] for t in timeline]

    summary = data.get("summary", {})
    avg_tput = summary.get("avg_throughput_tokens_per_sec")
    storage_tput = summary.get("storage_throughput_tokens_per_sec")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})

    # --- Main timeline ---
    ax1.plot(timestamps, throughputs, color="#2196F3", linewidth=1.5, alpha=0.85, label="token/s")
    if avg_tput:
        ax1.axhline(y=avg_tput, color="#FF9800", linestyle="--", linewidth=1.2,
                    label=f"avg: {avg_tput:.1f} tok/s")
    if storage_tput:
        ax1.axhline(y=storage_tput, color="#4CAF50", linestyle=":", linewidth=1.2,
                    label=f"storage throughput: {storage_tput:.1f} tok/s")
    ax1.set_xlabel("Elapsed Time (s)", fontsize=11)
    ax1.set_ylabel("Throughput (tokens/sec)", fontsize=11)
    ax1.set_title("ShareGPT LLM Inference — Token Generation Rate Over Time\n"
                  f"{data.get('summary',{}).get('total_requests','?')} requests | "
                  f"{data.get('summary',{}).get('total_tokens','?')} tokens | "
                  f"users={data.get('summary',{}).get('concurrent_users',data.get('requests_completed','?'))}",
                  fontsize=13, fontweight="bold")
    ax1.legend(loc="upper right", fontsize=10)
    ax1.grid(True, alpha=0.25)
    ax1.set_xlim(0, max(timestamps))

    # --- Rolling average (window=10) to see trend ---
    window = max(1, len(throughputs) // 30)
    if window >= 2:
        kernel = np.ones(window) / window
        smoothed = np.convolve(throughputs, kernel, mode="valid")
        smooth_ts = timestamps[window - 1:]
        ax1.plot(smooth_ts, smoothed, color="#E91E63", linewidth=2.5, alpha=0.7,
                 label=f"smooth (w={window})")

    # --- Bottom: per-second delta (token rate change) ---
    if len(throughputs) > 5:
        deltas = [throughputs[i+1] - throughputs[i] for i in range(len(throughputs)-1)]
        delta_ts = timestamps[1:]
        colors = ["#4CAF50" if d >= 0 else "#F44336" for d in deltas]
        ax2.bar(delta_ts, deltas, width=timestamps[2]-timestamps[0] if len(timestamps)>2 else 1,
                color=colors, alpha=0.6, linewidth=0)
        ax2.axhline(y=0, color="#333", linewidth=0.8)
        ax2.set_xlabel("Elapsed Time (s)", fontsize=11)
        ax2.set_ylabel("Δ token/s", fontsize=11)
        ax2.set_title("Per-step Rate Change (green=up, red=down)", fontsize=11)
        ax2.set_xlim(0, max(timestamps))
        ax2.grid(True, alpha=0.2)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Chart saved: {output_path}")
    plt.close()

    # Print summary to stdout
    print()
    print("=" * 60)
    print("ShareGPT Timeline Summary")
    print("=" * 60)
    print(f"  Duration:        {max(timestamps):.1f}s")
    print(f"  Data points:     {len(timestamps)}")
    print(f"  Avg throughput:  {np.mean(throughputs):.1f} tok/s")
    print(f"  Min throughput:  {np.min(throughputs):.1f} tok/s")
    print(f"  Max throughput:  {np.max(throughputs):.1f} tok/s")
    print(f"  Std deviation:   {np.std(throughputs):.1f} tok/s")
    if avg_tput:
        print(f"  Summary avg:     {avg_tput:.1f} tok/s")
    if storage_tput:
        print(f"  Storage avg:     {storage_tput:.1f} tok/s (excl. generation)")
    print(f"  Total requests:  {data.get('summary',{}).get('total_requests','?')}")
    print(f"  Total tokens:    {data.get('summary',{}).get('total_tokens','?')}")
    cache_stats = data.get("summary", {}).get("cache_stats", {})
    if cache_stats:
        print(f"  Cache hit rate:  {cache_stats.get('cache_hit_rate',0)*100:.1f}%")
        print(f"  Storage entries: {cache_stats.get('storage_entries','?')}")
        print(f"  Read bytes:      {cache_stats.get('total_read_bytes',0)/1024**3:.1f} GiB")
        print(f"  Write bytes:     {cache_stats.get('total_write_bytes',0)/1024**3:.1f} GiB")
        print(f"  Read IOPS:       {cache_stats.get('read_iops','?')}")
        print(f"  Write IOPS:      {cache_stats.get('write_iops','?')}")
        print(f"  R/W ratio:       {cache_stats.get('read_write_ratio','?'):.1f}x")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/plot_sharegpt_timeline.py <result.json> [--output chart.png]")
        print()
        print("Also checks existing results for timeline data:")
        import glob
        for fp in sorted(glob.glob("/home/ficus/llm/storage/results/kvcache-profile/*.json")):
            with open(fp) as f:
                d = json.load(f)
            tl = d.get("throughput_timeline", [])
            name = Path(fp).name
            if len(tl) > 0:
                print(f"  ✅ {name}: {len(tl)} data points, {tl[-1]['timestamp']:.0f}s")
        return 0

    result_path = sys.argv[1]
    output_path = "sharegpt_token_rate_timeline.png"
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    with open(result_path) as f:
        data = json.load(f)
    plot_timeline(data, output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
