#!/usr/bin/env python3
"""Compare ShareGPT and BurstGPT KV-cache block traces."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SECTOR_SIZE = 512
GIB = 1024 ** 3
MIB = 1024 ** 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sharegpt-run", type=Path, required=True)
    parser.add_argument("--burstgpt-run", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    return parser.parse_args()


def io_kind(rwbs: str) -> str:
    value = (rwbs or "").upper()
    if value.startswith("R") or ("R" in value and "W" not in value):
        return "read"
    if value.startswith("W") or "W" in value:
        return "write"
    return "other"


def load_trace(path: Path) -> dict[str, np.ndarray]:
    ts: list[int] = []
    sector: list[int] = []
    size: list[int] = []
    kind: list[str] = []
    rwbs: list[str] = []
    comm: list[str] = []
    pid: list[int] = []
    dev: list[int] = []

    with path.open(newline="") as fp:
        reader = csv.DictReader(
            row for row in fp
            if row.startswith("timestamp_ns,") or (row[:1].isdigit() and "," in row)
        )
        for row in reader:
            try:
                b = int(row["bytes"])
                if b <= 0:
                    continue
                ts.append(int(row["timestamp_ns"]))
                sector.append(int(row["sector"]))
                size.append(b)
                rw = row.get("rwbs", "")
                rwbs.append(rw)
                kind.append(io_kind(rw))
                comm.append(row.get("comm", ""))
                pid.append(int(row.get("pid") or 0))
                dev.append(int(row.get("dev") or 0))
            except (KeyError, ValueError):
                continue

    order = np.argsort(np.asarray(ts, dtype=np.int64))
    return {
        "timestamp_ns": np.asarray(ts, dtype=np.int64)[order],
        "dev": np.asarray(dev, dtype=np.int64)[order],
        "sector": np.asarray(sector, dtype=np.int64)[order],
        "bytes": np.asarray(size, dtype=np.int64)[order],
        "kind": np.asarray(kind, dtype=object)[order],
        "rwbs": np.asarray(rwbs, dtype=object)[order],
        "comm": np.asarray(comm, dtype=object)[order],
        "pid": np.asarray(pid, dtype=np.int64)[order],
    }


def write_processed_csv(trace: dict[str, np.ndarray], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["timestamp_ns", "dev", "sector", "bytes", "rwbs", "comm", "pid"])
        for row in zip(
            trace["timestamp_ns"],
            trace["dev"],
            trace["sector"],
            trace["bytes"],
            trace["rwbs"],
            trace["comm"],
            trace["pid"],
        ):
            writer.writerow(row)


def percentile(values: np.ndarray, pct: float) -> float | None:
    if len(values) == 0:
        return None
    return float(np.percentile(values, pct))


def seq_stats(trace: dict[str, np.ndarray], mask: np.ndarray) -> dict:
    if int(mask.sum()) < 2:
        return {"pairs": 0}
    starts = trace["sector"][mask].astype(np.int64) * SECTOR_SIZE
    sizes = trace["bytes"][mask].astype(np.int64)
    delta = starts[1:] - (starts[:-1] + sizes[:-1])
    abs_mib = np.abs(delta) / MIB
    direction = np.sign(delta)
    nonzero = direction[direction != 0]
    runs: list[int] = []
    if len(nonzero):
        current = int(nonzero[0])
        length = 1
        for item in nonzero[1:]:
            item = int(item)
            if item == current:
                length += 1
            else:
                runs.append(length)
                current = item
                length = 1
        runs.append(length)
    run_arr = np.asarray(runs, dtype=np.float64)
    return {
        "pairs": int(len(delta)),
        "exact_contiguous_pct": float(np.mean(delta == 0) * 100),
        "near_1mib_pct": float(np.mean(abs_mib < 1) * 100),
        "near_10mib_pct": float(np.mean(abs_mib < 10) * 100),
        "jump_ge_100mib_pct": float(np.mean(abs_mib >= 100) * 100),
        "forward_pct": float(np.mean(delta > 0) * 100),
        "backward_pct": float(np.mean(delta < 0) * 100),
        "abs_delta_mib": {
            "p50": percentile(abs_mib, 50),
            "p95": percentile(abs_mib, 95),
            "p99": percentile(abs_mib, 99),
            "max": float(abs_mib.max()) if len(abs_mib) else None,
        },
        "direction_run_length": {
            "p50": percentile(run_arr, 50),
            "p95": percentile(run_arr, 95),
            "max": int(run_arr.max()) if len(run_arr) else None,
        },
    }


def window_rows(trace: dict[str, np.ndarray], window_s: float = 1.0) -> list[dict]:
    ts = trace["timestamp_ns"]
    if len(ts) == 0:
        return []
    t0 = int(ts[0])
    rel_s = (ts - t0) / 1e9
    bins = np.arange(0, math.ceil(float(rel_s.max())) + window_s + 0.1, window_s)
    rows = []
    for i, lo in enumerate(bins[:-1]):
        hi = bins[i + 1]
        mask = (rel_s >= lo) & (rel_s < hi)
        if not mask.any():
            continue
        read = mask & (trace["kind"] == "read")
        write = mask & (trace["kind"] == "write")
        rows.append({
            "window_start_s": float(lo),
            "events": int(mask.sum()),
            "read_events": int(read.sum()),
            "write_events": int(write.sum()),
            "bytes": int(trace["bytes"][mask].sum()),
            "read_bytes": int(trace["bytes"][read].sum()),
            "write_bytes": int(trace["bytes"][write].sum()),
        })
    return rows


def burstiness(values: list[int]) -> dict:
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) == 0:
        return {"mean": 0, "p95": 0, "max": 0, "cv": 0, "peak_to_mean": 0}
    mean = float(arr.mean())
    return {
        "mean": mean,
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
        "cv": float(arr.std() / mean) if mean else 0,
        "peak_to_mean": float(arr.max() / mean) if mean else 0,
    }


def summarize(label: str, run_dir: Path, trace: dict[str, np.ndarray]) -> dict:
    ts = trace["timestamp_ns"]
    duration_s = float((int(ts[-1]) - int(ts[0])) / 1e9) if len(ts) > 1 else 0
    read = trace["kind"] == "read"
    write = trace["kind"] == "write"
    total_bytes = int(trace["bytes"].sum())
    lba_start = trace["sector"].astype(np.int64) * SECTOR_SIZE
    lba_end = lba_start + trace["bytes"].astype(np.int64)
    windows = window_rows(trace)
    size_counts = Counter(int(x) for x in trace["bytes"])
    comm_counts = Counter(str(x) for x in trace["comm"])
    kv = json.loads((run_dir / "kv_result.json").read_text())
    cache_stats = kv["summary"]["cache_stats"]
    return {
        "label": label,
        "run_dir": str(run_dir),
        "processed_csv": str(run_dir / "block_lba_trace.csv"),
        "events": int(len(ts)),
        "duration_s": duration_s,
        "total_bytes_gib": total_bytes / GIB,
        "read_events": int(read.sum()),
        "write_events": int(write.sum()),
        "read_bytes_gib": int(trace["bytes"][read].sum()) / GIB,
        "write_bytes_gib": int(trace["bytes"][write].sum()) / GIB,
        "read_event_ratio": float(read.sum() / max(1, read.sum() + write.sum())),
        "read_write_event_ratio": float(read.sum() / max(1, write.sum())),
        "iops": float(len(ts) / duration_s) if duration_s else 0,
        "read_iops": float(read.sum() / duration_s) if duration_s else 0,
        "write_iops": float(write.sum() / duration_s) if duration_s else 0,
        "bandwidth_gib_s": float(total_bytes / GIB / duration_s) if duration_s else 0,
        "read_bandwidth_gib_s": float(trace["bytes"][read].sum() / GIB / duration_s) if duration_s else 0,
        "write_bandwidth_gib_s": float(trace["bytes"][write].sum() / GIB / duration_s) if duration_s else 0,
        "lba_min_gib": float(lba_start.min() / GIB),
        "lba_max_gib": float(lba_end.max() / GIB),
        "lba_span_gib": float((lba_end.max() - lba_start.min()) / GIB),
        "top_io_sizes_bytes": dict(size_counts.most_common(10)),
        "dominant_size_bytes": int(size_counts.most_common(1)[0][0]),
        "dominant_size_pct": float(size_counts.most_common(1)[0][1] / len(ts) * 100),
        "top_comm": dict(comm_counts.most_common(10)),
        "read_sequence": seq_stats(trace, read),
        "write_sequence": seq_stats(trace, write),
        "windows": windows,
        "burstiness": {
            "iops_1s": burstiness([row["events"] for row in windows]),
            "bandwidth_1s_gib_s": burstiness([row["bytes"] / GIB for row in windows]),
        },
        "kv_summary": {
            "requests": kv["summary"]["total_requests"],
            "tokens": kv["summary"]["total_tokens"],
            "elapsed_time_s": kv["summary"]["elapsed_time"],
            "storage_read_gib": cache_stats["tier_storage_kv_bytes_read_gb"],
            "storage_write_gib": cache_stats["tier_storage_kv_bytes_written_gb"],
            "storage_read_iops": cache_stats["read_iops"],
            "storage_write_iops": cache_stats["write_iops"],
            "storage_read_bw_gib_s": cache_stats["tier_storage_read_bandwidth_gbps"],
            "storage_write_bw_gib_s": cache_stats["tier_storage_write_bandwidth_gbps"],
        },
    }


def setup_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "font.size": 10,
        "axes.grid": True,
        "grid.alpha": 0.25,
    })


def savefig(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()


def plot_timeline(asset_dir: Path, traces: dict[str, dict[str, np.ndarray]]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
    colors = {"ShareGPT": "#2563eb", "BurstGPT": "#dc2626"}
    for label, trace in traces.items():
        windows = window_rows(trace)
        x = [row["window_start_s"] for row in windows]
        iops = [row["events"] for row in windows]
        bw = [row["bytes"] / GIB for row in windows]
        axes[0].plot(x, iops, lw=1.4, label=label, color=colors[label])
        axes[1].plot(x, bw, lw=1.4, label=label, color=colors[label])
    axes[0].set_ylabel("IOPS, 1s windows")
    axes[1].set_ylabel("GiB/s, 1s windows")
    axes[1].set_xlabel("Trace time (s)")
    axes[0].legend()
    axes[1].legend()
    fig.suptitle("Block-layer I/O timeline")
    savefig(asset_dir / "01_timeline_iops_bandwidth.png")


def plot_lba(asset_dir: Path, traces: dict[str, dict[str, np.ndarray]]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
    for ax, (label, trace) in zip(axes, traces.items()):
        n = len(trace["timestamp_ns"])
        step = max(1, n // 180_000)
        idx = np.arange(0, n, step)
        t = (trace["timestamp_ns"][idx] - trace["timestamp_ns"][0]) / 1e9
        lba = trace["sector"][idx] * SECTOR_SIZE / GIB
        read = trace["kind"][idx] == "read"
        ax.scatter(t[~read], lba[~read], s=1.0, alpha=0.35, color="#dc2626", label="write")
        ax.scatter(t[read], lba[read], s=0.8, alpha=0.25, color="#2563eb", label="read")
        ax.set_ylabel(f"{label}\nLBA GiB")
        ax.legend(markerscale=6, loc="upper right")
    axes[-1].set_xlabel("Trace time (s)")
    fig.suptitle("Real LBA scatter, sampled")
    savefig(asset_dir / "02_lba_scatter.png")


def plot_delta(asset_dir: Path, summaries: dict[str, dict]) -> None:
    labels = ["R contiguous", "R >=100MiB", "W contiguous", "W >=100MiB"]
    x = np.arange(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(11, 6))
    for offset, label in [(-width / 2, "ShareGPT"), (width / 2, "BurstGPT")]:
        s = summaries[label]
        values = [
            s["read_sequence"]["exact_contiguous_pct"],
            s["read_sequence"]["jump_ge_100mib_pct"],
            s["write_sequence"]["exact_contiguous_pct"],
            s["write_sequence"]["jump_ge_100mib_pct"],
        ]
        ax.bar(x + offset, values, width, label=label)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Adjacent-pair share (%)")
    ax.set_title("LBA jump signature")
    ax.legend()
    savefig(asset_dir / "03_lba_delta_signature.png")


def plot_size_rw(asset_dir: Path, summaries: dict[str, dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    labels = list(summaries)
    reads = [summaries[x]["read_bytes_gib"] for x in labels]
    writes = [summaries[x]["write_bytes_gib"] for x in labels]
    axes[0].bar(labels, reads, label="read GiB", color="#2563eb")
    axes[0].bar(labels, writes, bottom=reads, label="write GiB", color="#dc2626")
    axes[0].set_ylabel("Block bytes (GiB)")
    axes[0].set_title("Read/write volume")
    axes[0].legend()
    iops_cv = [summaries[x]["burstiness"]["iops_1s"]["cv"] for x in labels]
    peak = [summaries[x]["burstiness"]["iops_1s"]["peak_to_mean"] for x in labels]
    x = np.arange(len(labels))
    axes[1].bar(x - 0.18, iops_cv, 0.36, label="IOPS CV")
    axes[1].bar(x + 0.18, peak, 0.36, label="Peak/mean IOPS")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)
    axes[1].set_title("Burstiness, 1s windows")
    axes[1].legend()
    savefig(asset_dir / "04_volume_and_burstiness.png")


def main() -> int:
    args = parse_args()
    setup_style()
    runs = {"ShareGPT": args.sharegpt_run, "BurstGPT": args.burstgpt_run}
    traces = {label: load_trace(run / "bpftrace.log") for label, run in runs.items()}

    for label, run in runs.items():
        write_processed_csv(traces[label], run / "block_lba_trace.csv")

    summaries = {label: summarize(label, runs[label], traces[label]) for label in runs}

    args.asset_dir.mkdir(parents=True, exist_ok=True)
    plot_timeline(args.asset_dir, traces)
    plot_lba(args.asset_dir, traces)
    plot_delta(args.asset_dir, summaries)
    plot_size_rw(args.asset_dir, summaries)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summaries, indent=2))
    print(json.dumps({
        label: {
            "events": s["events"],
            "duration_s": s["duration_s"],
            "read_gib": s["read_bytes_gib"],
            "write_gib": s["write_bytes_gib"],
            "iops": s["iops"],
            "bw_gib_s": s["bandwidth_gib_s"],
            "read_jump_ge_100mib_pct": s["read_sequence"]["jump_ge_100mib_pct"],
            "write_contiguous_pct": s["write_sequence"]["exact_contiguous_pct"],
        }
        for label, s in summaries.items()
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
