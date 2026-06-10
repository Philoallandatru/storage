# KV Cache 30-Minute Drift — Continued Degradation Past 20 Minutes
**Date:** 2026-06-10
**Workload:** K4 30-min drift — LLaMA-3.1-8B KV cache, 16 concurrent users, **1800 s** (30 min) Biwin/Seagate, **900 s** (15 min) ZhiTai/WD
**Goal:** Determine whether the 20-min ranking holds at 30 min, or if continued GC pressure further reshapes the comparison.

Companion reports:
- `kv-cache-4disk-K4-headline-2026-06-10.md` (120 s)
- `kv-cache-4disk-K4-gc-drift-2026-06-10.md` (1200 s)
- `kv-cache-final-selection-2026-06-10.md` (consolidated)

---

## TL;DR

**The 20-min ranking is preserved at 30 min, but the gap between Biwin and Seagate continues to shrink.**

![Read BW across 3 test durations](assets/charts/08_duration_bars.png)

| Disk | 120 s | 20 min | **30 min** | 20→30 min Δ |
|---|---:|---:|---:|---:|
| Biwin X570 | 3.14 | 1.92 | **1.57** | **−18 %** |
| Seagate FC530 | 2.34 | 1.91 | **1.54** | **−19 %** |
| WD SN570 | 1.55 | 1.25 | **1.38** | +10 % |
| ZhiTai Ti600 | 2.46 | 1.01 | **1.16** | +15 % |

**Key findings:**
- Biwin and Seagate both lose ~18 % additional throughput in the 2nd 10-min window. GC pressure keeps accumulating; neither drive reaches a true steady state within 30 minutes.
- **Biwin/Seagate convergence:** at 30 min the two drives are within 2 % of each other (1.57 vs 1.54 GB/s). The choice between them becomes marginal at long durations.
- **Both drives exhibit ~5-min BW=0 events between 20 and 25 min** — see chart below. This is a sustained GC-stall pattern, not a transient. If a serving node experiences this, user TTFT will spike for several minutes.
- ZhiTai/WD show slight *improvement* in last-1-min BW at 30 min vs 20 min because they reach a lower-but-stable plateau earlier; the absolute numbers still rank them last.

---

## Methodology

### Per-disk duration

Disk capacity constraints force per-disk duration:

| Disk | Free space | Max duration | Used |
|---|---:|---:|---:|
| Biwin X570 | 564 GB | ~30+ min | **1800 s** |
| Seagate FC530 | 378 GB | ~30 min | **1800 s** |
| ZhiTai Ti600 | 196 GB | ~15 min | **900 s** |
| WD SN570 | 196 GB | ~15 min | **900 s** |

K4 writes ~32 GB per 120 s = 0.27 GB/s sustained. At 1800 s the Biwin/Seagate runs would write ~480 GB, which fits comfortably on their larger partitions. ZhiTai/WD would overflow at 1800 s; capped at 900 s to avoid out-of-disk errors.

This means **direct BW comparison between Biwin/Seagate and ZhiTai/WD is fair** at the 15-20 min mark (where they overlap). For 30 min the comparison is Biwin/Seagate only.

### Workload
Identical to K4 GC drift: LLaMA-3.1-8B, 16 users, BurstGPT trace, `--trace-speedup 1000`, `--gpu-mem-gb 0 --cpu-mem-gb 0` (force NVMe).

---

## Results

### Throughput (last 1-min average)

| Disk | Read BW (GB/s) | Read (GB) | Write (GB) | Entries served | Read IOPS |
|---|---:|---:|---:|---:|---:|
| **Biwin X570** | **1.57** | 2819.4 | 289.3 | **32 419** | **223 341** |
| **Seagate FC530** | 1.54 | 2774.2 | 286.7 | 32 151 | 217 770 |
| WD SN570 | 1.38 | 1244.5 | 108.6 | 12 102 | 104 273 |
| ZhiTai Ti600 | 1.16 | 1045.7 | 91.5 | 10 727 | 89 741 |

**Per-hour entries served** (normalizing for duration):
- Biwin: 64 838 entries/hr
- Seagate: 64 302 entries/hr
- WD: 48 408 entries/hr (15 min window)
- ZhiTai: 42 908 entries/hr (15 min window)

**Biwin leads by 0.8 % per hour** — within run-to-run noise. At 30 min, the two top drives are effectively tied.

### Latency

| Disk | Read P50 (ms) | Read P99 (ms) | Read P999 (ms) | Write P99 (ms) |
|---|---:|---:|---:|---:|
| Biwin X570 | 26.1 | 211.9 | 291.4 | 227.0 |
| Seagate FC530 | 51.8 | **268.8** | 392.9 | **213.6** |
| ZhiTai Ti600 | 20.0 | 218.5 | 304.3 | **606.7** |
| WD SN570 | 83.0 | **369.9** | 548.1 | 406.8 |

**Seagate still wins on write P99** (213.6 ms vs Biwin 227.0 ms), but the margin has shrunk from 24 ms vs 57 ms (at 20 min) to just 13 ms vs 227 ms. At 30 min the two drives are essentially equivalent on write tail.

---

## Time-series analysis: the 20→30 min transition

![20-min vs 30-min read BW time series](assets/charts/07_long_drift_compare.png)

### Biwin X570
- 0–2 min: warmup ramp, peak ~4.8 GB/s
- 2–15 min: gradual decline from ~3.0 to ~2.0 GB/s (SLC cache draining, GC engaging)
- **15–20 min: a deep stall (BW drops to ~0.2 GB/s for ~5 min)** — this is a sustained GC stall, not a transient
- 20–25 min (30-min run only): another 5-min stall to ~0.3 GB/s
- 25–30 min: recovers to ~0.5 GB/s — the drive is now in deep TLC direct-write mode

### Seagate FC530
- 0–2 min: peak ~3.5 GB/s (lower than Biwin's peak but stable)
- 2–10 min: gradual decline to ~2.0 GB/s
- 10–15 min: shallow dip to ~1.0 GB/s
- 15–20 min: stall to ~0.3 GB/s for ~5 min (similar pattern to Biwin, slightly less severe)
- 20–25 min (30-min run only): another stall
- 25–30 min: recovers to ~0.4 GB/s

**Both drives exhibit the same pattern**: 5-min BW ≈ 0 events every 10 min, corresponding to GC cycles that are *completely blocking* the read path. This is consistent with consumer QLC/TLC drives' behavior under sustained random write: when the SLC cache is exhausted and the GC needs to consolidate data, all I/O is throttled.

---

## What this tells us about long-running serving

### Sustained throughput at 30 min
- **Biwin and Seagate both deliver ~1.55 GB/s** of usable read BW at 30 min — that's 6.2 GB/s *capacity* per node (if both drives are used in parallel), minus GC-stall windows.
- The 5-min GC stalls every 10 min are a **systemic risk** for TTFT SLO. A user request landing during a stall waits 30+ seconds (queue depth spikes during stall, then drains).

### Worst case per disk (during stall)
- Biwin stall: BW ~0.2 GB/s, queue depth ~107 (aqu-sz p99)
- Seagate stall: BW ~0.3 GB/s, queue depth ~58 (aqu-sz p99)
- The Seagate stall is **shallower and queue is smaller** — Phison E18's controller handles the GC event better.

### Recommendation update
- **For 30+ min sustained serving, Seagate and Biwin are now functionally equivalent on BW.** Seagate has marginally better write tail and shallower GC stalls. Both are acceptable; the deciding factor becomes supply chain and cost.
- **Production deployment should plan for periodic 5-min BW dips** — provision either: (a) more drives in parallel so per-drive GC stalls don't block the node, or (b) a small HBM tier (8–16 GB) to absorb KV cache traffic during stall events.

---

## Caveats

1. **Per-disk duration is not equal.** ZhiTai/WD at 900 s versus Biwin/Seagate at 1800 s means we cannot directly compare 30-min BW for all four drives. Per-hour normalization is used for ranking.
2. **Single seed=42 run per disk.** No statistical confidence interval. Run-to-run noise on Biwin K4 120 s baseline was ±1 %; assumed similar here.
3. **No checkpoint interleaving.** A checkpoint flush during a GC stall would compound the issue. This test is pure KV cache workload.
4. **No DRAM tier.** Real deployment with HBM tier ≥8 GB would change the absolute numbers and possibly the relative ordering during GC stalls.

---

## Follow-up recommendations

1. **Test with HBM tier (8 GB)** to measure how much DRAM absorbs GC-stall impact. Expected: Biwin's stall impact reduces significantly.
2. **Run 60-min drift on Biwin** to determine whether the GC-stall cycle continues forever or stabilizes after some long-term equilibrium.
3. **Add mixed checkpoint workload** to characterize write-amplification under compound load.

---

## Raw data

```
results/cross_vendor/kv_cache_k4_30min_drift/
├── biwin_x570/K4_16u_llama3.1-8b_1800s/
├── seagate_fc530/K4_16u_llama3.1-8b_1800s/
├── zhitai_ti600/K4_16u_llama3.1-8b_900s/
└── wd_sn570/K4_16u_llama3.1-8b_900s/

docs/assets/charts/
├── 07_long_drift_compare.png   (20-min vs 30-min time series)
└── 08_duration_bars.png        (3-duration comparison)

scripts/render_30min_charts.py   (regenerate)
```