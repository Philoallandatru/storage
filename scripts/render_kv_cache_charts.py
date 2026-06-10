#!/usr/bin/env python3
"""
Generate presentation-quality matplotlib charts for KV cache cross-vendor benchmark.

Charts produced:
  1. <out>/01_k4_k5_bw_compare.png     - read BW (GB/s) 4-disk, K5+K4 short + K4 GC drift
  2. <out>/02_k4_gc_p99_drift.png      - read P99 latency drift over time (rolling 30s)
  3. <out>/03_cliff_detection.png      - read BW time series with cliff markers
  4. <out>/04_io_pattern_boxplots.png  - request size + await boxplots per disk
  5. <out>/05_summary_ranking.png      - multi-metric ranking heatmap
  6. <out>/06_write_p99_drift.png      - write P99 drift (most damning metric)

All charts share style: seaborn-darkgrid, fontsize 11, 16:9 aspect.
"""
import os, sys, json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')   # no display
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '/home/ficus/llm/storage/scripts')
from analyze_kv_cache_iostat import parse_iostat, DEV_FOR_DISK, quartile_stats

# ---------- config ----------
BASE = Path('/home/ficus/llm/storage/results/cross_vendor')
OUT = Path('/home/ficus/llm/storage/docs/assets/charts')
OUT.mkdir(parents=True, exist_ok=True)

DISKS = ['biwin_x570', 'seagate_fc530', 'zhitai_ti600', 'wd_sn570']
DISK_LABEL = {
    'biwin_x570':    'Biwin X570\n(mainstream)',
    'seagate_fc530': 'Seagate FC530\n(high-end)',
    'zhitai_ti600':  'ZhiTai Ti600\n(YMTC NAND)',
    'wd_sn570':      'WD SN570\n(DRAM-less)',
}
COLOR = {
    'biwin_x570':    '#2ca02c',  # green
    'seagate_fc530': '#ffbb33',  # amber/gold
    'zhitai_ti600':  '#d62728',  # red
    'wd_sn570':      '#1f77b4',  # blue
}

plt.rcParams.update({
    'figure.dpi': 110,
    'savefig.dpi': 150,
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.labelsize': 11,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'legend.frameon': False,
    'figure.facecolor': 'white',
})
plt.style.use('seaborn-v0_8-darkgrid')


# ---------- helpers ----------
def load_kv_summary(variant_dir, scenario):
    """Return dict[disk] -> cache_stats dict."""
    out = {}
    for d in DISKS:
        p = BASE / variant_dir / d / scenario / 'kv_cache_summary.json'
        if not p.exists(): continue
        with open(p) as f:
            out[d] = json.load(f)['summary']['cache_stats']
    return out

def rolling(samples, key, window=30):
    vals = [s[key] for s in samples]
    n = len(vals)
    out = np.full(n, np.nan)
    for i in range(window-1, n):
        out[i] = np.mean(vals[i-window+1:i+1])
    return out


# =====================================================================
# Chart 1: K4/K5 read BW + GC drift side-by-side bar chart
# =====================================================================
def chart_01_k4_k5_bw():
    short = load_kv_summary('kv_cache_k4_only', 'K4_16u_llama3.1-8b_120s')
    burst = load_kv_summary('kv_cache_k5_only', 'K5_4u_llama3.1-70b-instruct_180s')
    drift = load_kv_summary('kv_cache_k4_gc_drift', 'K4_16u_llama3.1-8b_1200s')

    fig, ax = plt.subplots(figsize=(11, 6))
    x = np.arange(len(DISKS))
    width = 0.27

    bw_short = [short.get(d, {}).get('tier_storage_read_bandwidth_gbps', 0) for d in DISKS]
    bw_burst = [burst.get(d, {}).get('tier_storage_read_bandwidth_gbps', 0) for d in DISKS]
    bw_drift = [drift.get(d, {}).get('tier_storage_read_bandwidth_gbps', 0) for d in DISKS]

    b1 = ax.bar(x - width, bw_burst, width, label='K5 70B burst (180 s)', color='#7f7f7f', alpha=0.85)
    b2 = ax.bar(x,         bw_short, width, label='K4 8B burst (120 s)',  color=[COLOR[d] for d in DISKS])
    b3 = ax.bar(x + width, bw_drift, width, label='K4 8B GC drift (1200 s)', color=[COLOR[d] for d in DISKS], alpha=0.55, edgecolor='black', linewidth=1.5, hatch='//')

    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f'{h:.1f}', xy=(bar.get_x()+bar.get_width()/2, h),
                        xytext=(0, 3), textcoords='offset points',
                        ha='center', va='bottom', fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels([DISK_LABEL[d] for d in DISKS])
    ax.set_ylabel('Read bandwidth (GB/s)')
    ax.set_title('KV cache read bandwidth — three test scenarios, four NVMe SSDs')
    ax.legend(loc='upper right')
    ax.set_ylim(0, max(bw_burst)*1.15)
    fig.tight_layout()
    fig.savefig(OUT/'01_k4_k5_bw_compare.png')
    plt.close(fig)
    print('✓ 01_k4_k5_bw_compare.png')


# =====================================================================
# Chart 2: read P99 latency over time (rolling 30s)
# =====================================================================
def chart_02_p99_drift():
    fig, ax = plt.subplots(figsize=(11, 6))
    for d in DISKS:
        p = BASE/'kv_cache_k4_gc_drift'/d/'K4_16u_llama3.1-8b_1200s'/'iostat.txt'
        s = parse_iostat(p, DEV_FOR_DISK[d])
        if not s: continue
        # use device-side + queue:  r_await is device only.
        # We want end-to-end read latency (r_await + queue time = r_await*aqu_sz/r_s approximation)
        # Easier: use kv_cache_summary storage_read_p99 timeline? We only have summary stats per run.
        # So plot mean read latency (r_await) over time as a proxy for tail drift
        r_lat = np.array([x['r_await'] for x in s])
        r_roll = pd_series_rolling(r_lat, 60)
        ax.plot(np.arange(len(r_roll))/60, r_roll, label=DISK_LABEL[d].split('\n')[0],
                color=COLOR[d], linewidth=2)

    ax.set_xlabel('Time (minutes)')
    ax.set_ylabel('Mean read service time r_await (ms)\n[60 s rolling average]')
    ax.set_title('Read latency over time — long-steady-state KV cache run')
    ax.legend(loc='upper left')
    ax.set_xlim(0, 20)
    fig.tight_layout()
    fig.savefig(OUT/'02_k4_gc_p99_drift.png')
    plt.close(fig)
    print('✓ 02_k4_gc_p99_drift.png')

def pd_series_rolling(arr, window):
    """Simple rolling mean without pandas."""
    out = np.full_like(arr, np.nan, dtype=float)
    csum = np.cumsum(np.insert(arr, 0, 0.0))
    out[window-1:] = (csum[window:] - csum[:-window]) / window
    return out


# =====================================================================
# Chart 3: Cliff detection — read BW time series w/ markers
# =====================================================================
def chart_03_cliff():
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True, sharey=False)
    for ax, d in zip(axes.flat, DISKS):
        p = BASE/'kv_cache_k4_gc_drift'/d/'K4_16u_llama3.1-8b_1200s'/'iostat.txt'
        s = parse_iostat(p, DEV_FOR_DISK[d])
        if not s: continue
        r_mb = np.array([x['r_mbs'] for x in s])
        t = np.arange(len(r_mb)) / 60
        ax.plot(t, r_mb, color=COLOR[d], alpha=0.4, linewidth=0.7, label='_raw_')
        # 30s rolling
        roll = pd_series_rolling(r_mb, 30)
        ax.plot(t, roll, color=COLOR[d], linewidth=2, label='30 s mean')
        # Cliff detection: find first sustained 20% drop from peak (after 120s warmup)
        peak_idx = 120 + np.argmax(roll[120:-30])
        peak_v = roll[peak_idx]
        thresh = peak_v * 0.8
        after = np.where(roll[peak_idx:] < thresh)[0]
        if len(after):
            cliff_t = (peak_idx + after[0]) / 60
            ax.axvline(cliff_t, color='red', linestyle='--', linewidth=1.5, label=f'cliff ~{cliff_t:.1f} min')
            ax.axhline(peak_v, color='gray', linestyle=':', linewidth=1)
            ax.text(0.5, 0.92, f'peak {peak_v:.0f} MB/s', transform=ax.transAxes, fontsize=9, color='gray')
        ax.set_title(DISK_LABEL[d], color=COLOR[d], fontweight='bold')
        ax.set_xlabel('Time (min)')
        ax.set_ylabel('Read BW (MB/s)')
        ax.set_xlim(0, 20)
        ax.set_ylim(0, None)
    fig.suptitle('Read bandwidth over 20 min — GC cliff detection per disk', fontsize=14, fontweight='bold', y=1.0)
    fig.tight_layout()
    fig.savefig(OUT/'03_cliff_detection.png', bbox_inches='tight')
    plt.close(fig)
    print('✓ 03_cliff_detection.png')


# =====================================================================
# Chart 4: IO pattern boxplots (request size + await)
# =====================================================================
def chart_04_io_pattern():
    fig, axes = plt.subplots(1, 4, figsize=(15, 5.5))
    metrics = [
        ('rareq_sz', 'Read req size\n(kB)', axes[0]),
        ('wareq_sz', 'Write req size\n(kB)', axes[1]),
        ('r_await',  'Read service time\nr_await (ms)', axes[2]),
        ('w_await',  'Write service time\nw_await (ms, log)', axes[3]),
    ]
    for key, label, ax in metrics:
        data = []
        labels = []
        for d in DISKS:
            p = BASE/'kv_cache_k4_gc_drift'/d/'K4_16u_llama3.1-8b_1200s'/'iostat.txt'
            s = parse_iostat(p, DEV_FOR_DISK[d])
            vals = [x[key] for x in s if x[key] > 0]
            data.append(vals)
            labels.append(DISK_LABEL[d].split('\n')[0])
        bp = ax.boxplot(data, labels=labels, patch_artist=True, showfliers=False,
                        medianprops={'color':'black','linewidth':2})
        for patch, d in zip(bp['boxes'], DISKS):
            patch.set_facecolor(COLOR[d])
            patch.set_alpha(0.6)
        ax.set_title(label)
        ax.tick_params(axis='x', rotation=20)
        if key == 'w_await':
            ax.set_yscale('log')
    fig.suptitle('IO pattern characterization — KV cache 8B × 16u × 1200 s', fontsize=13, fontweight='bold', y=1.02)
    fig.tight_layout()
    fig.savefig(OUT/'04_io_pattern_boxplots.png', bbox_inches='tight')
    plt.close(fig)
    print('✓ 04_io_pattern_boxplots.png')


# =====================================================================
# Chart 5: Multi-metric ranking heatmap
# =====================================================================
def chart_05_ranking():
    drift = load_kv_summary('kv_cache_k4_gc_drift', 'K4_16u_llama3.1-8b_1200s')

    metrics = [
        ('Read BW (GB/s)',     'tier_storage_read_bandwidth_gbps', False),  # higher better
        ('Entries served',     'storage_entries',                   False),
        ('Read P99 (ms)',      'storage_read_p99_ms',               True),   # lower better
        ('Read P999 (ms)',     'storage_read_p999_ms',              True),
        ('Write P99 (ms)',     'storage_write_p99_ms',              True),
        ('Read P50 (ms)',      'storage_read_p50_ms',               True),
    ]
    fig, ax = plt.subplots(figsize=(10, 5))
    matrix = np.zeros((len(DISKS), len(metrics)))
    for j, (_, key, _) in enumerate(metrics):
        for i, d in enumerate(DISKS):
            matrix[i, j] = drift.get(d, {}).get(key, np.nan)
    # Normalize each column to 0..1 (1 = best)
    normed = np.zeros_like(matrix)
    for j, (_, _, lower_better) in enumerate(metrics):
        col = matrix[:, j]
        if np.all(np.isnan(col)):
            continue
        vmin, vmax = np.nanmin(col), np.nanmax(col)
        rng = vmax - vmin if vmax > vmin else 1
        for i in range(len(DISKS)):
            if lower_better:
                normed[i, j] = 1 - (col[i] - vmin) / rng
            else:
                normed[i, j] = (col[i] - vmin) / rng
    im = ax.imshow(normed, cmap='RdYlGn', aspect='auto', vmin=0, vmax=1)
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels([m[0] for m in metrics], rotation=25, ha='right')
    ax.set_yticks(range(len(DISKS)))
    ax.set_yticklabels([DISK_LABEL[d].split('\n')[0] for d in DISKS])
    # Annotate
    for i in range(len(DISKS)):
        for j in range(len(metrics)):
            ax.text(j, i, f'{matrix[i,j]:.0f}' if matrix[i,j] > 10 else f'{matrix[i,j]:.2f}',
                    ha='center', va='center', fontsize=9, color='black')
    ax.set_title('Multi-metric ranking — K4 GC drift (long-steady-state)\nGreen = best, Red = worst')
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.04)
    cb.set_label('Normalized score (1 = best)')
    fig.tight_layout()
    fig.savefig(OUT/'05_summary_ranking.png', bbox_inches='tight')
    plt.close(fig)
    print('✓ 05_summary_ranking.png')


# =====================================================================
# Chart 6: Write P99 drift over time (rolling 60s mean)
# =====================================================================
def chart_06_write_drift():
    fig, ax = plt.subplots(figsize=(11, 6))
    for d in DISKS:
        p = BASE/'kv_cache_k4_gc_drift'/d/'K4_16u_llama3.1-8b_1200s'/'iostat.txt'
        s = parse_iostat(p, DEV_FOR_DISK[d])
        if not s: continue
        w_lat = np.array([x['w_await'] for x in s])
        roll = pd_series_rolling(w_lat, 60)
        ax.plot(np.arange(len(roll))/60, roll, label=DISK_LABEL[d].split('\n')[0],
                color=COLOR[d], linewidth=2)
    ax.set_yscale('log')
    ax.set_xlabel('Time (minutes)')
    ax.set_ylabel('Mean write service time w_await (ms, log scale)\n[60 s rolling average]')
    ax.set_title('Write latency drift — 20 min sustained KV cache')
    ax.legend(loc='lower right')
    ax.set_xlim(0, 20)
    fig.tight_layout()
    fig.savefig(OUT/'06_write_p99_drift.png')
    plt.close(fig)
    print('✓ 06_write_p99_drift.png')


# =====================================================================
if __name__ == '__main__':
    chart_01_k4_k5_bw()
    chart_02_p99_drift()
    chart_03_cliff()
    chart_04_io_pattern()
    chart_05_ranking()
    chart_06_write_drift()
    print(f'\nAll charts saved to {OUT}/')