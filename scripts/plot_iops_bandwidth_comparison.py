#!/usr/bin/env python3
"""比较两个 workload 的 IOPS 和带宽时间线"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

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


def per_second(trace: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """计算每秒统计数据"""
    t = trace["t_s"]
    bins = np.arange(0, int(np.ceil(t[-1])) + 2)
    rmask = trace["rw"] == "R"
    wmask = trace["rw"] == "W"
    r_iops, _ = np.histogram(t[rmask], bins=bins)
    w_iops, _ = np.histogram(t[wmask], bins=bins)
    r_bytes, _ = np.histogram(t[rmask], bins=bins, weights=trace["bytes"][rmask])
    w_bytes, _ = np.histogram(t[wmask], bins=bins, weights=trace["bytes"][wmask])
    total = r_iops + w_iops
    read_pct = np.divide(r_iops, total, out=np.zeros_like(r_iops, dtype=float), where=total > 0) * 100
    return {
        "time": bins[:-1],
        "r_iops": r_iops,
        "w_iops": w_iops,
        "r_gibs": r_bytes / 1024**3,
        "w_gibs": w_bytes / 1024**3,
        "read_pct": read_pct,
    }


def setup_font() -> None:
    """设置字体"""
    try:
        fm.fontManager.addfont(FONT_PATH)
        plt.rcParams["font.family"] = fm.FontProperties(fname=FONT_PATH).get_name()
    except:
        # 如果字体不存在，使用默认字体
        plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def plot_comparison(label1: str, trace1: dict[str, np.ndarray],
                   label2: str, trace2: dict[str, np.ndarray],
                   out: Path) -> None:
    """绘制两个 workload 的 IOPS 和带宽对比图"""
    setup_font()

    sec1 = per_second(trace1)
    sec2 = per_second(trace2)

    # 浅色主题配色
    bg = "#ffffff"
    panel = "#f8f9fa"
    grid = "#dee2e6"
    text_color = "#212529"

    # 为两个 workload 设置不同的颜色方案
    workload1_color = "#0066cc"   # 深蓝色
    workload2_color = "#28a745"   # 绿色
    read_color = "#dc3545"        # 红色
    write_color = "#fd7e14"       # 橙色

    fig, axes = plt.subplots(4, 1, figsize=(18, 16), sharex=True, facecolor=bg)

    for ax in axes:
        ax.set_facecolor(panel)
        ax.grid(True, color=grid, alpha=0.5)
        ax.tick_params(colors=text_color)
        ax.spines['bottom'].set_color(grid)
        ax.spines['top'].set_color(grid)
        ax.spines['left'].set_color(grid)
        ax.spines['right'].set_color(grid)
        ax.xaxis.label.set_color(text_color)
        ax.yaxis.label.set_color(text_color)
        ax.title.set_color(text_color)

    # 第一张图：总 IOPS 对比
    total1 = sec1["r_iops"] + sec1["w_iops"]
    total2 = sec2["r_iops"] + sec2["w_iops"]

    axes[0].plot(sec1["time"], total1, color=workload1_color, linewidth=2.5,
                label=f"{label1}", alpha=0.8)
    axes[0].plot(sec2["time"], total2, color=workload2_color, linewidth=2.5,
                label=f"{label2}", alpha=0.8, linestyle='--')
    axes[0].set_ylabel("总 IOPS (ops/s)", fontsize=12)
    axes[0].set_title("总 IOPS 对比", fontsize=14, fontweight='bold')
    axes[0].legend(frameon=True, facecolor='white', edgecolor=grid, fontsize=11, loc='best')

    # 添加统计信息
    t1_mean = total1.mean()
    t1_max = total1.max()
    t2_mean = total2.mean()
    t2_max = total2.max()

    stats_text = f"{label1}: 平均={t1_mean:.0f}, 峰值={t1_max:.0f}\n{label2}: 平均={t2_mean:.0f}, 峰值={t2_max:.0f}"
    axes[0].text(0.02, 0.98, stats_text, transform=axes[0].transAxes,
                fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor=grid))

    # 第二张图：读写 IOPS 分解
    axes[1].plot(sec1["time"], sec1["r_iops"], color=workload1_color, linewidth=2,
                label=f"{label1} 读", alpha=0.8)
    axes[1].plot(sec1["time"], sec1["w_iops"], color=workload1_color, linewidth=2,
                label=f"{label1} 写", alpha=0.8, linestyle=':')
    axes[1].plot(sec2["time"], sec2["r_iops"], color=workload2_color, linewidth=2,
                label=f"{label2} 读", alpha=0.8, linestyle='--')
    axes[1].plot(sec2["time"], sec2["w_iops"], color=workload2_color, linewidth=2,
                label=f"{label2} 写", alpha=0.8, linestyle='-.')
    axes[1].set_ylabel("IOPS (ops/s)", fontsize=12)
    axes[1].set_title("读写 IOPS 分解", fontsize=14, fontweight='bold')
    axes[1].legend(frameon=True, facecolor='white', edgecolor=grid, fontsize=10, loc='best', ncol=2)

    # 第三张图：总带宽对比
    total_bw1 = sec1["r_gibs"] + sec1["w_gibs"]
    total_bw2 = sec2["r_gibs"] + sec2["w_gibs"]

    axes[2].plot(sec1["time"], total_bw1, color=workload1_color, linewidth=2.5,
                label=f"{label1}", alpha=0.8)
    axes[2].plot(sec2["time"], total_bw2, color=workload2_color, linewidth=2.5,
                label=f"{label2}", alpha=0.8, linestyle='--')
    axes[2].set_ylabel("总带宽 (GiB/s)", fontsize=12)
    axes[2].set_title("总带宽对比", fontsize=14, fontweight='bold')
    axes[2].legend(frameon=True, facecolor='white', edgecolor=grid, fontsize=11, loc='best')

    # 添加统计信息
    bw1_mean = total_bw1.mean()
    bw1_max = total_bw1.max()
    bw2_mean = total_bw2.mean()
    bw2_max = total_bw2.max()

    stats_text = f"{label1}: 平均={bw1_mean:.2f}, 峰值={bw1_max:.2f} GiB/s\n{label2}: 平均={bw2_mean:.2f}, 峰值={bw2_max:.2f} GiB/s"
    axes[2].text(0.02, 0.98, stats_text, transform=axes[2].transAxes,
                fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor=grid))

    # 第四张图：读写带宽分解
    axes[3].plot(sec1["time"], sec1["r_gibs"], color=workload1_color, linewidth=2,
                label=f"{label1} 读", alpha=0.8)
    axes[3].plot(sec1["time"], sec1["w_gibs"], color=workload1_color, linewidth=2,
                label=f"{label1} 写", alpha=0.8, linestyle=':')
    axes[3].plot(sec2["time"], sec2["r_gibs"], color=workload2_color, linewidth=2,
                label=f"{label2} 读", alpha=0.8, linestyle='--')
    axes[3].plot(sec2["time"], sec2["w_gibs"], color=workload2_color, linewidth=2,
                label=f"{label2} 写", alpha=0.8, linestyle='-.')
    axes[3].set_xlabel("时间 (s)", fontsize=12)
    axes[3].set_ylabel("带宽 (GiB/s)", fontsize=12)
    axes[3].set_title("读写带宽分解", fontsize=14, fontweight='bold')
    axes[3].legend(frameon=True, facecolor='white', edgecolor=grid, fontsize=10, loc='best', ncol=2)

    # 计算整体统计信息
    r1_events = int((trace1["rw"] == "R").sum())
    w1_events = int((trace1["rw"] == "W").sum())
    r2_events = int((trace2["rw"] == "R").sum())
    w2_events = int((trace2["rw"] == "W").sum())
    duration1 = trace1["t_s"][-1]
    duration2 = trace2["t_s"][-1]

    r1_bytes = trace1["bytes"][trace1["rw"] == "R"].sum()
    w1_bytes = trace1["bytes"][trace1["rw"] == "W"].sum()
    r2_bytes = trace2["bytes"][trace2["rw"] == "R"].sum()
    w2_bytes = trace2["bytes"][trace2["rw"] == "W"].sum()

    fig.suptitle(
        f"IOPS 和带宽对比: {label1} vs {label2}\n"
        f"{label1}: {duration1:.1f}s, R={r1_events:,} ({r1_bytes/1024**3:.1f} GiB), W={w1_events:,} ({w1_bytes/1024**3:.1f} GiB) | "
        f"{label2}: {duration2:.1f}s, R={r2_events:,} ({r2_bytes/1024**3:.1f} GiB), W={w2_events:,} ({w2_bytes/1024**3:.1f} GiB)",
        fontsize=16,
        fontweight='bold',
        color=text_color,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print(f"✓ 生成对比图: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="比较两个 workload 的 IOPS 和带宽时间线")
    parser.add_argument("--trace1", required=True, help="第一个 trace 文件路径，格式：label=path")
    parser.add_argument("--trace2", required=True, help="第二个 trace 文件路径，格式：label=path")
    parser.add_argument("--out", type=Path, required=True, help="输出图片路径")
    args = parser.parse_args()

    label1, path1 = args.trace1.split("=", 1)
    label2, path2 = args.trace2.split("=", 1)

    print(f"加载 {label1} 数据: {path1}")
    trace1 = load_trace(Path(path1))
    print(f"  - 加载了 {len(trace1['t_s'])} 条记录")

    print(f"加载 {label2} 数据: {path2}")
    trace2 = load_trace(Path(path2))
    print(f"  - 加载了 {len(trace2['t_s'])} 条记录")

    print("生成对比图...")
    plot_comparison(label1, trace1, label2, trace2, args.out)


if __name__ == "__main__":
    main()
