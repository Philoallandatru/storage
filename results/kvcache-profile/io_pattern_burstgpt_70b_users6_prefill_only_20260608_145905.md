# I/O Pattern Analysis — `results/kvcache-profile/profiling/burstgpt_70b_users6_prefill_only_20260608_145905/kv_trace.csv.zst`

Total operations: **9,425**
Total bytes: **219.41 GiB**
Duration: **300 seconds**

## By Operation Type

| Op | Count | % of total |
|---|---:|---:|
| Write | 9,425 | 100.0% |

## By Tier

| Tier | Count | % of total |
|---|---:|---:|
| Tier-0 | 746 | 7.9% |
| Tier-2 | 8,679 | 92.1% |

## Tier × Operation

| Tier | Read | Write |
|---|---:|---:|
| Tier-0 | 0 | 746 |
| Tier-2 | 0 | 8,679 |

## By Phase

| Phase | Count | % of total |
|---|---:|---:|
| Prefill | 9,425 | 100.0% |

## Object Size Distribution (bytes)

- count: 9,425
- sum:   224677.7 MiB (219.41 GiB)
- mean:  24996460 (24410.6 KiB)
- p50:   17244160 (16840.0 KiB)
- p95:   73605120 (71880.0 KiB)
- p99:   85755494 (83745.6 KiB)
- max:   139550720 (133.1 MiB)

## Size by Phase (bytes)

| Phase | Count | Mean | P50 | P95 | P99 |
|---|---:|---:|---:|---:|---:|
| Prefill | 9,425 | 24996460 | 17244160 | 73605120 | 85755494 |
