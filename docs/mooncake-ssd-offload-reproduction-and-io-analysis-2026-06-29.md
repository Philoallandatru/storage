# Mooncake SSD Offload 复测与综合 I/O 分析

**日期:** 2026-06-29  
**正式 run:** `/home/ficus/mooncake_smoke_test/ssd_retest_formal_20260629_074959`  
**图表与派生数据:** `docs/assets/mooncake-ssd-offload-final-formal-20260629/`  
**官方对照:** <https://kvcache-ai.github.io/Mooncake/performance/ssd-offload-benchmark-results.html>

## 结论

这次复测已经真正触发了 Mooncake SSD offload 路径，可以画出和官方页面同结构的本地图，包括整体性能、per-round TTFT/cache hit、NVMe I/O 证据。

但这不是“完全等价官方环境”的 benchmark。它证明的是：在本地 RTX 5080 单卡、Qwen3-4B、TCP localhost、10GB Mooncake pool、8 clients、8 rounds 的压力下，`+Mooncake+SSD` 相比 `+Mooncake` 复现了更高 cache hit 和更低 TTFT 的趋势；同时 Mooncake storage layer 在该压力下仍出现 `insufficient space` 和少量 `OBJECT_ALREADY_EXISTS`，所以性能数字应解释为本地压力复测结果，不应包装成无异常生产级吞吐结论。

## 旧主测报告的问题

旧报告 `/home/ficus/llm/infer/ai_ssd_prestudy/docs/mooncake-ssd-offload-main-test-report-2026-06-26.md` 的数据可以从 `bench.log` 复现，但它不能作为 SSD offload 性能报告。

关键原因是 SSD 路径没有被触发：

| 旧 run: `main_bench_20260626_123456/04_mooncake_ssd` | 计数 |
|---|---:|
| `Storage root directory is:` | 0 |
| `Storage root directory is not set` | 1 |
| `IsEnableOffloading result: true` | 0 |
| `offload key count: [1-9]` | 0 |
| `read store: [1-9]` | 0 |
| `O_DIRECT mode enabled` | 0 |

旧报告自己也写了 `Mooncake+SSD vs Mooncake 完全一致` 和 `SSD offload 路径没被触发`。因此它最多能说明 Mooncake DRAM cache 在本地配置下的效果，不能说明 SSD offload 的性能收益。

## 为什么之前没有触发 SSD 路径

从旧日志看，Mooncake 客户端没有拿到有效的 SSD offload root，也没有开启 file storage offload：

- 没有 `Storage root directory is: ...`
- 出现 `Storage root directory is not set`
- 没有 `IsEnableOffloading result: true`
- 没有 offload read/write 文件路径和 O_DIRECT 打开记录
- `+Mooncake` 与 `+Mooncake+SSD` 的 TTFT、throughput、cache hit 几乎完全重合

根因不是单纯“压力不够”，而是启动链路没有把 SSD offload 配置完整传到 Mooncake/SGLang 运行时。重新测试时必须同时满足：

- `mooncake_master -enable_offload=true -root_fs_dir=/mnt/ai_ssd0/mooncake_ssd0/file_storage`
- SGLang Mooncake config 中设置 `"enable_ssd_offload": true` 和 `"ssd_offload_path": "..."`
- SGLang server 环境变量显式设置 `MOONCAKE_ENABLE_SSD_OFFLOAD=true`、`MOONCAKE_OFFLOAD_FILE_STORAGE_PATH=...`、`MOONCAKE_OFFLOAD_LOCAL_BUFFER_SIZE_BYTES=...`
- 每个配置运行前清空 offload 目录，避免 GPU-only/HiCache 误读上一次遗留文件
- 采集 `server.log`、`master.log`、`iostat.log`、offload 目录 inventory，而不是只看 `bench.log`

## 正式复测配置

配置来自 `/home/ficus/mooncake_smoke_test/ssd_retest_formal_20260629_074959/config.env`：

| 项 | 值 |
|---|---|
| 模型 | `/home/ficus/llm/models/Qwen/Qwen3-4B-Instruct-2507` |
| Benchmark | `/home/ficus/llm/infer/ai_ssd_prestudy/sglang_repo/benchmark/hicache/bench_multiturn.py` |
| 配置组 | `gpu_only,hicache_l1_l2,mooncake_only,mooncake_ssd` |
| Clients / rounds | 8 clients, 8 rounds |
| Request / output length | 3072 input tokens, 1 output token |
| Request rate / max parallel | 8 req/s, max parallel 2 |
| Mooncake segment | 10GB / `10737418240` bytes |
| SSD offload buffer | `2147483648` bytes |
| SSD offload dir | `/mnt/ai_ssd0/mooncake_ssd0/file_storage` |
| Transport | TCP localhost, `P2PHANDSHAKE` |

`mooncake_ssd/mooncake_config.json` 中明确包含：

```json
{
  "global_segment_size": "10GB",
  "protocol": "tcp",
  "master_server_address": "127.0.0.1:50051",
  "standalone_storage": false,
  "enable_ssd_offload": true,
  "ssd_offload_path": "/mnt/ai_ssd0/mooncake_ssd0/file_storage"
}
```

## SSD 路径已触发的证据

正式 run 的 `mooncake_ssd` 原始日志和 inventory 显示：

| 证据 | 值 |
|---|---:|
| `Storage root directory is:` | 1 |
| `IsEnableOffloading result: true` | 1 |
| `offload key count: [1-9]` | 52 |
| `read store: [1-9]` | 52 |
| `O_DIRECT mode enabled` | 1341 |
| offload 文件数 | 5402 |
| offload 目录容量 | 41 GiB |
| max offload keys/read | 250 |
| iostat max write | 551.71 MB/s |
| iostat max read | 205.69 MB/s |

这和旧 run 的差别是实质性的：旧 run 没有 SSD root、没有 enable、没有 offload read、没有 O_DIRECT；新 run 全部出现。

## 性能结果

派生数据：`docs/assets/mooncake-ssd-offload-final-formal-20260629/summary.csv`

| 配置 | Avg TTFT | P90 TTFT | Input throughput | Cache hit |
|---|---:|---:|---:|---:|
| GPU only | 4.887s | 11.967s | 3600.5 tok/s | 4.35% |
| HiCache L1+L2 | 4.253s | 9.838s | 3915.9 tok/s | 20.36% |
| +Mooncake | 4.151s | 9.836s | 3981.8 tok/s | 23.84% |
| +Mooncake+SSD | 3.436s | 8.007s | 4469.9 tok/s | 67.76% |

相对提升：

| 对比 | Avg TTFT | Input throughput |
|---|---:|---:|
| `+Mooncake+SSD` vs GPU only | 降低 29.7% | 提升 24.1% |
| `+Mooncake+SSD` vs `+Mooncake` | 降低 17.2% | 提升 12.3% |

![overall](assets/mooncake-ssd-offload-final-formal-20260629/01_overall_performance_local.png)

## Per-round 形态

派生数据：`docs/assets/mooncake-ssd-offload-final-formal-20260629/per_round.csv`

`+Mooncake+SSD` 的 per-round cache hit：

| Round | Cache hit | Avg TTFT |
|---:|---:|---:|
| 0 | 0.00% | 0.522s |
| 1 | 49.99% | 0.781s |
| 2 | 66.65% | 1.026s |
| 3 | 74.98% | 2.743s |
| 4 | 79.98% | 5.884s |
| 5 | 71.51% | 5.076s |
| 6 | 79.14% | 3.787s |
| 7 | 57.08% | 7.667s |

和官方页面的逻辑一致：SSD offload 的价值不是 round 0 冷启动，而是在 Mooncake memory pool 压力上来之后，让被 eviction 的 KV cache 仍可从 NVMe 找回，避免完全重算。

不同点也必须说明：官方 DGX run 在 round 7 之后出现非常清楚的 `+Mooncake` cliff，而本地 run 是单卡、小模型、小并发、TCP localhost、10GB pool，曲线更受 GPU 排队和 Mooncake storage warning 影响，不能直接比较百分比。

![per-round](assets/mooncake-ssd-offload-final-formal-20260629/02_per_round_performance_local.png)

## I/O 证据

![io-evidence](assets/mooncake-ssd-offload-final-formal-20260629/03_io_evidence_local.png)

`iostat` 显示所有配置都有一些 NVMe 活动，因此不能只用 `iostat` 判断 SSD offload 是否发生。真正的 SSD offload 证据必须同时来自 Mooncake 日志和 offload 目录：

| 配置 | offload files | offload GiB | offload read events | O_DIRECT events | max write MB/s | max read MB/s |
|---|---:|---:|---:|---:|---:|---:|
| GPU only | 0 | 0.0 | 0 | 0 | 770.82 | 367.29 |
| HiCache L1+L2 | 0 | 0.0 | 0 | 0 | 570.07 | 107.23 |
| +Mooncake | 0 | 0.0 | 0 | 0 | 554.86 | 106.73 |
| +Mooncake+SSD | 5402 | 41.0 | 52 | 1341 | 551.71 | 205.69 |

这里的解释是：

- `iostat` 是设备级聚合，包含模型加载、日志、系统背景 I/O 等噪声。
- `offload files + O_DIRECT + read store + offload key count` 才能证明 Mooncake SSD path 被触发。
- 这次没有采集 block-level LBA trace，所以不能从这组数据继续推导“真实 LBA 随机/顺序规律”；LBA 规律仍应使用 `block:block_rq_issue` per-I/O trace 的报告来判断。

## 异常与限制

正式 run 比 4096-token 的早期 run 干净很多：四个配置 `Input length` 错误均为 0，没有 `BUFFER_OVERFLOW` 和 `INVALID_KEY`。

但 `mooncake_ssd` 仍有存储层 warning/error：

| 事件 | 计数 |
|---|---:|
| `OBJECT_ALREADY_EXISTS` | 3 |
| `insufficient space` | 86 |
| `Write page to storage` | 43 |
| `EVICT-TRIGGER` / `EVICT-DONE` | 10475 / 10475 |

因此本报告的结论边界是：

- 可以说：SSD offload 被真实触发，官方式曲线在本地被部分复现。
- 可以说：本地 `+Mooncake+SSD` 在这次压力下比 `+Mooncake` 有更高 cache hit、更低 TTFT、更高 input throughput。
- 不应说：这是无异常的最终性能数据。
- 不应说：本地结果可直接等同官方 DGX/A100/RDMA/RAID0 结果。
- 不应从这次 `iostat` 聚合数据推导 LBA 随机性。

## 和官方 benchmark 的差异

官方页面环境是 DGX 单节点、8 x A100-SXM4-40GB、Qwen3-8B、20 clients、10 rounds、request rate 16、max parallel 4、80GB Mooncake memory pool、20GB SSD buffer、RDMA、5 块 Samsung NVMe RAID0，理论顺序读约 27 GB/s。

本地复测环境是 RTX 5080 单卡、Qwen3-4B、8 clients、8 rounds、request rate 8、max parallel 2、10GB Mooncake memory pool、2GB SSD buffer、TCP localhost、本地 `/mnt/ai_ssd0` offload 目录。

所以可以达成“图的结构”和“SSD offload 生效证据”，不能达成“官方百分比完全复现”。

## 最终判断

目标“画出一张类似官方的 Mooncake SSD offload benchmark 图”已经达成：三张图分别覆盖整体性能、per-round 行为、I/O 证据。

目标“纠正之前错误数据和逻辑”也达成：旧报告的 `Mooncake+SSD` 不再作为 SSD 性能结论使用；新报告只基于 SSD root、enable、offload read、O_DIRECT、offload 目录增长、iostat、benchmark JSON 的组合证据。

下一步如果要把这份结果升级为更严格的 benchmark，应做三件事：

1. 每个配置重复至少 3 次，报告均值和误差。
2. 降低 `insufficient space` / duplicate-key 事件后再跑一版 clean run。
3. 给 `mooncake_ssd` 加 `block:block_rq_issue` per-I/O trace，单独分析真实读写 LBA 分布。
