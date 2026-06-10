# KV Cache IO Pattern Analysis — Random vs Sequential
**Date:** 2026-06-10
**Source data:** K4 GC-drift iostat samples (4 disks × 1200 s × 1 Hz)
**Goal:** Characterize the IO access pattern produced by LLM KV cache offload, and quantify how each SSD reacts to it.

Companion to: `kv-cache-4disk-K4-gc-drift-2026-06-10.md`

---

## TL;DR

**LLM KV cache offload produces pure random IO, not sequential streaming.**

- Read request size: **~125 kB** (~30 × 4K pages) — fixed by the LLaMA-3.1-8B KV entry footprint.
- Write request size: **~115 kB** — slightly smaller than reads (entry metadata vs full page).
- **%rrqm ≈ 0 % across all 4 disks, %wrqm ≈ 0.1 %.** The kernel cannot merge adjacent KV reads/writes into a single larger IO because they target **discrete, scattered LBAs**.
- The IO pattern is therefore **"sparse-large-block random"** — large requests to scattered locations. This is one of the *worst* patterns for an SSD because it cannot exploit sequential prefetch, internal write coalescing, or large-block controller optimizations.
- All four SSDs see the *same* IO pattern; differences between them are purely in how their controllers cope with this random workload.

---

## Why this matters for AI SSD selection

| Pattern | Friendly to | Why |
|---|---|---|
| Sequential large read | All NAND | High BW, low latency, large SLC-program units |
| Sequential small write | All NAND | Internal write coalescing |
| Random small read (4K DB) | DRAM-equipped enterprise SSD | Low latency from controller SRAM |
| **Random large read (KV cache)** | **DRAM + high-QD enterprise NVMe** | High queue depth hides latency |

The KV cache pattern sits in the worst quadrant: too random to exploit sequential prefetch, but too large to fit cheaply in the controller's DRAM cache. SSDs that handle this pattern well must have:
- High random read IOPS at deep queue depth
- Aggressive read-ahead into NAND plane-level parallelism
- Large controller DRAM for FTL mapping (ZhiTai/WD are at a disadvantage here)

---

## Detailed IO characterization

### Request size distribution (per disk)

| Disk | Read req median (kB) | Read req p99 (kB) | Write req median (kB) | Write req p99 (kB) |
|---|---:|---:|---:|---:|
| Biwin X570 | 124.4 | 126.7 | 113.7 | 122.6 |
| Seagate FC530 | 124.4 | 126.2 | 113.1 | 120.6 |
| ZhiTai Ti600 | 124.7 | 127.1 | 115.9 | 126.4 |
| WD SN570 | 124.8 | 127.1 | 115.7 | 125.8 |

**All four disks show identical request-size distributions** (within 1 kB). This is expected — the request size is determined by the application (KV cache entry size, set by the model architecture), not by the disk. The fact that read median ≈ 125 kB and write median ≈ 115 kB is the fingerprint of LLaMA-3.1-8B KV cache offload.

### Randomness indicators

| Disk | %rrqm median | %rrqm p99 | %wrqm median | %wrqm p99 | Verdict |
|---|---:|---:|---:|---:|---|
| Biwin X570 | 0.0 | 0.0 | 0.1 | **76.2** | Random reads; occasional write bursts |
| Seagate FC530 | 0.0 | 0.0 | 0.1 | 4.8 | Pure random |
| ZhiTai Ti600 | 0.0 | 0.0 | 0.1 | 6.4 | Pure random |
| WD SN570 | 0.0 | 0.0 | 0.1 | 5.4 | Pure random |

**%rrqm = 0 %** means the kernel never saw two read requests at adjacent LBAs in the same sample window — the access pattern is genuinely random.
**Biwin's high %wrqm p99 (76 %)** is interesting: it indicates that during sustained write phases, the kernel merged up to 76 % of writes into larger blocks. This suggests Biwin's controller is better at *tolerating* the random write pattern (it absorbs the merges), even though it cannot avoid the cliff.

### Per-request latency (`r_await`, `w_await`)

`r_await` and `w_await` are the *device-side* service time, excluding queue time. They measure how long a single request sits at the disk before completion.

| Disk | r_await median (ms) | r_await p99 (ms) | w_await median (ms) | **w_await p99 (ms)** |
|---|---:|---:|---:|---:|
| Biwin X570 | **0.38** | 0.67 | 14.3 | 57.2 |
| Seagate FC530 | 0.80 | 1.00 | **7.1** | **24.1** |
| ZhiTai Ti600 | 0.61 | 1.20 | 119.5 | **511.2** |
| WD SN570 | 1.57 | 4.09 | 59.0 | **604.8** |

**Read service time:** Biwin is fastest (0.38 ms) — its controller + DRAM combination delivers individual reads in well under 1 ms even under random pattern.

**Write service time:** **Seagate is dramatically better than everyone else** (w_await p99 = 24 ms vs Biwin 57 ms, ZhiTai 511 ms, WD 605 ms). This is the single largest write-latency gap observed in any of our cross-vendor tests, and it's the key reason Seagate wins the long-steady-state benchmark.

### Queue depth (`aqu_sz`)

| Disk | aqu_sz median | aqu_sz p95 | aqu_sz p99 |
|---|---:|---:|---:|
| Biwin X570 | **30.4** | 74.8 | 108.0 |
| Seagate FC530 | **28.1** | **48.0** | **58.0** |
| ZhiTai Ti600 | 102.4 | 266.4 | 328.0 |
| WD SN570 | 88.8 | 235.2 | 286.9 |

**Seagate and Biwin keep the queue shallow** (median ~30, p99 ~60–110). They are able to drain requests quickly.
**ZhiTai and WD build up deep queues** (median ~90–100, p99 ~290–330). The controller cannot drain requests fast enough under the random pattern; requests pile up in the device queue. **This is a direct consequence of the random pattern** — random IO cannot be coalesced, so each request must wait its turn at the NAND plane.

---

## GC cliff timing (cliff detection)

Detected by sustained 20 % drop in read BW after 2-min warmup, with 30-s smoothing window.

| Disk | Cliff time (s) | Cliff time (min) | Peak BW (MB/s) | Post-cliff BW (MB/s) | Drop |
|---|---:|---:|---:|---:|---:|
| Biwin X570 | **175** | **2.9** | 4929 | 2927 | −40.6 % |
| ZhiTai Ti600 | 337 | 5.6 | 4385 | 973 | **−77.8 %** |
| WD SN570 | 469 | 7.8 | 2228 | 1325 | −40.6 % |
| Seagate FC530 | **483** | **8.1** | 3533 | 2402 | −32.0 % |

### Interpretation

- **Biwin's SLC cache runs out first (2.9 min).** This is consistent with the "short-burst champion, long-steady-state loser" pattern we observed in the K4 GC drift results. After cliff, Biwin still has the *highest* absolute BW (2.9 GB/s) — its TLC direct-write is fast — but it has lost 40 % of its peak.

- **Seagate's SLC cache is the largest (8.1 min).** Phison E18 + high-end NAND + DRAM combination holds the cache the longest, and the post-cliff drop is the *smallest* (−32 %). This is the structural reason Seagate wins steady-state.

- **ZhiTai's cliff is catastrophic (−77.8 %).** YMTC NAND's TLC direct-write speed is the worst of the four; once the SLC cache exhausts, throughput crashes. This is the structural reason ZhiTai is unsuitable for sustained KV cache offload.

- **WD's cliff drop is moderate but its baseline is already low.** The cliff is hard to see in absolute terms because the drive was never very fast.

### Predicted cliff locations (theory vs measured)

| Disk | Theoretical SLC cache size (from prior Biwin characterization) | Predicted cliff at KV write rate | Measured cliff |
|---|---|---|---|
| Biwin X570 | ~95 GiB SLC | at write rate 0.27 GB/s → ~350 s = 5.8 min | **2.9 min** (cliff earlier than expected) |
| Seagate FC530 | ~140 GiB (estimated) | at write rate 0.17 GB/s → ~820 s = 13.7 min | 8.1 min |
| ZhiTai Ti600 | ~60–80 GiB (estimated) | at write rate 0.10 GB/s → ~600–800 s = 10–13 min | 5.6 min |
| WD SN570 | ~30–50 GiB (estimated, DRAM-less) | at write rate 0.12 GB/s → ~250–420 s = 4–7 min | 7.8 min |

The **measured cliffs are earlier than theoretical predictions** for Biwin and Seagate, which suggests the *effective* SLC cache under sustained random write is smaller than the spec-sheet SLC cache. WD's measured cliff is later than predicted — possibly because the DRAM-less controller throttles writes early, slowing the apparent drain rate.

---

## Cross-disk conclusion

### Why each disk handles KV cache random IO differently

**Biwin X570 (mainstream, DRAM):**
- Strong baseline (peak 4.9 GB/s) thanks to good controller + DRAM
- *But:* SLC cache runs out at 3 min; the cache is not large enough to absorb sustained random writes
- Best for *short* random-IO bursts

**Seagate FC530 (high-end, Phison E18):**
- Moderate baseline (peak 3.5 GB/s) — lower than Biwin
- *But:* largest effective SLC cache (8.1 min before cliff) and smallest cliff drop (−32 %)
- **w_await p99 of 24 ms is the killer metric** — 2–25× better than other drives on write service time
- Best for *sustained* random-IO workloads

**ZhiTai Ti600 (domestic, YMTC NAND):**
- Decent baseline (peak 4.4 GB/s)
- *But:* post-cliff BW drops to <1 GB/s; w_await p99 of 511 ms means every eviction is a multi-hundred-millisecond stall
- Worst per-request write latency under sustained load — YMTC NAND struggles with random write coalescing

**WD SN570 (entry-level, DRAM-less):**
- Lowest peak (2.2 GB/s) — DRAM-less controller limits throughput from the start
- *But:* at least the cliff is moderate; the drive is just *consistently slow* rather than fast-then-collapse
- Best avoided for KV cache offload, but won't catastrophically fail

---

## Implications for AI SSD selection

1. **For LLM serving nodes running > 5 min sessions: pick the disk with the largest effective SLC cache under random write.** That is Seagate FC530.

2. **For interactive / < 3 min sessions: pick the disk with the highest peak BW under random read.** That is Biwin X570.

3. **ZhiTai is unsuitable** for any random-write-heavy workload; its post-cliff behavior is unacceptable.

4. **DRAM matters more than NAND tier.** Biwin and Seagate both have DRAM and both handle random IO well. WD's DRAM-less architecture costs it from the start.

5. **The IO pattern itself is application-locked.** KV cache entry size (125 kB) is set by the model architecture; we cannot shrink it. SSD vendors must adapt to this pattern, not the other way around.

---

## Methodology — how this analysis was done

- **Source:** `iostat -dx -m 1` output from each disk during the K4 GC drift test (4 disks × 1200 s × 1 Hz = ~4800 samples per disk).
- **Tool:** `scripts/analyze_kv_cache_iostat.py`
- **Randomness indicators:**
  - `%rrqm`, `%wrqm` from iostat — kernel block-IO scheduler merge ratio; high = sequential
  - `rareq-sz`, `wareq-sz` — average request size in kB
  - `r_await`, `w_await` — device-side service time per request
  - `aqu-sz` — average queue depth
- **GC cliff detection:** rolling 30-s window, find first sustained 20 % drop after 120-s warmup.

---

## Raw analysis

```
results/cross_vendor/kv_cache_k4_gc_drift/_analysis/iostat_analysis.json
scripts/analyze_kv_cache_iostat.py
```