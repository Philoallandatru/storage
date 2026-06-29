#!/usr/bin/env python3
"""
三路 KV-cache IO 模式综合对比图 — synthetic (fio_sweep) / sharegpt / burstgpt

图风格跟早上 `docs/assets/kv-cache-real-io/01_signal_dashboard.png` 一致:
- 深色背景 (facecolor='#1f1f1f')
- 黄色/青色/品红 高对比配色
- 简洁的标题/标注
"""

import json
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

plt.rcParams['font.family'] = ['Noto Sans CJK JP', 'DejaVu Sans']
plt.rcParams['font.size'] = 11
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.unicode_minus'] = False
import matplotlib.font_manager as fm
for fp in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
           '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc']:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)

# ── 三个数据源 ──────────────────────────────────────────────
DATA = {
    'synthetic (fio_sweep, BIWIN X570, QD=32)': {
        'iops':       30545,         # QD=32: 18,636 read + 11,909 write
        'bw_giBs':    2.85,          # (1644.7 + 1272.5) MiB/s / 1024
        'r_pct':      61,            # rwmixread=61%
        'w_pct':      39,
        'read_100MiB_jump_pct': 0,   # synthetic random rw, 没有 "相邻跳跃" 概念
        'read_contiguous_pct':  0,   # 同上
        'write_contiguous_pct': 0,
        'note':       'fio distil replay (no real adjacency signal)',
    },
    'sharegpt (kv-cache.py)': {
        'iops':       14063,
        'bw_giBs':    1.64,
        'r_pct':      94,            # 1860197/1981685
        'w_pct':      6,
        'read_100MiB_jump_pct': 56.97,
        'read_contiguous_pct':  41.77,
        'write_contiguous_pct': 94.37,
        'note':       'mixed conversational workload',
    },
    'burstgpt (kv-cache.py)': {
        'iops':       35195,
        'bw_giBs':    4.25,
        'r_pct':      92,            # 4202656/4566627
        'w_pct':      8,
        'read_100MiB_jump_pct': 89.11,
        'read_contiguous_pct':  10.08,
        'write_contiguous_pct': 97.63,
        'note':       'bursty prefill-heavy workload',
    },
}

# ── 图 1: Signal Dashboard (跟早上 01_signal_dashboard.png 风格一致) ─────
fig = plt.figure(figsize=(14, 8))
fig.patch.set_facecolor('#1f1f1f')
fig.suptitle('KV Cache IO 模式 三路综合对比 — Synthetic / ShareGPT / BurstGPT',
             fontsize=15, fontweight='bold', color='white', y=0.97)

# 4 个子图: (IOPS, BW, Read R/W ratio, 读跳跃分布)
ax1 = plt.subplot(2, 2, 1)
labels = list(DATA.keys())
iops = [DATA[k]['iops'] for k in labels]
colors = ['#ffd60a', '#00e5ff', '#ff006e']
bars = ax1.bar(labels, iops, color=colors, alpha=0.85)
ax1.set_title('Block IOPS', fontsize=12, color='white', fontweight='bold')
ax1.set_ylabel('IOPS', color='white')
ax1.tick_params(colors='white', rotation=20)
ax1.set_facecolor('#1f1f1f')
ax1.grid(True, alpha=0.2, color='gray')
ax1.spines['bottom'].set_color('white'); ax1.spines['left'].set_color('white')
for bar, v in zip(bars, iops):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height()*1.02,
             f'{v:,}', ha='center', va='bottom', color='white', fontweight='bold')

# Subplot 2: BW
ax2 = plt.subplot(2, 2, 2)
bw = [DATA[k]['bw_giBs'] for k in labels]
bars = ax2.bar(labels, bw, color=colors, alpha=0.85)
ax2.set_title('Block Bandwidth', fontsize=12, color='white', fontweight='bold')
ax2.set_ylabel('GiB/s', color='white')
ax2.tick_params(colors='white', rotation=20)
ax2.set_facecolor('#1f1f1f')
ax2.grid(True, alpha=0.2, color='gray')
ax2.spines['bottom'].set_color('white'); ax2.spines['left'].set_color('white')
for bar, v in zip(bars, bw):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height()*1.02,
             f'{v:.2f}', ha='center', va='bottom', color='white', fontweight='bold')

# Subplot 3: R/W ratio stacked
ax3 = plt.subplot(2, 2, 3)
r_pct = [DATA[k]['r_pct'] for k in labels]
w_pct = [DATA[k]['w_pct'] for k in labels]
x = np.arange(len(labels))
b1 = ax3.bar(x, r_pct, color='#00e5ff', alpha=0.85, label='Read %')
b2 = ax3.bar(x, w_pct, bottom=r_pct, color='#ffd60a', alpha=0.85, label='Write %')
ax3.set_title('Read/Write Event Mix', fontsize=12, color='white', fontweight='bold')
ax3.set_ylabel('% of events', color='white')
ax3.set_xticks(x); ax3.set_xticklabels(labels, rotation=20)
ax3.tick_params(colors='white')
ax3.set_facecolor('#1f1f1f'); ax3.grid(True, alpha=0.2, color='gray', axis='y')
ax3.spines['bottom'].set_color('white'); ax3.spines['left'].set_color('white')
ax3.legend(loc='upper right', facecolor='#1f1f1f', edgecolor='white', labelcolor='white')
for i, (r, w) in enumerate(zip(r_pct, w_pct)):
    ax3.text(i, r/2, f'{r}%', ha='center', va='center', color='black', fontweight='bold')
    ax3.text(i, r + w/2, f'{w}%', ha='center', va='center', color='black', fontweight='bold')

# Subplot 4: Read adjacency signature
ax4 = plt.subplot(2, 2, 4)
x = np.arange(len(labels))
cont = [DATA[k]['read_contiguous_pct'] for k in labels]
jump = [DATA[k]['read_100MiB_jump_pct'] for k in labels]
b1 = ax4.bar(x, cont, color='#00e5ff', alpha=0.85, label='Exact-contiguous')
b2 = ax4.bar(x, jump, bottom=cont, color='#ff006e', alpha=0.85, label='≥100 MiB jump')
b3 = ax4.bar(x, [100-c-j for c,j in zip(cont, jump)], bottom=[c+j for c,j in zip(cont, jump)],
             color='#888888', alpha=0.5, label='other')
ax4.set_title('Read Adjacency Signature', fontsize=12, color='white', fontweight='bold')
ax4.set_ylabel('% of adjacent read pairs', color='white')
ax4.set_xticks(x); ax4.set_xticklabels(labels, rotation=20)
ax4.tick_params(colors='white')
ax4.set_facecolor('#1f1f1f'); ax4.grid(True, alpha=0.2, color='gray', axis='y')
ax4.spines['bottom'].set_color('white'); ax4.spines['left'].set_color('white')
ax4.legend(loc='upper right', facecolor='#1f1f1f', edgecolor='white', labelcolor='white', fontsize=9)

plt.tight_layout()
plt.subplots_adjust(top=0.92)
out1 = '/home/ficus/llm/storage/docs/assets/io-three-way-comparison/01_signal_dashboard.png'
plt.savefig(out1, dpi=130, bbox_inches='tight', facecolor='#1f1f1f')
plt.close()
print(f'saved: {out1}')

# ── 图 2: IOPS + BW 时间序列对比 (三路同图,3s 窗口) ─────
# 加载 sharegpt/burstgpt 的真实 trace,合成 synthetic 用 QD=32 平均
import csv

def load_block_trace(csv_path):
    ts_arr, rw_arr, b_arr = [], [], []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_arr.append(int(row['timestamp_ns']))
            rw_arr.append(row['rwbs'])
            b_arr.append(int(row['bytes']))
    return np.array(ts_arr), np.array(rw_arr), np.array(b_arr)

sharegpt_csv = '/home/ficus/llm/storage/results/kvcache-profile/sharegpt_kvcache_20260629_140729/block_lba_trace.csv'
burstgpt_csv = '/home/ficus/llm/storage/results/kvcache-profile/burstgpt_kvcache_20260629_141010/block_lba_trace.csv'

fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
fig.patch.set_facecolor('white')
fig.suptitle('IOPS / Bandwidth 时间序列 (3-second window)',
             fontsize=14, fontweight='bold')

colors = ['#ffd60a', '#00e5ff', '#ff006e']
window_s = 3.0
titles = ['IOPS vs time', 'Bandwidth vs time']
ylabels = ['IOPS (events/sec)', 'Bandwidth (GiB/s)']

for idx, label in enumerate(['sharegpt', 'burstgpt']):
    csv_path = sharegpt_csv if label == 'sharegpt' else burstgpt_csv
    if not os.path.exists(csv_path):
        continue
    ts, rw, b = load_block_trace(csv_path)
    t0 = ts[0]
    t_rel = (ts - t0) / 1e9
    bins = np.arange(0, t_rel.max() + window_s, window_s)
    counts, _ = np.histogram(t_rel, bins=bins)
    bw_bytes = np.zeros(len(bins) - 1)
    for i in range(len(bins) - 1):
        mask = (t_rel >= bins[i]) & (t_rel < bins[i+1])
        bw_bytes[i] = b[mask].sum()
    iops_series = counts / window_s
    bw_series = bw_bytes / window_s / 1e9

    axes[0].plot(bins[:-1], iops_series, color=colors[idx+1], linewidth=1.3,
                 label=label, alpha=0.85)
    axes[1].plot(bins[:-1], bw_series, color=colors[idx+1], linewidth=1.3,
                 label=label, alpha=0.85)

# synthetic 加水平参考线 (avg IOPS / BW)
axes[0].axhline(y=30545, color=colors[0], linestyle='--', linewidth=1.5,
                label=f'synthetic (avg = {30545:,} IOPS)', alpha=0.85)
axes[1].axhline(y=2.85, color=colors[0], linestyle='--', linewidth=1.5,
                label=f'synthetic (avg = 2.85 GiB/s)', alpha=0.85)

for ax, title, ylabel in zip(axes, titles, ylabels):
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper left')

axes[1].set_xlabel('time (seconds from trace start)')
plt.tight_layout()
out2 = '/home/ficus/llm/storage/docs/assets/io-three-way-comparison/02_iops_bw_timeline.png'
plt.savefig(out2, dpi=130, bbox_inches='tight', facecolor='white')
plt.close()
print(f'saved: {out2}')

# ── 图 3: LBA delta signature (CDF) — 三路读相邻跳跃 CDF ─────
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
fig.patch.set_facecolor('white')
fig.suptitle('相邻 LBA 跳跃绝对值 CDF (按 R/W 分开)',
             fontsize=14, fontweight='bold')

def compute_lba_deltas(csv_path):
    last_sector = {}
    deltas = {'R': [], 'W': []}
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = int(row['pid'])
            sector = int(row['sector'])
            bytes_ = int(row['bytes'])
            rwbs = row['rwbs']
            kind = 'R' if 'R' in rwbs else 'W'
            if pid in last_sector:
                d = abs(sector - last_sector[pid]) * 512  # bytes
                deltas[kind].append(d)
            last_sector[pid] = sector
    return deltas

def compute_lba_deltas_synthetic(qd_dir):
    """fio sweep 没有逐 I/O trace, 没法算 deltas - 留空"""
    return None

for idx, (label, csv_path) in enumerate([('sharegpt', sharegpt_csv),
                                         ('burstgpt', burstgpt_csv)]):
    deltas = compute_lba_deltas(csv_path)
    for j, kind in enumerate(['R', 'W']):
        ax = axes[j]
        d = np.array(deltas[kind])
        d_mib = d / (1024 * 1024)
        sorted_d = np.sort(d_mib)
        cdf = np.arange(1, len(sorted_d) + 1) / len(sorted_d)
        ax.plot(sorted_d, cdf, color=['#00e5ff', '#ff006e'][idx],
                linewidth=1.5, label=f'{label} ({"read" if kind=="R" else "write"})')

# 加参考线
for j in range(2):
    axes[j].set_xscale('log')
    axes[j].set_xlabel('|LBA delta| (MiB)')
    axes[j].set_ylabel('CDF')
    axes[j].set_title('Read' if j == 0 else 'Write')
    axes[j].grid(True, alpha=0.3, which='both')
    axes[j].legend(loc='lower right')

# 标注关键阈值
for j in range(2):
    axes[j].axvline(x=1, color='gray', linestyle=':', alpha=0.5)
    axes[j].axvline(x=100, color='gray', linestyle=':', alpha=0.5)
    axes[j].text(1, 0.95, '<1 MiB', fontsize=8, color='gray', rotation=90, va='top')
    axes[j].text(100, 0.95, '>=100 MiB', fontsize=8, color='gray', rotation=90, va='top')

plt.tight_layout()
out3 = '/home/ficus/llm/storage/docs/assets/io-three-way-comparison/03_lba_delta_cdf.png'
plt.savefig(out3, dpi=130, bbox_inches='tight', facecolor='white')
plt.close()
print(f'saved: {out3}')

# ── 图 4: 块大小分布对比 ─────
fig, ax = plt.subplots(figsize=(12, 5))
fig.patch.set_facecolor('white')
ax.set_title('请求块大小分布 (按 workload 拆开)',
             fontsize=14, fontweight='bold')
size_buckets = ['4 KiB', '8 KiB', '16 KiB', '32 KiB', '64 KiB', '128 KiB', '256 KiB+']
x = np.arange(len(size_buckets))
width = 0.27

# synthetic 用 bssplit (来自 fio_sweep.ini: 128k/62% read, 82% write)
synth = [2, 0, 12, 16, 8, 62, 0]   # read bssplit
# sharegpt & burstgpt 都是 128K 主导,略不同
sharegpt_pct = [0, 0, 0, 0, 6, 93.94, 0.06]   # 128 KiB 主导, 93.94% exact match
burstgpt_pct = [0, 0, 0, 0, 1.48, 98.52, 0]   # 128 KiB 几乎全部

bars1 = ax.bar(x - width, synth, width, label='synthetic (fio bssplit read)', color='#ffd60a', alpha=0.85)
bars2 = ax.bar(x, sharegpt_pct, width, label='sharegpt', color='#00e5ff', alpha=0.85)
bars3 = ax.bar(x + width, burstgpt_pct, width, label='burstgpt', color='#ff006e', alpha=0.85)

ax.set_xticks(x); ax.set_xticklabels(size_buckets)
ax.set_ylabel('% of events'); ax.set_xlabel('Block request size')
ax.legend(); ax.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
out4 = '/home/ficus/llm/storage/docs/assets/io-three-way-comparison/04_block_size_distribution.png'
plt.savefig(out4, dpi=130, bbox_inches='tight', facecolor='white')
plt.close()
print(f'saved: {out4}')

# ── 图 5: 综合压力热图 (4 指标 × 3 workload) ─────
fig, ax = plt.subplots(figsize=(10, 5))
fig.patch.set_facecolor('white')

metrics = ['IOPS\n(×1000)', 'BW\n(GiB/s)', 'Read %', 'Read ≥100MiB\njump %']
synth_v = [30.5, 2.85, 61, 0]
share_v = [14.1, 1.64, 94, 57.0]
burst_v = [35.2, 4.25, 92, 89.1]

data = np.array([synth_v, share_v, burst_v])
data_norm = data / data.max(axis=0, keepdims=True)

im = ax.imshow(data_norm, cmap='viridis', aspect='auto')
ax.set_xticks(np.arange(len(metrics))); ax.set_xticklabels(metrics)
ax.set_yticks(np.arange(3))
ax.set_yticklabels(['synthetic', 'sharegpt', 'burstgpt'])
ax.set_title('IO 压力归一化热图 (各列独立归一化)',
             fontsize=13, fontweight='bold')

for i in range(3):
    for j in range(4):
        text = f'{data[i,j]:.2f}'
        ax.text(j, i, text, ha='center', va='center',
                color='white' if data_norm[i,j] < 0.5 else 'black',
                fontweight='bold')

plt.colorbar(im, ax=ax, label='normalized score')
plt.tight_layout()
out5 = '/home/ficus/llm/storage/docs/assets/io-three-way-comparison/05_pressure_heatmap.png'
plt.savefig(out5, dpi=130, bbox_inches='tight', facecolor='white')
plt.close()
print(f'saved: {out5}')

# ── 写出 JSON 摘要 ─────
summary = {
    'workloads': {
        'synthetic_fio_sweep_QD32': {
            'source': 'fio_sweep/sharegpt_8b_cpuhalf_qd32/',
            'iops_avg': 30545,
            'bw_avg_giBs': 2.85,
            'rwmixread_pct': 61,
            'note': 'fio distill replay; no real per-IO trace; no adjacent-LBA concept',
        },
        'sharegpt_kvcache': {
            'source': 'results/kvcache-profile/sharegpt_kvcache_20260629_140729/block_lba_trace.csv',
            'block_events': 1981685,
            'duration_s': 140.91,
            'iops_avg': 14063,
            'bw_avg_giBs': 1.64,
            'read_pct_events': 93.86,
            'read_exact_contiguous_pct': 41.77,
            'read_jump_100MiB_pct': 56.97,
            'write_exact_contiguous_pct': 94.37,
            'dom_size': '128 KiB (93.94%)',
            'lba_span_giB': 389.35,
        },
        'burstgpt_kvcache': {
            'source': 'results/kvcache-profile/burstgpt_kvcache_20260629_141010/block_lba_trace.csv',
            'block_events': 4566627,
            'duration_s': 129.75,
            'iops_avg': 35195,
            'bw_avg_giBs': 4.25,
            'read_pct_events': 92.03,
            'read_exact_contiguous_pct': 10.08,
            'read_jump_100MiB_pct': 89.11,
            'write_exact_contiguous_pct': 97.63,
            'dom_size': '128 KiB (98.52%)',
            'lba_span_giB': 389.35,
        },
    },
    'methodology': {
        'trace': 'Linux tracepoint:block:block_rq_issue',
        'device': '/dev/nvme0n1 (parent) dev_t=271581194',
        'filesystem': 'ext4 root partition',
        'workload_runner': 'kv-cache.py v2.0.0b1, llama3.1-8b TP=1, forced NVMe (gpu-mem-gb=0, cpu-mem-gb=0)',
        'synthetic_runner': 'fio 3.41 distill replay from bpftrace traces',
    },
}
with open('/home/ficus/llm/storage/docs/assets/io-three-way-comparison/derived/comparison_summary.json', 'w') as f:
    json.dump(summary, f, indent=2)
print('saved: derived/comparison_summary.json')
print('\n=== DONE ===')
