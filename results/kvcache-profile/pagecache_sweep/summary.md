
=== Page Cache Sensitivity Sweep — 20260609_143617 ===

Cell                 |  R BW (MiB/s) |  W BW (MiB/s) |     R IOPS |    R P50 |    R P99 |  Sys Cached (MiB)
--------------------------------------------------------------------------------------------------------------
dram_32gb            |        1294.0 |         127.0 |          0 |      102 |      202 |           23797.1
dram_8gb             |        1231.0 |         121.0 |          0 |       97 |      269 |           24083.4
dram_8gb_evict       |        1158.0 |         114.0 |          0 |      115 |      258 |           23206.7
dram_unlimited       |        1071.0 |         104.0 |          0 |      121 |      277 |           22704.6

=== iostat device-level (avg over run) ===

Cell                 |      r/s |      w/s |    rMB/s |    wMB/s |    await |  %util
-----------------------------------------------------------------------------------------------
dram_32gb            |       20 |        2 |      0.0 |      0.0 |     6.83 |    0.0
dram_8gb             |       30 |        2 |      0.0 |      0.0 |     7.70 |    0.0
dram_8gb_evict       |       21 |        2 |      0.0 |      0.0 |     8.08 |    0.0
dram_unlimited       |       22 |        2 |      0.0 |      0.0 |     6.81 |    0.0

=== READ BW delta vs dram_unlimited (1071 MiB/s) ===
  dram_32gb           :  1294.0 MiB/s (+20.8%)
  dram_8gb            :  1231.0 MiB/s (+14.9%)
  dram_8gb_evict      :  1158.0 MiB/s (+8.1%)
  dram_unlimited      :  1071.0 MiB/s (+0.0%)
