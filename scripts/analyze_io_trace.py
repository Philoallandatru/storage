#!/usr/bin/env python3
"""analyze_io_trace.py — 解析 --io-trace-log 输出的 CSV(.zst),生成 I/O pattern 报告。

读 kv_trace.csv.zst,统计:
- 操作数 / 字节数 / 平均 size / P50/P95/P99 size
- Tier-0/1/2 操作 + 字节占比
- Phase (Prefill/Decode/Evict) 占比 + 时间序列

输出:
- <out>.md: Markdown 报告
- <out>.png: matplotlib 4-panel 图(size hist / tier pie / phase pie / time series)
"""
import argparse
import csv
import io
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


def read_trace(path: Path):
    """Read CSV trace, supporting .zst compression transparently."""
    if path.suffix == '.zst':
        try:
            import zstandard as zstd
        except ImportError:
            sys.exit("zstandard not installed; uv pip install zstandard")
        with open(path, 'rb') as f:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(f) as reader:
                text = io.TextIOWrapper(reader, encoding='utf-8')
                yield from csv.DictReader(text)
    else:
        with open(path, 'r') as f:
            yield from csv.DictReader(f)


def percentile(values, p):
    if not values:
        return 0
    return float(np.percentile(values, p))


def analyze(path: Path) -> dict:
    rows = list(read_trace(path))
    if not rows:
        sys.exit(f"empty trace: {path}")

    ops = Counter(r['Operation'] for r in rows)
    tiers = Counter(r['Tier'] for r in rows)
    phases = Counter(r['Phase'] for r in rows)
    sizes = [int(r['Object_Size_Bytes']) for r in rows
             if r['Object_Size_Bytes'].isdigit()]

    # Tier x Operation
    tier_op = defaultdict(Counter)
    for r in rows:
        tier_op[r['Tier']][r['Operation']] += 1

    # Tier x Phase
    tier_phase = defaultdict(Counter)
    for r in rows:
        tier_phase[r['Tier']][r['Phase']] += 1

    # Per-phase size stats
    by_phase_size = defaultdict(list)
    for r in rows:
        if r['Object_Size_Bytes'].isdigit():
            by_phase_size[r['Phase']].append(int(r['Object_Size_Bytes']))

    # Time series (per-second bucket)
    time_buckets = Counter()
    size_total = 0
    for r in rows:
        if not r['Timestamp']:
            continue
        try:
            t = float(r['Timestamp'])
            bucket = int(t)
            time_buckets[bucket] += 1
        except (ValueError, KeyError):
            pass
        if r['Object_Size_Bytes'].isdigit():
            size_total += int(r['Object_Size_Bytes'])

    return {
        'total_ops': len(rows),
        'ops_by_type': dict(ops),
        'ops_by_tier': dict(tiers),
        'ops_by_phase': dict(phases),
        'tier_op': {t: dict(c) for t, c in tier_op.items()},
        'tier_phase': {t: dict(c) for t, c in tier_phase.items()},
        'size_bytes': {
            'count': len(sizes),
            'sum': sum(sizes),
            'mean': float(np.mean(sizes)) if sizes else 0,
            'p50': percentile(sizes, 50),
            'p95': percentile(sizes, 95),
            'p99': percentile(sizes, 99),
            'max': max(sizes) if sizes else 0,
        },
        'size_by_phase': {
            p: {
                'count': len(v),
                'sum': sum(v),
                'mean': float(np.mean(v)) if v else 0,
                'p50': percentile(v, 50),
                'p95': percentile(v, 95),
                'p99': percentile(v, 99),
            }
            for p, v in by_phase_size.items()
        },
        'time_buckets': dict(time_buckets),
        'duration_s': max(time_buckets) - min(time_buckets) + 1
                        if time_buckets else 0,
    }


def render_md(stats, source_path: str) -> str:
    lines = [
        f"# I/O Pattern Analysis — `{source_path}`",
        "",
        f"Total operations: **{stats['total_ops']:,}**",
        f"Total bytes: **{stats['size_bytes']['sum'] / 1024**3:.2f} GiB**",
        f"Duration: **{stats['duration_s']} seconds**",
        "",
        "## By Operation Type",
        "",
        "| Op | Count | % of total |",
        "|---|---:|---:|",
    ]
    total = stats['total_ops']
    for op in ['Read', 'Write']:
        if op in stats['ops_by_type']:
            n = stats['ops_by_type'][op]
            lines.append(f"| {op} | {n:,} | {100*n/total:.1f}% |")

    lines += ["",
              "## By Tier",
              "",
              "| Tier | Count | % of total |",
              "|---|---:|---:|"]
    for tier in sorted(stats['ops_by_tier'].keys()):
        n = stats['ops_by_tier'][tier]
        lines.append(f"| {tier} | {n:,} | {100*n/total:.1f}% |")

    lines += ["", "## Tier × Operation", "",
              "| Tier | Read | Write |",
              "|---|---:|---:|"]
    for tier in sorted(stats['tier_op'].keys()):
        ro = stats['tier_op'][tier].get('Read', 0)
        wo = stats['tier_op'][tier].get('Write', 0)
        lines.append(f"| {tier} | {ro:,} | {wo:,} |")

    lines += ["", "## By Phase", "",
              "| Phase | Count | % of total |",
              "|---|---:|---:|"]
    for phase in sorted(stats['ops_by_phase'].keys()):
        n = stats['ops_by_phase'][phase]
        lines.append(f"| {phase} | {n:,} | {100*n/total:.1f}% |")

    s = stats['size_bytes']
    lines += [
        "", "## Object Size Distribution (bytes)",
        "",
        f"- count: {s['count']:,}",
        f"- sum:   {s['sum']/1024**2:.1f} MiB ({s['sum']/1024**3:.2f} GiB)",
        f"- mean:  {s['mean']:.0f} ({s['mean']/1024:.1f} KiB)",
        f"- p50:   {s['p50']:.0f} ({s['p50']/1024:.1f} KiB)",
        f"- p95:   {s['p95']:.0f} ({s['p95']/1024:.1f} KiB)",
        f"- p99:   {s['p99']:.0f} ({s['p99']/1024:.1f} KiB)",
        f"- max:   {s['max']} ({s['max']/1024**2:.1f} MiB)",
        "",
        "## Size by Phase (bytes)",
        "",
        "| Phase | Count | Mean | P50 | P95 | P99 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for phase in sorted(stats['size_by_phase'].keys()):
        v = stats['size_by_phase'][phase]
        lines.append(
            f"| {phase} | {v['count']:,} | {v['mean']:.0f} "
            f"| {v['p50']:.0f} | {v['p95']:.0f} | {v['p99']:.0f} |"
        )

    return "\n".join(lines) + "\n"


def render_png(stats, output_png: Path, source_path: str) -> bool:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping PNG")
        return False

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"I/O Pattern: {Path(source_path).name}", fontsize=14)

    # Panel 1: Tier pie
    tiers = sorted(stats['ops_by_tier'].keys())
    tier_counts = [stats['ops_by_tier'][t] for t in tiers]
    if sum(tier_counts) > 0:
        axes[0, 0].pie(tier_counts, labels=tiers, autopct='%1.1f%%', startangle=90)
        axes[0, 0].set_title('Operations by Tier')

    # Panel 2: Phase pie
    phases = sorted(stats['ops_by_phase'].keys())
    phase_counts = [stats['ops_by_phase'][p] for p in phases]
    if sum(phase_counts) > 0:
        axes[0, 1].pie(phase_counts, labels=phases, autopct='%1.1f%%', startangle=90)
        axes[0, 1].set_title('Operations by Phase')

    # Panel 3: Op type pie
    op_types = ['Read', 'Write']
    op_counts = [stats['ops_by_type'].get(t, 0) for t in op_types]
    if sum(op_counts) > 0:
        axes[1, 0].pie(op_counts, labels=op_types, autopct='%1.1f%%', startangle=90)
        axes[1, 0].set_title('Operations by Type')

    # Panel 4: Time series (ops per second)
    if stats['time_buckets']:
        times = sorted(stats['time_buckets'].keys())
        counts = [stats['time_buckets'][t] for t in times]
        axes[1, 1].plot(times, counts, alpha=0.7, linewidth=1)
        axes[1, 1].set_title('Operations per Second (time series)')
        axes[1, 1].set_xlabel('Timestamp (epoch sec)')
        axes[1, 1].set_ylabel('Ops/sec')
        axes[1, 1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_png, dpi=80, bbox_inches='tight')
    plt.close()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('trace', type=Path, help='kv_trace.csv or kv_trace.csv.zst')
    ap.add_argument('--out-md', type=Path, required=True)
    ap.add_argument('--out-png', type=Path, default=None)
    args = ap.parse_args()

    if not args.trace.exists():
        sys.exit(f"trace not found: {args.trace}")

    stats = analyze(args.trace)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_md(stats, str(args.trace)))
    print(f"wrote {args.out_md}")

    if args.out_png:
        if render_png(stats, args.out_png, str(args.trace)):
            print(f"wrote {args.out_png}")

    # Summary line for scripting
    print(f"--- summary ---")
    print(f"  total_ops:  {stats['total_ops']:,}")
    print(f"  ops_by_type: {stats['ops_by_type']}")
    print(f"  ops_by_tier: {stats['ops_by_tier']}")
    print(f"  ops_by_phase: {stats['ops_by_phase']}")
    print(f"  size_mean:  {stats['size_bytes']['mean']:.0f} bytes")
    print(f"  size_p95:   {stats['size_bytes']['p95']:.0f} bytes")
    print(f"  size_p99:   {stats['size_bytes']['p99']:.0f} bytes")
    print(f"  duration:   {stats['duration_s']} s")


if __name__ == '__main__':
    main()