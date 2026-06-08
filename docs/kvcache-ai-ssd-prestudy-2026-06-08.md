# KV Cache AI SSD Pre-Study Report

Date: 2026-06-08

Workspace: `/home/ficus/llm/storage`

Benchmark: `kv_cache_benchmark`

## Executive Summary

This report summarizes the KV cache experiments run for AI SSD product pre-study. The tests covered synthetic stress workloads, ShareGPT real conversation replay, BurstGPT production API trace replay, tensor-parallel object-size scaling, CPU cache sensitivity, user saturation, and Linux I/O profiling with `bpftrace`, `iostat`, and distilled `fio` workloads.

The most important result is that workload shape dominates the SSD requirement. Synthetic long-context workloads create large KV cache objects and can find the failure boundary. ShareGPT is realistic for chat, but has small contexts and very high cache locality, so it is a light SSD workload. BurstGPT with `--trace-speedup 1000` and `--cpu-mem-gb 0` is the best current production-trace SSD baseline: it drives all KV I/O to storage while preserving production-like request/token distributions.

Current baseline conclusions:

- Synthetic `llama3.1-8b`, TP8, CPU cache 0.5GB, 300s: maximum stable concurrency is `users=2`; `users=3` is the first clear failure.
- ShareGPT `llama3.1-8b`, TP8, CPU cache 0.5GB, `users=2`, 300s: PASS with large margin, but storage pressure is light.
- BurstGPT `llama3.1-8b`, TP8, CPU cache 0GB, `--trace-speedup 1000`, 300s: PASS through `users=8`; SSD utilization is meaningful but not saturated.
- BurstGPT `llama3.1-70b-instruct`, TP8, CPU cache 0GB, `users=2`, 300s: PASS. This is the first larger-model validation point and should be expanded.

### Related artifacts

The artifacts below are published alongside this report in the repository. They are intentionally tracked even though most of `results/` is `.gitignore`-d:

| Artifact | Why it is tracked |
|---|---|
| [`docs/kvcache-io-profiling-visual-analysis-2026-06-08.md`](../kvcache-io-profiling-visual-analysis-2026-06-08.md) and `docs/assets/kvcache-io-profiling/*` | Final I/O profiling report + 5 charts (PNG/SVG) + 3 distilled CSVs. This is the post-burstgpt view. |
| [`../results/kvcache-profile/report/kvcache_ai_ssd_baseline_report.pdf`](../results/kvcache-profile/report/kvcache_ai_ssd_baseline_report.pdf) (and `.html`, `.md`) | Early-stage baseline at `users=10`, generated 2026-06-07 15:39. This run **failed** (`Storage I/O P95 ≈ 19.6 s`, `read device P95 ≈ 3.2 s`, only 1/4 criteria passed) and motivated the TP + concurrency rework that led to the stable `users=2` baseline above. Useful as a historical reference; superseded by the current report. |
| [`../results/kvcache-profile/report/`](../results/kvcache-profile/report/) (PNG/SVG/CSV charts from that early baseline) | Companion charts for the early `users=10` baseline report. |
| [`../results/kvcache-profile/visualizations/kvcache_io_profile_visual_summary.xlsx`](../results/kvcache-profile/visualizations/kvcache_io_profile_visual_summary.xlsx) | Companion Excel with the visual-analysis charts in a single workbook. |

## Why KV Cache Stresses Storage

LLM inference stores attention state in the KV cache. The cache grows with sequence length. A request with more context tokens writes a larger KV object; decode then repeatedly reads that object while generating output tokens.

In this benchmark, one KV cache entry is stored as a `.npy` object. The storage latency numbers in the benchmark are per KV object, not per 4KiB disk page. A single object can be tens of MiB to multiple GiB depending on model, sequence length, and tensor parallelism. The Linux block layer then splits that object into many smaller NVMe commands, usually dominated by 128KiB requests.

This distinction explains the main observation:

- NVMe command latency can be very low, for example D2C read P99 under 1ms.
- KV object latency can still be tens or hundreds of milliseconds because it includes many block I/Os plus filesystem, VFS, Python, and NumPy object handling.

## Key Terms

- KV cache: Key/Value attention state saved during LLM inference so previous tokens do not need to be recomputed.
- Prefill: Prompt processing phase. It is write-heavy because it creates new KV cache entries.
- Decode: Token generation phase. It is read-heavy because it repeatedly reads existing KV cache entries.
- TP / Tensor Parallelism: Splits model tensors across ranks. In this benchmark, TP divides per-rank KV object size. TP8 makes each per-rank KV object roughly one eighth of TP1.
- CPU cache: DRAM spill tier. Larger CPU cache can hide SSD pressure.
- Storage tier: Filesystem path passed as `--cache-dir`. The docs call it NVMe, but it can be any mounted storage.
- Device P95 in benchmark: Per KV object "device" timing, not pure NVMe controller latency. For reads it includes `np.load()` and file I/O. For writes it includes flush and `fsync()`.
- D2C: Device-to-completion latency from bpftrace. This is closer to actual per-command block device latency.
- Q2D: Queue-to-dispatch latency in the Linux I/O scheduler.
- VFS latency: Application-visible filesystem syscall latency.
- bssplit: Block size distribution used by fio. In these tests, 128KiB dominated most real storage traffic.

## Test Matrix Summary

| Case | Status | Requests | tok/s | req/s | Storage IO P95 ms | Read dev P95 ms | Write dev P95 ms | Storage read GiB | Storage write GiB | Hit rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Synthetic baseline TP1 users10 | FAIL | 125 | 217.62 | 1.04 | 19635.46 | 3167.48 | 924.69 | 334.99 | 13.12 | 72.79 |
| Synthetic TP8 users4 clean 120s | PASS | 648 | 1356.02 | 5.40 | 902.16 | 163.66 | n/a | 71.34 | 0.00 | 78.98 |
| Synthetic TP8 CPU0.5 users4 300s | FAIL | 1290 | 1100.78 | 4.30 | 1500.16 | 233.84 | n/a | 328.00 | 0.00 | 79.32 |
| Synthetic TP8 CPU0.5 users1 300s | PASS | 438 | 437.10 | 1.46 | 823.67 | 74.33 | n/a | 156.51 | 0.00 | 76.80 |
| Synthetic TP8 CPU0.5 users2 300s | PASS | 1137 | 755.96 | 3.79 | 771.46 | 198.74 | 116.44 | 140.78 | 0.20 | 81.39 |
| Synthetic TP8 CPU0.5 users3 300s | FAIL | 1051 | 684.73 | 3.50 | 1452.01 | 255.07 | 141.83 | 253.49 | 0.25 | 73.29 |
| Synthetic TP8 CPU0.5 users4 300s | FAIL | 1104 | 953.49 | 3.68 | 2151.83 | 277.23 | n/a | 322.02 | 0.00 | 76.51 |
| ShareGPT io trace users2 | PASS | 11185 | 11531.07 | 37.14 | 0.00 | 0.00 | n/a | 203.14 | 0.00 | 98.20 |
| ShareGPT real IO users2 | PASS | 1724 | 1510.56 | 5.74 | 937.41 | 62.47 | n/a | 9.79 | 0.00 | 97.74 |
| ShareGPT profile users2 | PASS | 1678 | 1460.33 | 5.58 | 927.11 | 67.56 | n/a | 9.10 | 0.00 | 97.91 |
| BurstGPT sparse profile CPU0.5 users2 | PASS | 8 | 12.79 | 0.03 | 23.45 | n/a | n/a | 0.00 | 0.00 | 97.78 |
| BurstGPT speedup1000 CPU0.5 users2 | PASS | 9263 | 7418.91 | 30.88 | 33.50 | n/a | n/a | 0.00 | 0.00 | 97.79 |
| BurstGPT speedup1000 CPU0 users2 | PASS | 6515 | 5239.66 | 21.72 | 230.56 | 12.62 | 9.18 | 692.68 | 59.78 | 97.77 |
| BurstGPT speedup1000 CPU0 profile users2 | PASS | 5748 | 4632.68 | 19.16 | 282.58 | 17.96 | 18.90 | 614.97 | 52.48 | 97.75 |
| BurstGPT speedup1000 CPU0 users4 | PASS | 7118 | 5685.54 | 23.73 | 451.45 | 31.54 | 55.64 | 754.29 | 65.63 | 97.74 |
| BurstGPT speedup1000 CPU0 users6 | PASS | 7056 | 5631.62 | 23.52 | 647.24 | 41.54 | 114.54 | 756.74 | 65.52 | 97.73 |
| BurstGPT speedup1000 CPU0 users8 | PASS | 7339 | 5859.44 | 24.46 | 705.99 | 46.48 | 118.44 | 781.09 | 67.74 | 97.77 |
| BurstGPT 70B speedup1000 CPU0 users2 | PASS | 2421 | 1975.81 | 8.07 | 815.83 | 41.85 | 18.68 | 648.39 | 55.06 | 97.86 |

## Synthetic Workload Findings

Synthetic tests are useful because they can deliberately create high pressure. They are less representative of normal chat traffic, but they are the best way to find the failure boundary.

The initial TP1, users=10 run failed badly:

- Storage read device P95: 3167.48ms.
- Storage write device P95: 924.69ms.
- Storage I/O P95: 19635.46ms.

This was not a reasonable target configuration for the local PC. The KV objects were too large.

TP scaling was the strongest improvement. Moving to TP8 reduced per-rank object size and brought read latency close to or below the 200ms target. However, 300s testing showed that short runs can be misleading. TP8, CPU0.5GB, users=4 passed in some short cases but failed in 300s steady state:

- Storage read device P95: 233.84ms.
- Storage I/O P95: 1500.16ms.

The final synthetic concurrency boundary was:

- users=1: PASS with large margin.
- users=2: PASS, confirmed by three repeated 300s runs.
- users=3: FAIL.
- users=4: FAIL.

For synthetic long-context stress, the current system baseline is therefore:

```text
model: llama3.1-8b
TP: 8
CPU cache: 0.5GB
duration: 300s
maximum stable concurrency: users=2
first failure point: users=3
```

## ShareGPT Findings

ShareGPT provides real conversation structure. It is useful for checking realistic chat behavior, not worst-case SSD stress.

The logical trace run produced 127,477 KV operations and showed very high locality:

- Cache hit rate: 98.20%.
- Mean KV block size: about 2.1MiB.
- P95 KV block size: about 12.5MiB.
- Max KV block size: about 113.6MiB.

The real I/O baseline and profiling runs both passed with large margin:

- Storage read device P95: 62.47ms to 67.56ms.
- Storage read total P95: about 100ms to 109ms.
- Storage read volume: about 9GiB to 10GiB over 300s.

The bpftrace/iostat profile confirmed that the SSD was not saturated:

- D2C read P99: 128us.
- D2C write P99: 4096us.
- iostat r_await P95: 1.5ms.
- iostat w_await P95: 2.6ms.
- Device utilization P95: 8.0%.

Interpretation: ShareGPT is a good "real chat passes comfortably" test, but it should not be used alone for AI SSD product qualification because it hides storage pressure through small objects and high cache locality.

## BurstGPT Findings

The first BurstGPT run without speedup was too sparse:

- Only 8 requests completed in 300s.
- No storage tier reads or writes were recorded.

After adding `--trace-speedup 1000`, request density became useful. With CPU cache still enabled, the working set stayed in CPU memory and did not test the SSD. Setting `--cpu-mem-gb 0` forced all KV I/O to storage and produced a valid storage workload.

The key BurstGPT profile was:

```text
model: llama3.1-8b
TP: 8
CPU cache: 0GB
users: 2
duration: 300s
trace-speedup: 1000
```

This run passed:

- Storage read device P95: 17.96ms.
- Storage write device P95: 18.90ms.
- Storage read: 614.97GiB.
- Storage write: 52.48GiB.
- Read mix from fio distiller: 91%.

Block-layer profiling showed:

- Total traced I/Os: 5,856,651.
- D2C read P99: 256us.
- D2C write P99: 4096us.
- Read block size: 128KiB was 92%.
- Write block size: 128KiB was 94%.

iostat on the active device `nvme1n1` showed:

- Read IOPS average: 17,694.
- Read IOPS P95: 25,449.
- Read bandwidth average: about 2.04GiB/s.
- Read bandwidth P95: about 2.96GiB/s.
- Write bandwidth average: about 203MiB/s.
- Write bandwidth P95: about 303MiB/s.
- r_await P95: 0.16ms.
- w_await P95: 6.6ms.
- Utilization average: 55.0%.
- Utilization P95: 69.2%.

The users gradient with CPU0, TP8, speedup1000 remained PASS through users=8:

- users=2: read device P95 12.62ms, write device P95 9.18ms.
- users=4: read device P95 31.54ms, write device P95 55.64ms.
- users=6: read device P95 41.54ms, write device P95 114.54ms.
- users=8: read device P95 46.48ms, write device P95 118.44ms.

This is the strongest evidence that current storage has comfortable margin under a production-like API trace when KV objects are small after TP8 sharding.

## Larger Model Probe

A first `llama3.1-70b-instruct` BurstGPT run was started to increase KV bytes per token:

```text
model: llama3.1-70b-instruct
TP: 8
CPU cache: 0GB
users: 2
duration: 300s
trace-speedup: 1000
```

This run passed:

- Requests: 2421.
- Throughput: 1975.81 tokens/s.
- Storage I/O P95: 815.83ms.
- Storage read device P95: 41.85ms.
- Storage write device P95: 18.68ms.
- Storage read: 648.39GiB.
- Storage write: 55.06GiB.

This should be expanded with users=4, users=6, and users=8. It is more relevant to AI SSD product positioning than 8B alone because the KV cache per token is larger.

## Product Interpretation

For AI SSD pre-study, the storage product should not be evaluated with a single workload. Three workload families are needed:

- Synthetic: finds worst-case object-size and concurrency limits.
- ShareGPT: proves realistic chat is easy and validates full pipeline.
- BurstGPT: gives production-like API trace behavior and better SSD utilization.

Current data suggests:

- The local SSD is not limited by single NVMe command latency. D2C read P99 is typically hundreds of microseconds in the effective profiles.
- The synthetic failures are caused by object-level KV cache latency and host-path aggregation, not raw 4KiB/128KiB NVMe command latency.
- TP is a first-order tuning knob because it reduces per-rank KV object size.
- CPU cache can completely hide SSD traffic. For SSD product testing, CPU cache should be set to 0 or tightly controlled.
- ShareGPT should be reported as realistic chat validation, not as maximum SSD stress.
- BurstGPT CPU0 speedup1000 is the current best repeatable product baseline.

## Recommended Next Tests

Run these before drawing final product-level conclusions:

1. BurstGPT 70B users gradient: users=4, 6, 8.
2. Profile the final PASS and first FAIL point in the 70B gradient with bpftrace and iostat.
3. Add SSD preconditioning for at least BurstGPT CPU0 and synthetic users=2/3 tests.
4. Run prefill-only and decode-only modes for BurstGPT CPU0 to separate write and read behavior.
5. Convert distilled fio profiles into controlled fio sweeps with realistic iodepth values such as 32, 64, 128, and 256. Do not blindly use generated iodepth values like 524288.

## Reproducibility Notes

Important local output files were intentionally not added to Git:

- `results/kvcache-profile/*.json`
- `results/kvcache-profile/*.xlsx`
- `results/kvcache-profile/bpftrace*.txt`
- `results/kvcache-profile/iostat*.txt`
- `results/kvcache-profile/fio*.ini`
- `datasets/`

The raw bpftrace files are large, with some files around 1.2GiB each. They are useful locally but should not be uploaded to the repository. This report contains the distilled results needed for review.

## Conversation Export Summary

This section exports the working conversation as a compact timeline.

1. The project was inspected as an MLPerf Storage KV cache benchmark for LLM inference storage offload.
2. The first run failed because `/mnt/ai-ssd` was not writable. The cache directory was moved to project-local results paths.
3. Initial users=10 synthetic runs showed memory risk and high storage latency.
4. bpftrace setup initially failed because sudo required a terminal; standalone bpftrace commands were used.
5. Synthetic baseline, prefill-only, decode-only, users gradient, TP gradient, and CPU cache gradient were run.
6. The key synthetic finding was that TP8 reduces object size and that TP8 CPU0.5 users=2 is the stable 300s boundary.
7. Disk space was exhausted by raw cache directories and `/tmp` traces. Cache directories were cleaned and future commands used project-local paths.
8. The report/PDF workflow was discussed earlier; later focus shifted to I/O profiling and production trace workflows.
9. ShareGPT dataset replay was added. The io-trace mode produced a compact logical trace; the real I/O and profiling runs showed high cache locality and light SSD pressure.
10. BurstGPT was added. The initial run was too sparse, so `--trace-speedup 1000` was introduced.
11. BurstGPT with CPU cache 0.5GB did not touch storage; CPU cache was set to 0 to force SSD traffic.
12. BurstGPT CPU0 speedup1000 produced the best production-like SSD baseline and was profiled with bpftrace and iostat.
13. The user then requested a larger model; a first 70B BurstGPT CPU0 users=2 run completed and passed.
14. This document was created to preserve the experiment history, conclusions, and next steps while excluding large local artifacts from Git.

