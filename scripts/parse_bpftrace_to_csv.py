#!/usr/bin/env python3
"""Convert trace_block_lba.bt bpftrace output to block LBA CSV."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path


DEFAULT_INPUT = Path("/tmp/bt-default-baseline.log")
DEFAULT_OUTPUT = Path(
    "~/llm/storage/results/kvcache-profile/default_baseline/block_lba_trace.csv"
).expanduser()
CSV_COLUMNS = ["timestamp_ns", "dev", "sector", "bytes", "rwbs", "comm", "pid"]
ROW_RE = re.compile(
    r"^\s*(?P<timestamp_ns>\d+),(?P<dev>\d+),(?P<sector>\d+),"
    r"(?P<bytes>\d+),(?P<rwbs>[^,\s]+),(?P<comm>[^,\s]+),(?P<pid>\d+)\s*$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def io_kind(rwbs: str) -> str:
    value = (rwbs or "").upper()
    if value.startswith("R") or ("R" in value and "W" not in value):
        return "read"
    if value.startswith("W") or "W" in value:
        return "write"
    return "other"


def valid_row(line: str) -> dict[str, int | str] | None:
    match = ROW_RE.match(line)
    if not match:
        return None

    try:
        row: dict[str, int | str] = {
            "timestamp_ns": int(match.group("timestamp_ns")),
            "dev": int(match.group("dev")),
            "sector": int(match.group("sector")),
            "bytes": int(match.group("bytes")),
            "rwbs": match.group("rwbs"),
            "comm": match.group("comm"),
            "pid": int(match.group("pid")),
        }
    except ValueError:
        return None

    if row["bytes"] <= 0:
        return None
    return row


def main() -> int:
    args = parse_args()
    rows: list[dict[str, int | str]] = []
    kind_counts: Counter[str] = Counter()
    dev_counts: Counter[int] = Counter()

    with args.input.open() as fp:
        for line in fp:
            row = valid_row(line)
            if row is None:
                continue
            rows.append(row)
            kind_counts[io_kind(str(row["rwbs"]))] += 1
            dev_counts[int(row["dev"])] += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    if rows:
        ts_min = min(int(row["timestamp_ns"]) for row in rows)
        ts_max = max(int(row["timestamp_ns"]) for row in rows)
        duration_s = (ts_max - ts_min) / 1e9
    else:
        duration_s = 0.0

    print(f"events,total,{len(rows)}")
    print(f"events,read,{kind_counts['read']}")
    print(f"events,write,{kind_counts['write']}")
    print(f"events,other,{kind_counts['other']}")
    print(f"duration_s,{duration_s:.6f}")
    print(
        "dev_t_values,"
        + ";".join(f"{dev}:{count}" for dev, count in sorted(dev_counts.items()))
    )
    print(f"output,{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
