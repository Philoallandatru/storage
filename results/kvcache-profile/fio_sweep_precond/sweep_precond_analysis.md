# Preconditioned SSD fio sweep — comparison

Compare the original fio iodepth sweep (fresh SSD) against the same
sweep run after 100 GB of sequential preconditioning writes.

## Preconditioning summary

- Sequential writes: `570.4 GiB`
- Sustained BW: `1936.1 MiB/s`
- Avg IOPS: `15489`
- Time: `0.0 s`

## Side-by-side comparison

| Workload | qd | | R IOPS | W IOPS | R P99 (us) | W P99 (us) |
|---|---:|---|---:|---:|---:|---:|
| burstgpt_8b_cpurel_spd1000 | 32 | fresh | 20,946 | 2,067 | 3,555 | 17,170 |
| burstgpt_8b_cpurel_spd1000 | 32 | precond | 21,704 | 2,150 | 3,588 | 268.3 |
| burstgpt_8b_cpurel_spd1000 | 64 | fresh | 21,002 | 2,067 | 9,372 | 110,625 |
| burstgpt_8b_cpurel_spd1000 | 64 | precond | - | - | - | - |
| burstgpt_8b_cpurel_spd1000 | 128 | fresh | 21,003 | 2,074 | 13,042 | 152,044 |
| burstgpt_8b_cpurel_spd1000 | 128 | precond | - | - | - | - |
| burstgpt_8b_cpurel_spd1000 | 256 | fresh | 21,065 | 2,096 | 19,268 | 227,541 |
| burstgpt_8b_cpurel_spd1000 | 256 | precond | - | - | - | - |
| burstgpt_8b_cpurel_spd1000 | 1024 | fresh | 21,057 | 2,093 | 68,682 | 476,054 |
| burstgpt_8b_cpurel_spd1000 | 1024 | precond | 21,887 | 2,163 | 62,128 | 337,641 |
| sharegpt_8b_cpuhalf | 32 | fresh | 18,636 | 11,909 | 6,521 | 1,237 |
| sharegpt_8b_cpuhalf | 32 | precond | 20,324 | 12,995 | 5,800 | 1,319 |
| sharegpt_8b_cpuhalf | 64 | fresh | 13,108 | 8,393 | 11,993 | 17,433 |
| sharegpt_8b_cpuhalf | 64 | precond | - | - | - | - |
| sharegpt_8b_cpuhalf | 128 | fresh | 13,065 | 8,354 | 17,957 | 51,642 |
| sharegpt_8b_cpuhalf | 128 | precond | - | - | - | - |
| sharegpt_8b_cpuhalf | 256 | fresh | 12,576 | 8,039 | 28,443 | 102,236 |
| sharegpt_8b_cpuhalf | 256 | precond | - | - | - | - |
| sharegpt_8b_cpuhalf | 1024 | fresh | 11,536 | 7,380 | 166,724 | 379,585 |
| sharegpt_8b_cpuhalf | 1024 | precond | 13,268 | 8,503 | 111,673 | 221,250 |
| tp8_cpuhalf_generic | 32 | fresh | 13,322 | 4,922 | 5,079 | 12,124 |
| tp8_cpuhalf_generic | 32 | precond | 14,785 | 5,452 | 5,014 | 995.3 |
| tp8_cpuhalf_generic | 64 | fresh | 13,466 | 4,980 | 12,911 | 81,265 |
| tp8_cpuhalf_generic | 64 | precond | - | - | - | - |
| tp8_cpuhalf_generic | 128 | fresh | 13,216 | 4,890 | 20,054 | 145,752 |
| tp8_cpuhalf_generic | 128 | precond | - | - | - | - |
| tp8_cpuhalf_generic | 256 | fresh | 13,293 | 4,918 | 29,753 | 206,569 |
| tp8_cpuhalf_generic | 256 | precond | - | - | - | - |
| tp8_cpuhalf_generic | 1024 | fresh | 13,317 | 4,949 | 156,238 | 480,248 |
| tp8_cpuhalf_generic | 1024 | precond | 14,901 | 5,521 | 79,167 | 196,084 |

## Percent change (preconditioned vs fresh)

Positive % on IOPS = better (more throughput). Negative % on P99 = better (lower latency).

| Workload | qd | R IOPS Δ | R P99 Δ | W IOPS Δ | W P99 Δ |
|---|---:|---:|---:|---:|---:|
| burstgpt_8b_cpurel_spd1000 | 32 | +4% | +1% | +4% | -98% |
| burstgpt_8b_cpurel_spd1000 | 1024 | +4% | -10% | +3% | -29% |
| sharegpt_8b_cpuhalf | 32 | +9% | -11% | +9% | +7% |
| sharegpt_8b_cpuhalf | 1024 | +15% | -33% | +15% | -42% |
| tp8_cpuhalf_generic | 32 | +11% | -1% | +11% | -92% |
| tp8_cpuhalf_generic | 1024 | +12% | -49% | +12% | -59% |
