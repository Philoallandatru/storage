# 面向 LLM KV Cache Offload 的 AI SSD 产品预研整合报告

日期：2026-06-13

本文整合当前仓库内 KV Cache benchmark、fio、bpftrace/iostat profiling、四盘横向对比、K4/K5 短测、K4 长稳态与 30 分钟 drift 报告，目标是形成一份有逻辑的阶段性技术预研报告。本文不是最终采购规格书；它用于说明当前已经能确认什么、哪些结论仍只是趋势、下一轮产品验证应该补什么。

## 摘要

当前最重要的结论不是“某块盘峰值最快”，而是：**LLM KV Cache offload 对 SSD 产生的是 sparse-large-block random I/O，且 2 分钟短测和 20-30 分钟长稳态会给出不同答案。**

| 结论 | 当前判断 |
|---|---|
| I/O 模型 | KV Cache 读写约 115-125kB/request，`%rrqm ≈ 0%`，本质是离散大块随机 I/O |
| 短时 burst | BIWIN X570 最强，K4 120s 读带宽 3.14GB/s，K5 180s 读带宽 2.77GB/s |
| 长稳态 | Seagate FC530 与 BIWIN X570 在 20-30 分钟后收敛，Seagate 写尾延迟和 GC stall 更稳 |
| 不推荐盘 | ZhiTai Ti600 长稳态写尾延迟过高；WD SN570 DRAM-less，吞吐和 tail 均弱 |
| 产品验证重点 | 必须测 KV object tail、mixed R/W、GC cliff、长稳态 drift、多盘扩展，而不是只测顺序峰值 |

推荐口径：

| 场景 | 推荐 | 依据 |
|---|---|---|
| 短时交互、短会话、burst-heavy | BIWIN X570 | 短测吞吐和 read/write P99 最强 |
| 30min+ sustained serving | Seagate FC530 优先，BIWIN X570 备选 | 二者带宽接近，Seagate 写 tail 和 GC stall 更稳 |
| mixed inference + checkpoint | Seagate FC530 | mixed R/W 与写服务时间更稳定 |
| 国产/低成本探索 | 当前 ZhiTai Ti600 不推荐作主力 | 长稳态写 P99 可到 600-850ms 量级 |
| DRAM-less 低成本 spill | WD SN570 只能作低压力 overflow | 主力 KV Cache offload 不推荐 |

## 背景：为什么 KV Cache 会变成 SSD 问题

LLM 推理时，prefill 阶段会为输入上下文生成 KV cache，decode 阶段会持续读取已有 KV cache。理想情况下 KV cache 留在 GPU HBM；当上下文变长、并发增加或模型变大时，KV cache 会按层级下沉到 CPU DRAM 和 NVMe SSD。

这使 AI SSD 的关注点不同于普通模型加载盘：

| 普通 SSD 指标 | KV Cache 更关心 |
|---|---|
| 顺序读写峰值 | object-level P95/P99 |
| 4K random IOPS | 100-128kB random large-block latency |
| fresh SLC cache 峰值 | steady-state GC 后表现 |
| 平均吞吐 | mixed R/W 下 tail latency |
| 单盘跑分 | 多盘扩展和最慢盘 tail 放大 |

Tensor parallelism 会改变单个 KV object 大小，模型规模也会改变 bytes/token。因此 8B、70B、TP8、users 数不能混在一个指标里比较。当前更有产品价值的压力主线是 70B TP8 和 8B high-concurrency 两类。

## 测试体系

当前测试已经形成四层方法：

| 层级 | 工具/数据 | 回答的问题 |
|---|---|---|
| L4 KV object | `kv-cache.py` JSON/XLSX | 用户级 KV object read/write P95/P99、E2E、cache hit |
| L3 logical trace | `--io-trace-log` | workload 形态、读写比例、object size |
| L2 block/device | `bpftrace`, `iostat -x` | 设备服务时间、queue、request size、merge ratio |
| L1 synthetic distillation | `fio` | 用可复现实验验证顺序、随机、mixed、SLC、GC |

主要实验集：

| 报告 | 内容 |
|---|---|
| `docs/cross-vendor-nvme-comparison-2026-06-09.md` | fio 跨盘横评，T1-T7 |
| `docs/kv-cache-cross-vendor-2026-06-10.md` | K1-K5 早期 4 盘 KV Cache 短测 |
| `docs/kv-cache-test-evaluation-2026-06-10.md` | 对早期 K1-K5 方法论的批判性评估 |
| `docs/kv-cache-4disk-K4-headline-2026-06-10.md` | K4 8B×16 users×120s |
| `docs/kv-cache-4disk-K5-headline-2026-06-10.md` | K5 70B×4 users×180s |
| `docs/kv-cache-4disk-K4-gc-drift-2026-06-10.md` | K4 20 分钟 GC drift |
| `docs/kv-cache-4disk-K4-30min-drift-2026-06-10.md` | K4 30 分钟继续退化 |
| `docs/kv-cache-io-pattern-analysis-2026-06-10.md` | iostat I/O pattern 分析 |
| `docs/kv-cache-final-selection-2026-06-10.md` | 当前四盘阶段性选型报告 |
| `docs/ai-ssd-multidisk-validation-plan-2026-06-10.md` | 多盘对比与产品验证计划 |

## 核心发现一：KV Cache 是离散大块随机 I/O

来自 K4 GC-drift 的 iostat 分析：

| Disk | Read req median | Read req P99 | Write req median | Write req P99 | `%rrqm` median |
|---|---:|---:|---:|---:|---:|
| BIWIN X570 | 124.4kB | 126.7kB | 113.7kB | 122.6kB | 0.0% |
| Seagate FC530 | 124.4kB | 126.2kB | 113.1kB | 120.6kB | 0.0% |
| ZhiTai Ti600 | 124.7kB | 127.1kB | 115.9kB | 126.4kB | 0.0% |
| WD SN570 | 124.8kB | 127.1kB | 115.7kB | 125.8kB | 0.0% |

这说明四块盘看到的 I/O shape 几乎完全相同，差异来自控制器、DRAM、FTL、NAND 和 GC 策略，而不是应用发给不同盘的请求不同。

产品含义：

| 现象 | 含义 |
|---|---|
| 请求约 115-125kB | 不能只用 4K random 或 1MiB sequential 代表 KV Cache |
| `%rrqm≈0%` | kernel 基本无法合并读请求，不能依赖顺序预取 |
| write request 也接近 random | prefill/eviction 会触发随机写和 GC |
| 所有盘 I/O shape 相同 | 横评结果可归因到 SSD 行为，而不是 workload 不一致 |

## 核心发现二：短测选出 burst 盘，长测选出 serving 盘

### K4：8B×16 users×120s

K4 是高并发小模型压力，短测结果 BIWIN 明显领先。

| Disk | Read GB/s | Write GB/s | Read P99 | Write P99 | E2E P95 | Health |
|---|---:|---:|---:|---:|---:|---|
| BIWIN X570 | 3.14 | 0.27 | 72.9ms | 39.6ms | 35.1s | PASS |
| ZhiTai Ti600 | 2.46 | 0.20 | 84.4ms | 324.7ms | 55.6s | PASS |
| Seagate FC530 | 2.34 | 0.20 | 169.3ms | 63.4ms | 59.2s | PASS |
| WD SN570 | 1.55 | 0.13 | 281.2ms | 269.5ms | 41.3s | FAIL |

结论：短时 8B 高并发下，BIWIN 是明确 burst winner；ZhiTai 在读侧短测可看，但写尾延迟已经暴露风险。

### K5：70B×4 users×180s

K5 是大模型大 object 压力，BIWIN 仍领先，Seagate 是可接受 runner-up。

| Disk | Read GB/s | Write GB/s | Read P99 | Write P99 | E2E P95 | Health |
|---|---:|---:|---:|---:|---:|---|
| BIWIN X570 | 2.77 | 0.24 | 93.8ms | 48.2ms | 75.0s | PASS |
| Seagate FC530 | 2.09 | 0.18 | 131.2ms | 50.1ms | 73.8s | PASS |
| ZhiTai Ti600 | 1.93 | 0.17 | 212.1ms | 850.2ms | 60.7s | PASS |
| WD SN570 | 1.49 | 0.13 | 240.0ms | 477.6ms | 29.0s | PASS |

结论：70B 下 ZhiTai 的 write P99 到 850ms，说明平均读延迟不能掩盖写尾风险。Seagate 在 70B mixed path 上更接近 BIWIN。

### K4 GC drift：8B×16 users×1200s

20 分钟后，短测排名发生变化。BIWIN 和 Seagate 吞吐几乎相同，差异转向 tail 和 GC。

| Disk | Read GB/s | Write GB/s | Read P99 | Write P99 | E2E P95 | Health |
|---|---:|---:|---:|---:|---:|---|
| BIWIN X570 | 1.92 | 0.17 | 154.8ms | 180.8ms | 167.6s | PASS |
| Seagate FC530 | 1.91 | 0.17 | 209.2ms | 127.5ms | 223.2s | PASS |
| WD SN570 | 1.25 | 0.12 | 420.3ms | 480.4ms | 187.8s | FAIL |
| ZhiTai Ti600 | 1.01 | 0.10 | 251.9ms | 725.0ms | 287.1s | PASS |

结论：Seagate 写尾更稳；BIWIN 读延迟仍好，但 burst 优势被 GC 消耗。ZhiTai 退化严重。

### K4 30min drift

30 分钟后，BIWIN 和 Seagate 基本等价，差距已经进入 single-run 噪声范围。

| Disk | Duration | Read GB/s | Write GB/s | Read P99 | Write P99 | E2E P95 | Health |
|---|---:|---:|---:|---:|---:|---:|---|
| BIWIN X570 | 1800s | 1.57 | 0.16 | 211.9ms | 227.0ms | 567.5s | PASS |
| Seagate FC530 | 1800s | 1.54 | 0.16 | 268.8ms | 213.6ms | 555.4s | PASS |
| ZhiTai Ti600 | 900s | 1.16 | 0.10 | 218.5ms | 606.7ms | 255.1s | PASS |
| WD SN570 | 900s | 1.38 | 0.12 | 369.9ms | 406.8ms | 172.6s | FAIL |

注意：ZhiTai 和 WD 因容量限制只跑 900s，不能与 BIWIN/Seagate 做完整 30 分钟同口径比较。

## 核心发现三：GC cliff 是 AI SSD 产品风险

K4 GC drift 的 cliff 检测显示：

| Disk | Cliff time | Drop | 解读 |
|---|---:|---:|---|
| BIWIN X570 | 2.9min | -40.6% | SLC/缓存优势很快消耗，短时很强 |
| ZhiTai Ti600 | 5.6min | -77.8% | cliff 后吞吐崩塌 |
| WD SN570 | 7.8min | -40.6% | 本来就慢，cliff 不改变主结论 |
| Seagate FC530 | 8.1min | -32.0% | cliff 最晚、跌幅最浅 |

30 分钟报告还观察到 BIWIN/Seagate 在 20-30 分钟阶段出现周期性 5 分钟级 GC stall。这是产品级风险：即使平均带宽还可用，请求落在 stall 窗口里也会造成 TTFT 或 decode latency 尖峰。

## 单盘画像

### BIWIN X570

| 维度 | 判断 |
|---|---|
| 优点 | 短时吞吐、短时 read/write P99、QD64 random、burst sequential 均强 |
| 风险 | GC cliff 早，30 分钟后与 Seagate 收敛 |
| 适合 | 短会话、交互式、burst-heavy、冷启动加载 |
| 不适合 | 单盘承担长时间 sustained serving 的唯一依据 |

### Seagate FC530

| 维度 | 判断 |
|---|---|
| 优点 | mixed R/W、write tail、GC cliff 时间、长稳态稳定性最好 |
| 风险 | 短时读带宽不如 BIWIN，read P50/P99 有时更高 |
| 适合 | sustained serving、batch inference、mixed checkpoint + inference |
| 不适合 | 只追求 2 分钟 burst peak 的场景 |

### ZhiTai Ti600

| 维度 | 判断 |
|---|---|
| 优点 | 短时 8B 读侧表现尚可 |
| 风险 | 70B 和长稳态写尾延迟过高，GC 后吞吐下降大 |
| 适合 | 低压力探索或需进一步验证的国产替代候选 |
| 不适合 | KV Cache 主力盘、70B、大并发、mixed R/W |

### WD SN570

| 维度 | 判断 |
|---|---|
| 优点 | 成本低，退化相对“平缓” |
| 风险 | DRAM-less，吞吐和 tail 从一开始就弱，多次 health FAIL |
| 适合 | 低压力 overflow/spill 或方法验证 |
| 不适合 | AI SSD 主力盘 |

## 对 AI SSD 产品设计的启发

### 固件和控制器方向

| 方向 | 原因 |
|---|---|
| 优化 100-128kB random large-block I/O | KV Cache 真实 request size 集中在这个区间 |
| Read-priority mixed scheduling | decode 读路径直接影响用户可感知 latency |
| GC QoS 和后台整理限速 | 避免 5 分钟级 stall 阻塞服务 |
| 稳定 pSLC/reserved SLC | 产品需要长稳态，而不是 fresh 空盘峰值 |
| 更大的 DRAM/FTL cache | `%rrqm≈0%` 时，FTL 映射和随机访问能力更关键 |
| 暴露可观测 telemetry | 需要能看到 GC、throttle、write amplification、温度状态 |

### 系统软件方向

| 方向 | 原因 |
|---|---|
| 应用级分片优先于盲目 RAID0 | 可以隔离慢盘和 GC stall，做 per-disk backpressure |
| HBM/DRAM/NVMe tier 正常化测试 | 当前 CPU0/GPU0 是 worst-case，生产需要 tier cascade |
| 读写隔离 | prefill 写和 decode 读可分盘或分队列，降低互相干扰 |
| bounded cache pool | 必须模拟真实容量限制和 eviction |
| backpressure | SSD tail 恶化时限制新请求，避免 E2E 分钟级排队 |

## 多盘验证方向

当前跨盘测试是“多块单盘横评”，还不是“多盘系统验证”。下一阶段需要：

| 测试 | 目的 | 必看指标 |
|---|---|---|
| 1/2/4 盘 scaling | 看吞吐是否接近线性 | scaling efficiency、P99、CPU overhead |
| RAID0 vs 应用级分片 | 比较透明条带和可控 placement | tail amplification、per-disk skew |
| 异构盘混合 | 验证最慢盘是否拖累整体 | slowest-disk dominance |
| 读写分盘 | 降低 checkpoint/prefill 对 decode 的干扰 | read P99、write P99、E2E |
| 60/120min 多盘稳态 | 观察 GC stall 是否被多盘摊薄 | BW drift、stall overlap、queue depth |

初始门槛建议：

| 指标 | 建议 |
|---|---|
| 2 盘 scaling | >1.7x |
| 4 盘 scaling | >3.0x |
| per-disk skew | <1.2 较健康，>1.5 需要解释 |
| tail amplification | 多盘 P99 不应超过最强单盘 P99 的 2x |
| stall overlap | 多盘 GC stall 不应同时发生或拖垮整节点 |

## 当前不足与风险评估

### 1. 单次运行偏多

很多关键 cell 仍是 single run。BIWIN 与 Seagate 在 30 分钟的 1.57 vs 1.54GB/s 只有约 2% 差距，不能说 BIWIN 绝对更快，只能说二者功能等价。

建议：关键 cell 至少做 3-run median，并报告 min/median/max 或置信区间。

### 2. 长稳态仍不够长

当前最长主线是 30 分钟。AI SSD 产品需要 60min、120min、24h soak，才能确认 GC cycle 是否继续恶化、周期稳定还是恢复。

### 3. 强制 NVMe worst-case 不等于真实生产

大量测试使用 `--gpu-mem-gb 0 --cpu-mem-gb 0`，这是放大 SSD 差异的正确方法，但它不是生产真实 tiering。真实系统中 HBM/DRAM 会吸收热 KV，绝对吞吐、E2E 和 miss path 都会变化。

建议：保留 CPU0/GPU0 作为 worst-case，同时增加 `HBM/DRAM tier enabled` 的 production-like 对照。

### 4. `trace-speedup=1000` 改变时间尺度

1000x 可以快速制造压力，但会改变真实请求间隔、cache aging 和 eviction 行为。它适合压力测试，不适合作为唯一生产预测。

建议：补 `trace-speedup=10/100/1000` 对照。

### 5. 缺少 bounded cache capacity

如果 cache-dir 不设容量上限，hit rate、eviction 写入和 miss path 压力可能不真实。

建议：使用固定 storage capacity，例如 100/200/500GB，观察 hit rate 和 write amplification。

### 6. 缺少 mixed checkpoint + inference

当前主线是纯 KV Cache。实际 AI 节点可能同时有 checkpoint、RAG、日志、模型加载。Seagate 在 mixed R/W 上更稳，但仍需真实组合 workload 验证。

### 7. 多盘系统尚未验证

当前结论是单盘画像，不是多盘节点结论。多盘会引入 root complex、CPU、文件系统、RAID stripe、最慢盘 tail、GC stall overlap 等新问题。

### 8. 容量和挂载状态不完全一致

ZhiTai/WD 因容量限制只做 900s 30min 对照，BIWIN/Seagate 做 1800s。跨盘结论成立，但部分表格必须明确不是完全同 duration。

### 9. 消费级盘不等于最终 AI SSD

这些盘适合建立方法论和产品判断框架，但不能直接替代企业级 AI SSD 验证。最终还需要企业级 SSD、PLP、firmware QoS、DWPD、温控、异常恢复和多盘系统测试。

## 后续测试优先级

| 优先级 | 测试 | 目的 |
|---|---|---|
| P0 | BIWIN/Seagate K4 30min 3-run median | 确认二者是否真等价 |
| P0 | K4 60min/120min steady | 判断 GC stall 是否稳定或继续恶化 |
| P0 | production-like tiering | 加 HBM/DRAM tier，避免只看 worst-case |
| P1 | bounded cache capacity | 测真实 eviction 和 miss path |
| P1 | mixed checkpoint + KV Cache | 验证写放大和读写互扰 |
| P1 | 2 盘 RAID0 vs 应用级分片 | 开始多盘系统验证 |
| P2 | trace-speedup 10/100/1000 sweep | 区分压力测试和生产预测 |
| P2 | 企业级 SSD 对照 | 判断消费级结论能否迁移 |

## 最终阶段性结论

当前数据足以支持以下阶段性结论：

1. KV Cache offload 的核心 I/O 不是顺序流，而是约 115-125kB 的离散大块随机读写。
2. 2 分钟测试会偏向 burst 盘；20-30 分钟测试才会暴露 serving 盘需要面对的 GC 和 tail 风险。
3. BIWIN X570 是短时 burst 最强候选，但不能把它的短测优势外推到 30 分钟以上 sustained serving。
4. Seagate FC530 是当前更适合长稳态和 mixed R/W 的候选，尤其适合 sustained serving 和 checkpoint 互扰风险更高的场景。
5. ZhiTai Ti600 和 WD SN570 不适合作为 KV Cache 主力盘：前者长稳态写尾风险大，后者 DRAM-less 且整体性能弱。
6. AI SSD 产品验证应从“峰值带宽规格”转向“KV object tail + GC drift + mixed R/W + 多盘扩展效率”的组合指标。

因此，这份预研的产品判断不是“买哪块消费级盘”，而是明确了 AI SSD 应该如何被验证：用真实 KV Cache object workload、长稳态、I/O pattern 画像和多盘系统测试来定义产品价值。
