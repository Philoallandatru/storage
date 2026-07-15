#!/usr/bin/env python3
"""分时分析 LBA timeline 的细节，结合测试数据和 I/O 模式"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np


FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def kind(rwbs: str) -> str:
    value = (rwbs or "").upper()
    if "W" in value:
        return "W"
    if "R" in value:
        return "R"
    return "O"


def load_trace(path: Path) -> dict[str, np.ndarray]:
    """加载 trace 数据"""
    ts: list[int] = []
    sector: list[int] = []
    size: list[int] = []
    rw: list[str] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            k = kind(row.get("rwbs", ""))
            if k not in {"R", "W"}:
                continue
            ts.append(int(row["timestamp_ns"]))
            sector.append(int(row["sector"]))
            size.append(int(row["bytes"]))
            rw.append(k)

    order = np.argsort(np.asarray(ts, dtype=np.int64), kind="mergesort")
    return {
        "t_s": (np.asarray(ts, dtype=np.int64)[order] - np.asarray(ts, dtype=np.int64)[order][0]) / 1e9,
        "lba_gib": np.asarray(sector, dtype=np.float64)[order] * 512 / 1024**3,
        "bytes": np.asarray(size, dtype=np.float64)[order],
        "rw": np.asarray(rw, dtype=object)[order],
    }


def load_metadata(run_dir: Path) -> dict[str, Any]:
    """加载运行元数据"""
    meta = {}
    meta_file = run_dir / "run.meta"
    if meta_file.exists():
        with meta_file.open() as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    meta[key] = val

    result_file = run_dir / "kv_result.json"
    if result_file.exists():
        with result_file.open() as f:
            meta["results"] = json.load(f)

    return meta


def analyze_phases(trace: dict[str, np.ndarray], window: float = 10.0) -> list[dict[str, Any]]:
    """分析不同时间窗口的 I/O 模式"""
    t = trace["t_s"]
    duration = int(np.ceil(t[-1]))
    phases = []

    for start in range(0, duration, int(window)):
        end = min(start + window, duration)
        mask = (t >= start) & (t < end)

        if not mask.any():
            continue

        t_phase = t[mask]
        bytes_phase = trace["bytes"][mask]
        rw_phase = trace["rw"][mask]
        lba_phase = trace["lba_gib"][mask]

        r_mask = rw_phase == "R"
        w_mask = rw_phase == "W"

        r_count = r_mask.sum()
        w_count = w_mask.sum()
        r_bytes = bytes_phase[r_mask].sum() if r_count > 0 else 0
        w_bytes = bytes_phase[w_mask].sum() if w_count > 0 else 0

        # 计算 LBA 分散度（标准差）
        lba_std = lba_phase.std() if len(lba_phase) > 1 else 0

        # 计算平均 I/O 大小
        avg_r_size = (r_bytes / r_count) if r_count > 0 else 0
        avg_w_size = (w_bytes / w_count) if w_count > 0 else 0

        phases.append({
            "start": start,
            "end": end,
            "r_iops": r_count / window,
            "w_iops": w_count / window,
            "r_bandwidth": r_bytes / 1024**3 / window,  # GiB/s
            "w_bandwidth": w_bytes / 1024**3 / window,  # GiB/s
            "r_total_gib": r_bytes / 1024**3,
            "w_total_gib": w_bytes / 1024**3,
            "lba_std": lba_std,
            "avg_r_size_kib": avg_r_size / 1024,
            "avg_w_size_kib": avg_w_size / 1024,
            "rw_ratio": r_count / w_count if w_count > 0 else float('inf'),
        })

    return phases


def identify_phase_types(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """识别不同阶段的类型（预热、稳态、突发等）"""
    if not phases:
        return phases

    # 计算全局统计
    total_iops = [p["r_iops"] + p["w_iops"] for p in phases]
    mean_iops = np.mean(total_iops)
    std_iops = np.std(total_iops)

    for i, phase in enumerate(phases):
        total = phase["r_iops"] + phase["w_iops"]

        # 分类阶段类型
        if i < 3:  # 前 30 秒
            phase["type"] = "初始化/预热"
            phase["color"] = "#ffc107"
        elif total < mean_iops * 0.3:
            phase["type"] = "低活跃"
            phase["color"] = "#9e9e9e"
        elif total > mean_iops + std_iops:
            phase["type"] = "突发高负载"
            phase["color"] = "#f44336"
        elif phase["w_iops"] > phase["r_iops"]:
            phase["type"] = "写密集"
            phase["color"] = "#ff9800"
        elif phase["r_iops"] > phase["w_iops"] * 3:
            phase["type"] = "读密集"
            phase["color"] = "#2196f3"
        else:
            phase["type"] = "混合负载"
            phase["color"] = "#4caf50"

    return phases


def setup_font() -> None:
    """设置字体"""
    try:
        fm.fontManager.addfont(FONT_PATH)
        plt.rcParams["font.family"] = fm.FontProperties(fname=FONT_PATH).get_name()
    except:
        plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def plot_phase_analysis(
    label: str,
    trace: dict[str, np.ndarray],
    phases: list[dict[str, Any]],
    meta: dict[str, Any],
    out: Path,
) -> None:
    """绘制分阶段分析图"""
    setup_font()

    bg = "#ffffff"
    panel = "#f8f9fa"
    grid = "#dee2e6"
    text_color = "#212529"

    fig = plt.figure(figsize=(20, 16), facecolor=bg)
    gs = fig.add_gridspec(5, 2, hspace=0.3, wspace=0.25)

    # 1. IOPS 时间线 + 阶段标注
    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_facecolor(panel)

    time_bins = [p["start"] for p in phases] + [phases[-1]["end"]]
    r_iops_vals = [p["r_iops"] for p in phases]
    w_iops_vals = [p["w_iops"] for p in phases]

    ax1.step(time_bins[:-1], r_iops_vals, where='post', color='#2196f3', linewidth=2, label='读 IOPS', alpha=0.8)
    ax1.step(time_bins[:-1], w_iops_vals, where='post', color='#ff9800', linewidth=2, label='写 IOPS', alpha=0.8)

    # 标注不同阶段
    for phase in phases:
        ax1.axvspan(phase["start"], phase["end"], alpha=0.15, color=phase["color"])

    ax1.set_ylabel("IOPS (ops/s)", fontsize=11)
    ax1.set_title(f"{label} - IOPS 时间线与阶段分类", fontsize=13, fontweight='bold')
    ax1.legend(loc='upper right', fontsize=10)
    ax1.grid(True, color=grid, alpha=0.5)

    # 2. 带宽时间线
    ax2 = fig.add_subplot(gs[1, :])
    ax2.set_facecolor(panel)

    r_bw_vals = [p["r_bandwidth"] for p in phases]
    w_bw_vals = [p["w_bandwidth"] for p in phases]

    ax2.step(time_bins[:-1], r_bw_vals, where='post', color='#2196f3', linewidth=2, label='读带宽', alpha=0.8)
    ax2.step(time_bins[:-1], w_bw_vals, where='post', color='#ff9800', linewidth=2, label='写带宽', alpha=0.8)

    for phase in phases:
        ax2.axvspan(phase["start"], phase["end"], alpha=0.15, color=phase["color"])

    ax2.set_ylabel("带宽 (GiB/s)", fontsize=11)
    ax2.set_title("带宽时间线", fontsize=13, fontweight='bold')
    ax2.legend(loc='upper right', fontsize=10)
    ax2.grid(True, color=grid, alpha=0.5)

    # 3. LBA 分散度
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_facecolor(panel)

    lba_std_vals = [p["lba_std"] for p in phases]
    colors = [p["color"] for p in phases]

    bars = ax3.bar(range(len(phases)), lba_std_vals, color=colors, alpha=0.7, edgecolor='black', linewidth=0.5)
    ax3.set_xlabel("时间窗口 (10s)", fontsize=10)
    ax3.set_ylabel("LBA 标准差 (GiB)", fontsize=10)
    ax3.set_title("LBA 空间分散度", fontsize=12, fontweight='bold')
    ax3.grid(True, axis='y', color=grid, alpha=0.5)

    # 4. 平均 I/O 大小
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.set_facecolor(panel)

    avg_r_sizes = [p["avg_r_size_kib"] for p in phases]
    avg_w_sizes = [p["avg_w_size_kib"] for p in phases]

    x = np.arange(len(phases))
    width = 0.35
    ax4.bar(x - width/2, avg_r_sizes, width, label='读', color='#2196f3', alpha=0.7)
    ax4.bar(x + width/2, avg_w_sizes, width, label='写', color='#ff9800', alpha=0.7)

    ax4.set_xlabel("时间窗口 (10s)", fontsize=10)
    ax4.set_ylabel("平均 I/O 大小 (KiB)", fontsize=10)
    ax4.set_title("平均 I/O 操作大小", fontsize=12, fontweight='bold')
    ax4.legend(fontsize=9)
    ax4.grid(True, axis='y', color=grid, alpha=0.5)

    # 5. 读写比例
    ax5 = fig.add_subplot(gs[3, 0])
    ax5.set_facecolor(panel)

    rw_ratios = [min(p["rw_ratio"], 50) for p in phases]  # 限制最大值用于显示

    bars = ax5.bar(range(len(phases)), rw_ratios, color=colors, alpha=0.7, edgecolor='black', linewidth=0.5)
    ax5.axhline(y=1, color='red', linestyle='--', linewidth=1, alpha=0.5, label='读写平衡')

    ax5.set_xlabel("时间窗口 (10s)", fontsize=10)
    ax5.set_ylabel("读/写比例", fontsize=10)
    ax5.set_title("读写比例变化 (>1 表示读多)", fontsize=12, fontweight='bold')
    ax5.legend(fontsize=9)
    ax5.grid(True, axis='y', color=grid, alpha=0.5)

    # 6. 累计 I/O 量
    ax6 = fig.add_subplot(gs[3, 1])
    ax6.set_facecolor(panel)

    cumul_r = np.cumsum([p["r_total_gib"] for p in phases])
    cumul_w = np.cumsum([p["w_total_gib"] for p in phases])

    ax6.plot(time_bins[:-1], cumul_r, color='#2196f3', linewidth=2.5, label='累计读', marker='o', markersize=4)
    ax6.plot(time_bins[:-1], cumul_w, color='#ff9800', linewidth=2.5, label='累计写', marker='s', markersize=4)

    ax6.set_xlabel("时间 (s)", fontsize=10)
    ax6.set_ylabel("累计数据量 (GiB)", fontsize=10)
    ax6.set_title("累计 I/O 数据量", fontsize=12, fontweight='bold')
    ax6.legend(fontsize=10)
    ax6.grid(True, color=grid, alpha=0.5)

    # 7. 阶段类型统计表
    ax7 = fig.add_subplot(gs[4, :])
    ax7.axis('off')

    # 创建阶段摘要
    phase_summary = {}
    for phase in phases:
        ptype = phase["type"]
        if ptype not in phase_summary:
            phase_summary[ptype] = {"count": 0, "total_r": 0, "total_w": 0}
        phase_summary[ptype]["count"] += 1
        phase_summary[ptype]["total_r"] += phase["r_total_gib"]
        phase_summary[ptype]["total_w"] += phase["w_total_gib"]

    summary_text = f"阶段类型摘要:\n\n"
    for ptype, stats in phase_summary.items():
        summary_text += f"  • {ptype}: {stats['count']} 个窗口, "
        summary_text += f"读 {stats['total_r']:.2f} GiB, 写 {stats['total_w']:.2f} GiB\n"

    # 添加测试元数据
    if meta:
        summary_text += f"\n测试配置:\n"
        summary_text += f"  • Workload: {meta.get('workload', 'N/A')}\n"
        summary_text += f"  • Model: {meta.get('model', 'N/A')}\n"
        if 'results' in meta:
            r = meta['results']
            summary_text += f"  • 完成请求: {r.get('requests_completed', 'N/A')}\n"
            summary_text += f"  • 生成 tokens: {r.get('total_tokens_generated', 'N/A')}\n"
            summary_text += f"  • 总读: {r.get('total_tokens_generated', 0) * 0.128 / 1024:.2f} GiB (估算)\n"

    ax7.text(0.05, 0.95, summary_text, transform=ax7.transAxes,
            fontsize=10, verticalalignment='top', family='monospace',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=grid))

    # 图例：阶段类型颜色
    legend_items = list(set([(p["type"], p["color"]) for p in phases]))
    legend_text = "阶段类型颜色:\n" + "\n".join([f"  ■ {t}" for t, c in legend_items])

    ax7.text(0.65, 0.95, legend_text, transform=ax7.transAxes,
            fontsize=10, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=grid))

    # 总标题
    duration = trace["t_s"][-1]
    total_ops = len(trace["t_s"])
    fig.suptitle(
        f"{label} - 分阶段 I/O 行为分析\n"
        f"总时长: {duration:.1f}s | 总操作数: {total_ops:,} | 时间窗口: 10s",
        fontsize=16,
        fontweight='bold',
        color=text_color,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"✓ 生成分析图: {out}")


def print_phase_report(label: str, phases: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    """打印详细的阶段分析报告"""
    print(f"\n{'='*80}")
    print(f"{label} - 分阶段 I/O 行为分析报告")
    print(f"{'='*80}\n")

    if meta:
        print(f"测试配置:")
        print(f"  Workload: {meta.get('workload', 'N/A')}")
        print(f"  Model: {meta.get('model', 'N/A')}")
        print(f"  Device: {meta.get('device', 'N/A')}")
        if 'results' in meta:
            r = meta['results']
            print(f"  完成请求: {r.get('requests_completed', 'N/A')}")
            print(f"  生成 tokens: {r.get('total_tokens_generated', 'N/A')}")
        print()

    print(f"{'时间段':<12} {'类型':<12} {'读IOPS':<10} {'写IOPS':<10} {'读BW':<10} {'写BW':<10} {'读/写比':<8} {'平均读大小':<12} {'平均写大小':<12}")
    print(f"{'':<12} {'':<12} {'(ops/s)':<10} {'(ops/s)':<10} {'(GiB/s)':<10} {'(GiB/s)':<10} {'':<8} {'(KiB)':<12} {'(KiB)':<12}")
    print("-" * 140)

    for phase in phases:
        time_range = f"{phase['start']}-{phase['end']}s"
        print(f"{time_range:<12} {phase['type']:<12} "
              f"{phase['r_iops']:>9.1f} {phase['w_iops']:>9.1f} "
              f"{phase['r_bandwidth']:>9.2f} {phase['w_bandwidth']:>9.2f} "
              f"{phase['rw_ratio']:>7.1f} "
              f"{phase['avg_r_size_kib']:>11.1f} {phase['avg_w_size_kib']:>11.1f}")

    print(f"\n{'='*80}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="分时分析 LBA timeline 的细节")
    parser.add_argument("--run-dir", type=Path, required=True, help="测试结果目录")
    parser.add_argument("--window", type=float, default=10.0, help="时间窗口大小（秒）")
    parser.add_argument("--out", type=Path, help="输出图片路径（可选）")
    args = parser.parse_args()

    trace_file = args.run_dir / "block_lba_trace.csv"
    if not trace_file.exists():
        print(f"错误: 找不到 trace 文件: {trace_file}")
        return

    label = args.run_dir.name

    print(f"加载 trace 数据: {trace_file}")
    trace = load_trace(trace_file)
    print(f"  - 加载了 {len(trace['t_s'])} 条记录")
    print(f"  - 时长: {trace['t_s'][-1]:.1f} 秒")

    print(f"\n分析阶段（窗口: {args.window}s）...")
    phases = analyze_phases(trace, window=args.window)
    phases = identify_phase_types(phases)
    print(f"  - 识别了 {len(phases)} 个时间窗口")

    print(f"\n加载测试元数据...")
    meta = load_metadata(args.run_dir)

    # 打印报告
    print_phase_report(label, phases, meta)

    # 生成图表
    if args.out:
        out_path = args.out
    else:
        out_path = args.run_dir / "lba_timeline_phase_analysis.png"

    print(f"生成分析图表...")
    plot_phase_analysis(label, trace, phases, meta, out_path)


if __name__ == "__main__":
    main()
