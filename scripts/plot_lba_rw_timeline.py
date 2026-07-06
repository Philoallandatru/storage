#!/usr/bin/env python3
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
    fm.fontManager.addfont(FONT_PATH)
    plt.rcParams["font.family"] = fm.FontProperties(fname=FONT_PATH).get_name()
    plt.rcParams["axes.unicode_minus"] = False


def plot_case(label: str, trace: dict[str, np.ndarray], out: Path) -> None:
    setup_font()
    sec = per_second(trace)
    # Light theme colors
    bg = "#ffffff"
    panel = "#f8f9fa"
    grid = "#dee2e6"
    text_color = "#212529"
    read_color = "#0066cc"  # Deep blue for Read
    write_color = "#dc3545"  # Red for Write

    fig, axes = plt.subplots(4, 1, figsize=(16, 13), sharex=False, facecolor=bg)
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

    axes[0].plot(sec["time"], sec["r_iops"], color=read_color, linewidth=2, label="读 IOPS")
    axes[0].plot(sec["time"], sec["w_iops"], color=write_color, linewidth=2, label="写 IOPS")
    axes[0].set_ylabel("events/s")
    axes[0].set_title("每秒读写 IOPS")
    axes[0].legend(frameon=True, facecolor='white', edgecolor=grid)

    axes[1].plot(sec["time"], sec["r_gibs"], color=read_color, linewidth=2, label="读 GiB/s")
    axes[1].plot(sec["time"], sec["w_gibs"], color=write_color, linewidth=2, label="写 GiB/s")
    axes[1].set_ylabel("GiB/s")
    axes[1].set_title("每秒读写带宽")
    axes[1].legend(frameon=True, facecolor='white', edgecolor=grid)

    axes[2].fill_between(sec["time"], sec["read_pct"], color=read_color, alpha=0.3, label="读占比")
    axes[2].plot(sec["time"], sec["read_pct"], color=read_color, linewidth=2)
    axes[2].set_ylim(0, 100)
    axes[2].set_ylabel("读占比 %")
    axes[2].set_title("每秒读写混合比例")
    axes[2].legend(frameon=True, facecolor='white', edgecolor=grid)

    n = len(trace["t_s"])
    max_points = 180_000
    step = max(1, n // max_points)
    idx = np.arange(0, n, step)
    r = trace["rw"][idx] == "R"
    axes[3].scatter(trace["t_s"][idx][r], trace["lba_gib"][idx][r], s=1, color=read_color, alpha=0.5, label="读 LBA")
    axes[3].scatter(trace["t_s"][idx][~r], trace["lba_gib"][idx][~r], s=1, color=write_color, alpha=0.6, label="写 LBA")
    axes[3].set_xlabel("时间 (s)")
    axes[3].set_ylabel("Host LBA (GiB)")
    axes[3].set_title("时间顺序上的 LBA 分布")
    axes[3].legend(frameon=True, markerscale=6, facecolor='white', edgecolor=grid)

    r_events = int((trace["rw"] == "R").sum())
    w_events = int((trace["rw"] == "W").sum())
    duration = trace["t_s"][-1]
    fig.suptitle(
        f"{label} block LBA 时间顺序读写分布 | {duration:.1f}s, R={r_events:,}, W={w_events:,}",
        fontsize=20,
        color=text_color,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", action="append", required=True, help="label=path")
    parser.add_argument("--out-dir", type=Path, default=Path("docs/assets/lba-rw-timeline"))
    args = parser.parse_args()

    for item in args.trace:
        label, path = item.split("=", 1)
        trace = load_trace(Path(path))
        plot_case(label, trace, args.out_dir / f"{label.lower()}_rw_lba_timeline.png")


if __name__ == "__main__":
    main()
