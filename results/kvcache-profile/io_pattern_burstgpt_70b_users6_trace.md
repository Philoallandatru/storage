# I/O Pattern Analysis — `results/kvcache-profile/profiling/burstgpt_70b_users6_full_20260608_113434/kv_trace.csv.zst`

Total operations: **94,883**
Total bytes: **2756.83 GiB**
Duration: **301 seconds**

## By Operation Type

| Op | Count | % of total |
|---|---:|---:|
| Read | 85,458 | 90.1% |
| Write | 9,425 | 9.9% |

## By Tier

| Tier | Count | % of total |
|---|---:|---:|
| Tier-0 | 2,238 | 2.4% |
| Tier-2 | 92,645 | 97.6% |

## Tier × Operation

| Tier | Read | Write |
|---|---:|---:|
| Tier-0 | 1,492 | 746 |
| Tier-2 | 83,966 | 8,679 |

## By Phase

| Phase | Count | % of total |
|---|---:|---:|
| Decode | 85,458 | 90.1% |
| Prefill | 9,425 | 9.9% |

## Object Size Distribution (bytes)

- count: 94,883
- sum:   2822989.2 MiB (2756.83 GiB)
- mean:  31197567 (30466.4 KiB)
- p50:   25190400 (24600.0 KiB)
- p95:   77905920 (76080.0 KiB)
- p99:   91832320 (89680.0 KiB)
- max:   139550720 (133.1 MiB)

## Size by Phase (bytes)

| Phase | Count | Mean | P50 | P95 | P99 |
|---|---:|---:|---:|---:|---:|
| Decode | 85,458 | 31881475 | 26542080 | 78151680 | 92528640 |
| Prefill | 9,425 | 24996460 | 17244160 | 73605120 | 85755494 |
