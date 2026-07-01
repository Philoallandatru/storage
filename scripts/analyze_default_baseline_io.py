#!/usr/bin/env python3
"""Summarize the default mixed KV-cache block LBA trace."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


SECTOR_SIZE = 512
GIB = 1024**3
MIB = 1024**2
DEFAULT_INPUT = Path(
    "~/llm/storage/results/kvcache-profile/default_baseline/block_lba_trace.csv"
).expanduser()
DEFAULT_OUTPUT = Path(
    "~/llm/storage/results/kvcache-profile/default_baseline/lba_trace_summary.json"
).expanduser()
DEFAULT_CSV_OUTPUT = Path(
    "~/llm/storage/results/kvcache-profile/default_baseline/lba_trace_summary.csv"
).expanduser()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    return parser.parse_args()


def io_kind(rwbs: str) -> str:
    value = (rwbs or "").upper()
    if value.startswith("R") or ("R" in value and "W" not in value):
        return "read"
    if value.startswith("W") or "W" in value:
        return "write"
    return "other"


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * pct / 100
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(ordered[lo])
    weight = rank - lo
    return float(ordered[lo] * (1 - weight) + ordered[hi] * weight)


def load_rows(path: Path) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    with path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            try:
                size = int(row["bytes"])
                if size <= 0:
                    continue
                rows.append(
                    {
                        "timestamp_ns": int(row["timestamp_ns"]),
                        "dev": int(row["dev"]),
                        "sector": int(row["sector"]),
                        "bytes": size,
                        "rwbs": row.get("rwbs", ""),
                        "comm": row.get("comm", ""),
                        "pid": int(row.get("pid") or 0),
                    }
                )
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda item: int(item["timestamp_ns"]))
    return rows


def adjacent_stats(rows: list[dict[str, int | str]], kind: str) -> dict[str, float | int | None]:
    by_pid: dict[int, list[dict[str, int | str]]] = defaultdict(list)
    for row in rows:
        if io_kind(str(row["rwbs"])) == kind:
            by_pid[int(row["pid"])].append(row)

    deltas: list[float] = []
    for pid_rows in by_pid.values():
        pid_rows.sort(key=lambda item: int(item["timestamp_ns"]))
        for prev, current in zip(pid_rows, pid_rows[1:]):
            delta = abs(int(current["sector"]) - int(prev["sector"])) * SECTOR_SIZE
            deltas.append(float(delta))

    pairs = len(deltas)
    return {
        "pairs": pairs,
        "jump_ge_100mib_pct": (sum(delta >= 100 * MIB for delta in deltas) / pairs * 100)
        if pairs
        else None,
        "exact_contiguous_pct": (sum(delta == 0 for delta in deltas) / pairs * 100)
        if pairs
        else None,
        "abs_delta_mib_p50": (percentile(deltas, 50) / MIB) if pairs else None,
        "abs_delta_mib_p95": (percentile(deltas, 95) / MIB) if pairs else None,
    }


def time_series(rows: list[dict[str, int | str]], ts_min: int, ts_max: int) -> tuple[list[dict], list[dict]]:
    if not rows:
        return [], []
    seconds = int(math.floor((ts_max - ts_min) / 1e9)) + 1
    bins = [
        {"second": second, "events": 0, "read_events": 0, "write_events": 0, "bytes": 0}
        for second in range(seconds)
    ]
    for row in rows:
        second = int((int(row["timestamp_ns"]) - ts_min) // 1_000_000_000)
        bucket = bins[second]
        kind = io_kind(str(row["rwbs"]))
        bucket["events"] += 1
        bucket["bytes"] += int(row["bytes"])
        if kind == "read":
            bucket["read_events"] += 1
        elif kind == "write":
            bucket["write_events"] += 1

    iops = [
        {
            "second": bucket["second"],
            "events": bucket["events"],
            "read_events": bucket["read_events"],
            "write_events": bucket["write_events"],
        }
        for bucket in bins
    ]
    bw = [
        {
            "second": bucket["second"],
            "gib_s": bucket["bytes"] / GIB,
        }
        for bucket in bins
    ]
    return iops, bw


def summarize(rows: list[dict[str, int | str]]) -> dict:
    if not rows:
        return {"block_events": 0}

    ts_min = int(rows[0]["timestamp_ns"])
    ts_max = int(rows[-1]["timestamp_ns"])
    duration_s = (ts_max - ts_min) / 1e9
    kind_counts = Counter(io_kind(str(row["rwbs"])) for row in rows)
    size_counts = Counter(int(row["bytes"]) for row in rows)
    comm_counts = Counter(str(row["comm"]) for row in rows)
    dev_counts = Counter(int(row["dev"]) for row in rows)

    read_rows = [row for row in rows if io_kind(str(row["rwbs"])) == "read"]
    write_rows = [row for row in rows if io_kind(str(row["rwbs"])) == "write"]
    read_bytes = sum(int(row["bytes"]) for row in read_rows)
    write_bytes = sum(int(row["bytes"]) for row in write_rows)
    total_bytes = sum(int(row["bytes"]) for row in rows)
    lba_start = [int(row["sector"]) * SECTOR_SIZE for row in rows]
    lba_end = [start + int(row["bytes"]) for start, row in zip(lba_start, rows)]
    dominant_size, dominant_count = size_counts.most_common(1)[0]
    read_adjacent = adjacent_stats(rows, "read")
    write_adjacent = adjacent_stats(rows, "write")
    iops_per_sec, bw_per_sec_gib = time_series(rows, ts_min, ts_max)

    return {
        "block_events": len(rows),
        "trace_duration_s": duration_s,
        "read_events": kind_counts["read"],
        "write_events": kind_counts["write"],
        "other_events": kind_counts["other"],
        "read_write_ratio": kind_counts["read"] / kind_counts["write"]
        if kind_counts["write"]
        else None,
        "block_read_bytes_gib": read_bytes / GIB,
        "block_write_bytes_gib": write_bytes / GIB,
        "block_total_bytes_gib": total_bytes / GIB,
        "iops": len(rows) / duration_s if duration_s else 0,
        "read_iops": kind_counts["read"] / duration_s if duration_s else 0,
        "write_iops": kind_counts["write"] / duration_s if duration_s else 0,
        "bandwidth_gib_s": total_bytes / GIB / duration_s if duration_s else 0,
        "read_bw_gib_s": read_bytes / GIB / duration_s if duration_s else 0,
        "write_bw_gib_s": write_bytes / GIB / duration_s if duration_s else 0,
        "lba_min_gib": min(lba_start) / GIB,
        "lba_max_gib": max(lba_end) / GIB,
        "lba_span_gib": (max(lba_end) - min(lba_start)) / GIB,
        "dominant_request_size_bytes": dominant_size,
        "dominant_size_share_pct": dominant_count / len(rows) * 100,
        "adjacent_read_jump_ge_100mib_pct": read_adjacent["jump_ge_100mib_pct"],
        "adjacent_read_exact_contiguous_pct": read_adjacent["exact_contiguous_pct"],
        "adjacent_write_exact_contiguous_pct": write_adjacent["exact_contiguous_pct"],
        "adjacent_read_abs_delta_mib_p50": read_adjacent["abs_delta_mib_p50"],
        "adjacent_read_abs_delta_mib_p95": read_adjacent["abs_delta_mib_p95"],
        "adjacent_write_abs_delta_mib_p50": write_adjacent["abs_delta_mib_p50"],
        "adjacent_write_abs_delta_mib_p95": write_adjacent["abs_delta_mib_p95"],
        "adjacent_read_pairs": read_adjacent["pairs"],
        "adjacent_write_pairs": write_adjacent["pairs"],
        "dev_t_values": dict(sorted(dev_counts.items())),
        "top_comm": dict(comm_counts.most_common(10)),
        "top_io_sizes_bytes": dict(size_counts.most_common(10)),
        "iops_per_sec": iops_per_sec,
        "bw_per_sec_giB": bw_per_sec_gib,
    }


def format_value(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def print_table(summary: dict) -> None:
    order = [
        ("Block events", "block_events"),
        ("Trace duration (s)", "trace_duration_s"),
        ("Read events", "read_events"),
        ("Write events", "write_events"),
        ("Read/Write ratio", "read_write_ratio"),
        ("Block read bytes (GiB)", "block_read_bytes_gib"),
        ("Block write bytes (GiB)", "block_write_bytes_gib"),
        ("IOPS", "iops"),
        ("Read IOPS", "read_iops"),
        ("Write IOPS", "write_iops"),
        ("Bandwidth (GiB/s)", "bandwidth_gib_s"),
        ("Read BW (GiB/s)", "read_bw_gib_s"),
        ("Write BW (GiB/s)", "write_bw_gib_s"),
        ("LBA span (GiB)", "lba_span_gib"),
        ("Dominant request size", "dominant_request_size_bytes"),
        ("Dominant size share (%)", "dominant_size_share_pct"),
        ("Adjacent read jump % (>=100 MiB)", "adjacent_read_jump_ge_100mib_pct"),
        ("Adjacent read exact-contiguous %", "adjacent_read_exact_contiguous_pct"),
        ("Adjacent write exact-contiguous %", "adjacent_write_exact_contiguous_pct"),
        ("Adjacent read p50 abs delta (MiB)", "adjacent_read_abs_delta_mib_p50"),
        ("Adjacent read p95 abs delta (MiB)", "adjacent_read_abs_delta_mib_p95"),
        ("Adjacent write p50 abs delta (MiB)", "adjacent_write_abs_delta_mib_p50"),
        ("Adjacent write p95 abs delta (MiB)", "adjacent_write_abs_delta_mib_p95"),
        ("dev_t values", "dev_t_values"),
        ("Top comm", "top_comm"),
    ]
    width = max(len(label) for label, _ in order)
    print(f"{'Metric'.ljust(width)} | Value")
    print(f"{'-' * width}-|-{'-' * 16}")
    for label, key in order:
        print(f"{label.ljust(width)} | {format_value(summary.get(key))}")


def write_summary_csv(summary: dict, path: Path) -> None:
    excluded = {"iops_per_sec", "bw_per_sec_giB"}
    flat = {
        key: json.dumps(value, sort_keys=True) if isinstance(value, dict) else value
        for key, value in summary.items()
        if key not in excluded
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(flat.keys()))
        writer.writeheader()
        writer.writerow(flat)


def main() -> int:
    args = parse_args()
    rows = load_rows(args.input)
    summary = summarize(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    write_summary_csv(summary, args.csv_output)
    print_table(summary)
    print(f"output_json | {args.output}")
    print(f"output_csv | {args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
