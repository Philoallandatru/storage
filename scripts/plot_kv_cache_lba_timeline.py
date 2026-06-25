#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plot_kv_cache_lba_timeline.py
==============================

设备端 LBA 时间序列分析 — 把 bpftrace 的 `@d[dev, sector]: ts` 还原成"按时间排序的访问序列",
量化设备层 IO 是顺序 vs 随机,以及随时间如何变化。

数据源
------
bpftrace_sharegpt_*.txt 里 `@d[dev, sector]: timestamp_ns` 格式:
    @d[271581194, 1433281280]: 3831793992320
含义: (dev_id, sector) 位置最后一次被访问的时间戳(纳秒)。

**重要限制**: `@d[]` 是 bpftrace 的 dedup histogram — 同一个 LBA 位置只保留最后一次访问。
所以本分析看到的是"最近访问时间序列",而不是完整的 per-IO log。
但即使这样,仍然可以量化:
- LBA 跳跃距离分布 (gap)
- 顺序 vs 随机比例
- LBA 访问范围随时间的演变
- 顺序流长度分布

输出图 (4 张):
  1. lba_timeline_scatter.png  — (时间, LBA) 散点 + 直方图
  2. lba_timeline_sequentiality.png  — LBA gap CDF + 顺序率分时窗
  3. lba_timeline_runs.png  — 顺序流长度分布 + Forward/Backward 直方图
  4. lba_timeline_window_coverage.png  — 滑动窗口下 LBA range 变化

Usage:
    python3 scripts/plot_kv_cache_lba_timeline.py \
        --bpftrace results/kvcache-profile/bpftrace_sharegpt_8b_tp8_cpu0p5g_users2_300s_profile_20260608_014520.txt \
        --out results/kvcache-profile/lba_timeline/
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

# 中文字体 (强制指定 ttf 路径)
from matplotlib import font_manager as fm
import os
cjk_font_path = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
if os.path.exists(cjk_font_path):
    fm.fontManager.addfont(cjk_font_path)
    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'Noto Sans CJK JP', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def parse_bpftrace_lba(bpftrace_path: str) -> list:
    """解析 bpftrace 文件, 提取 @d[dev, sector]: ts 行."""
    events = []
    pattern = re.compile(r'@d\[(\d+),\s*(\d+)\]:\s*(\d+)')
    with open(bpftrace_path) as fp:
        for line in fp:
            m = pattern.match(line.strip())
            if m:
                dev = int(m.group(1))
                sector = int(m.group(2))
                ts_ns = int(m.group(3))
                events.append({
                    'dev': dev,
                    'sector': sector,
                    'sector_bytes': sector * 512,
                    'lba_gb': sector * 512 / 1024 / 1024 / 1024,
                    'ts_ns': ts_ns,
                })
    if not events:
        raise RuntimeError(f"未在 {bpftrace_path} 找到 @d[...] 行")

    events.sort(key=lambda x: x['ts_ns'])
    t0 = events[0]['ts_ns']
    for ev in events:
        ev['t_s'] = (ev['ts_ns'] - t0) / 1e9
    return events


def compute_gaps(events: list) -> tuple:
    """算 LBA gap (按时间顺序的相邻 LBA 差) + 时间间隔."""
    abs_gaps_bytes = []
    signed_diffs_gb = []
    time_deltas_ms = []
    for i in range(1, len(events)):
        gap = abs(events[i]['sector'] - events[i-1]['sector']) * 512
        abs_gaps_bytes.append(gap)
        signed_diff = (events[i]['sector'] - events[i-1]['sector']) * 512 / 1024 / 1024 / 1024
        signed_diffs_gb.append(signed_diff)
        dt_ms = (events[i]['ts_ns'] - events[i-1]['ts_ns']) / 1e6
        time_deltas_ms.append(dt_ms)
    return abs_gaps_bytes, signed_diffs_gb, time_deltas_ms


def find_directional_runs(signed_diffs_gb: list) -> list:
    """找连续同方向的访问 run.
    返回: [(direction, run_length), ...]
    direction: +1 (forward, LBA 递增), -1 (backward, LBA 递减)
    """
    if not signed_diffs_gb:
        return []
    runs = []
    direction = 1 if signed_diffs_gb[0] > 0 else -1
    run_len = 1
    for d in signed_diffs_gb[1:]:
        if d == 0:
            continue  # 跳过同位置 (dedup 限制下应该 0 个)
        cur_dir = 1 if d > 0 else -1
        if cur_dir == direction:
            run_len += 1
        else:
            runs.append((direction, run_len))
            direction = cur_dir
            run_len = 1
    runs.append((direction, run_len))
    return runs


def plot_timeline_scatter(events: list, out_dir: str):
    """图 1: LBA 时间序列散点 + 直方图"""
    fig = plt.figure(figsize=(14, 9))
    gs = gridspec.GridSpec(2, 2, height_ratios=[1, 1.5], width_ratios=[3, 1])

    # 顶部: LBA 直方图 (按时间分 50 桶)
    ax_hist = fig.add_subplot(gs[0, 0])
    times = np.array([e['t_s'] for e in events])
    lbas = np.array([e['lba_gb'] for e in events])

    # 按时间画颜色梯度
    scatter = ax_hist.scatter(times, lbas, c=times, cmap='plasma', s=8, alpha=0.7, edgecolors='none')
    ax_hist.set_xlabel('时间 (秒)', fontsize=11)
    ax_hist.set_ylabel('LBA (GB)', fontsize=11)
    ax_hist.set_title(f'设备端 LBA 时间序列 (n={len(events)}, dedup heatmap, 同一 (dev, sector) 仅记最新)',
                     fontsize=12, weight='bold')
    ax_hist.grid(True, alpha=0.3)
    plt.colorbar(scatter, ax=ax_hist, label='时间 (秒)', fraction=0.04)

    # 右侧: LBA 位置直方图
    ax_rh = fig.add_subplot(gs[0, 1])
    ax_rh.hist(lbas, bins=30, orientation='horizontal', color='steelblue', edgecolor='white')
    ax_rh.set_xlabel('频次', fontsize=10)
    ax_rh.set_ylabel('')
    ax_rh.set_title('LBA 分布', fontsize=10)

    # 底部: 滑动 10 秒窗口的 LBA range
    ax_cov = fig.add_subplot(gs[1, :])
    window = 10.0
    step = 5.0
    window_starts = np.arange(0, max(times) - window, step)
    mins = []
    maxs = []
    centers = []
    for ws in window_starts:
        in_win = [(t, l) for t, l in zip(times, lbas) if ws <= t < ws + window]
        if in_win:
            t_w, l_w = zip(*in_win)
            mins.append(min(l_w))
            maxs.append(max(l_w))
            centers.append(ws + window/2)
    mins = np.array(mins)
    maxs = np.array(maxs)
    centers = np.array(centers)

    ax_cov.fill_between(centers, mins, maxs, alpha=0.4, color='coral', label='LBA range')
    ax_cov.plot(centers, mins, 'b-', lw=1, label='min LBA')
    ax_cov.plot(centers, maxs, 'r-', lw=1, label='max LBA')
    ax_cov.set_xlabel('时间 (秒)', fontsize=11)
    ax_cov.set_ylabel('LBA (GB)', fontsize=11)
    ax_cov.set_title(f'滑动窗口 ({int(window)}s) LBA range 演变 — 是否存在"扫描模式"?', fontsize=12, weight='bold')
    ax_cov.grid(True, alpha=0.3)
    ax_cov.legend(loc='upper right')

    plt.tight_layout()
    out_path = os.path.join(out_dir, 'lba_timeline_scatter.png')
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  ✅ {out_path}")
    return mins, maxs, centers


def plot_sequentiality(abs_gaps_bytes: list, signed_diffs_gb: list, out_dir: str):
    """图 2: LBA gap CDF + 顺序率随时间变化"""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # 左: CDF (log scale)
    gaps_mb = np.array([g/1024/1024 for g in abs_gaps_bytes])
    sorted_gaps = np.sort(gaps_mb)
    cdf_y = np.arange(1, len(sorted_gaps) + 1) / len(sorted_gaps)
    ax = axes[0]
    ax.plot(sorted_gaps, cdf_y, 'b-', lw=2)
    ax.set_xscale('log')
    ax.set_xlabel('LBA gap (MB, log scale)', fontsize=11)
    ax.set_ylabel('CDF', fontsize=11)
    ax.set_title('LBA 跳跃距离 CDF', fontsize=12, weight='bold')
    ax.grid(True, alpha=0.3, which='both')
    # 标注 1MB 阈值
    ax.axvline(1, color='red', ls='--', alpha=0.7, label='1 MB 顺序阈值')
    ax.axvline(10, color='orange', ls='--', alpha=0.7, label='10 MB')
    ax.axvline(100, color='purple', ls='--', alpha=0.7, label='100 MB')
    # 计算顺序比例
    seq_1mb = (gaps_mb < 1).sum() / len(gaps_mb) * 100
    seq_10mb = (gaps_mb < 10).sum() / len(gaps_mb) * 100
    seq_100mb = (gaps_mb < 100).sum() / len(gaps_mb) * 100
    ax.text(0.95, 0.05,
            f'gap < 1 MB:   {seq_1mb:.1f}%\n'
            f'gap < 10 MB:  {seq_10mb:.1f}%\n'
            f'gap < 100 MB: {seq_100mb:.1f}%\n'
            f'gap ≥ 100 MB: {100-seq_100mb:.1f}% (随机跳跃)',
            transform=ax.transAxes, ha='right', va='bottom',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            fontsize=10, family='monospace')
    ax.legend(loc='upper left', fontsize=9)

    # 中: Direction 分布 (绝对值 log 直方图 + 方向比例)
    ax = axes[1]
    abs_diffs_gb = [abs(d) for d in signed_diffs_gb if d != 0]
    # 用 log bins 让大部分小 gap 也能看见
    log_bins = np.logspace(np.log10(0.001), np.log10(max(abs_diffs_gb)+1), 60)
    ax.hist(abs_diffs_gb, bins=log_bins, color='steelblue', edgecolor='white', alpha=0.8)
    ax.set_xscale('log')
    ax.set_xlabel('|LBA 差| (GB, log scale)', fontsize=11)
    ax.set_ylabel('频次', fontsize=11)
    ax.set_title('LBA 跳跃绝对值分布\n(不管方向, 看跳跃距离)', fontsize=12, weight='bold')
    ax.grid(True, alpha=0.3, which='both')
    n_forward = sum(1 for d in signed_diffs_gb if d > 0)
    n_backward = sum(1 for d in signed_diffs_gb if d < 0)
    ax.text(0.95, 0.95,
            f'Forward (LBA↑): {n_forward} ({n_forward/len(signed_diffs_gb)*100:.1f}%)\n'
            f'Backward (LBA↓): {n_backward} ({n_backward/len(signed_diffs_gb)*100:.1f}%)\n\n'
            f'中位 |gap|: {np.median(abs_diffs_gb):.2f} GB\n'
            f'p95 |gap|: {np.percentile(abs_diffs_gb, 95):.1f} GB',
            transform=ax.transAxes, ha='right', va='top',
            bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8),
            fontsize=10, family='monospace')

    # 右: 顺序率随时间 (10s 窗口)
    ax = axes[2]
    # 重新计算每个窗口的顺序率
    events = json.load(open(os.path.join(os.path.dirname(out_dir), 'lba_events.json'))) if os.path.exists(os.path.join(os.path.dirname(out_dir), 'lba_events.json')) else None
    if events is None:
        # 从 saved file 直接读
        events_path = os.path.join(out_dir, '..', 'lba_timeline', 'lba_events.json')
        if not os.path.exists(events_path):
            events_path = '/home/ficus/llm/storage/results/kvcache-profile/lba_timeline/lba_events.json'
        with open(events_path) as fp:
            events = json.load(fp)
    events.sort(key=lambda x: x['ts_ns'])
    t0 = events[0]['ts_ns']
    for ev in events:
        ev['t_s'] = (ev['ts_ns'] - t0) / 1e9

    window = 30.0
    step = 10.0
    centers = []
    seq_rates = []
    for ws in np.arange(0, max(e['t_s'] for e in events) - window, step):
        in_win = [ev for ev in events if ws <= ev['t_s'] < ws + window]
        if len(in_win) >= 2:
            in_win_sectors = [ev['sector'] for ev in in_win]
            gaps = [abs(in_win_sectors[i] - in_win_sectors[i-1]) * 512 for i in range(1, len(in_win_sectors))]
            gaps_mb = [g/1024/1024 for g in gaps]
            seq_rate = sum(1 for g in gaps_mb if g < 1) / len(gaps_mb) * 100
            centers.append(ws + window/2)
            seq_rates.append(seq_rate)

    ax.plot(centers, seq_rates, 'o-', color='darkgreen', lw=1.5, markersize=4)
    ax.set_xlabel('时间 (秒)', fontsize=11)
    ax.set_ylabel(f'顺序率 (%) [gap < 1 MB]', fontsize=11)
    ax.set_title(f'滑动窗口 ({int(window)}s) 顺序率变化', fontsize=12, weight='bold')
    ax.grid(True, alpha=0.3)
    ax.set_ylim(-5, 105)
    ax.axhline(50, color='gray', ls=':', alpha=0.5)
    # 平均
    if seq_rates:
        avg_seq = np.mean(seq_rates)
        ax.axhline(avg_seq, color='red', ls='--', alpha=0.7, label=f'平均 {avg_seq:.1f}%')
        ax.legend(loc='upper right')

    plt.tight_layout()
    out_path = os.path.join(out_dir, 'lba_timeline_sequentiality.png')
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  ✅ {out_path}")


def plot_runs(events: list, signed_diffs_gb: list, out_dir: str):
    """图 3: 顺序流长度分布"""
    runs = find_directional_runs(signed_diffs_gb)
    forward_runs = [r[1] for r in runs if r[0] == 1]
    backward_runs = [r[1] for r in runs if r[0] == -1]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # 左: Run length 直方图 (分开 forward/backward)
    ax = axes[0]
    max_len = max(max(forward_runs) if forward_runs else 0,
                  max(backward_runs) if backward_runs else 0)
    bins = np.arange(1, max_len + 2) - 0.5
    ax.hist([forward_runs, backward_runs], bins=bins, label=['Forward runs', 'Backward runs'],
            color=['steelblue', 'coral'], edgecolor='white', alpha=0.8)
    ax.set_xlabel('Run length (连续同方向事件数)', fontsize=11)
    ax.set_ylabel('Run 数量', fontsize=11)
    ax.set_title('顺序流长度分布', fontsize=12, weight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 中: Forward run length CDF
    ax = axes[1]
    if forward_runs:
        sorted_fr = np.sort(forward_runs)
        cdf = np.arange(1, len(sorted_fr) + 1) / len(sorted_fr)
        ax.plot(sorted_fr, cdf, 'b-', lw=2, label=f'Forward (n={len(forward_runs)})')
    if backward_runs:
        sorted_br = np.sort(backward_runs)
        cdf = np.arange(1, len(sorted_br) + 1) / len(sorted_br)
        ax.plot(sorted_br, cdf, 'r-', lw=2, label=f'Backward (n={len(backward_runs)})')
    ax.set_xlabel('Run length', fontsize=11)
    ax.set_ylabel('CDF', fontsize=11)
    ax.set_title('Run 长度 CDF\nForward: 平均扫描多长?', fontsize=12, weight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend()
    if forward_runs:
        ax.axvline(np.mean(forward_runs), color='blue', ls='--', alpha=0.7,
                   label=f'Forward mean {np.mean(forward_runs):.1f}')
    if backward_runs:
        ax.axvline(np.mean(backward_runs), color='red', ls='--', alpha=0.7,
                   label=f'Backward mean {np.mean(backward_runs):.1f}')
    ax.legend(loc='lower right')

    # 右: Time series of LBA with run coloring
    ax = axes[2]
    times = [e['t_s'] for e in events]
    lbas = [e['lba_gb'] for e in events]
    ax.plot(times, lbas, 'k-', lw=0.3, alpha=0.3)
    # 用颜色画 run 段
    idx = 0
    cmap = plt.cm.tab10
    for i, (direction, run_len) in enumerate(runs):
        if idx + run_len <= len(times) - 1:
            x = times[idx:idx+run_len+1]
            y = lbas[idx:idx+run_len+1]
            color = 'steelblue' if direction == 1 else 'coral'
            ax.plot(x, y, '-', lw=1.5, color=color, alpha=0.8)
        idx += run_len
    # 散点叠加
    ax.scatter(times, lbas, c='black', s=3, alpha=0.5, zorder=5)
    ax.set_xlabel('时间 (秒)', fontsize=11)
    ax.set_ylabel('LBA (GB)', fontsize=11)
    ax.set_title(f'LBA 时间序列按 run 上色\n蓝=Forward (LBA↑), 红=Backward (LBA↓)', fontsize=12, weight='bold')
    ax.grid(True, alpha=0.3)
    # 自定义 legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color='steelblue', lw=2, label=f'Forward run ({len(forward_runs)} 条, 平均 {np.mean(forward_runs):.1f} events)'),
        Line2D([0], [0], color='coral', lw=2, label=f'Backward run ({len(backward_runs)} 条, 平均 {np.mean(backward_runs):.1f} events)'),
    ]
    ax.legend(handles=legend_elements, loc='upper left')

    plt.tight_layout()
    out_path = os.path.join(out_dir, 'lba_timeline_runs.png')
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  ✅ {out_path}")


def plot_window_coverage(events: list, out_dir: str):
    """图 4: 滑动窗口覆盖率分析 (无重叠)
    不同窗口大小下, 平均访问多少 GB 的 LBA 范围"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    times = np.array([e['t_s'] for e in events])
    lbas = np.array([e['lba_gb'] for e in events])
    max_t = times.max()

    # 左: 不同窗口大小的 coverage
    ax = axes[0]
    window_sizes = [1, 5, 10, 30, 60, 120, 300]
    avg_ranges = []
    std_ranges = []
    for ws in window_sizes:
        ranges = []
        for start in np.arange(0, max_t - ws, ws):
            in_win = lbas[(times >= start) & (times < start + ws)]
            if len(in_win) >= 2:
                ranges.append(in_win.max() - in_win.min())
        if ranges:
            avg_ranges.append(np.mean(ranges))
            std_ranges.append(np.std(ranges))
        else:
            avg_ranges.append(0)
            std_ranges.append(0)

    ax.errorbar(window_sizes, avg_ranges, yerr=std_ranges, fmt='o-', lw=2, capsize=5,
                color='steelblue', markersize=8)
    ax.set_xscale('log')
    ax.set_xlabel('窗口大小 (秒, log)', fontsize=11)
    ax.set_ylabel('LBA range (GB)', fontsize=11)
    ax.set_title('不同时间窗口下设备 LBA 覆盖范围', fontsize=12, weight='bold')
    ax.grid(True, alpha=0.3, which='both')
    # 标注总设备大小
    ax.axhline(lbas.max() - lbas.min(), color='red', ls='--', alpha=0.5,
               label=f'总 LBA range = {lbas.max()-lbas.min():.0f} GB')
    ax.legend()

    # 右: LBA min/max 累积 (从开始到现在扫到过哪些 LBA)
    ax = axes[1]
    sort_idx = np.argsort(times)
    sorted_times = times[sort_idx]
    sorted_lbas = lbas[sort_idx]
    cum_min = np.minimum.accumulate(sorted_lbas)
    cum_max = np.maximum.accumulate(sorted_lbas)
    ax.fill_between(sorted_times, cum_min, cum_max, alpha=0.4, color='steelblue',
                    label='累计访问过的 LBA 范围')
    ax.plot(sorted_times, cum_min, 'b-', lw=1)
    ax.plot(sorted_times, cum_max, 'r-', lw=1)
    ax.scatter(sorted_times, sorted_lbas, c='black', s=2, alpha=0.5, label='每次访问')
    ax.set_xlabel('时间 (秒)', fontsize=11)
    ax.set_ylabel('LBA (GB)', fontsize=11)
    ax.set_title('LBA 累积覆盖范围\n(到达当前时间为止, 设备访问过哪些区域)', fontsize=12, weight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend()

    plt.tight_layout()
    out_path = os.path.join(out_dir, 'lba_timeline_window_coverage.png')
    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  ✅ {out_path}")


def write_summary(events, abs_gaps_bytes, signed_diffs_gb, out_dir):
    """写 JSON 总结 + 文本报告"""
    runs = find_directional_runs(signed_diffs_gb)
    forward_runs = [r[1] for r in runs if r[0] == 1]
    backward_runs = [r[1] for r in runs if r[0] == -1]
    gaps_mb = [g/1024/1024 for g in abs_gaps_bytes]

    summary = {
        "data_source": "bpftrace @d[dev, sector]: timestamp_ns",
        "dedup_warning": "同一 (dev, sector) 仅记最新访问, 不是 per-IO log",
        "n_events": len(events),
        "time_range_s": events[-1]['t_s'] - events[0]['t_s'],
        "lba_min_gb": min(e['lba_gb'] for e in events),
        "lba_max_gb": max(e['lba_gb'] for e in events),
        "lba_total_range_gb": max(e['lba_gb'] for e in events) - min(e['lba_gb'] for e in events),
        "gap_distribution_mb": {
            "min": min(gaps_mb),
            "median": float(np.median(gaps_mb)),
            "mean": float(np.mean(gaps_mb)),
            "p95": float(np.percentile(gaps_mb, 95)),
            "p99": float(np.percentile(gaps_mb, 99)),
            "max": max(gaps_mb),
        },
        "sequential_rate_by_threshold": {
            "gap_lt_1mb_pct": float(sum(1 for g in gaps_mb if g < 1) / len(gaps_mb) * 100),
            "gap_lt_10mb_pct": float(sum(1 for g in gaps_mb if g < 10) / len(gaps_mb) * 100),
            "gap_lt_100mb_pct": float(sum(1 for g in gaps_mb if g < 100) / len(gaps_mb) * 100),
            "gap_ge_100mb_pct": float(sum(1 for g in gaps_mb if g >= 100) / len(gaps_mb) * 100),
        },
        "direction_distribution": {
            "forward_pct": float(sum(1 for d in signed_diffs_gb if d > 0) / len(signed_diffs_gb) * 100),
            "backward_pct": float(sum(1 for d in signed_diffs_gb if d < 0) / len(signed_diffs_gb) * 100),
        },
        "directional_runs": {
            "n_forward_runs": len(forward_runs),
            "mean_forward_run_length": float(np.mean(forward_runs)) if forward_runs else 0,
            "max_forward_run_length": int(max(forward_runs)) if forward_runs else 0,
            "n_backward_runs": len(backward_runs),
            "mean_backward_run_length": float(np.mean(backward_runs)) if backward_runs else 0,
            "max_backward_run_length": int(max(backward_runs)) if backward_runs else 0,
        },
    }

    out_json = os.path.join(out_dir, 'lba_timeline_summary.json')
    with open(out_json, 'w') as fp:
        json.dump(summary, fp, indent=2, ensure_ascii=False)
    print(f"  ✅ {out_json}")

    # 同时存 events 列表
    out_events = os.path.join(out_dir, 'lba_events.json')
    with open(out_events, 'w') as fp:
        json.dump(events, fp, ensure_ascii=False, indent=2)
    print(f"  ✅ {out_events}")

    return summary


def main():
    parser = argparse.ArgumentParser(description='设备端 LBA 时间序列分析')
    parser.add_argument('--bpftrace', required=True, help='bpftrace log 文件路径')
    parser.add_argument('--out', required=True, help='输出目录')
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"📖 解析 bpftrace: {args.bpftrace}")
    events = parse_bpftrace_lba(args.bpftrace)
    print(f"  ✅ 找到 {len(events)} 个 LBA 位置 (dedup heatmap)")

    print(f"📏 计算 gap 和方向")
    abs_gaps_bytes, signed_diffs_gb, time_deltas_ms = compute_gaps(events)

    print(f"🎨 画图")
    plot_timeline_scatter(events, args.out)
    plot_sequentiality(abs_gaps_bytes, signed_diffs_gb, args.out)
    plot_runs(events, signed_diffs_gb, args.out)
    plot_window_coverage(events, args.out)

    print(f"📝 写总结")
    summary = write_summary(events, abs_gaps_bytes, signed_diffs_gb, args.out)

    print()
    print("=" * 60)
    print("📊 三句话结论:")
    print(f"  1. 顺序率 (gap<1MB): {summary['sequential_rate_by_threshold']['gap_lt_1mb_pct']:.1f}%")
    print(f"  2. 大跳跃 (gap>100MB): {summary['sequential_rate_by_threshold']['gap_ge_100mb_pct']:.1f}%")
    print(f"  3. Forward runs: {summary['directional_runs']['n_forward_runs']} 条, 平均 {summary['directional_runs']['mean_forward_run_length']:.1f} events/run")
    print("=" * 60)


if __name__ == '__main__':
    main()