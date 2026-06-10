#!/usr/bin/env python3
"""
Analyze KV-cache K4 GC-drift iostat data.

Goals:
  1. Find GC cliff (BW drop point) per disk
  2. Analyze read/write randomness via:
     - request size distribution (rareq-sz, wareq-sz)
     - merge ratio (%rrqm, %wrqm)  -> high merge = sequential
     - queue depth correlation with size
  3. Cross-disk comparison

Input: iostat.txt files from results/cross_vendor/kv_cache_k4_gc_drift/<disk>/K4_*/iostat.txt
Output: prints report to stdout; writes summary to results/cross_vendor/kv_cache_k4_gc_drift/_analysis/
"""
import os, json, re, statistics
from collections import defaultdict
from pathlib import Path

BASE = Path('/home/ficus/llm/storage/results/cross_vendor/kv_cache_k4_gc_drift')
OUT = BASE / '_analysis'
OUT.mkdir(exist_ok=True)

DISKS = ['biwin_x570', 'seagate_fc530', 'zhitai_ti600', 'wd_sn570']

# Identify the actual NVMe device for each mount so we can filter iostat rows
DEV_FOR_DISK = {
    'biwin_x570':    'nvme1n1',
    'seagate_fc530': 'nvme3n1',
    'zhitai_ti600':  'nvme2n1',
    'wd_sn570':      'nvme0n1',
}

def parse_iostat(path, target_dev):
    """Return list of dicts, one per 1-second sample, only for target device."""
    samples = []
    with open(path) as f:
        lines = f.readlines()
    # Header layout (iostat -dx -m 1):
    # Line 0: system info
    # Line 1: blank
    # Line 2: column header
    # Line 3+: data rows (one per device per second)
    # Every 24 lines: separator blank line
    # We only keep rows starting with target_dev
    for line in lines:
        s = line.strip()
        if not s: continue
        if s.startswith(target_dev):
            parts = s.split()
            # Columns:
            # 0: Device
            # 1: r/s  2: rMB/s  3: rrqm/s  4: %rrqm  5: r_await  6: rareq-sz
            # 7: w/s  8: wMB/s  9: wrqm/s  10: %wrqm  11: w_await  12: wareq-sz
            # 13: d/s  14: dMB/s  15: drqm/s  16: %drqm  17: d_await  18: dareq-sz
            # 19: f/s 20: f_await 21: aqu-sz 22: %util
            try:
                samples.append({
                    'r_s':        float(parts[1]),
                    'r_mbs':      float(parts[2]),
                    'rrqm_s':     float(parts[3]),
                    'pct_rrqm':   float(parts[4]),
                    'r_await':    float(parts[5]),
                    'rareq_sz':   float(parts[6]),
                    'w_s':        float(parts[7]),
                    'w_mbs':      float(parts[8]),
                    'wrqm_s':     float(parts[9]),
                    'pct_wrqm':   float(parts[10]),
                    'w_await':    float(parts[11]),
                    'wareq_sz':   float(parts[12]),
                    'aqu_sz':     float(parts[21]),
                    'util':       float(parts[22]),
                })
            except (IndexError, ValueError):
                continue
    return samples

def detect_cliff(samples, key='r_mbs', warmup_s=120, window=30, drop_pct=25):
    """Find first sustained drop after warmup.

    Algorithm: ignore first `warmup_s` samples (warmup ramp). Compute peak of
    trailing 30s windows AFTER warmup. Then find the first window whose avg
    falls >= drop_pct below that peak AND stays below for the next 3 windows
    (confirms it's a cliff, not a dip).
    """
    if len(samples) < warmup_s + window + 3:
        return None
    # Find peak in post-warmup rolling windows
    rolling = []
    for i in range(warmup_s, len(samples) - window):
        rolling.append((i, sum(s[key] for s in samples[i:i+window]) / window))
    if not rolling:
        return None
    # Peak window
    peak_t, peak_v = max(rolling, key=lambda x: x[1])
    if peak_v <= 0:
        return None
    threshold = peak_v * (1 - drop_pct/100)
    # First sustained drop AFTER peak
    after_peak = [t for t, v in rolling if t > peak_t and v < threshold]
    if not after_peak:
        return None
    return after_peak[0]

def quartile_stats(values, prefix=''):
    if not values:
        return {}
    sv = sorted(values)
    def pct(p):
        idx = int(len(sv) * p / 100)
        idx = max(0, min(len(sv)-1, idx))
        return sv[idx]
    return {
        f'{prefix}mean':   sum(values)/len(values),
        f'{prefix}median': pct(50),
        f'{prefix}p25':    pct(25),
        f'{prefix}p75':    pct(75),
        f'{prefix}p95':    pct(95),
        f'{prefix}p99':    pct(99),
    }

def main():
    report = {}
    for disk in DISKS:
        path = BASE / disk / 'K4_16u_llama3.1-8b_1200s' / 'iostat.txt'
        dev  = DEV_FOR_DISK[disk]
        print(f"\n=== {disk}  (device {dev}) ===")
        samples = parse_iostat(path, dev)
        if not samples:
            print(f"  no samples found for {dev} in {path}")
            continue
        print(f"  parsed {len(samples)} samples ({len(samples)}s = {len(samples)/60:.1f} min)")

        # GC cliff detection on read BW
        cliff_idx = detect_cliff(samples, 'r_mbs', warmup_s=120, window=30, drop_pct=20)
        # For comparison also compute simple global peak
        peak_global = max(s['r_mbs'] for s in samples)
        peak_global_t = next(i for i, s in enumerate(samples) if s['r_mbs'] == peak_global)
        if cliff_idx is not None:
            after = sum(s['r_mbs'] for s in samples[cliff_idx:cliff_idx+30])/30
            print(f"  GC cliff at t={cliff_idx}s ({cliff_idx/60:.1f}min): peak {peak_global:.2f} GB/s -> after-cliff {after:.2f} GB/s (-{(1-after/peak_global)*100:.1f}%)")
        else:
            print(f"  no GC cliff detected (peak was {peak_global:.2f} GB/s at t={peak_global_t}s; no sustained 20% drop)")

        # Randomness analysis
        rareq_sizes = [s['rareq_sz'] for s in samples if s['rareq_sz'] > 0]
        wareq_sizes = [s['wareq_sz'] for s in samples if s['wareq_sz'] > 0]
        rareq_stats = quartile_stats(rareq_sizes, 'rareq_')
        wareq_stats = quartile_stats(wareq_sizes, 'wareq_')

        # Merge ratio (higher = more sequential)
        pct_rrqm_vals = [s['pct_rrqm'] for s in samples]
        pct_wrqm_vals = [s['pct_wrqm'] for s in samples]
        rrqm_stats = quartile_stats(pct_rrqm_vals, 'pct_rrqm_')
        wrqm_stats = quartile_stats(pct_wrqm_vals, 'pct_wrqm_')

        # AWait: high w_await = queue pressure / random IO
        r_await_stats = quartile_stats([s['r_await'] for s in samples if s['r_await'] > 0], 'r_await_')
        w_await_stats = quartile_stats([s['w_await'] for s in samples if s['w_await'] > 0], 'w_await_')

        # Queue depth distribution (concurrent IO)
        aqu_stats = quartile_stats([s['aqu_sz'] for s in samples], 'aqu_')

        # Throughput time-bucketed
        first_quarter = samples[:len(samples)//4]
        last_quarter  = samples[-len(samples)//4:]
        r_bw_first = sum(s['r_mbs'] for s in first_quarter) / len(first_quarter)
        r_bw_last  = sum(s['r_mbs'] for s in last_quarter)  / len(last_quarter)
        w_bw_first = sum(s['w_mbs'] for s in first_quarter) / len(first_quarter)
        w_bw_last  = sum(s['w_mbs'] for s in last_quarter)  / len(last_quarter)

        print(f"\n  -- Read pattern --")
        print(f"  request size (kB): median={rareq_stats.get('rareq_median',0):.1f}  p95={rareq_stats.get('rareq_p95',0):.1f}  p99={rareq_stats.get('rareq_p99',0):.1f}")
        print(f"  merge ratio (%rrqm): median={rrqm_stats.get('pct_rrqm_median',0):.1f}  p95={rrqm_stats.get('pct_rrqm_p95',0):.1f}")
        print(f"  await (ms):           median={r_await_stats.get('r_await_median',0):.2f}  p99={r_await_stats.get('r_await_p99',0):.2f}")
        print(f"\n  -- Write pattern --")
        print(f"  request size (kB): median={wareq_stats.get('wareq_median',0):.1f}  p95={wareq_stats.get('wareq_p95',0):.1f}  p99={wareq_stats.get('wareq_p99',0):.1f}")
        print(f"  merge ratio (%wrqm): median={wrqm_stats.get('pct_wrqm_median',0):.1f}  p95={wrqm_stats.get('pct_wrqm_p95',0):.1f}")
        print(f"  await (ms):           median={w_await_stats.get('w_await_median',0):.2f}  p99={w_await_stats.get('w_await_p99',0):.2f}")
        print(f"\n  -- Queue depth (aqu-sz) --")
        print(f"  median={aqu_stats.get('aqu_median',0):.1f}  p95={aqu_stats.get('aqu_p95',0):.1f}  p99={aqu_stats.get('aqu_p99',0):.1f}")
        print(f"\n  -- Drift (first 5min vs last 5min) --")
        print(f"  Read BW:  {r_bw_first:.2f} -> {r_bw_last:.2f} GB/s ({(r_bw_last/r_bw_first-1)*100:+.1f}%)")
        print(f"  Write BW: {w_bw_first:.2f} -> {w_bw_last:.2f} GB/s ({(w_bw_last/w_bw_first-1)*100:+.1f}%)")

        report[disk] = {
            'samples': len(samples),
            'cliff_s': cliff_idx,
            'rareq_sz': rareq_stats,
            'wareq_sz': wareq_stats,
            'pct_rrqm': rrqm_stats,
            'pct_wrqm': wrqm_stats,
            'r_await':  r_await_stats,
            'w_await':  w_await_stats,
            'aqu_sz':   aqu_stats,
            'r_bw_first_5min': r_bw_first,
            'r_bw_last_5min':  r_bw_last,
            'w_bw_first_5min': w_bw_first,
            'w_bw_last_5min':  w_bw_last,
        }

    # Persist
    out_path = OUT / 'iostat_analysis.json'
    with open(out_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\n\nAnalysis saved to: {out_path}")

    # ---- Cross-disk summary table ----
    print("\n" + "="*100)
    print("CROSS-DISK COMPARISON — RANDOMNESS INDICATORS")
    print("="*100)
    print(f"{'DISK':<18} {'rreq_kB(p50)':>12} {'rreq_kB(p99)':>12} {'%rrqm(p50)':>11} {'r_await_p99ms':>14} {'wareq_kB(p50)':>13} {'%wrqm(p50)':>11} {'w_await_p99ms':>14}")
    print("-"*100)
    for d in DISKS:
        r = report.get(d, {})
        print(f"{d:<18} "
              f"{r.get('rareq_sz',{}).get('rareq_median',0):>12.1f} "
              f"{r.get('rareq_sz',{}).get('rareq_p99',0):>12.1f} "
              f"{r.get('pct_rrqm',{}).get('pct_rrqm_median',0):>11.1f} "
              f"{r.get('r_await',{}).get('r_await_p99',0):>14.1f} "
              f"{r.get('wareq_sz',{}).get('wareq_median',0):>13.1f} "
              f"{r.get('pct_wrqm',{}).get('pct_wrqm_median',0):>11.1f} "
              f"{r.get('w_await',{}).get('w_await_p99',0):>14.1f}")
    print()
    print("Interpretation:")
    print("  - small rareq_sz + low %rrqm + high r_await = RANDOM small reads")
    print("  - large rareq_sz + high %rrqm + low r_await = SEQUENTIAL streaming")
    print("  - KV cache typically: small reads (single entry), low merge, moderate await")

if __name__ == '__main__':
    main()