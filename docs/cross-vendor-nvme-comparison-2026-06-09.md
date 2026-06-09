# Cross-Vendor NVMe SSD Comparison Report

**Date**: 2026-06-09
**Test suite**: `scripts/cross_vendor_*.sh` (7 tests, see methodology below)
**Platform**: Linux 7.0.0-22-generic, 24 cores, 83 GB DRAM, fio 3.41

## Executive Summary

We benchmarked **4 consumer NVMe SSDs (1TB class)** from different vendors under a unified
test suite that simulates LLM KV-cache access patterns. The lineup spans:

| Slot | Model | Vendor positioning | NAND | DRAM |
|---|---|---|---|---|
| nvme0 | WD SN570 (WDS960G2G0C-00AJM0) | Entry-level | TLC (SanDisk) | **DRAM-less** |
| nvme1 | Biwin X570 1TB | Mainstream | TLC | 1 GB DRAM |
| nvme2 | ZhiTai Ti600 1TB | Domestic (China) | TLC (YMTC) | DRAM |
| nvme3 | Seagate FC530 (ZP1000GV30012) | High-end | TLC (Micron) | DRAM (Phison E18) |

## Headline Results

### Sequential burst (Test 1, 10 GB file, bs=128k, QD=32, direct=1)

| Vendor | Seq Read | Seq Write | Read latency | Vendor spec R/W |
|---|---:|---:|---:|---|
| WD SN570       | 2,275 MB/s | 1,936 MB/s | 1,758 μs | 3,500 / 3,000 |
| **Biwin X570** | **8,573 MB/s** 🏆 | **7,965 MB/s** 🏆 | **467 μs** | 7,400 / 6,800 |
| ZhiTai Ti600   | 6,345 MB/s | 3,696 MB/s | 630 μs | 7,000 / 6,500 |
| Seagate FC530  | 4,989 MB/s | 4,600 MB/s | 802 μs | 7,300 / 6,000 |

### 4K Random IOPS (Test 5, QD=64, sweet spot for most consumer SSDs)

| Vendor | Rand Read IOPS | Rand Write IOPS | Read lat | Write lat |
|---|---:|---:|---:|---:|
| WD SN570       | 337,255 | 331,012 | 190 μs | 193 μs |
| **Biwin X570** | **494,891** 🏆 | **510,840** 🏆 | 129 μs | 125 μs |
| ZhiTai Ti600   | 392,477 | 444,001 | 163 μs | 144 μs |
| Seagate FC530  | 454,003 | 457,291 | 141 μs | 140 μs |

### Mixed R/W (Test 6, 4k, QD=32, 20 GB file, 60s)

| Vendor | 90/10 Read | 90/10 Write | 50/50 Read | 50/50 Write |
|---|---:|---:|---:|---:|
| WD SN570       | 437 MB/s | 49 MB/s | 139 MB/s | 139 MB/s |
| Biwin X570     | 902 MB/s | 100 MB/s | 460 MB/s | 460 MB/s |
| ZhiTai Ti600   | 846 MB/s | 94 MB/s | 313 MB/s | 313 MB/s |
| **Seagate FC530** | **1,271 MB/s** 🏆 | **141 MB/s** 🏆 | **862 MB/s** 🏆 | **862 MB/s** 🏆 |

### Page cache sensitivity (Test 7, 4k buffered, 6 GB file)

| Vendor | Warm BW | Evict BW | Page cache speedup |
|---|---:|---:|---:|
| WD SN570       | 1,592 MB/s | 1,157 MB/s | **1.38x** |
| Biwin X570     | 2,565 MB/s | 2,522 MB/s | 1.02x |
| ZhiTai Ti600   | 2,204 MB/s | 2,285 MB/s | 0.96x |
| Seagate FC530  | 1,910 MB/s | 1,907 MB/s | 1.00x |

### SLC cache behavior (Test 2, 168 GB sequential write)

| Vendor | Probe mean BW (160GB sustained) | Post-idle fresh BW | Interpretation |
|---|---:|---:|---|
| WD SN570       | 1,971 MB/s | 1,998 MB/s | Tiny SLC cache (~10 MiB DRAM buffer), instantaneous peak |
| **Biwin X570** | **7,931 MB/s** | **7,299 MB/s** | **SLC cache > 168 GB** (never observed cliff in 160 GB) |
| ZhiTai Ti600   | 4,971 MB/s | 5,485 MB/s | SLC ~4 GB, post-idle ~5.5 GB/s suggests pSLC retained |
| Seagate FC530  | 4,587 MB/s | 4,569 MB/s | SLC ~170 MB, post-idle recovers 4.6 GB/s |

## Key Findings

### 1. DRAM-less WD SN570 is the weakest by every measure
- Sequential throughput is 27-73% of Biwin. Latency is 2-4x worse.
- DRAM-less shows in **mixed R/W**: 437 MB/s vs Biwin 902 MB/s (read) under 90/10.
- **But** WD benefits most from OS page cache (+38%) because it has no onboard DRAM cache.
- This is the **strongest argument for DRAM-equipped SSDs in LLM inference**: under sustained
  read-heavy workloads without cache hits, DRAM-less SSDs fall off a cliff.

### 2. Biwin X570 dominates for raw performance
- **8.5 GB/s sequential read** — exceeds vendor spec (7.4 GB/s), best in class.
- **495k IOPS random read** at QD=64 — second only to ZhiTai at QD=256.
- **Mixed 90/10**: 902 MB/s read + 100 MB/s write — best balanced profile for KV cache.
- **SLC cache appears to exceed 168 GB** — sustained 7.9 GB/s over a 160 GB write, with no
  measurable cliff. This is dramatically larger than the other 3 drives.
- **Page cache speedup is minimal (1.02x)** — its onboard 1 GB DRAM handles caching natively.

### 3. ZhiTai Ti600 needs high queue depth to shine
- QD=1 read: 16k IOPS (worst), QD=256 read: 581k IOPS (**best**).
- The YMTC NAND + controller has **deep queue parallelism** but single-thread latency suffers.
- For LLM inference (where multiple users = high concurrency), Ti600 is competitive.
- For single-user / prefill-decode (low concurrency), it underperforms.

### 4. Seagate FC530 is the mixed-workload king
- **Mixed R/W read 1,271 MB/s at 90/10** — 41% faster than Biwin's 902 MB/s.
- **Mixed R/W read 862 MB/s at 50/50** — almost 2x Biwin.
- Phison E18 controller excels at interleaving reads and writes.
- Lower pure sequential (5 GB/s) but balanced performance is what matters for KV cache.

### 5. SLC cache behavior is wildly different across vendors
| | SLC behavior in 160 GB sequential write |
|---|---|
| WD | DRAM-only buffer, no real pSLC |
| Biwin | pSLC ≥ 168 GB (very large, or aggressive write caching) |
| ZhiTai | pSLC ~4 GB |
| Seagate | pSLC ~170 MB |

The "SLC cache" effect everyone talks about is mostly absent on Biwin (which stays in fast
mode for the entire 160 GB run) and minimal on Seagate. Only ZhiTai shows a clean cliff at
~4 GB.

## Recommendations for AI SSD procurement

| Use case | Best vendor | Why |
|---|---|---|
| Single-stream prefill (long sequential read) | **Biwin X570** | 8.5 GB/s, beats spec |
| Multi-user decode (high QD, read-heavy) | **ZhiTai Ti600** | Best QD=256 scaling |
| Mixed R/W checkpointing + serving | **Seagate FC530** | 1.27 GB/s 90/10 read |
| Budget / DRAM-constrained | **WD SN570** only if system has plenty of DRAM for page cache |
| All-rounder / production deployment | **Biwin X570** | Best peak + lowest latency |

## Methodology

All 7 tests use a unified `cross_vendor_lib.sh` that defines the 4 vendor mounts:

```bash
wd_sn570     -> /mnt/ai_ssd0           (nvme0n1p2)
biwin_x570   -> /run/media/ficus/新加卷 (nvme1n1p2)
zhitai_ti600 -> /mnt/ai_ssd1           (nvme2n1p3)
seagate_fc530-> /mnt/ai_ssd2           (nvme3n1p2)
```

**Test 1 — Sequential Burst** (`cross_vendor_t1_seqburst.sh`):
10 GB file, bs=128k, QD=32, direct=1, 60s time_based.

**Test 2 — SLC Fresh** (`cross_vendor_t2_slc_fresh.sh`):
Write 168 GB in 10 GB slices (bs=1M, QD=32, direct=1) — log BW per slice.
Then 5 min idle. Then 10 GB fresh slice to measure "cold SLC refill" BW.

**Test 5 — Random 4K** (`cross_vendor_t5_random4k.sh`):
4 GB file, bs=4k, QD={1,4,16,64,256}, direct=1, 30s per cell.

**Test 6 — Mixed R/W** (`cross_vendor_t6_mixed_rw.sh`):
20 GB file, bs=4k, QD=32, direct=1, 60s time_based, rwmixread={90,50}.

**Test 7 — Page cache** (`cross_vendor_t7_pagecache.sh`):
6 GB file, bs=4k, QD=16, direct=0. Two conditions: buffered (warm cache) vs `invalidate=1`
(OS evicts after each block).

## Caveats

- **Single sample per test per vendor.** No 3-run median. Variance on small numbers (e.g.
  T2 BW_min of 5 MB/s) may be due to single IO spikes rather than steady state.
- **Disk free space**: WD had only 198 GB free; T2/T3 reduced to 168 GB to avoid filling.
- **Tests run serially**, no parallel disk access. Each disk's full suite is sequential.
- **T3 (steady state SLC) and T4 (15-min GC drift)** were not yet completed at report time.
  See `scripts/cross_vendor_t3_slc_steady.sh` and `cross_vendor_t4_gc_drift.sh`.

## Files

- `scripts/cross_vendor_lib.sh` — shared library
- `scripts/cross_vendor_t{1,2,3,4,5,6,7}_*.sh` — test scripts
- `scripts/cross_vendor_analyze.py` — aggregator
- `scripts/cross_vendor_slc_analyze.py` — SLC cliff detector
- `results/cross_vendor/{t1,t2,t5,t6,t7}/<vendor>_<ts>/` — raw fio output
- `results/cross_vendor/_compiled.json` — aggregated metrics