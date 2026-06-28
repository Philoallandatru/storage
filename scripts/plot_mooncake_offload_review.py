#!/usr/bin/env python3
"""Render Mooncake SSD offload benchmark charts and IO evidence."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt
import numpy as np


CONFIG_ALIASES = [
    (("gpu_only", "01_gpu_only"), "GPU only"),
    (("hicache_l1_l2", "02_hicache_l1_l2"), "HiCache L1+L2"),
    (("mooncake_only", "03_mooncake_only"), "+Mooncake"),
    (("mooncake_ssd", "04_mooncake_ssd"), "+Mooncake+SSD"),
]

COLORS = {
    "GPU only": "#f97316",
    "HiCache L1+L2": "#06b6d4",
    "+Mooncake": "#8b5cf6",
    "+Mooncake+SSD": "#22c55e",
}


def first_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = root / name
        if path.exists():
            return path
    return None


def read_json_line(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("{"):
                return json.loads(line)
    raise ValueError(f"No JSON line found in {path}")


def parse_stdout_bench(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"{path} does not exist")
    summary: dict[str, float] = {}
    rounds: dict[str, dict[str, float]] = {}
    metric_map = {
        "Total requests": ("total_requests", int),
        "Average Prompt Length": ("average_prompt_len", float),
        "Average Output Length": ("average_output_len", float),
        "P90 Prompt Length": ("p90_prompt_len", float),
        "P99 Prompt Length": ("p99_prompt_len", float),
        "P90 Output Length": ("p90_output_len", float),
        "P99 Output Length": ("p99_output_len", float),
        "Average TTFT": ("average_ttft", float),
        "P90 TTFT": ("p90_ttft", float),
        "P99 TTFT": ("p99_ttft", float),
        "Median TTFT": ("median_ttft", float),
        "Max TTFT": ("max_ttft", float),
        "Average ITL": ("average_itl", float),
        "P90 ITL": ("p90_itl", float),
        "P99 ITL": ("p99_itl", float),
        "Median ITL": ("median_itl", float),
        "Max ITL": ("max_itl", float),
        "Average latency": ("average_latency", float),
        "P90 latency": ("p90_latency", float),
        "P99 latency": ("p99_latency", float),
        "Median latency": ("median_latency", float),
        "Max latency": ("max_latency", float),
        "Input token throughput": ("input_token_throughput", float),
        "Output token throughput": ("output_token_throughput", float),
        "Request Throughput": ("throughput", float),
        "Cache Hit Rate": ("cache_hit_rate", float),
    }
    round_rx = re.compile(
        r"Round\s+(\d+): Average TTFT = ([0-9.]+)s, Cache Hit Rate = ([0-9.]+) \((\d+) requests"
    )
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("Total requests:"):
                match = re.search(r"Total requests: (\d+) at ([0-9.]+)", stripped)
                if match:
                    summary["total_requests"] = int(match.group(1))
                    summary["request_rate"] = float(match.group(2))
                continue
            match = round_rx.search(stripped)
            if match:
                rounds[f"round_{match.group(1)}"] = {
                    "average_ttft": float(match.group(2)),
                    "cache_hit_rate": float(match.group(3)),
                    "request_count": int(match.group(4)),
                }
                continue
            for label, (key, caster) in metric_map.items():
                if stripped.startswith(f"{label}:"):
                    value = stripped.split(":", 1)[1].strip().split()[0]
                    summary[key] = caster(value)
                    break
    required = {"average_ttft", "p90_ttft", "p99_ttft", "input_token_throughput", "cache_hit_rate"}
    missing = required - set(summary)
    if missing:
        raise ValueError(f"Missing metrics in {path}: {sorted(missing)}")
    return {"timestamp": "", "tag": path.parent.name, "summary": summary, "round": rounds}


def count_pattern(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    rx = re.compile(pattern)
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if rx.search(line):
                count += 1
    return count


def max_offload_key_count(path: Path) -> int:
    if not path.exists():
        return 0
    rx = re.compile(r"offload key count:\s*(\d+)")
    max_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            match = rx.search(line)
            if match:
                max_count = max(max_count, int(match.group(1)))
    return max_count


def parse_iostat(path: Path) -> dict[str, float]:
    if not path.exists() or path.stat().st_size == 0:
        return {
            "avg_read_mb_s": 0.0,
            "avg_write_mb_s": 0.0,
            "max_read_mb_s": 0.0,
            "max_write_mb_s": 0.0,
            "max_util_pct": 0.0,
        }

    read_values: list[float] = []
    write_values: list[float] = []
    util_values: list[float] = []
    header: list[str] | None = None
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "Device":
                header = parts
                continue
            if header is None or not parts[0].startswith("nvme"):
                continue
            row = dict(zip(header, parts, strict=False))
            try:
                # iostat -m uses MB/s for rMB/s and wMB/s.
                read_values.append(float(row.get("rMB/s", "0")))
                write_values.append(float(row.get("wMB/s", "0")))
                util_values.append(float(row.get("%util", "0")))
            except ValueError:
                continue

    nonzero_reads = [v for v in read_values if v > 0]
    nonzero_writes = [v for v in write_values if v > 0]
    return {
        "avg_read_mb_s": mean(nonzero_reads) if nonzero_reads else 0.0,
        "avg_write_mb_s": mean(nonzero_writes) if nonzero_writes else 0.0,
        "max_read_mb_s": max(read_values) if read_values else 0.0,
        "max_write_mb_s": max(write_values) if write_values else 0.0,
        "max_util_pct": max(util_values) if util_values else 0.0,
    }


def parse_inventory(path: Path) -> dict[str, float]:
    if not path.exists():
        return {"offload_file_count": 0, "offload_du_gb": 0.0}
    text = path.read_text(encoding="utf-8", errors="replace")
    file_count = 0
    match = re.search(r"=== file count ===\n(\d+)", text)
    if match:
        file_count = int(match.group(1))
    du_gb = 0.0
    match = re.search(r"=== du ===\n([0-9.]+)([KMGTP]?)", text)
    if match:
        value = float(match.group(1))
        unit = match.group(2)
        factor = {"": 1 / (1024**3), "K": 1 / (1024**2), "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024**2}.get(unit, 0)
        du_gb = value * factor
    return {"offload_file_count": file_count, "offload_du_gb": du_gb}


def load_bench(root: Path) -> list[dict]:
    rows: list[dict] = []
    for aliases, label in CONFIG_ALIASES:
        config_dir = first_existing(root, aliases)
        if config_dir is None:
            continue
        log_path = config_dir / "bench.log"
        if log_path.exists() and log_path.stat().st_size > 0:
            payload = read_json_line(log_path)
        else:
            payload = parse_stdout_bench(config_dir / "bench_stdout.log")
        evidence = {
            **parse_iostat(config_dir / "iostat.log"),
            **parse_inventory(config_dir / "inventory.log"),
            "storage_root_set_count": count_pattern(config_dir / "server.log", r"Storage root directory is:"),
            "storage_root_missing_count": count_pattern(config_dir / "server.log", r"Storage root directory is not set"),
            "ssd_enabled_count": count_pattern(config_dir / "server.log", r"IsEnableOffloading result: true"),
            "offload_read_events": count_pattern(config_dir / "server.log", r"offload key count:\s*[1-9]"),
            "max_offload_key_count": max_offload_key_count(config_dir / "server.log"),
            "invalid_key_errors": count_pattern(config_dir / "server.log", r"INVALID_KEY"),
            "duplicate_key_errors": count_pattern(config_dir / "server.log", r"OBJECT_ALREADY_EXISTS"),
            "insufficient_space_errors": count_pattern(config_dir / "server.log", r"insufficient space"),
        }
        rows.append(
            {
                "dirname": config_dir.name,
                "label": label,
                "timestamp": payload.get("timestamp", ""),
                "summary": payload["summary"],
                "rounds": payload["round"],
                "evidence": evidence,
            }
        )
    if not rows:
        raise RuntimeError(f"No bench.log JSON files found under {root}")
    return rows


def write_derived(rows: list[dict], out_dir: Path) -> None:
    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "config",
                "avg_ttft_s",
                "p90_ttft_s",
                "p99_ttft_s",
                "input_token_throughput_tok_s",
                "cache_hit_rate_pct",
                "total_requests",
                "avg_prompt_len",
                "offload_file_count",
                "offload_du_gb",
                "offload_read_events",
                "max_offload_key_count",
                "max_write_mb_s",
                "max_read_mb_s",
                "invalid_key_errors",
                "insufficient_space_errors",
            ]
        )
        for row in rows:
            s = row["summary"]
            e = row["evidence"]
            writer.writerow(
                [
                    row["label"],
                    s["average_ttft"],
                    s["p90_ttft"],
                    s["p99_ttft"],
                    s["input_token_throughput"],
                    s["cache_hit_rate"] * 100,
                    s["total_requests"],
                    s["average_prompt_len"],
                    e["offload_file_count"],
                    e["offload_du_gb"],
                    e["offload_read_events"],
                    e["max_offload_key_count"],
                    e["max_write_mb_s"],
                    e["max_read_mb_s"],
                    e["invalid_key_errors"],
                    e["insufficient_space_errors"],
                ]
            )

    with (out_dir / "per_round.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["config", "round", "avg_ttft_s", "cache_hit_rate_pct", "request_count"])
        for row in rows:
            for key, values in sorted(row["rounds"].items(), key=lambda item: int(item[0].split("_")[1])):
                writer.writerow(
                    [
                        row["label"],
                        int(key.split("_")[1]),
                        values["average_ttft"],
                        values["cache_hit_rate"] * 100,
                        values["request_count"],
                    ]
                )

    (out_dir / "derived_mooncake_offload_review.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


def setup_theme() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "#0b1020",
            "axes.facecolor": "#111827",
            "axes.edgecolor": "#334155",
            "axes.labelcolor": "#e5e7eb",
            "xtick.color": "#cbd5e1",
            "ytick.color": "#cbd5e1",
            "text.color": "#f8fafc",
            "grid.color": "#334155",
            "font.size": 11,
            "axes.titleweight": "bold",
            "axes.titlepad": 14,
            "legend.frameon": False,
            "savefig.facecolor": "#0b1020",
            "savefig.bbox": "tight",
        }
    )


def annotate_bars(ax: plt.Axes, bars, fmt: str, dy: float) -> None:
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, height + dy, fmt.format(height), ha="center", va="bottom", fontsize=9)


def plot_overall(rows: list[dict], out_path: Path, bench_root: Path) -> None:
    labels = [row["label"] for row in rows]
    x = np.arange(len(labels))
    ttft = np.array([row["summary"]["average_ttft"] for row in rows])
    p90 = np.array([row["summary"]["p90_ttft"] for row in rows])
    throughput = np.array([row["summary"]["input_token_throughput"] for row in rows])
    hit = np.array([row["summary"]["cache_hit_rate"] * 100 for row in rows])

    setup_theme()
    fig = plt.figure(figsize=(14.5, 8.5), dpi=180)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 0.82], width_ratios=[1, 1], hspace=0.38, wspace=0.18)
    ax_ttft = fig.add_subplot(gs[0, 0])
    ax_tput = fig.add_subplot(gs[0, 1])
    ax_meta = fig.add_subplot(gs[1, :])

    bar_colors = [COLORS[label] for label in labels]
    bars = ax_ttft.bar(x, ttft, color=bar_colors, width=0.66, edgecolor="#e5e7eb", linewidth=0.7)
    ax_ttft.errorbar(x, ttft, yerr=np.maximum(p90 - ttft, 0), fmt="none", ecolor="#94a3b8", elinewidth=1.4, capsize=4)
    if "+Mooncake+SSD" in labels:
        bars[labels.index("+Mooncake+SSD")].set_hatch("///")
    ax_ttft.set_title("Average TTFT, with P90 tail")
    ax_ttft.set_ylabel("seconds")
    ax_ttft.set_xticks(x, labels, rotation=0)
    ax_ttft.grid(axis="y", linestyle="--", alpha=0.5)
    ax_ttft.set_ylim(0, max(p90) * 1.12)
    annotate_bars(ax_ttft, bars, "{:.2f}s", max(p90) * 0.012)

    bars2 = ax_tput.bar(x, throughput, color=bar_colors, width=0.66, edgecolor="#e5e7eb", linewidth=0.7)
    if "+Mooncake+SSD" in labels:
        bars2[labels.index("+Mooncake+SSD")].set_hatch("///")
    ax_tput.set_title("Input token throughput")
    ax_tput.set_ylabel("tokens/s")
    ax_tput.set_xticks(x, labels, rotation=0)
    ax_tput.grid(axis="y", linestyle="--", alpha=0.5)
    ax_tput.set_ylim(0, max(throughput) * 1.18)
    annotate_bars(ax_tput, bars2, "{:.0f}", max(throughput) * 0.025)

    ax_meta.axis("off")
    config_text = " | ".join(f"{label}: hit {value:.1f}%" for label, value in zip(labels, hit, strict=True))
    ssd_rows = [row for row in rows if row["label"] == "+Mooncake+SSD"]
    if ssd_rows:
        e = ssd_rows[0]["evidence"]
        evidence_text = (
            f"SSD evidence: {e['offload_file_count']} files, {e['offload_du_gb']:.1f} GiB, "
            f"{e['offload_read_events']} offload-read log events, "
            f"max offload keys/read {e['max_offload_key_count']}, max write {e['max_write_mb_s']:.0f} MB/s."
        )
    else:
        evidence_text = "SSD evidence: SSD config not present."
    ax_meta.text(
        0.02,
        0.76,
        f"Raw-log benchmark root: {bench_root}\n{evidence_text}\n{config_text}",
        fontsize=12,
        linespacing=1.45,
        va="top",
        ha="left",
    )
    fig.suptitle("Mooncake SSD Offload Benchmark - Overall Performance", fontsize=19, fontweight="bold", y=0.98)
    fig.savefig(out_path)
    plt.close(fig)


def plot_per_round(rows: list[dict], out_path: Path) -> None:
    setup_theme()
    fig, axes = plt.subplots(2, 1, figsize=(14.5, 9.2), dpi=180, sharex=True, gridspec_kw={"hspace": 0.18})
    ax_ttft, ax_hit = axes

    max_round = 0
    for row in rows:
        label = row["label"]
        rounds = sorted(row["rounds"].items(), key=lambda item: int(item[0].split("_")[1]))
        xs = np.array([int(name.split("_")[1]) for name, _ in rounds])
        max_round = max(max_round, int(xs.max()))
        ttft = np.array([values["average_ttft"] for _, values in rounds])
        hit = np.array([values["cache_hit_rate"] * 100 for _, values in rounds])
        linestyle = "--" if label == "+Mooncake+SSD" else "-"
        marker = "D" if label == "+Mooncake+SSD" else "o"
        ax_ttft.plot(xs, ttft, marker=marker, linewidth=2.4, markersize=6, color=COLORS[label], label=label, linestyle=linestyle)
        ax_hit.plot(xs, hit, marker=marker, linewidth=2.4, markersize=6, color=COLORS[label], label=label, linestyle=linestyle)

    ax_ttft.set_title("Per-round prefill TTFT")
    ax_ttft.set_ylabel("seconds")
    ax_ttft.grid(True, linestyle="--", alpha=0.45)
    ax_ttft.legend(ncol=min(4, len(rows)), loc="upper left")

    ax_hit.set_title("Per-round cache hit rate")
    ax_hit.set_xlabel("conversation round")
    ax_hit.set_ylabel("%")
    ax_hit.set_xticks(list(range(max_round + 1)))
    ax_hit.set_ylim(-3, max(60, ax_hit.get_ylim()[1]))
    ax_hit.grid(True, linestyle="--", alpha=0.45)

    fig.suptitle("Mooncake SSD Offload Benchmark - Per-turn Performance", fontsize=19, fontweight="bold", y=0.98)
    fig.savefig(out_path)
    plt.close(fig)


def plot_io(rows: list[dict], out_path: Path) -> None:
    labels = [row["label"] for row in rows]
    x = np.arange(len(labels))
    write = np.array([row["evidence"]["max_write_mb_s"] for row in rows])
    read = np.array([row["evidence"]["max_read_mb_s"] for row in rows])
    offload_files = np.array([row["evidence"]["offload_file_count"] for row in rows])
    offload_reads = np.array([row["evidence"]["offload_read_events"] for row in rows])

    setup_theme()
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.2), dpi=180, gridspec_kw={"hspace": 0.35})
    ax_bw, ax_ev = axes
    width = 0.36
    ax_bw.bar(x - width / 2, write, width=width, color="#22c55e", label="max write MB/s")
    ax_bw.bar(x + width / 2, read, width=width, color="#38bdf8", label="max read MB/s")
    ax_bw.set_title("NVMe IO observed by iostat")
    ax_bw.set_ylabel("MB/s")
    ax_bw.set_xticks(x, labels)
    ax_bw.grid(axis="y", linestyle="--", alpha=0.45)
    ax_bw.legend(loc="upper left")

    ax_ev.bar(x - width / 2, offload_files, width=width, color="#a78bfa", label="offload file count")
    ax_ev2 = ax_ev.twinx()
    ax_ev2.plot(x + width / 2, offload_reads, color="#f97316", marker="o", linewidth=2.2, label="offload read events")
    ax_ev.set_title("Mooncake SSD offload evidence")
    ax_ev.set_ylabel("files")
    ax_ev2.set_ylabel("log events")
    ax_ev.set_xticks(x, labels)
    ax_ev.grid(axis="y", linestyle="--", alpha=0.45)
    lines, line_labels = ax_ev.get_legend_handles_labels()
    lines2, line_labels2 = ax_ev2.get_legend_handles_labels()
    ax_ev.legend(lines + lines2, line_labels + line_labels2, loc="upper left")

    fig.suptitle("Mooncake SSD Offload Benchmark - IO Evidence", fontsize=19, fontweight="bold", y=0.98)
    fig.savefig(out_path)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench-root", type=Path, default=Path("/home/ficus/mooncake_smoke_test/main_bench_20260626_123456"))
    parser.add_argument("--out-dir", type=Path, default=Path("docs/assets/mooncake-ssd-offload-review"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = load_bench(args.bench_root)
    write_derived(rows, args.out_dir)
    plot_overall(rows, args.out_dir / "01_overall_performance_local.png", args.bench_root)
    plot_per_round(rows, args.out_dir / "02_per_round_performance_local.png")
    plot_io(rows, args.out_dir / "03_io_evidence_local.png")
    print(f"Wrote charts and derived data to {args.out_dir}")


if __name__ == "__main__":
    main()
