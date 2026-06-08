# I/O Pattern Analysis — `results/kvcache-profile/profiling/burstgpt_8b_tp8_cpu0g_users32_20260608_215751/kv_trace.csv.zst`

Total operations: **94,883**
Total bytes: **1102.73 GiB**
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
- sum:   1129195.7 MiB (1102.73 GiB)
- mean:  12479027 (12186.5 KiB)
- p50:   10076160 (9840.0 KiB)
- p95:   31162368 (30432.0 KiB)
- p99:   36732928 (35872.0 KiB)
- max:   55820288 (53.2 MiB)

## Size by Phase (bytes)

| Phase | Count | Mean | P50 | P95 | P99 |
|---|---:|---:|---:|---:|---:|
| Decode | 85,458 | 12752590 | 10616832 | 31260672 | 37011456 |
| Prefill | 9,425 | 9998584 | 6897664 | 29442048 | 34302198 |
