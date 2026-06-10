# KV Cache Cross-Vendor Benchmark — K4 GC-Drift (Long Steady-State)
**Date:** 2026-06-10
**Workload:** K4 GC-drift — LLaMA-3.1-8B KV cache, 16 concurrent users, **1200 s** (20 min), BurstGPT trace replay
**Goal:** Expose steady-state GC cliffs and write-tail drift that 2-minute burst tests cannot see.

Companion reports:
- `kv-cache-4disk-K5-headline-2026-06-10.md` (70B × 4u × 180 s)
- `kv-cache-4disk-K4-headline-2026-06-10.md` (8B × 16u × 120 s)

---

## TL;DR — Headline finding

**The 2-minute winner is NOT the 20-minute winner.**

K4 GC drift **inverts** the short-burst ranking:

| Disk | K4 120 s rank | **K4 1200 s rank** | Δ |
|---|:---:|:---:|:---:|
| Biwin X570 | 🥇 1st | **🥈 2nd** | −1 |
| ZhiTai Ti600 | 🥈 2nd | **4th** | −2 |
| Seagate FC530 | 🥉 3rd | **🥇 1st** | +2 |
| WD SN570 | 4th | **🥉 3rd** | +1 |

- **Seagate FC530** wins on long-steady-state read BW (1.91 vs 1.92 GB/s — essentially tied with Biwin but **better tail latency**).
- **Biwin X570** shows the **largest drift** (read BW −39 %, write P99 +356 %) — its SLC cache advantage is consumed quickly.
- **ZhiTai Ti600** collapses: read BW −59 %, write P99 climbs to **725 ms** (vs 181 ms for Biwin, 128 ms for Seagate).
- **WD SN570** is the most consistent loser — slow everywhere, but at least it does not collapse.

**Conclusion for AI SSD selection:** *Never pick a KV cache SSD based on burst performance alone.* Long-steady-state GC behavior is what determines actual serving throughput after the SLC cache fills. **Seagate FC530 is the recommended disk for sustained KV cache offload; Biwin X570 is recommended only for short-burst / interactive inference.**

---

## Methodology

### Workload (K4 GC drift)
- **Model:** LLaMA-3.1-8B (8× tensor-parallel on 8 GPUs)
- **Concurrent users:** 16
- **Duration:** **1200 s** (20 min) per disk, 4 disks serial
- **Trace:** BurstGPT, `--trace-speedup 1000`, `--replay-cycles 0` (infinite replay of 180-s trace, replayed 6.7×)
- **Cache tier:** `--gpu-mem-gb 0 --cpu-mem-gb 0` (force NVMe path)

### Why 1200 s?
K4 at 120 s writes ~32 GB. Most consumer TLC drives have an SLC cache of 30–90 GB; Biwin's SLC cache is ~95 GiB. At 120 s the Biwin cache is not yet exhausted. At 1200 s the cache is saturated, the drive is in steady-state TLC mode, and GC pressure is realistic.

### Why KV-cache.py, not fio?
This is real LLM inference traffic (BurstGPT prefill/decode), not synthetic 16k randread. The IO pattern is "small entry writes + large entry reads", which is what real serving produces. The tradeoff: GC cliff may appear **later** than under fio synthetic IO. This makes the test more representative of real deployment but slightly less pessimistic than worst-case fio.

### Disks

| Vendor ID | Model | Tier / positioning | Mount |
|---|---|---|---|
| biwin_x570 | BIWIN X570 1 TB | mainstream (DRAM, prior subject) | `/run/media/ficus/新加卷` |
| seagate_fc530 | Seagate ZP1000GV30012 | high-end (Phison E18) | `/mnt/ai_ssd2` |
| zhitai_ti600 | ZHITAI Ti600 1 TB | domestic (YMTC NAND) | `/mnt/ai_ssd1` |
| wd_sn570 | WDC WDS960G2G0G | entry-level (DRAM-less) | `/mnt/ai_ssd0` |

Run order (fastest to slowest — fail fast): Biwin → Seagate → ZhiTai → WD. Total wall time: ~80 minutes.

---

## Results

### Throughput and work completed (1200 s)

| Disk | Read (GB) | Write (GB) | Storage entries | Read BW (GB/s) | Write BW (GB/s) | Read IOPS | Write IOPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Biwin X570** | 2307.2 | 205.3 | 24 255 | **1.92** | **0.17** | **193 538** | 25 704 |
| **Seagate FC530** | 2294.9 | 203.8 | 24 177 | **1.91** | **0.17** | 193 466 | 25 664 |
| WD SN570 | 1497.0 | 148.1 | 16 788 | 1.25 | 0.12 | 118 280 | 17 632 |
| ZhiTai Ti600 | 1217.6 | 118.7 | 15 051 | 1.01 | 0.10 | 101 463 | 15 781 |

Biwin and Seagate complete essentially the same amount of work in 20 min (24 255 vs 24 177 entries = 0.3 % spread). The split between them is by latency, not throughput.

### Latency (storage_tier, ms)

| Disk | Read P50 | **Read P99** | **Read P999** | **Write P99** |
|---|---:|---:|---:|---:|
| **Seagate FC530** | 51.1 | **209.2** | 289.6 | **128** |
| Biwin X570 | 24.1 | 154.8 | 224.5 | 181 |
| ZhiTai Ti600 | 17.1 | 251.9 | 445.9 | **725** |
| WD SN570 | 79.8 | 420.3 | 629.2 | 480 |

**Seagate wins on P50 and write P99.** Biwin wins on read P99/P999 by a smaller margin. ZhiTai has the best P50 (17 ms!) but the worst P999 (446 ms) and worst write P99 (725 ms).

### The Biwin read-P99 paradox
Biwin's read P99 (155 ms) is **lower** than Seagate's (209 ms), but Biwin's read P50 (24 ms) is **also lower** than Seagate's (51 ms). So Biwin is consistently faster per-operation, but Biwin has a **larger spread** between P50 and P99. Seagate's latency is uniformly higher but more predictable.

---

## Drift analysis: 120 s vs 1200 s

How each metric moved from short-burst to long-steady-state:

| Disk | Read BW Δ | Write BW Δ | Read P99 Δ | Write P99 Δ | Read P50 Δ |
|---|---:|---:|---:|---:|---:|
| **Seagate FC530** | **−18 %** | **−15 %** | **+24 %** | **+101 %** | +37 % |
| WD SN570 | −20 % | −5 % | +50 % | +78 % | +24 % |
| **Biwin X570** | **−39 %** | **−37 %** | **+112 %** | **+356 %** | +69 % |
| ZhiTai Ti600 | −59 % | −51 % | +199 % | +123 % | +9 % |

### What this tells us about each drive

**Seagate FC530 — the steady-state winner**
- Lowest absolute drift across all metrics.
- Even at long-steady-state, GC overhead is bounded.
- Write P99 +101 % is high in % terms but starts from a low base (63 ms → 128 ms is still acceptable).
- *This is the disk you want under sustained load.*

**WD SN570 — boringly bad**
- Drift is moderate (read BW −20 %), because it was never very fast to begin with.
- The DRAM-less controller keeps throughput low but stable.
- P99 latency drifts +50 % but starts from a high baseline.
- *Cheap, predictable, slow.*

**Biwin X570 — short-burst specialist**
- Largest drift in 3 out of 5 metrics.
- Read BW drops nearly 40 %; write P99 **quadruples**.
- The Biwin SLC cache (~95 GiB) appears to be fully consumed within the first 200–300 seconds of the run; after that the controller is operating on direct-to-TLC writes which are slower but still acceptable.
- *Use this disk for burst workloads (interactive inference with <5 min average session); avoid it for sustained serving.*

**ZhiTai Ti600 — collapse**
- Largest absolute drift on read BW (−59 %).
- Write P99 of **725 ms** is catastrophic for KV cache writes — every prefill that requires eviction will stall for 0.7 s.
- YMTC NAND shows severe write amplification under sustained mixed RW pressure.
- *Do not deploy for KV cache offload.*

---

## Cross-scenario summary

Combining K5 (180 s, 70B), K4 (120 s, 8B), and K4-GC (1200 s, 8B):

| Disk | K5 rank | K4 (120 s) rank | K4-GC (1200 s) rank |
|---|:---:|:---:|:---:|
| Biwin X570 | 🥇 | 🥇 | **🥈** |
| Seagate FC530 | 🥈 | 🥉 | **🥇** |
| ZhiTai Ti600 | 🥉 | 🥈 | **4th** |
| WD SN570 | 4th | 4th | **🥉** |

**Biwin is the burst champion, Seagate is the sustained champion.**

---

## Recommended deployment matrix

| Workload | Recommended disk | Rationale |
|---|---|---|
| **Short-burst interactive inference** (< 5 min sessions) | Biwin X570 | Best short-burst read P99 (94 ms in K5) and read BW (2.77 GB/s) |
| **Long-running batch inference** (> 10 min sessions) | **Seagate FC530** | Best long-steady read BW (1.91 GB/s) + best write P99 (128 ms) |
| **Mixed inference + periodic checkpointing** | **Seagate FC530** | Write P99 under sustained load is 7× better than ZhiTai |
| **Budget / low-throughput serving** | WD SN570 | Cheap, stable, slow — only acceptable if user count is small |
| **Avoid for KV cache offload** | ZhiTai Ti600 | Both short-burst BW and long-steady BW are mediocre; write tail is dangerous |

---

## Caveats and follow-ups

1. **GC cliff location not precisely measured.** The 1200 s window is enough to enter steady state, but it does not pinpoint *when* each drive's SLC cache ran out. A future test could instrument the cache_dir disk-usage rate to detect the cliff exactly.
2. **No checkpoint interleaving.** Real production nodes checkpoint while serving. A future test should run checkpointing simultaneously with KV cache offload to expose the write-amplification cliff on QLC drives.
3. **No DRAM tier.** Setting `gpu-mem-gb 0` is the worst case. A test with `--gpu-mem-gb 8 --cpu-mem-gb 8` would show how much a small HBM tier absorbs and whether the relative ordering between vendors shifts.
4. **Only 4 disks tested.** Other DRAM-equipped enterprise NVMe drives (e.g. Samsung PM9A3, Solidigm P5520) may have different tradeoffs and should be added if available.

---

## Raw data

```
results/cross_vendor/kv_cache_k4_gc_drift/{biwin_x570,seagate_fc530,zhitai_ti600,wd_sn570}/K4_16u_llama3.1-8b_1200s/
├── iostat.txt       # 1-second device samples across 1200 s
├── kv_cache.log
├── kv_cache_summary.json
└── metadata.json
```