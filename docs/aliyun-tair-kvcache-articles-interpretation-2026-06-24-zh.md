# 阿里云 Tair KVCache 两篇文章解读

**日期:** 2026-06-24  
**解读对象:**

- [阿里云 Tair 基于 3FS 工程化落地 KVCache：企业级部署、高可用运维与性能调优实践](https://developer.aliyun.com/article/1695651)
- [阿里云 Tair KVCache 仿真分析：高精度的计算和缓存模拟设计与实现](https://developer.aliyun.com/article/1704428)

## 一句话结论

这两篇文章共同传递的核心不是“哪块 SSD 更快”，而是：

**KVCache 已经从推理引擎内部的显存优化，演进为一个跨 GPU HBM、Host DRAM、远端/本地 SSD、分布式文件系统、调度器和仿真器的生产级状态管理系统。**

因此，AI SSD 预研不能停留在 CrystalDiskMark/fio/单盘带宽排名，也不能只看 LMCache/HiCache 的单次 TTFT。更合理的研究对象应是：

> 在给定业务 workload 和 SLO 下，KVCache L3 存储层如何用最低成本稳定提供足够的容量、随机读尾延迟、追加写吸收能力、预取能力和长稳态可靠性。

## 第一篇：3FS 工程化落地 KVCache

### 文章解决的问题

第一篇文章讨论的是生产环境的 L3 KVCache 存储底座。它把 KVCache 从“单机 cache directory”提升到“企业级共享存储层”。

文章给出的 L3 KVCache 需求非常明确：

| 生产特征 | 含义 | 对存储层的压力 |
| --- | --- | --- |
| 超长上下文 | 单次推理 KVCache 可达 GB 到数十 GB | 需要 PB 级容量池，DRAM 成本不可接受 |
| 多轮对话 / RAG 复用 | 历史 KV 被反复读取 | 读写比典型大于 10:1 |
| 写入模式 | KV 生成后追加写入 | 更像顺序追加 / append |
| 读取模式 | 回溯、检索、prefix reload | 随机跳转读取 |
| 高并发低延迟 SLA | P99 端到端响应要求 50ms 甚至 10ms 级 | 存储不能成为尾延迟瓶颈 |
| 节点带宽 | 文章给出节点级高带宽诉求 | 单盘能力不足，需要池化和 RDMA |

这和我们本地 `kv-cache.py` / iostat 的观察一致：KVCache 不是顺序流式读写，而是读多写少、随机读取为主。我们的单盘测试看到的是约 115-125KB 的大块随机 IO、读写比约 9-12:1、`%rrqm≈0`；生产系统把同样的访问模式放大到了分布式文件系统、RDMA 网络、元数据服务和多副本协议上。

### 3FS 为什么适合 KVCache

文章选择 3FS 的逻辑是：KVCache L3 需要的是共享、低延迟、高吞吐、大容量、低成本的存储层。传统通用分布式文件系统有各自限制，3FS 的定位更接近 AI 工作负载存储底座。

关键设计点：

- **SSD + RDMA 的共享存储层**：通过 RDMA 网络连接 Client、Meta、Mgmtd、Storage 等组件。
- **CRAQ 复制协议**：写全部副本、读任一副本，对读多写少的 KVCache 很友好。
- **USRBIO 用户态接口**：绕过部分 POSIX/FUSE 路径开销，做异步、零拷贝数据通路。
- **PB 级容量池化**：多个存储节点上的 SSD 统一管理，解决单机 DRAM/HBM 容量不够的问题。

从 AI SSD 角度看，3FS 把“SSD 性能”从单盘指标扩展成了集群指标：

```text
单盘 SSD p99 / GC / 写尾延迟
    ↓
Storage 节点局部性能
    ↓
RDMA 网络与队列均衡
    ↓
副本读写协议
    ↓
3FS / KVCache L3 端到端 P99
```

也就是说，单盘再快，如果 RDMA 队列、元数据、复制链路、GDR、客户端并发没打通，生产端到端仍然可能慢。

### 文章的工程化重点

文章最有价值的部分是它没有停留在架构图，而是列出了真实工程问题。

**1. 大 IO 与 RDMA 流量均衡**

3FS 大块读写本身能力强，但客户端数量增加后，RDMA 端口流量可能不均衡。文章通过调整 Queue Pair 等参数，让网卡端口流量更均衡，并提升总读带宽扩展性。

这说明 KVCache L3 性能不只取决于 SSD，还取决于网络队列、客户端并发和调度。

**2. 小 IO / 随机读优化**

文章提到 4K 随机读从约 200K IOPS 提升到约 500K IOPS，提升约 150%。优化点包括 Storage 监听线程、I/O worker、队列深度，以及全用户态落盘引擎。

这对我们很关键：即使 KVCache block 不一定是 4K，随机访问和小/中等粒度 IO 仍是核心压力。我们的 115-125KB KV-like random IO 与文章的“小 IO 调优”属于同一类问题：SSD 和存储栈要能稳定处理大量非连续读。

**3. GDR 消除 HBM→Host DRAM 中转**

KVCache 生成后在 GPU HBM 中，如果写入 3FS 还要先拷到 Host DRAM，就会有额外 CPU/GPU 开销和内存带宽压力。文章引入 GPU Direct RDMA，把 HBM 地址暴露给 3FS 数据通路，减少冗余拷贝。

这意味着生产 AI SSD 评估不能只看 SSD 端 `r_await/w_await`，还要看：

- HBM 到存储路径是否零拷贝
- 是否经 Host DRAM 中转
- CPU 是否被 memcpy / pin memory / kernel path 消耗
- GPU 计算和 KV 写回是否能重叠

**4. 元数据和小文件问题**

文章后半段提到 KVCM 与 3FS 集成时，海量小文件会带来元数据压力，因此引入大文件 + Slab 分配器，减少 create/delete/open/close 操作。

这和我们 HiCache/LMCache 观察一致：真实 KVCache 不只是 block IO，文件数量、page size、chunk size、allocator、metadata cache 都会改变端到端延迟。用 fio 只测裸块设备，会漏掉这部分。

**5. 云原生和运维**

Operator、一键部署、Sidecar 注入、故障自愈、弹性扩容、多集群隔离、Grafana 监控这些内容说明：生产 KVCache L3 是基础设施产品，不是实验脚本。

AI SSD 若要进入生产方案，必须回答：

- 如何扩容？
- 如何故障恢复？
- 如何多租户隔离？
- 如何观测 P99 抖动？
- 如何定位瓶颈在 GPU、网络、元数据、SSD 还是调度？

## 第二篇：KVCache-HiSim 仿真分析

### 文章解决的问题

第二篇文章的核心问题是：真实 GPU 集群压测太贵、太慢、组合空间太大，无法靠实测穷举配置。

文章提出 Tair-KVCache-HiSim，用 CPU 上的高保真仿真来预测 LLM 推理系统性能。文章声称在 CPU 上实现小于 5% 误差的端到端性能预测，成本约为真实集群的 1/39 万，并支持 SLO 约束下的配置优化。

这篇文章的价值不在某个单点数字，而在方法论：

> KVCache 优化必须从“跑 benchmark”升级为“基于 workload、SLO 和成本的配置搜索”。

### 为什么需要仿真器

文章指出 LLM 推理性能由多个强耦合因素决定：

- 模型结构：层数、head 数、GQA/MQA/MLA/MoE、attention 实现
- 硬件：GPU 型号、显存带宽、互联拓扑、存储介质
- 引擎：SGLang、vLLM、TensorRT-LLM 的调度策略
- 运行时：prefill/decode 混合、continuous batching、chunk prefill、PD 分离
- KVCache：命中率、L3→L2 预取、L2→L1 加载、驱逐、TTL
- workload：请求到达时间、上下文长度、输出长度、prefix 复用率

这些因素会互相反馈。例如：

- 调度策略决定请求在 waiting queue 里待多久。
- waiting 时间决定 L3→L2 预取是否来得及完成。
- 预取是否完成决定请求是否能进入 batch。
- batch 组成决定 GPU step latency。
- step latency 又影响下一轮到达请求和队列长度。

这就是为什么单独测 SSD、单独测 GPU kernel、单独测 LMCache cold/warm 都不够。生产性能是一个闭环系统问题。

### HiSim 的系统模型

文章把仿真器拆成几个关键模块。

**1. Workload Generator**

支持随机合成数据和带时间戳的真实 trace replay。相比我们目前的测试，这里多了生产 workload 维度：

- 多轮对话
- Agent 场景
- 请求间隔分布
- prompt/output 长度分布
- 真实到达时间

这是 AI SSD 预研下一步最缺的部分。没有 workload trace，就无法判断缓存命中率、L3 reload 频率和 SSD 压力是否真实。

**2. Global Router Simulator**

支持 random、round-robin、cache-aware、power-of-two、bucket 等策略。特别是 cache-aware routing 很关键：如果请求被路由到有 prefix cache 的 worker，L3 读压力和 TTFT 会完全不同。

这直接影响 AI SSD 结论：同一块盘，在 cache-aware routing 下可能几乎不被打到；在随机路由下可能频繁 L3 reload。

**3. Inference Engine Simulator**

模拟 tokenization、调度入队、prefill/decode batch、KVCache 加载/驱逐、detokenization，以及 waiting/running/swapped 状态迁移。

这比我们的 `kv-cache.py` trace replay 更接近真实系统。`kv-cache.py` 适合隔离 SSD 能力，但不建模完整调度状态。

**4. KVCacheManagerSimulator**

文章明确建模：

- prefix matching
- L3 命中后是否触发 L3→L2 异步预取
- 调度 prefill 前是否等待预取完成
- GPU 执行上一 batch 时是否重叠 L2→L1 加载
- LRU/LFU/Radix Tree 等缓存行为

这正好解释我们 HiCache 真实测试里的现象：如果 L2 host DRAM 命中，盘差被遮住；只有 L2 miss 且 L3 reload 不被预取完全隐藏时，AI SSD 差异才会出现在 TTFT。

**5. BatchRunnerEstimator**

文章强调不能只用 batch size、平均 input length 这种粗粒度统计，而要用请求级状态，比如 `(cache_len, input_len)`。这点很重要：两个 batch 的总 token 数一样，若 cache_len 分布不同，attention 和 KV load 行为完全不同。

### HiSim 对 AI SSD 预研的启示

HiSim 文章把 AI SSD 测试从“硬件跑分”提升到了“SLO 约束下的系统配置搜索”。

对我们来说，下一版 AI SSD 预研应该从下面这个问题：

> 哪块盘在 KV cache trace replay 中 p99 最好？

升级为：

> 在目标 TTFT p99、TPOT p99、QPS、成本约束下，GPU HBM、Host DRAM、本地 SSD、远端 3FS/RDMA、缓存策略和调度策略如何配置？

这意味着报告的指标体系要变。

## 两篇文章放在一起看：技术路线图

两篇文章其实是一个完整闭环：

```text
3FS 文章：生产 L3 KVCache 存储底座怎么建
HiSim 文章：如何在建之前/上线前判断配置是否满足 SLO
```

前者回答“系统怎么做”，后者回答“怎么选配置、怎么证明值得做”。

合起来形成一条路线：

1. KVCache 变成可存储、可共享、可调度的状态。
2. 单机 GPU HBM 不够，Host DRAM 也太贵，L3 存储成为必要。
3. L3 不能只是普通文件系统，必须面向读多写少、随机读取、低尾延迟优化。
4. 分布式 L3 需要 RDMA、GDR、metadata 优化、多租户、Operator 和监控。
5. 因配置空间太大，必须用仿真器做 SLO-driven 配置搜索。
6. 实测用于校准仿真器，仿真器用于缩小实测空间。

## 和我们 AI SSD 预研的关系

### 我们当前测试覆盖了什么

当前 `/home/ficus/llm/storage` 和 `/home/ficus/llm/infer/ai_ssd_prestudy` 的测试覆盖了几个关键组件：

- fio / SSD 表征：盘的顺序、随机、SLC、GC、preconditioning。
- `kv-cache.py` trace replay：KV-like 大块随机 IO 下的 p95/p99、读写比、GC cliff。
- LMCache：证明 external KVCache 命中可以显著降低 TTFT，但 CPU tier 会遮住 SSD 差异。
- SGLang HiCache：证明只有 L2 miss / L3 reload 才暴露盘差，write policy 会改变 TTFT 和 OOM 风险。
- iostat / bpftrace：验证目标盘是否真的发生 IO，避免 page cache/L2 命中造成误判。

这些是 3FS/HiSim 路线中的“组件级实测”和“小规模端到端实测”。

### 我们当前测试缺什么

对照阿里云文章，还缺四类能力：

| 缺口 | 影响 |
| --- | --- |
| 生产 workload trace | 不知道真实 prefix 复用率、TTL、L3 reload 频率 |
| 分布式 L3 模型 | 无法评估 RDMA、复制、metadata、远端存储 |
| SLO-driven 搜索 | 只能给盘排名，不能给成本/容量/延迟最优配置 |
| 仿真器校准闭环 | 实测结果不能外推到更多模型、更多 GPU、更多并发 |

所以，当前 AI SSD 预研结论应该明确边界：

> 我们已经能判断某块盘在 KV-like random IO 下是否有长稳态和尾延迟风险；但还不能单独凭这组数据判断生产 KVCache L3 架构的最终性价比。

### 对现有结论的修正

| 原来容易说成 | 更准确的表述 |
| --- | --- |
| AI SSD 就是 KVCache 盘 | AI SSD 是 KVCache L3 service 的本地介质或节点介质 |
| 顺序带宽高就适合 AI | 需要看随机读尾延迟、追加写吸收、GC cliff、预取可隐藏性 |
| LMCache/HiCache TTFT 直接排名盘 | 只有确认 L2 miss 和目标盘真读写后，TTFT 才能用于盘差判断 |
| fio 不重要 | fio 是硬件上限和稳态风险基线，但不能替代真实 KVCache |
| 单盘排名即可决策 | 生产要看 SLO、成本、容量、网络、调度、缓存命中率的 Pareto frontier |

## 对 AI SSD 产品定义的影响

如果面向生产 KVCache，而不是消费级 SSD 跑分，AI SSD 产品定义应包含以下能力。

### 1. 读路径

- 100KB 级到 MB 级随机读的 p95/p99 稳定性
- 高并发随机读下低 queue buildup
- 支持预取窗口内完成 L3→L2 load
- 长时间运行后读尾延迟不随 GC 明显劣化

### 2. 写路径

- prefill / eviction 追加写吞吐
- write_back 模式下 async flush 不堆积
- 长稳态写入后的 GC cliff 时间和 cliff 后带宽
- 写 tail latency，不只看平均写带宽

### 3. 软件路径

- Direct IO / io_uring / SPDK / 用户态引擎适配
- 文件系统或 KV allocator 降低元数据操作
- page/chunk size 对齐 KVCache block
- 支持 GDR 或减少 HBM→DRAM→SSD 拷贝

### 4. 集群与运维

- 多租户 QoS
- 可观测性：按阶段分解 TTFT、L3 reload、SSD await、RDMA、metadata
- 故障自愈和扩容
- 与 SGLang/vLLM/LMCache/KVCM 的标准接口

## 建议的下一阶段实验

### P1：把现有单盘测试转为 SLO 测试

当前已经有单盘和 4 盘的 KV-like trace replay。下一步应把输出从 GB/s / p99 表格改为：

- TTFT p95/p99 是否满足目标
- TPOT p95/p99 是否满足目标
- L3 reload p99 是否被预取隐藏
- 每 1M tokens 的 SSD 成本和容量成本

### P2：构造 production-like workload

至少包含：

- 多轮对话
- RAG 长上下文
- Agent 多步骤调用
- prefix 复用率分布
- 到达时间分布
- 上下文长度和输出长度分布
- TTL 和 eviction 策略

这可以先用合成 trace，再逐步接入真实 trace。

### P3：建立 mini-HiSim

不需要一开始完整复刻 Tair-KVCache-HiSim，但可以先做一个轻量版：

```text
Workload trace
  → router/cache-aware routing
  → L1/L2/L3 capacity model
  → L3 read/write latency model from our SSD measurements
  → prefetch policy
  → TTFT/TPOT estimation
```

其中 L3 latency model 可以直接来自我们已经测到的：

- FIO fresh/preconditioned
- KV-like trace replay p95/p99
- K4 GC drift
- HiCache L3 reload
- write policy matrix

### P4：把本地 SSD 和 remote 3FS-like 模型并列比较

需要比较：

| 方案 | 优点 | 风险 |
| --- | --- | --- |
| Local SSD L3 | 简单、低网络延迟、便宜 | 容量孤岛、跨 worker 复用弱、运维分散 |
| Remote 3FS/RDMA L3 | 容量池化、全局共享、易扩展 | 网络、metadata、复制协议、部署复杂 |
| Host DRAM L2 放大 | 延迟最低、遮住盘差 | 成本高、容量有限 |
| 混合层级 | 可按 SLO/成本折中 | 需要调度和仿真器支持 |

## 关键判断

1. **阿里云文章验证了我们的 block IO 判断方向**：KVCache 读多写少、读取随机、写入追加，不能用顺序带宽代表生产表现。
2. **阿里云文章也指出我们的预研边界**：单盘 AI SSD 排名只是组件层结论，生产需要 L3 service、调度和仿真。
3. **AI SSD 的核心卖点不是峰值 GB/s**，而是在 KVCache L3 service 中稳定满足 p99 reload latency 和长稳态写入。
4. **下一阶段最该做的是 SLO-driven 模型**：用我们已有实测校准一个轻量 HiSim，把盘测试结果转译成 TTFT/TPOT/QPS/成本。
5. **真正的产品路线是软硬一体**：SSD 控制器、文件系统/用户态引擎、RDMA/GDR、KV allocator、缓存管理器和推理调度必须一起设计。

## 给报告的最终表述建议

建议在 AI SSD 预研报告中使用下面这段表述：

> 本预研的单盘和 KV-like trace replay 测试，证明了 KVCache L3 访问不是传统顺序带宽问题，而是读多写少、随机读取、追加写入、尾延迟和长稳态 GC 问题。结合阿里云 Tair KVCache 的 3FS 工程化与 HiSim 仿真路线，AI SSD 不应被定义为单块“跑分更高的 SSD”，而应作为生产 KVCache L3 service 的硬件组件来评估。后续选型必须在真实 workload 和 SLO 下，联合 GPU HBM、Host DRAM、本地 SSD、远程 3FS/RDMA、预取/驱逐策略和调度策略，寻找延迟、吞吐、容量和成本的 Pareto frontier。
