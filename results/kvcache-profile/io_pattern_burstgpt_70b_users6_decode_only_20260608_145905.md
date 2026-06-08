# I/O Pattern Analysis — `results/kvcache-profile/profiling/burstgpt_70b_users6_decode_only_20260608_145905/kv_trace.csv.zst`

Total operations: **85,550**
Total bytes: **6683.59 GiB**
Duration: **301 seconds**

## By Operation Type

| Op | Count | % of total |
|---|---:|---:|
| Read | 85,490 | 99.9% |
| Write | 60 | 0.1% |

## By Tier

| Tier | Count | % of total |
|---|---:|---:|
| Tier-2 | 85,550 | 100.0% |

## Tier × Operation

| Tier | Read | Write |
|---|---:|---:|
| Tier-2 | 85,490 | 60 |

## By Phase

| Phase | Count | % of total |
|---|---:|---:|
| Decode | 85,490 | 99.9% |
| Prefill | 60 | 0.1% |

## Object Size Distribution (bytes)

- count: 85,550
- sum:   6844000.0 MiB (6683.59 GiB)
- mean:  83886080 (81920.0 KiB)
- p50:   83886080 (81920.0 KiB)
- p95:   83886080 (81920.0 KiB)
- p99:   83886080 (81920.0 KiB)
- max:   83886080 (80.0 MiB)

## Size by Phase (bytes)

| Phase | Count | Mean | P50 | P95 | P99 |
|---|---:|---:|---:|---:|---:|
| Decode | 85,490 | 83886080 | 83886080 | 83886080 | 83886080 |
| Prefill | 60 | 83886080 | 83886080 | 83886080 | 83886080 |
