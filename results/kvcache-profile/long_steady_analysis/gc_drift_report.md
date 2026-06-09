# Long Steady-State Run — GC Drift Analysis

Total runtime: 1810 s (30.2 min)
Total iostat samples: 1810

## Overall Statistics

| Metric | Value |
|---|---:|
| Avg Read BW | 2081.69 MB/s |
| Avg Write BW | 267.82 MB/s |
| Avg Read IOPS | 17049.1 |
| Avg Write IOPS | 2204.2 |
| Avg %util | 59.55 % |
| Avg await | 2.51 ms |
| Peak %util | 79.70 % |
| Peak await | 25.21 ms |

## GC Drift — 5-minute Window Comparison

This shows whether SSD behavior changes over a long run
(early vs middle vs late).

| Window | R MB/s | W MB/s | R IOPS | W IOPS | %util | await | await P95 | await max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-299s | 2981.13 | 275.10 | 24456.4 | 2254.3 | 61.30 | 1.19 | 2.98 | 6.65 |
| 300-599s | 2702.94 | 244.28 | 22137.4 | 2003.5 | 68.58 | 1.68 | 3.63 | 5.81 |
| 600-899s | 2332.23 | 231.42 | 19150.8 | 1913.2 | 63.04 | 1.57 | 3.71 | 7.50 |
| 900-1199s | 1671.79 | 295.97 | 13621.9 | 2431.4 | 57.80 | 3.72 | 7.75 | 20.67 |
| 1200-1499s | 2008.38 | 335.00 | 16274.8 | 2736.4 | 64.45 | 3.76 | 7.23 | 15.52 |
| 1500-1799s | 843.77 | 230.62 | 7055.3 | 1930.6 | 43.26 | 3.15 | 8.01 | 25.21 |
| 1800-1809s | 578.98 | 103.32 | 4982.9 | 874.3 | 26.36 | 1.68 | 5.59 | 5.59 |

## Drift Detection

- First window %util: 61.30 %
- Last window %util:  26.36 %
- Drift: -34.94 % (positive = SSD busier)
- First window await: 1.19 ms
- Last window await:  1.68 ms
- Drift: +0.49 ms (positive = slower)

**Conclusion**: Mixed signal — investigate further.
