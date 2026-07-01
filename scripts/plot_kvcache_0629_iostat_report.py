#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np

from analyze_kvcache_rw_qd_compare import parse_iostat, summarize_case


FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def setup_style() -> None:
    fm.fontManager.addfont(FONT_PATH)
    font_name = fm.FontProperties(fname=FONT_PATH).get_name()
    plt.rcParams["font.family"] = font_name
    plt.rcParams["axes.unicode_minus"] = False
    plt.style.use("dark_background")


def load_result(case_dir: Path) -> dict:
    return json.loads((case_dir / "result.json").read_text())


def throughput_timeline(case_dir: Path) -> tuple[list[float], list[float]]:
    data = load_result(case_dir)
    timeline = data.get("throughput_timeline", [])
    return (
        [float(x["timestamp"]) for x in timeline],
        [float(x["throughput_tokens_per_sec"]) for x in timeline],
    )


def case_label(name: str) -> str:
    if "burst" in name.lower():
        return "BurstGPT"
    if "share" in name.lower():
        return "ShareGPT"
    return name


def read_duration(run_root: Path) -> str:
    for meta in run_root.glob("*/metadata.env"):
        for line in meta.read_text(errors="replace").splitlines():
            if line.startswith("duration="):
                return line.split("=", 1)[1].strip()
    return "300"


def draw(run_root: Path, out_dir: Path, device: str) -> None:
    setup_style()
    out_dir.mkdir(parents=True, exist_ok=True)
    case_dirs = sorted(p for p in run_root.iterdir() if (p / "result.json").exists())
    summaries = [summarize_case(p, device) for p in case_dirs]
    summaries.sort(key=lambda x: 0 if "burst" in x["case"].lower() else 1)
    labels = [case_label(s["case"]) for s in summaries]
    duration = read_duration(run_root)
    colors = ["#38bdf8", "#f97316"]
    pink = "#fb7185"
    green = "#34d399"
    bg = "#070b18"
    panel = "#101827"
    grid = "#334155"

    # One-page dashboard.
    fig = plt.figure(figsize=(18, 10), facecolor=bg)
    gs = fig.add_gridspec(2, 3, height_ratios=[1.05, 1], hspace=0.28, wspace=0.22)
    axes = [fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[0, 2]), fig.add_subplot(gs[1, :])]
    for ax in axes:
        ax.set_facecolor(panel)
        ax.grid(True, color=grid, alpha=0.3)

    x = np.arange(len(labels))
    kv_read = [s["kv_read_gib"] for s in summaries]
    kv_write = [s["kv_write_gib"] for s in summaries]
    axes[0].bar(x, kv_read, color=colors, label="KV 读")
    axes[0].bar(x, kv_write, bottom=kv_read, color=pink, label="KV 写")
    axes[0].set_xticks(x, labels)
    axes[0].set_ylabel("GiB")
    axes[0].set_title("Benchmark KV 层读写量")
    axes[0].legend(frameon=False)
    for idx, s in enumerate(summaries):
        axes[0].text(idx, kv_read[idx] + kv_write[idx] + 10, f"读 {s['kv_read_share']:.1%}", ha="center", color="#e5e7eb", fontsize=11)

    dev_read = [s["dev_read_mib"] / 1024 for s in summaries]
    dev_write = [s["dev_write_mib"] / 1024 for s in summaries]
    axes[1].bar(x, dev_read, color=green, label="设备读")
    axes[1].bar(x, dev_write, bottom=dev_read, color=pink, label="设备写")
    axes[1].set_xticks(x, labels)
    axes[1].set_ylabel("GiB, iostat")
    axes[1].set_title("块设备实际读写量")
    axes[1].legend(frameon=False)
    for idx, s in enumerate(summaries):
        axes[1].text(idx, dev_read[idx] + dev_write[idx] + 1, f"设备读 {s['dev_read_share']:.1%}", ha="center", color="#e5e7eb", fontsize=11)

    width = 0.35
    axes[2].bar(x - width / 2, [s["aqu_mean"] for s in summaries], width, color="#a78bfa", label="QD mean")
    axes[2].bar(x + width / 2, [s["aqu_p95"] for s in summaries], width, color="#facc15", label="QD p95")
    axes[2].set_xticks(x, labels)
    axes[2].set_ylabel("aqu-sz")
    axes[2].set_title("Queue Depth 对比")
    axes[2].legend(frameon=False)

    ax = axes[3]
    for idx, case_dir in enumerate(case_dirs):
        rows = parse_iostat(case_dir / "iostat.log", device)
        label = case_label(case_dir.name)
        ax.plot([r["t_s"] for r in rows], [r["aqu_sz"] for r in rows], color=colors[idx], linewidth=2.1, label=f"{label} QD")
    ax.set_xlabel("时间 (s)")
    ax.set_ylabel("aqu-sz")
    ax.set_title("Queue Depth 随时间变化")
    ax.legend(frameon=False, loc="upper left")

    fig.suptitle(f"KV Cache SSD Offload {duration}s 复现：读写口径与队列深度", fontsize=24, color="#f8fafc", y=0.98)
    fig.text(0.015, 0.02, f"配置：llama3.1-8b, users=16, duration={duration}s, GPU/CPU=0GiB, TP=8, generation=none, autoscaling, iostat -dx -m 1", color="#94a3b8")
    fig.savefig(out_dir / f"0629_{duration}s_iostat_dashboard.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    # Token/s and device bandwidth timeline.
    fig2, axes2 = plt.subplots(3, 1, figsize=(16, 11), sharex=False, facecolor=bg)
    for ax in axes2:
        ax.set_facecolor(panel)
        ax.grid(True, color=grid, alpha=0.3)
    for idx, case_dir in enumerate(case_dirs):
        label = case_label(case_dir.name)
        t, y = throughput_timeline(case_dir)
        axes2[0].plot(t, y, color=colors[idx], linewidth=2.2, label=label)
        rows = parse_iostat(case_dir / "iostat.log", device)
        axes2[1].plot([r["t_s"] for r in rows], [r["wMB_s"] for r in rows], color=colors[idx], linewidth=1.8, label=f"{label} 写 MB/s")
        axes2[1].plot([r["t_s"] for r in rows], [r["rMB_s"] for r in rows], color=colors[idx], linewidth=1.4, linestyle="--", alpha=0.8, label=f"{label} 读 MB/s")
        axes2[2].plot([r["t_s"] for r in rows], [r["pct_util"] for r in rows], color=colors[idx], linewidth=1.8, label=label)
    axes2[0].set_title("Token/s 随时间变化")
    axes2[0].set_ylabel("token/s")
    axes2[1].set_title("设备读写带宽随时间变化")
    axes2[1].set_ylabel("MB/s")
    axes2[2].set_title("设备利用率随时间变化")
    axes2[2].set_ylabel("%util")
    axes2[2].set_xlabel("时间 (s)")
    for ax in axes2:
        ax.legend(frameon=False, ncols=2)
    fig2.suptitle("KV Cache Offload 运行时曲线", fontsize=22, color="#f8fafc")
    fig2.savefig(out_dir / f"0629_{duration}s_runtime_timeline.png", dpi=180, bbox_inches="tight")
    plt.close(fig2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--device", default="nvme2n1")
    parser.add_argument("--out-dir", type=Path, default=Path("docs/assets/kvcache-0629-iostat-repro"))
    args = parser.parse_args()
    draw(args.run_root, args.out_dir, args.device)


if __name__ == "__main__":
    main()
