#!/usr/bin/env python3
"""LBA-over-time scatter plot from bpftrace CSV.

Reads block_lba_trace.csv (250MB, 4M events) in streaming fashion,
samples every Nth event for visualization, plots LBA (y) vs time_ns (x)
with read/write color split.

Output: docs/assets/io-three-way-comparison/06_lba_scatter_default.png
"""

from __future__ import annotations
import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


BG_PAGE = '#1f1f1f'
BG_CARD = '#2a2a2a'
COLOR_VAL = '#ffffff'
COLOR_LBL = '#cccccc'
COLOR_DIM = '#888888'
COLOR_BORDER = '#444444'
COLOR_READ = '#00d4ff'    # cyan
COLOR_WRITE = '#ffaa00'   # amber/yellow
COLOR_DEFAULT = '#ff77ff'  # magenta

SAMPLE_RATE = 100  # sample 1 in every 100 events (~40K from 4M)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True,
                        help='block_lba_trace.csv path')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-events', type=int, default=50000,
                        help='target number of events to plot')
    args = parser.parse_args()

    print(f'Reading {args.csv} (sampling 1/{SAMPLE_RATE} events)...')
    t0_ns: list[int] = []
    lba_gib: list[float] = []
    kinds: list[str] = []

    with args.csv.open(newline='') as fp:
        reader = csv.DictReader(fp)
        for i, row in enumerate(reader):
            if i % SAMPLE_RATE != 0:
                continue
            try:
                ts = int(row['timestamp_ns'])
                sector = int(row['sector'])
                b = int(row['bytes'])
                if b <= 0:
                    continue
                rwbs = (row.get('rwbs') or '').upper()
                kind = 'R' if rwbs.startswith('R') else ('W' if rwbs.startswith('W') else 'O')
                t0_ns.append(ts)
                lba_gib.append(sector * 512 / (1024 ** 3))
                kinds.append(kind)
            except (KeyError, ValueError):
                continue

    print(f'Sampled {len(t0_ns)} events from {args.csv.name}')
    t0_ns_arr = np.asarray(t0_ns)
    lba_arr = np.asarray(lba_gib)
    kinds_arr = np.asarray(kinds)
    # time → seconds from start
    t_sec = (t0_ns_arr - t0_ns_arr.min()) / 1e9

    # ----- Plot -----
    fig, axes = plt.subplots(2, 1, figsize=(16, 10))
    fig.suptitle(
        'LBA-over-Time Scatter (real default mixed prefill+decode, 4M events → 1/100 sampled)',
        fontsize=18, fontweight='bold', color=COLOR_VAL, y=0.995)

    # Subplot 1: all events, color by R/W
    ax = axes[0]
    ax.set_facecolor(BG_CARD)
    r_mask = kinds_arr == 'R'
    w_mask = kinds_arr == 'W'
    o_mask = kinds_arr == 'O'
    ax.scatter(t_sec[r_mask], lba_arr[r_mask],
               s=1.5, c=COLOR_READ, alpha=0.5, label=f'read (n={r_mask.sum():,})', rasterized=True)
    ax.scatter(t_sec[w_mask], lba_arr[w_mask],
               s=2.5, c=COLOR_WRITE, alpha=0.7, label=f'write (n={w_mask.sum():,})', rasterized=True)
    if o_mask.any():
        ax.scatter(t_sec[o_mask], lba_arr[o_mask],
                   s=1.0, c=COLOR_DIM, alpha=0.3, label=f'other (n={o_mask.sum():,})', rasterized=True)
    ax.set_xlabel('time (s)', color=COLOR_DIM)
    ax.set_ylabel('LBA (GiB)', color=COLOR_DIM)
    ax.set_title('All events — read (cyan) vs write (yellow) over time',
                 color=COLOR_VAL, fontsize=13)
    ax.legend(loc='upper left', facecolor=BG_CARD, edgecolor=COLOR_BORDER,
              labelcolor=COLOR_VAL, fontsize=10)
    ax.grid(True, alpha=0.10, color=COLOR_DIM)
    for s in ['top', 'right']: ax.spines[s].set_visible(False)
    for s in ['left', 'bottom']: ax.spines[s].set_color(COLOR_BORDER)
    ax.tick_params(colors=COLOR_DIM)

    # Subplot 2: write only, with phase shading
    ax = axes[1]
    ax.set_facecolor(BG_CARD)
    # Show write density as background heat
    if w_mask.sum() > 0:
        ax.scatter(t_sec[w_mask], lba_arr[w_mask],
                   s=4.0, c=COLOR_WRITE, alpha=0.85, label='write', rasterized=True)
    ax.scatter(t_sec[r_mask], lba_arr[r_mask],
               s=1.0, c=COLOR_READ, alpha=0.3, label='read (light)', rasterized=True)
    ax.set_xlabel('time (s)', color=COLOR_DIM)
    ax.set_ylabel('LBA (GiB)', color=COLOR_DIM)
    ax.set_title('Write-dominant view — sequential LBA append visible as horizontal stripes',
                 color=COLOR_VAL, fontsize=13)
    ax.legend(loc='upper left', facecolor=BG_CARD, edgecolor=COLOR_BORDER,
              labelcolor=COLOR_VAL, fontsize=10)
    ax.grid(True, alpha=0.10, color=COLOR_DIM)
    for s in ['top', 'right']: ax.spines[s].set_visible(False)
    for s in ['left', 'bottom']: ax.spines[s].set_color(COLOR_BORDER)
    ax.tick_params(colors=COLOR_DIM)

    plt.subplots_adjust(left=0.05, right=0.98, top=0.93, bottom=0.05, hspace=0.28)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, dpi=130, bbox_inches='tight', facecolor=BG_PAGE)
    plt.close()
    print(f'saved {args.output}')

    # Also print summary stats
    print(f'\n=== LBA scatter summary ===')
    print(f'Time range:  {t_sec.min():.2f} s – {t_sec.max():.2f} s')
    print(f'LBA range:   {lba_arr.min():.2f} GiB – {lba_arr.max():.2f} GiB (span {lba_arr.max()-lba_arr.min():.2f} GiB)')
    print(f'Read count:  {r_mask.sum():,} ({r_mask.sum()/len(kinds)*100:.1f}%)')
    print(f'Write count: {w_mask.sum():,} ({w_mask.sum()/len(kinds)*100:.1f}%)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())