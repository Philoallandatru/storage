# I/O Pattern Analysis — `results/kvcache-profile/profiling/burstgpt_8b_users8_full_20260608_114639/kv_trace.csv.zst`

Total operations: **94,801**
Total bytes: **1100.75 GiB**
Duration: **300 seconds**

## By Operation Type

| Op | Count | % of total |
|---|---:|---:|
| Read | 85,383 | 90.1% |
| Write | 9,418 | 9.9% |

## By Tier

| Tier | Count | % of total |
|---|---:|---:|
| Tier-0 | 2,238 | 2.4% |
| Tier-2 | 92,563 | 97.6% |

## Tier × Operation

| Tier | Read | Write |
|---|---:|---:|
| Tier-0 | 1,492 | 746 |
| Tier-2 | 83,891 | 8,672 |

## By Phase

| Phase | Count | % of total |
|---|---:|---:|
| Decode | 85,383 | 90.1% |
| Prefill | 9,418 | 9.9% |

## Object Size Distribution (bytes)

- count: 94,801
- sum:   1127164.0 MiB (1100.75 GiB)
- mean:  12467348 (12175.1 KiB)
- p50:   10076160 (9840.0 KiB)
- p95:   31162368 (30432.0 KiB)
- p99:   36667392 (35808.0 KiB)
- max:   55820288 (53.2 MiB)

## Size by Phase (bytes)

| Phase | Count | Mean | P50 | P95 | P99 |
|---|---:|---:|---:|---:|---:|
| Decode | 85,383 | 12740367 | 10616832 | 31260672 | 37011456 |
| Prefill | 9,418 | 9992179 | 6897664 | 29442048 | 34111160 |
