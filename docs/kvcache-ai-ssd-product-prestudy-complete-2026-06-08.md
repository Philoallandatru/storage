# KV Cache AI SSD 产品预研完整总结

日期：2026-06-08

本文是本轮 KV Cache I/O profiling 与 AI SSD 产品预研的总入口文档。它整合已有测试报告、最新 saturation sweep 进展、测试技术栈说明、全部实验内容总结，以及面向 AI SSD 产品定义的判断。

相关报告：

| 文档 | 作用 |
|---|---|
| `docs/kvcache-ai-ssd-prestudy-2026-06-08.md` | 早期 AI SSD 预研结果 |
| `docs/kvcache-io-profiling-visual-analysis-2026-06-08.md` | I/O profiling 图表分析 |
| `docs/kvcache-full-profiling-results-2026-06-08.md` | 4 层 profiling 完整结果 |
| `docs/kvcache-prefill-decode-split-2026-06-08.md` | prefill-only / decode-only 拆分 |
| `docs/kvcache-fio-iodepth-sweep-2026-06-08.md` | fio iodepth sweep |
| `docs/kvcache-ssd-preconditioning-2026-06-08.md` | SSD preconditioning 对比 |
| `docs/kvcache-saturation-points-2026-06-08.md` | 最新 saturation point sweep |

## 最新进展摘要

截至 2026-06-08 晚间，测试已经从“能否跑通流程”推进到“找到产品饱和边界”。

| 阶段 | 状态 | 最新结论 |
|---|---|---|
| ShareGPT 完整流程 | 完成 | 真实聊天 workload 很轻，适合流程验证，不适合做 SSD 压力上限 |
| BurstGPT 真实 trace | 完成 | `--trace-speedup 1000` + `--cpu-mem-gb 0` 是当前最有价值的产品 baseline |
| 70B 扩展 | 完成 | 70B TP8 users=2/4/6/8 全 PASS，users=12 触发真硬件饱和 |
| 4 层 profiling | 完成 | L4 KV object、L3 I/O trace、L2 bpftrace、L1 iostat/pidstat/perf 已打通 |
| prefill/decode 分离 | 完成 | 纯写和纯读都比混合 workload 更轻，混合读写更能暴露 SSD tail latency |
| fio iodepth sweep | 完成 | 合理 `iodepth` 是 32 左右，超过 64 基本只增加尾延迟 |
| SSD preconditioning | 完成 | 570GiB sequential write 后，P99 尾延迟整体更稳定，写 P99 改善最明显 |
| saturation sweep | 完成第一轮 | 70B users=12 是当前设备的真硬件饱和门槛；8B users=32 仍未饱和 |

最新最重要的产品判断：

1. 当前本地 NVMe 对 70B TP8 KV cache 的安全并发边界大约在 users=8 到 users=12 之间。
2. 70B users=12 已出现真硬件饱和信号：device P95 超过 100ms，E2E P95 超过 100s，SLA 大面积失败。
3. 8B TP8 users=32 仍未饱和，说明模型 KV bytes/token 是决定 SSD 压力的关键变量。
4. Trace mode 只能分析 workload 形态，不能做容量规划。容量规划必须看 Round 2 真硬件 I/O。
5. AI SSD 预研不能只看 fio 单点指标，必须同时看 KV object tail、设备 await/util、block D2C、workload trace。

## 测试技术栈完整介绍

### 1. MLPerf KV Cache Benchmark

本项目使用 `kv_cache_benchmark` 模拟 LLM 推理中的 KV cache 存储路径。它把 KV cache 按 tier 管理：

| Tier | 含义 | 本轮测试中的作用 |
|---|---|---|
| Tier-0 | GPU VRAM / HBM | 为了强制 SSD 压力，多数测试设为 `--gpu-mem-gb 0` |
| Tier-1 | CPU DRAM | 用于评估 CPU cache 对 SSD 压力的遮蔽；产品压力测试多设为 `--cpu-mem-gb 0` |
| Tier-2 | NVMe SSD | AI SSD 预研重点，所有 KV object 读写最终落到这里 |

核心参数：

| 参数 | 作用 | 本轮推荐用法 |
|---|---|---|
| `--model` | 选择模型，决定 KV bytes/token | 8B 用于轻压力，70B 用于产品边界 |
| `--num-users` | 并发用户数 | 通过 users 梯度找 first PASS / first FAIL |
| `--tensor-parallel` | 张量并行度，决定单 rank KV object 大小 | TP8 是当前主要产品口径 |
| `--num-gpus` | 模拟 GPU 数 | TP8 配 `--num-gpus 8` |
| `--gpu-mem-gb` | GPU cache 容量 | SSD 压力测试设为 0 |
| `--cpu-mem-gb` | CPU cache 容量 | SSD 压力测试设为 0；cache sensitivity 测试扫 0/0.5/1/2 |
| `--max-concurrent-allocs` | 限制并发内存分配 | 本机安全值为 2 或 4 |
| `--generation-mode none` | 关闭生成延迟模拟 | 用于纯存储 I/O benchmark |
| `--enable-autoscaling` | 自动扩容找容量边界 | saturation sweep 使用 |

### 2. Workload 类型

本轮使用了三类 workload：

| Workload | 来源 | 优点 | 局限 | 产品定位 |
|---|---|---|---|---|
| Synthetic | benchmark 随机生成用户画像 | 长上下文、大 object，容易找失败边界 | 不是真实用户 trace | 压力边界测试 |
| ShareGPT | 真实聊天数据集 | 完整真实聊天流程 | 上下文短、cache hit 高、SSD 压力轻 | 流程验证和真实聊天 baseline |
| BurstGPT | 真实 API trace | 请求间隔、token 分布更像生产 | 原始 trace 太稀疏，需要 `--trace-speedup 1000` | AI SSD 产品 baseline |

结论：AI SSD 产品预研应以 BurstGPT CPU0 TP8 为主线，用 Synthetic 找极限，用 ShareGPT 验证完整流程。

### 3. 4 层 I/O Profiling 架构

本轮已经打通 4 层 profiling。每层回答的问题不同，不能互相替代。

| 层 | 工具 | 输出 | 回答的问题 |
|---|---|---|---|
| L4 KV object | benchmark JSON/XLSX | Read/Write Device P95、Storage I/O P95、cache hit、tier bytes | 用户级 KV cache object 是否满足目标 |
| L3 filesystem/logical trace | `--io-trace-log *.csv.zst` | Read/Write ops、object size、tier、phase | workload 形态是什么 |
| L2 block layer | `bpftrace storage_latency_stack.bt` | D2C、Q2D、VFS、fsync、bssplit、QD | 瓶颈在设备、调度器、文件系统还是应用路径 |
| L1 device/process | `iostat`, `pidstat`, `perf` | await、IOPS、bandwidth、util、进程 I/O、CPU 计数器 | 设备是否被打满，进程和系统是否一致 |

必须区分三类 latency：

| 指标 | 层级 | 含义 | 使用方式 |
|---|---|---|---|
| D2C | block layer | 单条 block I/O 从 dispatch 到 complete 的设备服务时间 | 判断 SSD 原生命令延迟 |
| `r_await` / `w_await` | device aggregate | 设备级平均等待时间 | 判断设备是否拥塞 |
| Read/Write Device P95 | KV object | 一个 KV object 的设备侧读写时间 | 判断 AI workload 的真实对象级 tail latency |

一个 KV object 可能被拆成大量 128KiB block I/O，所以 object-level P95 通常远大于 D2C。

### 4. fio 蒸馏与 iodepth sweep

`bpftrace` 可以蒸馏出 fio workload：

| 字段 | 含义 | 本轮典型值 |
|---|---|---|
| `rwmixread` | 读比例 | BurstGPT 约 91% read |
| `bssplit` | block size 分布 | 128KiB 占主导 |
| `iodepth` | 队列深度 | 自动蒸馏值可达 32768、524288、1048576 |

关键原则：蒸馏出的超大 `iodepth` 不是产品测试建议值。它代表系统侧堆积，不代表 SSD 合理队列深度。

本轮 sweep 结论：

| Workload | 最佳/合理 iodepth | 现象 |
|---|---:|---|
| ShareGPT 8B CPU0.5 | 32 | qd>32 后 IOPS 下降，P99 快速变差 |
| BurstGPT 8B CPU0 speedup1000 | 32 到 64 | IOPS 基本持平，高 qd 只增加 write tail |
| Synthetic TP8 CPU0.5 | 32 | qd>64 后延迟恶化明显 |

### 5. SSD Preconditioning

Preconditioning 是为了避免空盘或不稳定 GC 状态带来的偏差。本轮对目标分区做了约 570GiB sequential write，再重复代表性 fio sweep。

结果：

| 指标 | 变化 |
|---|---|
| R IOPS | 多数 workload 提升 4% 到 15% |
| R P99 | 高 iodepth 下改善 10% 到 49% |
| W P99 | 改善最明显，部分 workload 下降 90% 以上 |
| 结论 | 稳态后 tail latency 更稳定，产品规格应使用 preconditioned 后的数据 |

注意：当前测试设备是系统盘分区，不是裸盘企业 SSD；preconditioning 结论应在专用 SSD 上复验。

### 6. Autoscaling 与 Saturation

`--enable-autoscaling --autoscaler-mode qos` 用于观察系统是否还能继续加用户。它能暴露两类问题：

| 信号 | 含义 |
|---|---|
| final users 一路到上限 | trace mode 或轻 workload 下，系统认为还能扩 |
| saturation >= 0.5 | 真硬件压力已经明显 |
| queue depth 暴涨 | 用户请求排队严重，服务已经不可用 |
| SLA compliance 接近 0 | 从产品角度已经失败，即使单个 device P95 还没超过硬阈值 |

最新 saturation sweep 证明：trace mode 下 latency 为 0，autoscaler 会高估容量；真硬件 Round 2 才能用于容量规划。

## 全部测试内容总结

### 1. Synthetic baseline 与 TP 扩展

| 测试 | 结果 | 关键数据 | 结论 |
|---|---|---|---|
| 8B TP1 users10 | FAIL | Read Device P95 3167ms，Write Device P95 925ms | TP1 object 太大，是明确失败 baseline |
| 8B TP8 CPU0.5 users2 | PASS | Read Device P95 199ms | synthetic 安全边界 |
| 8B TP8 CPU0.5 users3 | FAIL | Read Device P95 255ms | synthetic 首个失败点 |
| 8B TP8 CPU0.5 users4 | FAIL | Storage I/O P95 1500ms | 并发增加后 object tail 明显恶化 |

产品含义：TP 是影响 KV object size 的第一因素。AI SSD 规格必须标注 TP 口径，否则性能数字不可比较。

### 2. ShareGPT 完整流程

| 测试 | 结果 | 关键数据 | 结论 |
|---|---|---|---|
| ShareGPT io-trace | PASS | 127477 ops，trace mode 无真实 I/O | 能生成完整 logical workload |
| ShareGPT real I/O | PASS | Read Device P95 62ms，Storage Read 9.79GiB | 真实聊天 workload 很轻 |
| ShareGPT profile | PASS | iostat util P95 8%，D2C read P99 128us | SSD 基本空闲 |

产品含义：ShareGPT 可用于“真实聊天能跑通”，但不能用于 AI SSD 压力上限或容量规划。

### 3. BurstGPT 8B CPU0 TP8

| 测试 | 结果 | 关键数据 | 结论 |
|---|---|---|---|
| users2 speedup1000 profile | PASS | Read P95 17.96ms，Write P95 18.90ms，Storage Read 615GiB | 当前最佳 8B 产品 baseline |
| users4 | PASS | Read P95 31.54ms，Write P95 55.64ms | 写 tail 开始上升 |
| users6 | PASS | Read P95 41.54ms，Write P95 114.54ms | 写路径更敏感 |
| users8 | PASS | Read P95 46.48ms，Write P95 118.44ms | 8B users8 仍有余量 |
| users32 saturation sweep | PASS | Read P95 43.05ms，Write P95 112.05ms，SLA 100% | 8B users32 仍未饱和 |

产品含义：对 8B 级模型，本地 NVMe 不是主要瓶颈。AI SSD 差异需要更高 users 或更大模型才能放大。

### 4. BurstGPT 70B CPU0 TP8

| 测试 | 结果 | 关键数据 | 结论 |
|---|---|---|---|
| users2 | PASS | Read P95 41.85ms，Write P95 18.68ms | 70B 起点健康 |
| users4 | PASS | Read P95 92.67ms，Write P95 125.53ms | tail 明显上升 |
| users6 bursttrace/full | PASS | Read P95 96.10/96.53ms，Write P95 127.60/114.02ms | users6 稳定 PASS |
| users8 full | PASS | Read P95 164.63ms，Write P95 175.41ms | 接近 read 200ms 目标，但仍 PASS |
| users12 saturation | 饱和 | Read P95 127.86ms，Write P95 154.87ms，E2E P95 115.6s，SLA 近乎全失败 | 真硬件容量已经不可接受 |

为什么 users12 的 read/write device P95 还没超过 200/500ms，但仍判定饱和：因为产品体验看的是整体服务可用性。users12 下 queue depth 和 E2E latency 已经崩溃，SLA compliance 接近 0。这说明瓶颈不仅是单个 KV object device P95，还包括队列堆积和调度压力。

产品含义：当前设备对 70B TP8 的实用边界在 users8 到 users12 之间。AI SSD 产品定义应优先围绕 70B users8/10/12 做边界验证。

### 5. 4 层 Full Profiling

| 测试 | 结果 | 关键数据 | 结论 |
|---|---|---|---|
| 70B users6 full | PASS | 94883 ops，887GiB read，78GiB write，util avg 30.9% | profiling 数据完整且可信 |
| 70B users8 full | PASS | Read P95 164.63ms，util avg 30.4% | 更接近边界 |
| 8B users8 full | PASS | Read P95 67.60ms，Write P95 180.22ms | 8B object 小，读更轻 |

产品含义：4 层 profiling 是后续 AI SSD 验证标准流程。只看 benchmark JSON 不够，必须同时看 trace、block、device。

### 6. Prefill-only / Decode-only 拆分

| 模式 | 结果 | 关键数据 | 结论 |
|---|---|---|---|
| prefill-only | 写路径 PASS，整体规则 FAIL | Write P95 117.93ms，152GiB write，0 read | FAIL 来自 cache hit=0，不代表写入失败 |
| decode-only | PASS | Read P95 88.92ms，1266GiB read | 纯读路径比混合更快 |
| mixed 对照 | PASS | Read P95 96.53ms，Write P95 114.02ms | 混合读写最接近真实压力 |

产品含义：AI SSD 需要分别优化 prefill 写路径和 decode 读路径，但验收应以混合 workload 为主。

### 7. fio sweep 与 preconditioning

| 测试 | 结果 | 产品结论 |
|---|---|---|
| fio iodepth sweep | qd=32 最合理，qd>64 延迟恶化 | 产品测试不要直接使用蒸馏出的超大 iodepth |
| preconditioned qd32/1024 sweep | 多数 tail latency 改善，写 P99 改善最大 | 产品 spec 应使用稳态数字，不应只看空盘 |

产品含义：fio 是硬件极限验证工具，不是 KV benchmark 的替代品。推荐用 benchmark/bpftrace 蒸馏 `rwmixread` 和 `bssplit`，但用人工设定的合理 qd sweep 来做 SSD 对比。

## AI SSD 产品预研判断

### 判断 1：AI SSD 的核心指标不是单条 NVMe latency，而是 KV object tail latency

本轮测试中 D2C 往往是微秒级到亚毫秒级，但 KV object P95 是几十到几百毫秒。这说明产品规格不能只写 4KiB random read latency 或 fio P99，而要定义 KV object-level SLA。

建议指标：

| 指标 | 建议目标 |
|---|---|
| KV object read device P95 | < 200ms |
| KV object write device P95 | < 500ms |
| mixed workload E2E P95 | 不出现分钟级排队 |
| SLA compliance | interactive/responsive 不应接近 0 |
| device util | 保持可解释，不能只看高吞吐 |

### 判断 2：70B 比 8B 更适合做 AI SSD 产品边界测试

70B 的 KV bytes/token 是 320KiB，8B 是 128KiB，TP8 后 object size 仍约为 8B 的 2.5 倍。最新 saturation sweep 中，70B users12 已经暴露真硬件边界，而 8B users32 仍未饱和。

产品建议：用 70B TP8 CPU0 BurstGPT users8/10/12 作为核心评估矩阵；8B 作为低压 baseline。

### 判断 3：Trace mode 是 workload 设计工具，不是容量规划工具

`--io-trace-log` 使用 NullBackend，不做真实硬件 I/O，device latency 为 0。它适合生成 workload 形态、统计 object size 和读写比例，但不能判断 SSD 能否承载。

产品建议：任何容量数字必须来自真实硬件 Round 2；trace mode 只能作为 Round 1。

### 判断 4：混合读写 workload 比纯读/纯写更接近真实服务风险

prefill-only 和 decode-only 分别隔离了写和读，但混合模式才同时触发读路径、写路径、GC、队列调度和 host 序列化。users12 的 SLA 崩溃说明整体系统风险可能早于单项 device P95 阈值。

产品建议：验收报告中必须有 mixed BurstGPT profile，prefill/decode split 作为诊断附件。

### 判断 5：当前设备的实用边界

在当前本地 NVMe 系统盘分区上：

| 模型 | 当前结论 |
|---|---|
| 8B TP8 CPU0 | users32 仍未饱和，可继续上探 users64/128 |
| 70B TP8 CPU0 | users8 仍 PASS，users12 已触发真实服务饱和 |
| SSD 持续读吞吐 | 约 3GiB/s 是当前设备级上限附近 |
| 合理 fio qd | 约 32；qd>64 主要增加 tail latency |

这些结论适用于当前测试平台，不应直接泛化到企业级 SSD 或多 SSD 阵列。企业级 AI SSD 需要在同一 workload 下重跑。

## 建议的 AI SSD 测试规范

### P0：产品 baseline 必跑

| 测试 | 配置 | 目的 |
|---|---|---|
| ShareGPT real I/O | 8B TP8 CPU0.5 users2 | 验证真实聊天完整流程 |
| BurstGPT 8B baseline | 8B TP8 CPU0 users8/32 | 轻模型 baseline |
| BurstGPT 70B boundary | 70B TP8 CPU0 users8/10/12 | 找产品并发边界 |
| Full profiling | 对 first PASS 和 first FAIL 开 4 层 profiling | 定位瓶颈层级 |
| fio sweep | 使用蒸馏 bssplit/rwmixread，扫 qd32/64/128/256/1024 | 验证硬件极限 |
| preconditioning | 预写满后重复代表性 fio sweep | 得到稳态产品数字 |

### P1：提高可信度

| 测试 | 价值 |
|---|---|
| 70B users10 | 精确定位 users8 和 users12 之间的拐点 |
| 30 到 60 分钟长稳态 | 观察热、GC、wear leveling、page cache 漂移 |
| CPU cache sensitivity | 评估 DRAM cache 对 SSD 压力的遮蔽 |
| prefill/decode split for first FAIL | 判断失败来自读路径还是写路径 |

### P2：产品扩展

| 测试 | 价值 |
|---|---|
| Qwen3-32B / DeepSeek V3 / GPT-OSS | 覆盖不同 KV bytes/token 和注意力结构 |
| 多 SSD / RAID0 | 看吞吐和 tail 是否按盘数改善 |
| 企业级 SSD 对照 | 验证 AI SSD firmware / PLP / GC 优势 |
| 不同文件系统或 direct I/O | 分离 filesystem/page cache 影响 |

## 当前风险和注意事项

| 风险 | 说明 | 建议 |
|---|---|---|
| 系统盘测试 | `/dev/nvme1n1p3` 是系统分区，存在后台 I/O 干扰 | 后续用专用裸盘或独立分区 |
| 残留监控进程 | 曾发现 `iostat`/`pidstat` 测试后继续运行并追加日志 | wrapper 必须 trap/cleanup，测试后 `ps` 检查 |
| Trace mode 高估容量 | NullBackend latency 为 0 | 容量规划必须用真实 I/O |
| 自动蒸馏 iodepth 过大 | 32768 到百万级不适合直接跑 fio | 只复用 read mix 和 block size，人工 sweep qd |
| cache hit 极高 | BurstGPT hit rate 约 97.7%，可能低估 cold miss 压力 | 增加 cold cache / replay cycles / eviction 压力测试 |
| 本轮不是企业 SSD | 当前设备不是面向数据中心的 AI SSD | 结论用于方法论和相对边界，最终需换目标盘复测 |

## 最终结论

本轮预研已经形成一套可复用的 AI SSD KV Cache 测试方法：

1. 用 ShareGPT 验证真实聊天流程。
2. 用 BurstGPT CPU0 TP8 建立产品 baseline。
3. 用 70B users 梯度找真硬件 first PASS / first FAIL。
4. 用 4 层 profiling 定位问题在 KV object、filesystem、block layer 还是 device。
5. 用 fio sweep 和 preconditioning 把 workload 转成可复现的 SSD 硬件验收项。

当前最有价值的产品结论是：在本地 NVMe 上，8B TP8 仍有很大余量；70B TP8 的真实服务边界已经出现在 users8 到 users12 之间。AI SSD 产品预研下一步应优先围绕 70B TP8 CPU0 BurstGPT users10/12、长稳态、企业级 SSD 对照展开。
