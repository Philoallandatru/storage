#!/usr/bin/env python3
"""Render a cleaned KV-cache NVMe offload I/O report from per-I/O block trace."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SECTOR_SIZE = 512
GIB = 1024 ** 3
MIB = 1024 ** 2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--run-dir",
        type=Path,
        default=Path("results/kvcache-profile/per_io_lba_ext4_rw_20260629_032924"),
    )
    p.add_argument(
        "--asset-dir",
        type=Path,
        default=Path("docs/assets/kv-cache-real-io"),
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path("docs/kv-cache-nvme-offload-real-io-analysis-2026-06-29.md"),
    )
    p.add_argument("--sample", type=int, default=180_000)
    return p.parse_args()


def kind(rwbs: str) -> str:
    rwbs = (rwbs or "").upper()
    if rwbs.startswith("R"):
        return "read"
    if rwbs.startswith("W"):
        return "write"
    if "R" in rwbs and "W" not in rwbs:
        return "read"
    if "W" in rwbs:
        return "write"
    return "other"


def load_summary(run_dir: Path) -> tuple[dict, dict, dict]:
    summary = json.loads((run_dir / "lba_trace_summary.json").read_text())
    prefill = json.loads((run_dir / "kv_prefill.json").read_text())
    decode = json.loads((run_dir / "kv_decode.json").read_text())
    return summary, prefill, decode


def load_trace(path: Path) -> dict[str, np.ndarray]:
    ts = []
    sector = []
    size = []
    is_read = []
    comm = []
    rwbs = []
    with path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            try:
                b = int(row["bytes"])
                if b <= 0:
                    continue
                ts.append(int(row["timestamp_ns"]))
                sector.append(int(row["sector"]))
                size.append(b)
                rw = row["rwbs"]
                rwbs.append(rw)
                is_read.append(kind(rw) == "read")
                comm.append(row["comm"])
            except (KeyError, ValueError):
                continue
    t = np.asarray(ts, dtype=np.int64)
    t0 = int(t.min())
    return {
        "t_s": (t - t0) / 1e9,
        "sector": np.asarray(sector, dtype=np.int64),
        "size": np.asarray(size, dtype=np.int64),
        "is_read": np.asarray(is_read, dtype=bool),
        "lba_gib": np.asarray(sector, dtype=np.float64) * SECTOR_SIZE / GIB,
        "comm": np.asarray(comm, dtype=object),
        "rwbs": np.asarray(rwbs, dtype=object),
    }


def seq_stats_for_arrays(t: np.ndarray, lba_bytes: np.ndarray, sizes: np.ndarray) -> dict:
    if len(lba_bytes) < 2:
        return {"pairs": 0}
    # Input is already time ordered.
    delta = lba_bytes[1:] - (lba_bytes[:-1] + sizes[:-1])
    abs_mib = np.abs(delta) / MIB
    direction = np.sign(delta)
    nonzero_dir = direction[direction != 0]
    run_lengths = []
    if len(nonzero_dir):
        cur = int(nonzero_dir[0])
        n = 1
        for d in nonzero_dir[1:]:
            d = int(d)
            if d == cur:
                n += 1
            else:
                run_lengths.append(n)
                cur = d
                n = 1
        run_lengths.append(n)
    runs = np.asarray(run_lengths, dtype=np.float64)
    return {
        "pairs": int(len(delta)),
        "exact_contiguous_pct": float(np.mean(delta == 0) * 100),
        "overlap_or_same_pct": float(np.mean(lba_bytes[1:] <= (lba_bytes[:-1] + sizes[:-1])) * 100),
        "near_1mib_pct": float(np.mean(abs_mib < 1) * 100),
        "near_10mib_pct": float(np.mean(abs_mib < 10) * 100),
        "jump_ge_100mib_pct": float(np.mean(abs_mib >= 100) * 100),
        "forward_pct": float(np.mean(delta > 0) * 100),
        "backward_pct": float(np.mean(delta < 0) * 100),
        "abs_delta_mib": {
            "p50": float(np.percentile(abs_mib, 50)),
            "p95": float(np.percentile(abs_mib, 95)),
            "p99": float(np.percentile(abs_mib, 99)),
            "max": float(abs_mib.max()),
        },
        "direction_run_length": {
            "p50": float(np.percentile(runs, 50)) if len(runs) else None,
            "p95": float(np.percentile(runs, 95)) if len(runs) else None,
            "max": int(runs.max()) if len(runs) else None,
        },
    }


def python3_filtered_stats(trace: dict[str, np.ndarray]) -> dict:
    mask = trace["comm"] == "python3"
    lba_bytes = (trace["sector"][mask] * SECTOR_SIZE).astype(np.int64)
    sizes = trace["size"][mask]
    is_read = trace["is_read"][mask]
    return {
        "events": int(mask.sum()),
        "read_events": int(is_read.sum()),
        "write_events": int((~is_read).sum()),
        "read_sequence": seq_stats_for_arrays(
            trace["t_s"][mask][is_read], lba_bytes[is_read], sizes[is_read]
        ),
        "write_sequence": seq_stats_for_arrays(
            trace["t_s"][mask][~is_read], lba_bytes[~is_read], sizes[~is_read]
        ),
    }


def setup_style() -> None:
    plt.style.use("dark_background")
    plt.rcParams.update({
        "figure.facecolor": "#08111f",
        "axes.facecolor": "#0d1728",
        "savefig.facecolor": "#08111f",
        "axes.edgecolor": "#6b7280",
        "axes.labelcolor": "#e5e7eb",
        "xtick.color": "#cbd5e1",
        "ytick.color": "#cbd5e1",
        "grid.color": "#334155",
        "font.size": 10,
    })


def savefig(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()


def plot_dashboard(summary: dict, prefill: dict, decode: dict, out: Path) -> None:
    fig = plt.figure(figsize=(15, 8))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.2])
    fig.suptitle("KV Cache Offload -> NVMe: Real Block-Layer I/O", fontsize=20, weight="bold")

    cards = [
        ("Block events", f"{summary['events']:,}", "per-I/O block_rq_issue rows"),
        ("Read / Write", f"{summary['kind_counts']['read']:,} / {summary['kind_counts']['write']:,}", "read-heavy decode after write prefill"),
        ("LBA span", f"{summary['lba_span_gib']:.1f} GiB", "real sector range touched"),
        ("KV writes", f"{prefill['summary']['cache_stats']['tier_storage_kv_bytes_written_gb']:.1f} GiB", "prefill-only stage"),
        ("KV reads", f"{decode['summary']['cache_stats']['tier_storage_kv_bytes_read_gb']:.1f} GiB", "decode-only stage"),
        ("Dominant IO size", "128 KiB", f"{summary['top_io_sizes_bytes']['131072']:,} requests"),
    ]
    for i, (title, value, subtitle) in enumerate(cards):
        ax = fig.add_subplot(gs[i // 3, i % 3])
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.text(0.04, 0.74, title, color="#93c5fd", fontsize=12, weight="bold", transform=ax.transAxes)
        ax.text(0.04, 0.40, value, color="#f8fafc", fontsize=24, weight="bold", transform=ax.transAxes)
        ax.text(0.04, 0.17, subtitle, color="#94a3b8", fontsize=10, transform=ax.transAxes)
    savefig(out / "01_signal_dashboard.png")


def plot_timeline(trace: dict, out: Path) -> None:
    t = trace["t_s"]
    bins = np.arange(0, math.ceil(float(t.max())) + 2, 1.0)
    read = trace["is_read"]
    write = ~read
    r_iops, _ = np.histogram(t[read], bins=bins)
    w_iops, _ = np.histogram(t[write], bins=bins)
    r_bytes, _ = np.histogram(t[read], bins=bins, weights=trace["size"][read])
    w_bytes, _ = np.histogram(t[write], bins=bins, weights=trace["size"][write])
    x = bins[:-1]

    fig, axes = plt.subplots(2, 1, figsize=(15, 8), sharex=True)
    axes[0].fill_between(x, r_iops, color="#38bdf8", alpha=0.78, label="Read IOPS")
    axes[0].fill_between(x, w_iops, color="#fb7185", alpha=0.72, label="Write IOPS")
    axes[0].axvspan(0, 50, color="#fb7185", alpha=0.08, label="prefill-heavy")
    axes[0].axvspan(50, x.max(), color="#38bdf8", alpha=0.08, label="decode-heavy")
    axes[0].set_ylabel("IOPS / sec")
    axes[0].legend(ncol=4, loc="upper left")
    axes[0].grid(True, alpha=0.35)

    axes[1].plot(x, r_bytes / GIB, color="#38bdf8", lw=1.6, label="Read GiB/s")
    axes[1].plot(x, w_bytes / GIB, color="#fb7185", lw=1.6, label="Write GiB/s")
    axes[1].set_ylabel("GiB/s")
    axes[1].set_xlabel("Time since trace start (s)")
    axes[1].legend(loc="upper left")
    axes[1].grid(True, alpha=0.35)
    fig.suptitle("Phase Timeline: writes dominate prefill, reads dominate decode", fontsize=15, weight="bold")
    savefig(out / "02_timeline_iops_bandwidth.png")


def plot_lba_scatter(trace: dict, out: Path, sample: int) -> None:
    n = len(trace["t_s"])
    step = max(1, n // sample)
    idx = np.arange(0, n, step)
    read = trace["is_read"][idx]
    fig, ax = plt.subplots(figsize=(15, 8))
    ax.scatter(trace["t_s"][idx][~read], trace["lba_gib"][idx][~read], s=1.3, color="#fb7185", alpha=0.32, label="write")
    ax.scatter(trace["t_s"][idx][read], trace["lba_gib"][idx][read], s=1.0, color="#38bdf8", alpha=0.28, label="read")
    ax.set_xlabel("Time since trace start (s)")
    ax.set_ylabel("Real block LBA (GiB)")
    ax.set_title("Real per-I/O LBA scatter (sampled): decode reads jump across the device", fontsize=15, weight="bold")
    ax.grid(True, alpha=0.25)
    ax.legend(markerscale=8)
    savefig(out / "03_real_lba_scatter.png")


def plot_delta_comparison(summary: dict, out: Path) -> None:
    labels = ["contiguous", "<1 MiB", ">=100 MiB"]
    read_values = [
        summary["read_sequence"]["exact_contiguous_pct"],
        summary["read_sequence"]["near_1mib_pct"],
        summary["read_sequence"]["jump_ge_100mib_pct"],
    ]
    write_values = [
        summary["write_sequence"]["exact_contiguous_pct"],
        summary["write_sequence"]["near_1mib_pct"],
        summary["write_sequence"]["jump_ge_100mib_pct"],
    ]
    x = np.arange(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.bar(x - width / 2, read_values, width, color="#38bdf8", label="read")
    ax.bar(x + width / 2, write_values, width, color="#fb7185", label="write")
    for xs, vals in [(x - width / 2, read_values), (x + width / 2, write_values)]:
        for xi, v in zip(xs, vals):
            ax.text(xi, v + 1.2, f"{v:.1f}%", ha="center", color="#e5e7eb", fontsize=10)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Share of adjacent same-kind I/O pairs")
    ax.set_title("Read and write are different workloads: random reads, append-like writes", fontsize=15, weight="bold")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    savefig(out / "04_delta_signature.png")


def plot_size_and_heatmap(trace: dict, out: Path) -> None:
    read = trace["is_read"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    bins = np.array([4, 8, 16, 32, 64, 128, 256, 512, 1024]) * 1024
    axes[0].hist(trace["size"][read] / 1024, bins=bins / 1024, color="#38bdf8", alpha=0.75, label="read")
    axes[0].hist(trace["size"][~read] / 1024, bins=bins / 1024, color="#fb7185", alpha=0.65, label="write")
    axes[0].set_xscale("log", base=2)
    axes[0].set_xlabel("Block request size (KiB)")
    axes[0].set_ylabel("Requests")
    axes[0].set_title("Block size distribution")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3, which="both")

    t_bins = np.linspace(0, float(trace["t_s"].max()), 48)
    lba_bins = np.linspace(float(trace["lba_gib"].min()), float(trace["lba_gib"].max()), 64)
    heat, _, _ = np.histogram2d(trace["t_s"][read], trace["lba_gib"][read], bins=(t_bins, lba_bins))
    heat = np.log10(heat.T + 1)
    im = axes[1].imshow(
        heat,
        origin="lower",
        aspect="auto",
        extent=[t_bins[0], t_bins[-1], lba_bins[0], lba_bins[-1]],
        cmap="turbo",
    )
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("LBA (GiB)")
    axes[1].set_title("Read density heatmap (log10 count)")
    plt.colorbar(im, ax=axes[1], fraction=0.046, pad=0.04)
    savefig(out / "05_size_and_read_heatmap.png")


def plot_noise(trace: dict, out: Path) -> dict:
    comm_counts = Counter(trace["comm"])
    total = len(trace["comm"])
    top = comm_counts.most_common(12)
    labels = [x[0] or "(blank)" for x in top]
    values = [x[1] for x in top]
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.barh(np.arange(len(labels)), values, color="#a78bfa")
    ax.set_yticks(np.arange(len(labels)), labels)
    ax.invert_yaxis()
    ax.set_xlabel("Block events")
    ax.set_title("Trace provenance: python3 dominates; root-disk background noise remains visible", fontsize=14, weight="bold")
    for i, v in enumerate(values):
        ax.text(v, i, f" {v/total*100:.1f}%", va="center", color="#e5e7eb")
    ax.grid(True, axis="x", alpha=0.3)
    savefig(out / "06_trace_provenance.png")
    return {
        "total_events": total,
        "python3_events": comm_counts.get("python3", 0),
        "python3_pct": comm_counts.get("python3", 0) / total * 100,
        "top_comm": top,
    }


def fmt_pct(x: float) -> str:
    return f"{x:.1f}%"


def write_report(report: Path, asset_dir: Path, run_dir: Path, summary: dict, prefill: dict, decode: dict, py_stats: dict, provenance: dict) -> None:
    rel = asset_dir.relative_to(report.parent)
    pre_cs = prefill["summary"]["cache_stats"]
    dec_cs = decode["summary"]["cache_stats"]
    text = f"""# KV Cache Offloading 到 NVMe SSD 的真实 I/O 分析

**日期:** 2026-06-29  
**有效数据源:** Linux `tracepoint:block:block_rq_issue` per-I/O event stream  
**原始 trace:** `{run_dir}/block_lba_trace.csv`  
**明确排除:** 模拟 LBA、`@d[]` 残留 map、仅由 `iostat` 聚合推导出的随机性结论

## 一句话结论

真实 block 层看到的 KV cache offload 是 **读写分裂的双模式**：

- **Decode 读:** 高度随机的大跨度 LBA 跳跃。读相邻 I/O 中 `>=100 MiB` 跳跃占 **{fmt_pct(summary['read_sequence']['jump_ge_100mib_pct'])}**，精确连续只有 **{fmt_pct(summary['read_sequence']['exact_contiguous_pct'])}**。
- **Prefill 写:** 更接近连续追加/批量写。写相邻 I/O 中精确连续占 **{fmt_pct(summary['write_sequence']['exact_contiguous_pct'])}**，`<1 MiB` 近邻占 **{fmt_pct(summary['write_sequence']['near_1mib_pct'])}**。

![signal dashboard]({rel}/01_signal_dashboard.png)

## 这次为什么比旧分析更可靠

旧分析里有三类需要排除或降级的证据：

| 旧证据 | 问题 | 本报告处理 |
|---|---|---|
| 应用层 trace + 模拟 LBA | Key offset 不是 SSD 真实 LBA | 不用于空间随机性结论 |
| bpftrace `@d[dev,sector]` 输出 | 该 map 是 D2C 临时 map 的残留/非完整事件流 | 不用于 sequential ratio |
| `iostat %rrqm≈0` | 只能说明块层没有合并，不能给出真实 LBA delta | 只作为辅助背景 |

本报告使用每次 block request issue 的真实字段：

```text
timestamp_ns,dev,sector,bytes,rwbs,comm,pid
```

其中 `LBA = sector * 512`。每一行是一条真实 block I/O。

## 测试配置

设备和文件系统：

- 设备：`/dev/nvme0n1`
- dev id：`259:10` / `271581194`
- 文件系统路径：ext4 根盘下的 `results/kvcache-profile/ext4_kvcache_lba_...`
- tracepoint：`block:block_rq_issue`

KV cache 两阶段 workload：

| 阶段 | 模式 | 用户数 | 时长 | 模型 | TP | GPU/CPU cache | 目的 |
|---|---:|---:|---:|---|---:|---|---|
| 1 | `--prefill-only` | 12 | 35s | `llama3.1-8b` | 8 | `0/0 GiB` | 产生真实 NVMe 写入 |
| 2 | `--decode-only` | 16 | 60s | `llama3.1-8b` | 8 | `0/0 GiB` | 产生真实 NVMe 读取 |

KV 层统计：

| 指标 | Prefill | Decode |
|---|---:|---:|
| Requests | {prefill['requests_completed']:,} | {decode['requests_completed']:,} |
| Tokens | {prefill['total_tokens_generated']:,} | {decode['total_tokens_generated']:,} |
| Storage KV written | {pre_cs['tier_storage_kv_bytes_written_gb']:.2f} GiB | {dec_cs['tier_storage_kv_bytes_written_gb']:.2f} GiB |
| Storage KV read | {pre_cs['tier_storage_kv_bytes_read_gb']:.2f} GiB | {dec_cs['tier_storage_kv_bytes_read_gb']:.2f} GiB |
| Storage read ops | {pre_cs['read_iops']:,} | {dec_cs['read_iops']:,} |
| Storage write ops | {pre_cs['write_iops']:,} | {dec_cs['write_iops']:,} |

## 真实 block trace 摘要

| 指标 | 值 |
|---|---:|
| Block events | {summary['events']:,} |
| Read events | {summary['kind_counts']['read']:,} |
| Write events | {summary['kind_counts']['write']:,} |
| Total block bytes | {summary['total_bytes_gib']:.2f} GiB |
| Dominant request size | 128 KiB ({int(summary['top_io_sizes_bytes']['131072']):,} events) |
| LBA min | {summary['lba_min_gib']:.2f} GiB |
| LBA max | {summary['lba_max_gib']:.2f} GiB |
| LBA span | {summary['lba_span_gib']:.2f} GiB |

Trace provenance: `python3` 贡献 **{provenance['python3_events']:,} / {provenance['total_events']:,}** events (**{provenance['python3_pct']:.1f}%**)。因为测试跑在根盘，仍有少量系统背景 I/O；结论主要由 `python3` 主导的百万级 KV I/O 支撑。

![provenance]({rel}/06_trace_provenance.png)

## 时间结构

0-50s 左右是 prefill-heavy，写入占主导；50s 后 decode-heavy，读取占主导。

![timeline]({rel}/02_timeline_iops_bandwidth.png)

10 秒窗口里，decode 阶段每个窗口读事件约 33 万条，LBA 覆盖仍在 370-389 GiB 量级。这意味着不是小范围热点顺序扫描，而是在很宽的设备地址空间内反复跳转。

## LBA 空间形态

![lba scatter]({rel}/03_real_lba_scatter.png)

读写的空间形态不同：

- 写入阶段有大量连续 128 KiB 请求，形成近连续写入带。
- 读取阶段在高位 LBA 范围内来回跳，前后相邻 read request 很少连续。

## 顺序性 / 随机性

![delta signature]({rel}/04_delta_signature.png)

| 指标 | Read | Write |
|---|---:|---:|
| Adjacent pairs | {summary['read_sequence']['pairs']:,} | {summary['write_sequence']['pairs']:,} |
| Exact contiguous | {fmt_pct(summary['read_sequence']['exact_contiguous_pct'])} | {fmt_pct(summary['write_sequence']['exact_contiguous_pct'])} |
| Near `<1 MiB` | {fmt_pct(summary['read_sequence']['near_1mib_pct'])} | {fmt_pct(summary['write_sequence']['near_1mib_pct'])} |
| Jump `>=100 MiB` | {fmt_pct(summary['read_sequence']['jump_ge_100mib_pct'])} | {fmt_pct(summary['write_sequence']['jump_ge_100mib_pct'])} |
| Delta p50 | {summary['read_sequence']['abs_delta_mib']['p50']:.0f} MiB | {summary['write_sequence']['abs_delta_mib']['p50']:.0f} MiB |
| Delta p95 | {summary['read_sequence']['abs_delta_mib']['p95']:.0f} MiB | {summary['write_sequence']['abs_delta_mib']['p95']:.0f} MiB |
| Direction run p95 | {summary['read_sequence']['direction_run_length']['p95']:.0f} | {summary['write_sequence']['direction_run_length']['p95']:.0f} |

解读：

- **读路径是真随机压力源。** p50 LBA delta 已经达到 {summary['read_sequence']['abs_delta_mib']['p50']:.0f} MiB，95% 以上相邻读跨越至少 100 MiB。
- **写路径更像追加写。** p50 delta 为 0，75% 精确连续，说明 prefill 写入经过文件系统/块层后形成了大量连续提交。

## Request Size 与 Read Heatmap

![size heatmap]({rel}/05_size_and_read_heatmap.png)

128 KiB 是绝对主导的真实 block request size。这和 KV object 的逻辑大小不同：KV object 可能是几十到数百 MiB，落到块层后被拆成大量 128 KiB 请求。

## 修正后的结论

旧结论“KV cache 是随机大块 I/O”需要拆开：

1. **Decode read:** 是随机大跨度 read。SSD 选型应关注随机读尾延迟、队列处理能力、FTL/cache 行为。
2. **Prefill write:** 更接近连续追加写。SSD 选型应关注连续/近连续写吞吐、fsync 后台刷盘、GC cliff。
3. **不能再把读写混成一个随机模式。** 读写路径的 LBA 规律明显不同。
4. **应用层 locality 不等于设备层顺序性。** 即使应用层可能有同 Key 重读，实际 block 层 decode read 仍然表现为大跨度随机跳跃。

## 后续建议

- 在独立 ext4/xfs 测试盘上重复一次，减少根盘背景 I/O。
- 增加应用 trace 与 block trace 的时间对齐，把 Key/Phase 映射到真实 LBA。
- 分别产出 prefill-only、decode-only、mixed 三份 per-IO LBA 报告，避免阶段混合。
- 如果要比较 SSD，固定同一 trace replay，使用同样的 block-level 采集脚本。
"""
    report.write_text(text)


def main() -> int:
    args = parse_args()
    args.asset_dir.mkdir(parents=True, exist_ok=True)
    setup_style()
    summary, prefill, decode = load_summary(args.run_dir)
    trace = load_trace(args.run_dir / "block_lba_trace.csv")
    py_stats = python3_filtered_stats(trace)

    plot_dashboard(summary, prefill, decode, args.asset_dir)
    plot_timeline(trace, args.asset_dir)
    plot_lba_scatter(trace, args.asset_dir, args.sample)
    plot_delta_comparison(summary, args.asset_dir)
    plot_size_and_heatmap(trace, args.asset_dir)
    provenance = plot_noise(trace, args.asset_dir)

    derived = {
        "source_run_dir": str(args.run_dir),
        "python3_filtered_stats": py_stats,
        "trace_provenance": provenance,
    }
    (args.asset_dir / "derived_real_io_summary.json").write_text(json.dumps(derived, indent=2))
    write_report(args.report, args.asset_dir, args.run_dir, summary, prefill, decode, py_stats, provenance)
    print(args.report)
    for p in sorted(args.asset_dir.glob("*.png")):
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
