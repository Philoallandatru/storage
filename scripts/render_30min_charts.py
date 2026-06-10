#!/usr/bin/env python3
"""
Generate charts for 30-min drift data:
  - Time-series comparison: 1200s vs 1800s (Biwin/Seagate)
  - Final 1-min BW comparison across all 3 durations
"""
import os, sys, json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '/home/ficus/llm/storage/scripts')
from analyze_kv_cache_iostat import parse_iostat, DEV_FOR_DISK

BASE = Path('/home/ficus/llm/storage/results/cross_vendor')
OUT = Path('/home/ficus/llm/storage/docs/assets/charts')
OUT.mkdir(parents=True, exist_ok=True)

DISKS = ['biwin_x570', 'seagate_fc530', 'zhitai_ti600', 'wd_sn570']
COLOR = {
    'biwin_x570':    '#2ca02c',
    'seagate_fc530': '#ffbb33',
    'zhitai_ti600':  '#d62728',
    'wd_sn570':      '#1f77b4',
}
plt.style.use('seaborn-v0_8-darkgrid')
plt.rcParams.update({
    'figure.dpi': 110, 'savefig.dpi': 150, 'font.size': 11,
    'axes.titlesize': 13, 'axes.labelsize': 11,
    'axes.spines.top': False, 'axes.spines.right': False,
    'legend.frameon': False, 'figure.facecolor': 'white',
})

def pd_series_rolling(arr, window):
    out = np.full_like(arr, np.nan, dtype=float)
    csum = np.cumsum(np.insert(arr, 0, 0.0))
    out[window-1:] = (csum[window:] - csum[:-window]) / window
    return out


# Chart 7: 20-min vs 30-min BW time-series comparison (Biwin + Seagate)
def chart_07_long_drift_compare():
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5), sharey=True)
    for ax, disk in zip(axes, ['biwin_x570', 'seagate_fc530']):
        # 1200s
        p1 = BASE/'kv_cache_k4_gc_drift'/disk/'K4_16u_llama3.1-8b_1200s'/'iostat.txt'
        s1 = parse_iostat(p1, DEV_FOR_DISK[disk])
        r1 = np.array([x['r_mbs'] for x in s1])
        t1 = np.arange(len(r1))/60
        roll1 = pd_series_rolling(r1, 30)
        ax.plot(t1, roll1, color=COLOR[disk], linewidth=2, label='20-min run', alpha=0.95)

        # 1800s
        p2 = BASE/'kv_cache_k4_30min_drift'/disk
        sub = list(p2.iterdir())[0]/'iostat.txt'
        s2 = parse_iostat(sub, DEV_FOR_DISK[disk])
        r2 = np.array([x['r_mbs'] for x in s2])
        t2 = np.arange(len(r2))/60
        roll2 = pd_series_rolling(r2, 30)
        ax.plot(t2, roll2, color=COLOR[disk], linewidth=2, linestyle='--',
                label='30-min run', alpha=0.95)
        # Annotate end values
        end1 = np.nanmean(roll1[-60:])
        end2 = np.nanmean(roll2[-60:])
        ax.annotate(f'last 1 min avg:\n20-min: {end1:.0f} MB/s\n30-min: {end2:.0f} MB/s',
                    xy=(20, end2), xytext=(11, end2*0.55),
                    fontsize=10, color='black',
                    arrowprops=dict(arrowstyle='->', color='gray'))
        ax.set_title(f'{disk.replace("_", " ").upper()}', fontweight='bold')
        ax.set_xlabel('Time (min)')
        ax.set_ylabel('Read BW (MB/s, 30s rolling)')
        ax.set_xlim(0, 30)
        ax.legend(loc='upper right')
        ax.set_ylim(0, 5000)
    fig.suptitle('Read bandwidth: 20-min vs 30-min sustained KV cache — both drives keep degrading',
                 fontsize=13, fontweight='bold', y=1.02)
    fig.tight_layout()
    fig.savefig(OUT/'07_long_drift_compare.png', bbox_inches='tight')
    plt.close(fig)
    print('✓ 07_long_drift_compare.png')


# Chart 8: Read BW across all 3 test durations (per-disk)
def chart_08_duration_bars():
    fig, ax = plt.subplots(figsize=(11, 6))
    data = {
        'biwin_x570':    {'120s': 3.14, '1200s': 1.92, '1800s': 1.57},
        'seagate_fc530': {'120s': 2.34, '1200s': 1.91, '1800s': 1.54},
        'zhitai_ti600':  {'120s': 2.46, '1200s': 1.01, '900s':  1.16},
        'wd_sn570':      {'120s': 1.55, '1200s': 1.25, '900s':  1.38},
    }
    x = np.arange(len(DISKS))
    width = 0.27
    short = [data[d]['120s'] for d in DISKS]
    med   = [data[d]['1200s'] for d in DISKS]
    long_ = [data[d].get('1800s', data[d].get('900s')) for d in DISKS]

    for i, (vals, label, hatch) in enumerate([
        (short, 'Burst 120 s', ''),
        (med,   '20 min drift', '//'),
        (long_, '30 min drift', '\\\\')]):
        offset = (i - 1) * width
        bars = ax.bar(x + offset, vals, width, label=label,
                      color=[COLOR[d] for d in DISKS], alpha=0.85,
                      edgecolor='black' if hatch else 'none', hatch=hatch)
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f'{h:.2f}', xy=(bar.get_x()+bar.get_width()/2, h),
                        xytext=(0, 3), textcoords='offset points',
                        ha='center', va='bottom', fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels([d.replace('_','\n') for d in DISKS], fontsize=10)
    ax.set_ylabel('Read BW (GB/s, last-1-min average)')
    ax.set_title('Read BW across 3 test durations — long-steady-state reveals continued degradation')
    ax.legend(loc='upper right')
    fig.tight_layout()
    fig.savefig(OUT/'08_duration_bars.png', bbox_inches='tight')
    plt.close(fig)
    print('✓ 08_duration_bars.png')


if __name__ == '__main__':
    chart_07_long_drift_compare()
    chart_08_duration_bars()
    print(f'\nDone. Charts in {OUT}/')