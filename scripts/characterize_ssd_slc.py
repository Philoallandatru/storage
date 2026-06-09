#!/usr/bin/env python3
"""Characterize SSD write behavior and estimate SLC cache properties.

This is a safe file-level test: it writes a large temporary file under the
given target directory using fio, records per-second write bandwidth, then
estimates:

- cache-in write speed
- likely SLC cache cliff and size
- post-cache write speed
- steady-state tail speed
- a conservative TLC/QLC tendency from sustained write behavior

It cannot prove NAND type. Use vendor specs or NAND package inspection for a
definitive TLC/QLC answer.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


GIB = 1024**3


@dataclass
class Sample:
    sec: float
    mib_s: float


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def median(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return None
    return statistics.median(vals)


def percentile(values: list[float], pct: float) -> float | None:
    vals = sorted(v for v in values if v is not None and not math.isnan(v))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * pct / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return vals[int(pos)]
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}{suffix}"


def detect_mount(path: Path) -> dict[str, str]:
    df = run(["df", "-P", str(path)]).stdout.strip().splitlines()
    if len(df) < 2:
        return {}
    fields = df[-1].split()
    device = fields[0]
    mountpoint = fields[-1]
    info = {"device": device, "mountpoint": mountpoint}

    lsblk = shutil.which("lsblk")
    if lsblk:
        try:
            out = run(["lsblk", "-no", "PKNAME,MODEL,SIZE,FSTYPE", device], check=False).stdout.strip()
            if out:
                info["lsblk"] = out
        except Exception:
            pass
    return info


def parse_bw_logs(run_dir: Path, prefix: str) -> list[Sample]:
    logs = sorted(run_dir.glob(f"{prefix}_bw*.log"))
    if not logs:
        logs = sorted(run_dir.glob("*_bw*.log"))
    samples: list[Sample] = []
    for log in logs:
        with log.open() as f:
            for row in csv.reader(f):
                if len(row) < 2:
                    continue
                try:
                    msec = float(row[0].strip())
                    kib_s = float(row[1].strip())
                except ValueError:
                    continue
                # fio bandwidth logs use KiB/s. Convert to MiB/s.
                samples.append(Sample(sec=msec / 1000.0, mib_s=kib_s / 1024.0))
    samples.sort(key=lambda s: s.sec)
    return samples


def rolling_median(samples: list[Sample], index: int, window: int) -> float:
    start = max(0, index - window + 1)
    return statistics.median(s.mib_s for s in samples[start : index + 1])


def find_cache_cliff(
    samples: list[Sample],
    *,
    initial_speed: float,
    drop_ratio: float,
    window: int,
    sustain_seconds: int,
) -> int | None:
    if not samples or initial_speed <= 0:
        return None
    threshold = initial_speed * drop_ratio
    for i in range(window, len(samples)):
        if samples[i].sec < 5:
            continue
        if rolling_median(samples, i, window) > threshold:
            continue
        end = min(len(samples), i + sustain_seconds)
        sustained = [rolling_median(samples, j, window) <= threshold for j in range(i, end)]
        if len(sustained) >= min(5, sustain_seconds) and all(sustained):
            return i
    return None


def cumulative_gib(samples: list[Sample], end_index: int) -> float:
    if not samples or end_index <= 0:
        return 0.0
    total_mib = 0.0
    prev_sec = samples[0].sec
    for s in samples[: end_index + 1]:
        dt = max(0.0, s.sec - prev_sec)
        total_mib += s.mib_s * dt
        prev_sec = s.sec
    return total_mib / 1024.0


def infer_media(post_cache_mib_s: float | None, steady_mib_s: float | None, total_gib: float) -> str:
    speed = post_cache_mib_s if post_cache_mib_s is not None else steady_mib_s
    if speed is None:
        return "insufficient-data"
    if total_gib < 128:
        return "insufficient-write-volume: run at least 200-600GiB for NAND inference"
    if speed < 300:
        return "QLC-like or severely throttled low-end TLC"
    if speed < 900:
        return "QLC-like or low-end DRAM-less TLC"
    if speed < 1500:
        return "TLC-like, but not definitive"
    return "strong TLC-like sustained write behavior"


def write_report(run_dir: Path, data: dict) -> None:
    report = run_dir / "ssd_characterization_report.md"
    samples_csv = run_dir / "bandwidth_samples.csv"
    with samples_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["second", "write_MiB_s"])
        for s in data["samples"]:
            w.writerow([f"{s.sec:.3f}", f"{s.mib_s:.3f}"])

    lines = [
        "# SSD SLC Cache Characterization Report",
        "",
        f"Generated: {data['generated']}",
        "",
        "## Target",
        "",
        f"- Target directory: `{data['target_dir']}`",
        f"- Test file: `{data['test_file']}`",
        f"- Filesystem device: `{data['mount'].get('device', 'unknown')}`",
        f"- Mountpoint: `{data['mount'].get('mountpoint', 'unknown')}`",
        f"- lsblk: `{data['mount'].get('lsblk', 'unknown')}`",
        "",
        "## fio Configuration",
        "",
        f"- Size: `{data['size_gib']:.2f} GiB`",
        f"- Block size: `{data['bs']}`",
        f"- iodepth: `{data['iodepth']}`",
        "- Workload: sequential write, direct=1, libaio",
        "",
        "## Result",
        "",
        f"- Total written: `{fmt(data['total_written_gib'], ' GiB')}`",
        f"- Runtime: `{fmt(data['runtime_s'], ' s')}`",
        f"- Average write speed: `{fmt(data['avg_mib_s'], ' MiB/s')}`",
        f"- Initial/cache-in speed: `{fmt(data['initial_mib_s'], ' MiB/s')}`",
        f"- Post-cache speed: `{fmt(data['post_cache_mib_s'], ' MiB/s')}`",
        f"- Steady tail speed: `{fmt(data['steady_mib_s'], ' MiB/s')}`",
        f"- P50/P95/P99 per-second speed: `{fmt(data['p50_mib_s'])}` / `{fmt(data['p95_mib_s'])}` / `{fmt(data['p99_mib_s'])}` MiB/s",
        f"- Estimated SLC cache size: `{data['cache_size_text']}`",
        f"- Media tendency from sustained write: `{data['media_inference']}`",
        "",
        "## Interpretation",
        "",
        "- This test estimates SLC cache behavior from the write-speed cliff.",
        "- It cannot definitively prove TLC vs QLC. Use official specs, controller/NAND inspection, or vendor data for confirmation.",
        "- If no cliff appears, increase `--size-gb` until the write curve drops or the device reaches steady state.",
        "- For AI SSD product evaluation, use the post-cache and steady-tail speeds, not only the initial cache-in speed.",
        "",
        "## Files",
        "",
        f"- fio JSON: `{data['fio_json'].name}`",
        f"- fio stderr: `{data['fio_stderr'].name}`",
        f"- bandwidth samples: `{samples_csv.name}`",
    ]
    report.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate SSD SLC cache size and sustained write behavior.")
    parser.add_argument("--target-dir", default="results/ssd-characterization", help="Directory on the SSD/filesystem to test.")
    parser.add_argument("--size-gb", type=float, required=True, help="Amount to write. Use 200-600 for SLC/cache inference.")
    parser.add_argument("--iodepth", type=int, default=32)
    parser.add_argument("--bs", default="1M")
    parser.add_argument("--drop-ratio", type=float, default=0.65, help="Cliff threshold vs initial speed.")
    parser.add_argument("--name", default=None, help="Optional run name suffix.")
    parser.add_argument("--keep-file", action="store_true", help="Keep the test file after the run.")
    parser.add_argument("--yes", action="store_true", help="Actually run fio. Without this, print the plan and exit.")
    args = parser.parse_args()

    fio = shutil.which("fio")
    if not fio:
        print("ERROR: fio is not installed or not in PATH.", file=sys.stderr)
        return 2

    target_dir = Path(args.target_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(target_dir)
    requested = int(args.size_gb * GIB)
    reserve = max(10 * GIB, int(usage.total * 0.03))
    if usage.free < requested + reserve:
        print(
            f"ERROR: not enough free space in {target_dir}. "
            f"free={usage.free/GIB:.1f}GiB requested={args.size_gb:.1f}GiB reserve={reserve/GIB:.1f}GiB",
            file=sys.stderr,
        )
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"ssd_slc_{args.name + '_' if args.name else ''}{stamp}"
    run_dir = target_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    test_file = run_dir / "fio_slc_test.dat"
    fio_json = run_dir / "fio_output.json"
    fio_stderr = run_dir / "fio_stderr.txt"
    log_prefix = "slc_write"

    mount = detect_mount(target_dir)
    print("SSD characterization plan")
    print(f"  target_dir: {target_dir}")
    print(f"  mount:      {mount.get('device', 'unknown')} on {mount.get('mountpoint', 'unknown')}")
    print(f"  lsblk:      {mount.get('lsblk', 'unknown')}")
    print(f"  write:      {args.size_gb:.1f} GiB, bs={args.bs}, iodepth={args.iodepth}")
    print(f"  output:     {run_dir}")
    if not args.yes:
        print("\nDry run only. Re-run with --yes to start fio.")
        return 0

    cmd = [
        fio,
        "--name=slc-characterize",
        f"--filename={test_file}",
        "--rw=write",
        f"--bs={args.bs}",
        f"--iodepth={args.iodepth}",
        "--ioengine=libaio",
        "--direct=1",
        "--numjobs=1",
        "--group_reporting=1",
        "--refill_buffers=1",
        "--time_based=0",
        f"--size={max(1, int(args.size_gb * 1024))}M",
        "--log_avg_msec=1000",
        f"--write_bw_log={run_dir / log_prefix}",
        "--per_job_logs=0",
        "--output-format=json",
    ]

    print("\nRunning fio...")
    with fio_json.open("w") as out, fio_stderr.open("w") as err:
        proc = subprocess.run(cmd, stdout=out, stderr=err, text=True)
    if proc.returncode != 0:
        print(f"ERROR: fio failed. See {fio_stderr}", file=sys.stderr)
        return proc.returncode

    fio_data = json.loads(fio_json.read_text())
    job = fio_data["jobs"][0]
    write = job["write"]
    total_written_gib = float(write.get("io_bytes", 0)) / GIB
    runtime_s = float(write.get("runtime", 0)) / 1000.0
    avg_mib_s = float(write.get("bw_bytes", 0)) / 1024 / 1024

    samples = parse_bw_logs(run_dir, log_prefix)
    if not samples:
        # Very small smoke tests can finish before the first 1s bandwidth log.
        # Keep the script usable, but tell the user the run is too short for
        # cache-size inference.
        samples = [Sample(sec=max(runtime_s, 0.001), mib_s=avg_mib_s)]

    speeds = [s.mib_s for s in samples]
    first_n = max(5, min(30, max(1, len(samples) // 10)))
    last_n = max(10, min(60, max(1, len(samples) // 5)))
    initial_mib_s = median(speeds[:first_n])
    steady_mib_s = median(speeds[-last_n:])
    cliff_idx = find_cache_cliff(
        samples,
        initial_speed=initial_mib_s or 0,
        drop_ratio=args.drop_ratio,
        window=5,
        sustain_seconds=15,
    )
    if cliff_idx is None:
        cache_size_text = f">= {total_written_gib:.2f} GiB (no sustained cliff detected)"
        post_cache_mib_s = None
    else:
        cache_gib = cumulative_gib(samples, cliff_idx)
        cache_size_text = f"~ {cache_gib:.2f} GiB"
        post_start = min(len(samples), cliff_idx + 10)
        post_cache_mib_s = median(s.mib_s for s in samples[post_start:])

    media_inference = infer_media(post_cache_mib_s, steady_mib_s, total_written_gib)
    data = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "target_dir": str(target_dir),
        "test_file": str(test_file),
        "mount": mount,
        "size_gib": args.size_gb,
        "bs": args.bs,
        "iodepth": args.iodepth,
        "total_written_gib": total_written_gib,
        "runtime_s": runtime_s,
        "avg_mib_s": avg_mib_s,
        "initial_mib_s": initial_mib_s,
        "post_cache_mib_s": post_cache_mib_s,
        "steady_mib_s": steady_mib_s,
        "p50_mib_s": percentile(speeds, 50),
        "p95_mib_s": percentile(speeds, 95),
        "p99_mib_s": percentile(speeds, 99),
        "cache_size_text": cache_size_text,
        "media_inference": media_inference,
        "samples": samples,
        "fio_json": fio_json,
        "fio_stderr": fio_stderr,
    }
    write_report(run_dir, data)

    print("\nResult")
    print(f"  total_written:   {total_written_gib:.2f} GiB")
    print(f"  runtime:         {runtime_s:.1f} s")
    print(f"  avg speed:       {avg_mib_s:.2f} MiB/s")
    print(f"  initial speed:   {fmt(initial_mib_s, ' MiB/s')}")
    print(f"  post-cache:      {fmt(post_cache_mib_s, ' MiB/s')}")
    print(f"  steady tail:     {fmt(steady_mib_s, ' MiB/s')}")
    print(f"  SLC cache size:  {cache_size_text}")
    print(f"  media tendency:  {media_inference}")
    print(f"  report:          {run_dir / 'ssd_characterization_report.md'}")

    if not args.keep_file:
        try:
            test_file.unlink()
            print("  cleanup:         test file removed")
        except FileNotFoundError:
            pass
    else:
        print("  cleanup:         test file kept")

    return 0


if __name__ == "__main__":
    sys.exit(main())
