#!/usr/bin/env python3
"""Analyze per-I/O block LBA trace emitted by scripts/trace_block_lba.bt."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path


SECTOR_SIZE = 512


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--window-s", type=float, default=10.0)
    return parser.parse_args()


def rw_kind(rwbs: str) -> str:
    if not rwbs:
        return "other"
    first = rwbs[0].upper()
    if first == "R":
        return "read"
    if first == "W":
        return "write"
    if "R" in rwbs.upper() and "W" not in rwbs.upper():
        return "read"
    if "W" in rwbs.upper():
        return "write"
    return "other"


def load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    with path.open(newline="") as fp:
        reader = csv.DictReader(
            row for row in fp
            if row.startswith("timestamp_ns,") or (row[:1].isdigit() and "," in row)
        )
        for row in reader:
            try:
                ts = int(row["timestamp_ns"])
                sector = int(row["sector"])
                size = int(row["bytes"])
            except (KeyError, TypeError, ValueError):
                continue
            if size <= 0:
                continue
            lba = sector * SECTOR_SIZE
            events.append({
                "timestamp_ns": ts,
                "dev": int(row.get("dev") or 0),
                "sector": sector,
                "bytes": size,
                "start": lba,
                "end": lba + size,
                "rwbs": row.get("rwbs", ""),
                "kind": rw_kind(row.get("rwbs", "")),
                "comm": row.get("comm", ""),
                "pid": int(row.get("pid") or 0),
            })
    events.sort(key=lambda ev: ev["timestamp_ns"])
    return events


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * pct / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def summarize_sequence(events: list[dict]) -> dict:
    if len(events) < 2:
        return {"pairs": 0}

    deltas: list[int] = []
    abs_deltas_mib: list[float] = []
    forward = 0
    backward = 0
    exact_contiguous = 0
    overlap_or_same = 0

    current_dir = 0
    current_len = 0
    runs: list[int] = []

    for prev, cur in zip(events, events[1:]):
        delta = cur["start"] - prev["end"]
        deltas.append(delta)
        abs_deltas_mib.append(abs(delta) / 1024 / 1024)
        if delta == 0:
            exact_contiguous += 1
        if cur["start"] <= prev["end"] and cur["end"] >= prev["start"]:
            overlap_or_same += 1
        direction = 1 if delta > 0 else -1 if delta < 0 else 0
        if direction > 0:
            forward += 1
        elif direction < 0:
            backward += 1
        if direction == 0:
            continue
        if direction == current_dir:
            current_len += 1
        else:
            if current_len:
                runs.append(current_len)
            current_dir = direction
            current_len = 1
    if current_len:
        runs.append(current_len)

    pairs = len(deltas)
    return {
        "pairs": pairs,
        "exact_contiguous_pct": exact_contiguous / pairs * 100,
        "overlap_or_same_pct": overlap_or_same / pairs * 100,
        "near_1mib_pct": sum(1 for x in abs_deltas_mib if x < 1) / pairs * 100,
        "near_10mib_pct": sum(1 for x in abs_deltas_mib if x < 10) / pairs * 100,
        "jump_ge_100mib_pct": sum(1 for x in abs_deltas_mib if x >= 100) / pairs * 100,
        "forward_pct": forward / pairs * 100,
        "backward_pct": backward / pairs * 100,
        "abs_delta_mib": {
            "p50": percentile(abs_deltas_mib, 50),
            "p95": percentile(abs_deltas_mib, 95),
            "p99": percentile(abs_deltas_mib, 99),
            "max": max(abs_deltas_mib),
        },
        "direction_run_length": {
            "count": len(runs),
            "p50": percentile([float(x) for x in runs], 50),
            "p95": percentile([float(x) for x in runs], 95),
            "max": max(runs) if runs else None,
        },
    }


def summarize_windows(events: list[dict], window_s: float) -> list[dict]:
    if not events:
        return []
    t0 = events[0]["timestamp_ns"]
    rows = []
    duration_s = (events[-1]["timestamp_ns"] - t0) / 1e9
    n_windows = int(math.ceil(duration_s / window_s))
    for idx in range(n_windows):
        start_s = idx * window_s
        end_s = start_s + window_s
        lo_ns = t0 + int(start_s * 1e9)
        hi_ns = t0 + int(end_s * 1e9)
        win = [ev for ev in events if lo_ns <= ev["timestamp_ns"] < hi_ns]
        if not win:
            continue
        lba_min = min(ev["start"] for ev in win)
        lba_max = max(ev["end"] for ev in win)
        rows.append({
            "window_start_s": start_s,
            "window_end_s": end_s,
            "events": len(win),
            "read_events": sum(1 for ev in win if ev["kind"] == "read"),
            "write_events": sum(1 for ev in win if ev["kind"] == "write"),
            "lba_min_gib": lba_min / 1024 ** 3,
            "lba_max_gib": lba_max / 1024 ** 3,
            "lba_span_gib": (lba_max - lba_min) / 1024 ** 3,
        })
    return rows


def main() -> int:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    events = load_events(args.trace)
    if not events:
        raise SystemExit(f"No events parsed from {args.trace}")

    total_bytes = sum(ev["bytes"] for ev in events)
    kind_counts = Counter(ev["kind"] for ev in events)
    rwbs_counts = Counter(ev["rwbs"] for ev in events)
    size_counts = Counter(ev["bytes"] for ev in events)
    lba_min = min(ev["start"] for ev in events)
    lba_max = max(ev["end"] for ev in events)

    summary = {
        "trace": str(args.trace),
        "events": len(events),
        "duration_s": (events[-1]["timestamp_ns"] - events[0]["timestamp_ns"]) / 1e9,
        "total_bytes_gib": total_bytes / 1024 ** 3,
        "kind_counts": dict(kind_counts),
        "rwbs_counts": dict(rwbs_counts),
        "top_io_sizes_bytes": dict(size_counts.most_common(20)),
        "lba_min_gib": lba_min / 1024 ** 3,
        "lba_max_gib": lba_max / 1024 ** 3,
        "lba_span_gib": (lba_max - lba_min) / 1024 ** 3,
        "all_io_sequence": summarize_sequence(events),
        "read_sequence": summarize_sequence([ev for ev in events if ev["kind"] == "read"]),
        "write_sequence": summarize_sequence([ev for ev in events if ev["kind"] == "write"]),
        "windows": summarize_windows(events, args.window_s),
    }

    summary_path = args.out / "lba_trace_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    windows_path = args.out / "lba_trace_windows.csv"
    with windows_path.open("w", newline="") as fp:
        fieldnames = [
            "window_start_s", "window_end_s", "events", "read_events",
            "write_events", "lba_min_gib", "lba_max_gib", "lba_span_gib",
        ]
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary["windows"])

    print(json.dumps({
        "events": summary["events"],
        "duration_s": summary["duration_s"],
        "kind_counts": summary["kind_counts"],
        "lba_span_gib": summary["lba_span_gib"],
        "read_sequence": summary["read_sequence"],
        "write_sequence": summary["write_sequence"],
        "summary": str(summary_path),
        "windows": str(windows_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
