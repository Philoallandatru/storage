#!/usr/bin/env python3
"""分时段 zoom-in LBA 分布:burstgpt 和 sharegpt 各画 4 个时段,看顺序 vs 随机性"""
from __future__ import annotations
import csv
from pathlib import Path
import numpy as np
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
fm.fontManager.addfont(FONT_PATH)
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# Time windows to zoom into (seconds from start)
# These are picked to show "burst" vs "idle" vs "transition" vs "end-of-run"
WINDOWS = [
    (0, 5, "T0: 启动期 0-5s (冷启动)"),
    (15, 25, "T1: 第一波突发 15-25s (读密集)"),
    (60, 75, "T2: 中段稳态 60-75s (读写混合)"),
    (130, 140, "T3: 末尾静默 130-140s (IO 稀疏)"),
]

WORKLOADS = {
    "sharegpt": {
        "path": Path("/home/ficus/llm/storage/results/kvcache-profile/sharegpt_kvcache_20260629_140729/block_lba_trace.csv"),
        "label": "ShareGPT",
    },
    "burstgpt": {
        "path": Path("/home/ficus/llm/storage/results/kvcache-profile/burstgpt_kvcache_20260629_141010/block_lba_trace.csv"),
        "label": "BurstGPT",
    },
}


def load(path: Path) -> dict[str, np.ndarray]:
    """Load bpftrace CSV into numpy arrays, convert to seconds."""
    ts_list, sector_list, size_list, rw_list = [], [], [], []
    t0 = None
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_ns = int(row["timestamp_ns"])
            if t0 is None:
                t0 = ts_ns
            ts_list.append((ts_ns - t0) / 1e9)
            sector_list.append(int(row["sector"]))
            size_list.append(int(row["bytes"]))
            rwbs = (row.get("rwbs") or "").upper()
            rw_list.append("W" if "W" in rwbs else ("R" if "R" in rwbs else "O"))
    return {
        "t": np.array(ts_list),
        "sector": np.array(sector_list),
        "bytes": np.array(size_list),
        "rw": np.array(rw_list),
    }


def make_zoom_figure(workload_key: str, data: dict, out_path: Path):
    """4 windows × 2 subplots (lba scatter + lba offset distribution) for one workload."""
    fig = plt.figure(figsize=(20, 18), facecolor="#1f1f1f")
    gs = GridSpec(4, 2, figure=fig, hspace=0.45, wspace=0.25)

    label = WORKLOADS[workload_key]["label"]
    fig.suptitle(f"{label} — 分时段 LBA 分布(读蓝/写红,Zoom-in)", fontsize=18, color="white", y=0.995)

    for i, (t0, t1, title) in enumerate(WINDOWS):
        mask = (data["t"] >= t0) & (data["t"] < t1)
        if mask.sum() == 0:
            continue
        t = data["t"][mask]
        sector = data["sector"][mask]
        rw = data["rw"][mask]
        bytes_arr = data["bytes"][mask]

        # Convert sector (512B) to GiB offset
        lba_gib = sector * 512 / (1024 ** 3)

        # === Left: LBA scatter (the "经典"lba-rw-timeline view, but zoomed) ===
        ax_scatter = fig.add_subplot(gs[i, 0])
        r_mask = rw == "R"
        w_mask = rw == "W"

        # Sample down to avoid overplot
        n_total = mask.sum()
        if n_total > 5000:
            idx = np.random.choice(n_total, 5000, replace=False)
            t_s = t[idx]
            lba_s = lba_gib[idx]
            rw_s = rw[idx]
            r_mask = rw_s == "R"
            w_mask = rw_s == "W"
        else:
            t_s = t
            lba_s = lba_gib
            rw_s = rw

        ax_scatter.scatter(t_s[r_mask], lba_s[r_mask], s=4, c="#4FC3F7", alpha=0.6, label="读")
        ax_scatter.scatter(t_s[w_mask], lba_s[w_mask], s=4, c="#FF6E6E", alpha=0.7, label="写")
        ax_scatter.set_facecolor("#1f1f1f")
        ax_scatter.set_title(f"{title} | LBA 时间分布", color="white", fontsize=12)
        ax_scatter.set_xlabel("时间 (s)", color="white")
        ax_scatter.set_ylabel("LBA 偏移 (GiB)", color="white")
        ax_scatter.tick_params(colors="white")
        ax_scatter.grid(True, color="#444", alpha=0.3)
        ax_scatter.legend(loc="upper right", fontsize=9, facecolor="#2b2b2b", edgecolor="#555", labelcolor="white")
        # Annotate counts
        ax_scatter.text(0.02, 0.97, f"读: {rw[rw=='R'].shape[0]}\n写: {rw[rw=='W'].shape[0]}",
                        transform=ax_scatter.transAxes, color="white", fontsize=10,
                        verticalalignment="top",
                        bbox=dict(boxstyle="round,pad=0.3", facecolor="#2b2b2b", edgecolor="#666", alpha=0.8))

        # === Right: LBA offset histogram (read vs write distribution) ===
        ax_hist = fig.add_subplot(gs[i, 1])
        if rw[rw == "R"].shape[0] > 0:
            ax_hist.hist(lba_gib[rw == "R"], bins=80, color="#4FC3F7", alpha=0.6, label="读", edgecolor="#0288D1", linewidth=0.3)
        if rw[rw == "W"].shape[0] > 0:
            ax_hist.hist(lba_gib[rw == "W"], bins=80, color="#FF6E6E", alpha=0.7, label="写", edgecolor="#C62828", linewidth=0.3)
        ax_hist.set_facecolor("#1f1f1f")
        ax_hist.set_title(f"{title} | LBA 偏移分布直方图", color="white", fontsize=12)
        ax_hist.set_xlabel("LBA 偏移 (GiB)", color="white")
        ax_hist.set_ylabel("事件数", color="white")
        ax_hist.tick_params(colors="white")
        ax_hist.grid(True, color="#444", alpha=0.3)
        ax_hist.legend(loc="upper right", fontsize=9, facecolor="#2b2b2b", edgecolor="#555", labelcolor="white")

    plt.savefig(out_path, dpi=110, facecolor=fig.get_facecolor())
    plt.close()
    print(f"Saved: {out_path}")


def main():
    out_dir = Path("/home/ficus/llm/storage/docs/assets/lba-zoom-in")
    out_dir.mkdir(parents=True, exist_ok=True)

    for key, info in WORKLOADS.items():
        if not info["path"].exists():
            print(f"Skip {key}: {info['path']} not found")
            continue
        print(f"Loading {key} from {info['path']} ...")
        data = load(info["path"])
        print(f"  Total events: {len(data['t'])}, time span: {data['t'][-1]:.1f}s")
        out_path = out_dir / f"{key}_zoom_in_4windows.png"
        make_zoom_figure(key, data, out_path)


if __name__ == "__main__":
    main()
