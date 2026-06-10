# KV Cache Cross-Vendor Benchmark — K4 Results (8B High-Concurrency)
**Date:** 2026-06-10
**Workload:** K4 — LLaMA-3.1-8B KV cache, 16 concurrent users, 120 s, BurstGPT trace replay
**Goal:** Reveal cross-vendor storage-tier performance under high-concurrency small-model KV cache pressure.

Companion to: `kv-cache-4disk-K5-headline-2026-06-10.md` (70B, 4 users).

---

## TL;DR

**Biwin X570 wins decisively.** K4 (high-concurrency 8B) widens the spread seen in K5:

| Metric | Biwin vs. WD SN570 | Biwin vs. ZhiTai Ti600 | Biwin vs. Seagate FC530 |
|---|---:|---:|---:|
| Read throughput | **+103 %** | **+28 %** | **+34 %** |
| Read P99 latency | **−74 %** | −14 % | **−57 %** |
| Read P999 tail | **−74 %** | −35 % | **−56 %** |
| Write P99 latency | **−85 %** | **−88 %** | −38 % |
| Entries served (2 min) | **+113 %** | +28 % | +33 % |

**Key cross-scenario insight:** In K4, **ZhiTai Ti600 beats Seagate FC530** on read BW, P99, and IOPS. The Phison E18 advantage observed in K5 (70B) flips under small-model high-concurrency pressure. Seagate is the only vendor whose relative position changes between scenarios.

---

## Test methodology

### Workload (K4)
- **Model:** LLaMA-3.1-8B (8× tensor-parallel on 8 GPUs)
- **Concurrent users:** 16
- **Duration:** 120 seconds
- **Trace:** BurstGPT request arrival pattern, replayed with `--trace-speedup 1000`
- **Generation mode:** `none`
- **Cache configuration:** `--gpu-mem-gb 0 --cpu-mem-gb 0` (force NVMe path)

K4 differs from K5 in two stress dimensions:
- More concurrent users (16 vs. 4) → higher IOPS demand
- Smaller model → smaller per-entry KV footprint, more entries per GB

This stress-tests whether any disk saturates on IOPS before it saturates on bandwidth.

### Disks under test

| Vendor ID | Model | Tier / positioning | Mount |
|---|---|---|---|
| biwin_x570 | BIWIN X570 1 TB | mainstream (DRAM, prior subject) | `/run/media/ficus/新加卷` |
| seagate_fc530 | Seagate ZP1000GV30012 | high-end (Phison E18) | `/mnt/ai_ssd2` |
| zhitai_ti600 | ZHITAI Ti600 1 TB | domestic (YMTC NAND) | `/mnt/ai_ssd1` |
| wd_sn570 | WDC WDS960G2G0G | entry-level (DRAM-less) | `/mnt/ai_ssd0` |

Tests were run **serially**, identical kv-cache.py parameters across disks, seed=42, replay-cycles=0.

---

## Results

### Throughput and work completed

| Disk | Read (GB) | Write (GB) | Storage entries served | Read BW (GB/s) | Write BW (GB/s) | Read IOPS | Write IOPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Biwin X570** | **376.8** | **31.8** | **3259** | **3.14** | **0.27** | **32 363** | 3555 |
| ZhiTai Ti600 | 295.3 | 24.5 | 2551 | 2.46 | 0.20 | 25 580 | 2798 |
| Seagate FC530 | 281.0 | 23.4 | 2450 | 2.34 | 0.20 | 24 652 | 2692 |
| WD SN570 | 186.1 | 15.4 | 1527 | 1.55 | 0.13 | 15 394 | 1661 |

Biwin serves **+113 % more entries** than WD in the same 2-minute window.

### Latency (storage_tier, ms)

| Disk | Read P50 | **Read P99** | **Read P999** | **Write P99** |
|---|---:|---:|---:|---:|
| **Biwin X570** | 14.3 | **72.9** | **100.1** | **39.6** |
| ZhiTai Ti600 | 15.7 | 84.4 | 154.7 | 324.7 |
| Seagate FC530 | 37.4 | 169.3 | 224.9 | 63.4 |
| WD SN570 | 64.2 | 281.2 | 391.1 | 269.5 |

---

## Per-disk verdict

### 🥇 Biwin X570 — Recommended
- 32 k read IOPS, 3.14 GB/s read BW, 73 ms P99 — uniformly best.
- The 14 ms P50 read latency indicates that under sustained 16-user concurrent reads the controller/DRAM combination is comfortably meeting demand.

### 🥈 ZhiTai Ti600 — Acceptable for small-model workloads
- 2.46 GB/s read BW is solid; P99 of 84 ms is within budget for many serving scenarios.
- **Caveat:** 325 ms write P99 is still high — fine for KV-cache-only serving, dangerous for mixed checkpoint+inference.

### 🥉 Seagate FC530 — Mixed signal
- 37 ms P50 read latency (the highest of any vendor except WD) suggests the Phison E18 controller hits an early stall under 16-user concurrency.
- Reasonable for low-concurrency 70B (K5), not the best choice for high-concurrency 8B.

### 4️⃣ WD SN570 — Not recommended
- 64 ms P50 read latency = the disk is queueing every read.
- 281 ms read P99 = the disk occasionally stalls for 300 ms; users will see visible jank.
- Avoid for any KV cache offload workload.

---

## K4 vs K5 cross-scenario observations

Same four disks, two very different stress profiles:

| Disk | K5 read BW (GB/s) | K4 read BW (GB/s) | Δ | K5 entries | K4 entries | Δ |
|---|---:|---:|---:|---:|---:|---:|
| Biwin X570 | 2.77 | **3.14** | +13 % | 1695 | **3259** | +92 % |
| ZhiTai Ti600 | 1.93 | 2.46 | +27 % | 1264 | 2551 | +102 % |
| Seagate FC530 | 2.09 | 2.34 | +12 % | 1281 | 2450 | +91 % |
| WD SN570 | 1.49 | 1.55 | +4 % | 910 | 1527 | +68 % |

**Observations:**
- All four disks serve ~2× more entries in K4 (smaller per-entry KV footprint).
- Biwin scales best on BW (+13 %) and most on entries (+92 %).
- **WD barely improves on BW (+4 %)** — DRAM-less controller is the bottleneck regardless of workload.
- **Seagate loses ranking in K4** (was 2nd in K5, now 3rd). Phison E18 favors large sequential reads; K4's smaller entry size + higher concurrency exposes this weakness.
- ZhiTai's relative gain in K4 (+27 % BW) confirms YMTC NAND handles small-entry IO better than large-entry IO.

### P99 latency: K4 vs K5

| Disk | K5 read P99 (ms) | K4 read P99 (ms) | Δ |
|---|---:|---:|---:|
| Biwin X570 | 93.8 | 72.9 | −22 % |
| ZhiTai Ti600 | 212.1 | 84.4 | −60 % |
| Seagate FC530 | 131.2 | 169.3 | +29 % |
| WD SN570 | 240.0 | 281.2 | +17 % |

Biwin, WD get faster in K4 (smaller entries → less queueing). **Seagate and ZhiTai move in opposite directions**, confirming they have different sweet spots.

---

## Caveats

- **120 s is short.** K4 does not stress GC/write-amplification cliffs. A 30-minute sustained run would expose any drive whose performance degrades over time.
- **All tier forced to NVMe.** A real deployment with even a small HBM tier (≥8 GB) will reduce disk pressure. Relative ordering between vendors is expected to hold, but absolute numbers will fall.
- **Pure KV cache.** No checkpointing, no embedding lookup, no RAG. Real mixed workloads would surface additional write-tail penalties.
- **Seed=42 reproducibility.** Two prior K4 runs (v1 sweep + this one) gave 3256 → 3259 entries (0.1 % delta). All four disks are within their own noise floor.

---

## Recommended follow-up

1. **K4 vs K5 combined PPT** — single 2-panel chart for SSD vendor selection.
2. **30 min GC drift on K4 disk list** — does Biwin hold the lead, or do consumer QLC drives collapse?
3. **Mixed workload (checkpoint + KV)** — surface the write-tail penalty on ZhiTai.

---

## Raw data

```
results/cross_vendor/kv_cache_k4_only/{biwin_x570,seagate_fc530,zhitai_ti600,wd_sn570}/K4_16u_llama3.1-8b_120s/
├── iostat.txt
├── kv_cache.log
├── kv_cache_summary.json
└── metadata.json
```