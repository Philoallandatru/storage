#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any


IOSTAT_FIELDS = [
    "device",
    "r_s",
    "rMB_s",
    "rrqm_s",
    "pct_rrqm",
    "r_await",
    "rareq_sz",
    "w_s",
    "wMB_s",
    "wrqm_s",
    "pct_wrqm",
    "w_await",
    "wareq_sz",
    "d_s",
    "dMB_s",
    "drqm_s",
    "pct_drqm",
    "d_await",
    "dareq_sz",
    "f_s",
    "f_await",
    "aqu_sz",
    "pct_util",
]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * pct / 100
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def parse_iostat(path: Path, device: str) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split()
        if not parts or parts[0] != device or len(parts) < len(IOSTAT_FIELDS):
            continue
        row: dict[str, float] = {}
        for key, value in zip(IOSTAT_FIELDS[1:], parts[1:]):
            row[key] = float(value)
        rows.append(row)
    if len(rows) > 1:
        # Drop iostat's first report, which is since boot, not the benchmark interval.
        rows = rows[1:]
    for idx, row in enumerate(rows):
        row["t_s"] = float(idx)
    return rows


def load_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def get_cache_stats(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("summary", {}).get("cache_stats", {})


def summarize_case(case_dir: Path, device: str) -> dict[str, Any]:
    result = load_result(case_dir / "result.json")
    stats = get_cache_stats(result)
    rows = parse_iostat(case_dir / "iostat.log", device)
    rmb = [r["rMB_s"] for r in rows]
    wmb = [r["wMB_s"] for r in rows]
    aqu = [r["aqu_sz"] for r in rows]
    util = [r["pct_util"] for r in rows]
    rs = [r["r_s"] for r in rows]
    ws = [r["w_s"] for r in rows]

    read_gib = float(stats.get("tier_storage_kv_bytes_read_gb", stats.get("total_read_gb", 0.0)) or 0.0)
    write_gib = float(stats.get("tier_storage_kv_bytes_written_gb", stats.get("total_write_gb", 0.0)) or 0.0)
    total_gib = read_gib + write_gib
    iostat_read_mib = sum(rmb)
    iostat_write_mib = sum(wmb)
    iostat_total_mib = iostat_read_mib + iostat_write_mib

    return {
        "case": case_dir.name,
        "exit_code": (case_dir / "exit_code").read_text().strip() if (case_dir / "exit_code").exists() else "",
        "requests": result.get("requests_completed", 0),
        "tokens": result.get("total_tokens_generated", 0),
        "avg_token_s": result.get("summary", {}).get(
            "avg_throughput_tokens_per_sec",
            result.get("summary", {}).get("avg_token_per_sec", result.get("summary", {}).get("avg_token_s", 0)),
        ),
        "cache_hit_rate": stats.get("cache_hit_rate", 0),
        "kv_read_gib": read_gib,
        "kv_write_gib": write_gib,
        "kv_read_share": read_gib / total_gib if total_gib else 0,
        "kv_write_share": write_gib / total_gib if total_gib else 0,
        "kv_rw_ratio": read_gib / write_gib if write_gib else 0,
        "decode_reads": stats.get("decode_reads", 0),
        "prefill_writes": stats.get("prefill_writes", 0),
        "kv_read_bw_gib_s": stats.get("tier_storage_read_bandwidth_gbps", 0),
        "kv_write_bw_gib_s": stats.get("tier_storage_write_bandwidth_gbps", 0),
        "iostat_samples": len(rows),
        "dev_read_mib": iostat_read_mib,
        "dev_write_mib": iostat_write_mib,
        "dev_read_share": iostat_read_mib / iostat_total_mib if iostat_total_mib else 0,
        "dev_write_share": iostat_write_mib / iostat_total_mib if iostat_total_mib else 0,
        "dev_avg_rMB_s": statistics.fmean(rmb) if rmb else 0,
        "dev_avg_wMB_s": statistics.fmean(wmb) if wmb else 0,
        "dev_avg_rs": statistics.fmean(rs) if rs else 0,
        "dev_avg_ws": statistics.fmean(ws) if ws else 0,
        "aqu_mean": statistics.fmean(aqu) if aqu else 0,
        "aqu_p50": percentile(aqu, 50),
        "aqu_p95": percentile(aqu, 95),
        "aqu_max": max(aqu) if aqu else 0,
        "util_mean": statistics.fmean(util) if util else 0,
        "util_p95": percentile(util, 95),
        "timeline": rows,
    }


def write_csv(path: Path, summaries: list[dict[str, Any]]) -> None:
    fields = [
        "case",
        "requests",
        "tokens",
        "cache_hit_rate",
        "kv_read_gib",
        "kv_write_gib",
        "kv_read_share",
        "kv_write_share",
        "kv_rw_ratio",
        "kv_read_bw_gib_s",
        "kv_write_bw_gib_s",
        "dev_read_mib",
        "dev_write_mib",
        "dev_read_share",
        "dev_write_share",
        "dev_avg_rMB_s",
        "dev_avg_wMB_s",
        "dev_avg_rs",
        "dev_avg_ws",
        "aqu_mean",
        "aqu_p50",
        "aqu_p95",
        "aqu_max",
        "util_mean",
        "util_p95",
    ]
    lines = [",".join(fields)]
    for row in summaries:
        lines.append(",".join(str(row.get(field, "")) for field in fields))
    path.write_text("\n".join(lines) + "\n")


def plot(run_root: Path, summaries: list[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt

    plt.style.use("dark_background")
    colors = {
        "synthetic_realistic_cpu4": "#2dd4bf",
        "sharegpt_realistic_cpu4": "#f59e0b",
        "burstgpt_realistic_cpu4": "#60a5fa",
    }

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    fig.patch.set_facecolor("#0b1020")
    for ax in axes:
        ax.set_facecolor("#111827")
        ax.grid(True, color="#334155", alpha=0.35)

    for summary in summaries:
        case = summary["case"]
        color = colors.get(case, None)
        t = [r["t_s"] for r in summary["timeline"]]
        axes[0].plot(t, [r["rMB_s"] for r in summary["timeline"]], label=f"{case} read", color=color, linewidth=1.8)
        axes[0].plot(t, [r["wMB_s"] for r in summary["timeline"]], label=f"{case} write", color=color, linestyle="--", alpha=0.75)
        axes[1].plot(t, [r["aqu_sz"] for r in summary["timeline"]], label=case, color=color, linewidth=1.8)
        axes[2].plot(t, [r["pct_util"] for r in summary["timeline"]], label=case, color=color, linewidth=1.8)

    axes[0].set_ylabel("MB/s")
    axes[0].set_title("Device Read/Write Bandwidth")
    axes[1].set_ylabel("aqu-sz")
    axes[1].set_title("Average Queue Size")
    axes[2].set_ylabel("%util")
    axes[2].set_xlabel("Time (s)")
    axes[2].set_title("Device Utilization")
    for ax in axes:
        ax.legend(loc="upper right", fontsize=8)
    fig.suptitle("KV Cache Offload I/O Pattern: Synthetic vs ShareGPT vs BurstGPT", fontsize=16, color="#e5e7eb")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = run_root / "io_qd_timeline.png"
    fig.savefig(out, dpi=180)

    fig2, axes2 = plt.subplots(1, 2, figsize=(14, 5))
    fig2.patch.set_facecolor("#0b1020")
    labels = [s["case"].replace("_realistic_cpu4", "") for s in summaries]
    read = [s["kv_read_gib"] for s in summaries]
    write = [s["kv_write_gib"] for s in summaries]
    aqu95 = [s["aqu_p95"] for s in summaries]
    x = range(len(labels))
    axes2[0].bar(x, read, label="KV read GiB", color="#38bdf8")
    axes2[0].bar(x, write, bottom=read, label="KV write GiB", color="#fb7185")
    axes2[0].set_xticks(list(x), labels, rotation=15)
    axes2[0].set_title("Benchmark KV Bytes")
    axes2[0].legend()
    axes2[1].bar(labels, aqu95, color=["#2dd4bf", "#f59e0b", "#60a5fa"])
    axes2[1].set_title("Device Queue Depth P95")
    axes2[1].set_ylabel("aqu-sz p95")
    axes2[1].tick_params(axis="x", rotation=15)
    for ax in axes2:
        ax.set_facecolor("#111827")
        ax.grid(True, axis="y", color="#334155", alpha=0.35)
    fig2.tight_layout()
    fig2.savefig(run_root / "rw_mix_and_qd_summary.png", dpi=180)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--device", default="nvme2n1")
    args = parser.parse_args()

    case_dirs = sorted(p for p in args.run_root.iterdir() if (p / "iostat.log").exists())
    summaries = [summarize_case(case_dir, args.device) for case_dir in case_dirs]
    serializable = [{k: v for k, v in s.items() if k != "timeline"} for s in summaries]
    (args.run_root / "summary.json").write_text(json.dumps(serializable, indent=2, ensure_ascii=False))
    write_csv(args.run_root / "summary.csv", summaries)
    plot(args.run_root, summaries)
    print(json.dumps(serializable, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
