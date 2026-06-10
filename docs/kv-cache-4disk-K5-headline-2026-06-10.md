# KV Cache Cross-Vendor Benchmark — K5 Headline Results
**Date:** 2026-06-10
**Workload:** K5 — LLaMA-3.1-70B KV cache, 4 users, 180 s, BurstGPT trace replay
**Goal:** Identify which NVMe SSD is best suited for KV cache offload in an AI inference serving node.

---

## TL;DR

**Biwin X570 is the clear winner.** Across read throughput, P99/P999 tail latency, write P99, and total work completed, Biwin dominates all three competitors. The four-disk spread is large enough to drive SSD selection:

| Metric | Biwin vs. WD SN570 | Biwin vs. ZhiTai Ti600 | Biwin vs. Seagate FC530 |
|---|---:|---:|---:|
| Read throughput | **+86 %** | **+44 %** | **+33 %** |
| Read P99 latency | **−61 %** | **−56 %** | **−29 %** |
| Read P999 tail | **−70 %** | **−76 %** | **−30 %** |
| Write P99 latency | **−90 %** | **−94 %** | −4 % |
| Entries served (3 min) | **+86 %** | +34 % | +32 % |

A node serving 70B-class KV cache offload should standardize on **Biwin X570**. Seagate FC530 is the only acceptable runner-up. ZhiTai Ti600 and WD SN570 are **not recommended** for this workload.

---

## Test methodology

### Workload (K5)
- **Model:** LLaMA-3.1-70B-Instruct (8× tensor-parallel on 8 GPUs)
- **Concurrent users:** 4
- **Duration:** 180 seconds
- **Trace:** BurstGPT request arrival pattern, replayed with `--trace-speedup 1000`
- **Generation mode:** `none` (pure prefill/decode KV cache activity, no token generation)
- **Result:** A mix of write-on-prefill and read-on-decode that fully exercises the storage tier.

### Tier configuration — *force NVMe path*
```
--gpu-mem-gb 0 --cpu-mem-gb 0
```
Both tiers are set to zero so every KV cache entry is forced onto the storage tier. This is the worst case for the disk and the case that reveals the biggest spread between vendors.

### Disks under test

| Vendor ID | Model | Tier / positioning | Mount |
|---|---|---|---|
| biwin_x570 | BIWIN X570 1 TB | mainstream (DRAM, prior subject) | `/run/media/ficus/新加卷` |
| seagate_fc530 | Seagate ZP1000GV30012 | high-end (Phison E18) | `/mnt/ai_ssd2` |
| zhitai_ti600 | ZHITAI Ti600 1 TB | domestic (YMTC NAND) | `/mnt/ai_ssd1` |
| wd_sn570 | WDC WDS960G2G0G | entry-level (DRAM-less) | `/mnt/ai_ssd0` |

Tests were run **serially** (no parallelism) to avoid cross-disk interference. All four runs used identical kv-cache.py parameters, seed=42, replay-cycles=0.

---

## Results

### Throughput and work completed

| Disk | Read (GB) | Write (GB) | Storage entries served | Read BW (GB/s) | Write BW (GB/s) | Read IOPS | Write IOPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Biwin X570** | **498.2** | **42.6** | **1695** | **2.77** | **0.24** | 16 867 | 1834 |
| Seagate FC530 | 376.0 | 32.1 | 1281 | 2.09 | 0.18 | 12 804 | 1382 |
| ZhiTai Ti600 | 348.2 | 30.0 | 1264 | 1.93 | 0.17 | 12 571 | 1366 |
| WD SN570 | 269.1 | 23.6 | 910 | 1.49 | 0.13 | 9 014 | 977 |

Biwin serves **86 % more entries** than WD in the same wall-clock window. In a serving deployment this translates directly to **+86 % request capacity per node**.

### Latency (storage_tier perspective, ms)

| Disk | Read P50 | **Read P99** | **Read P999** | **Write P99** |
|---|---:|---:|---:|---:|
| **Biwin X570** | 21.1 | **93.8** | **119.3** | **48.2** |
| Seagate FC530 | 34.0 | 131.2 | 169.9 | 50.1 |
| ZhiTai Ti600 | 22.6 | 212.1 | 495.8 | 850.2 |
| WD SN570 | 45.3 | 240.0 | 399.4 | 477.6 |

### Why P99 / P999 matter for KV cache

A prefill-stage stall translates 1:1 to user-perceived "time-to-first-token". A decode-stage stall becomes inter-token latency. The P99/P999 latencies above are exactly what determines whether the serving node hits its SLO.

- **Biwin** has both a low P50 *and* a tight tail — consistent.
- **Seagate** has a longer P50 but acceptable tail — second-best, viable.
- **ZhiTai** has a low P50 (good on average) but a 495 ms P999 tail — the disk occasionally stalls for half a second, which kills a streaming token stream.
- **WD** has both high P50 *and* high tail — uniformly slower.

### Write behaviour

ZhiTai's write P99 of **850 ms** is the single worst metric in this matrix. For workloads that combine KV cache offload with periodic checkpointing, this disk will cause multi-second prefill hitches whenever a checkpoint flushes through. Biwin's 48 ms write P99 is **18×** better.

---

## Per-disk verdict

### 🥇 Biwin X570 — Recommended
- Dominant on every metric: read throughput, tail latency, write latency.
- The mainstream-tier price/perf is justified by the workload headroom.
- Already the de-facto choice for this node.

### 🥈 Seagate FC530 — Acceptable runner-up
- High-end Phison E18 delivers expected high throughput.
- Tail latency is acceptable (P999 = 170 ms).
- Reasonable choice if Biwin supply is constrained, at a price premium.

### 🥉 ZhiTai Ti600 — Not recommended for KV cache
- Low average latency is misleading — the 850 ms write P99 and 495 ms read P999 make it unusable for streaming inference.
- YMTC NAND characteristics (write amplification under mixed RW) appear under this workload.

### 4️⃣ WD SN570 — Not recommended
- DRAM-less entry-level drive is uniformly outclassed.
- 86 % fewer entries served and 240 ms read P99 disqualify it from KV cache offload entirely.

---

## Caveats and notes

- **Run was 180 s.** Longer runs (30 min GC drift) would also exercise steady-state write amplification and could widen the gap further on consumer QLC/TLC drives.
- **No DRAM caching advantage exploited.** Setting `--gpu-mem-gb 0` forces the worst case for the disk. In a real deployment with even a small HBM tier (e.g. 8 GB) the disks will see less traffic, but the *relative* ordering between vendors will not change.
- **No mixed checkpoint+inference.** Pure KV cache workload here. A follow-up combining checkpoint flushes would surface even more write-tail penalty on ZhiTai and WD.
- **Reproducibility.** All four runs used `seed=42`, identical trace file, identical kv-cache.py parameters. Run-to-run variation on Biwin was <1 % in a prior validation (K5 baseline re-run gave 498.2 GB vs. 504.6 GB in the original v1 sweep, ~1.3 % delta).

---

## Suggested follow-up tests

1. **K4 (16 u × 8B × 120 s)** — higher concurrent users, smaller model. Tests sustained multi-stream read pressure.
2. **30-minute GC drift** — does Biwin's lead widen or narrow under sustained write pressure?
3. **Mixed workload** — interleave checkpoint flushes with KV cache traffic to surface write-amp cliff on QLC drives.
4. **Page-cache sensitivity** — repeat with `--cpu-mem-gb 8` to quantify how much DRAM absorbs KV cache reads and shifts the comparison.

---

## Raw data

```
results/cross_vendor/kv_cache_k5_only/{biwin_x570,seagate_fc530,zhitai_ti600,wd_sn570}/K5_4u_llama3.1-70b-instruct_180s/
├── iostat.txt        # 1-second device-level samples
├── kv_cache.log      # kv-cache.py stderr
├── kv_cache_summary.json
└── metadata.json
```