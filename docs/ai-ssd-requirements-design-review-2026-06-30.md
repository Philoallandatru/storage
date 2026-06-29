# AI SSD 需求与产品设计合理性评审

**日期:** 2026-06-30  
**评审对象:** `docs/ai-ssd-prestudy-data-direction-2026-06-29.md` 中提出的 AI SSD 预研需求、测试方向和产品设计方向  
**评审目标:** 判断这些需求和设计是否合理，给出理由、证据边界、风险和建议调整

## 1. 总体判断

结论：当前提出的 AI SSD 需求和产品设计方向**总体合理**，但必须按证据强度分层推进。

最可靠、最应该保留为 P0 的方向是：

1. **128 KiB random read tail**；
2. **长稳态 GC / tail latency drift**；
3. **read-priority GC / mixed R/W isolation**；
4. **真实 KV workload + per-I/O block trace 的测试方法论**；
5. **Mooncake / LMCache / SGLang 这类系统级 offload path 的验证门禁**。

合理但还属于 P1/P2 预研的方向是：

1. **GDS / GPU Direct path**；
2. **多盘路径绑定 / application sharding**；
3. **cache-aware telemetry / prefetch hint / eviction hint**；
4. **高容量 QLC cold context tier**；
5. **AI SSD System Kit**。

暂时不建议直接承诺为产品规格的方向是：

1. “某块盘已经适合作为最终 AI SSD 选型”；
2. “Mooncake+SSD 本地收益可以等同官方 benchmark”；
3. “只要支持 GDS 就一定能提升 TTFT”；
4. “AI SSD 只需要优化 KV cache，不需要考虑 RAG、checkpoint、小文件、模型加载等混部”。

## 2. 评审方法

本文按以下标准判断需求是否合理：

| 标准 | 说明 |
|---|---|
| 数据支撑 | 是否有真实 trace、benchmark 或日志证据 |
| 因果链条 | 是否能从 workload 特征推导到 SSD 能力要求 |
| 可测试性 | 是否能设计清晰实验验证 |
| 产品可实现性 | 是否对应固件、控制器、驱动、系统集成或规格定义 |
| 风险边界 | 是否避免从局部测试过度外推 |

结论分为三类：

| 级别 | 含义 |
|---|---|
| 应保留 | 已有数据充分支持，可作为 P0 方向 |
| 可预研 | 逻辑合理，但还需要补测试或生态验证 |
| 需降级 | 当前证据不足，不应作为明确产品承诺 |

## 3. 需求合理性评审

### 3.1 需求：优化 128 KiB random read P99/P999

判断：**应保留，P0。**

理由：

1. 最新 per-I/O block trace 显示，KV cache real I/O 的主导 request size 是 128 KiB。
2. ShareGPT 中 128 KiB 占比为 93.94%，BurstGPT 中为 98.52%。
3. decode read 的 LBA 大跳比例很高：BurstGPT read `>=100 MiB` jump 为 89.11%，分离 decode/read 证据中可达 95.1%。
4. 这说明核心压力不是顺序读，也不是传统 4 KiB random，而是 128 KiB 大块随机读。

逻辑链条：

```text
KV cache page/block 序列化
  -> block layer 看到 128 KiB request
  -> decode 阶段从分散位置读历史 KV
  -> 相邻 read LBA 大跨度跳跃
  -> 用户感知受 read tail / TTFT 影响
  -> 产品应优化 128 KiB random read P99/P999
```

设计含义：

- 固件调度不能只服务 4 KiB random 指标。
- 测试规格应增加 `128 KiB random read, preconditioned, QD32/QD64, 30min+`。
- P99/P999 比平均 IOPS 更重要。

风险边界：

- 128 KiB 是当前 SGLang/kv-cache.py 路径下的实测结果，不应假设所有框架永远固定 128 KiB。
- 因此测试矩阵保留 64 KiB、128 KiB、256 KiB 是合理的。

### 3.2 需求：read-priority GC

判断：**应保留，P0。**

理由：

1. 真实 workload 是 read-heavy，ShareGPT/BurstGPT read event 都超过 92%。
2. 写路径虽然更连续，但 eviction/writeback 会触发 FTL/GC，间接污染前台 decode read。
3. 长稳态测试显示 GC cliff、await P95 上升、read BW 下降等现象。
4. 用户体验主要受 decode read tail、TTFT、stall window 影响。

逻辑链条：

```text
KV cache serving 前台是 decode read
  + 后台持续 eviction/write
  -> SSD 内部 GC/写放大
  -> 如果 GC 与前台 read 抢资源
  -> read P99/P999 上升
  -> TTFT / decode latency / 服务队列受影响
```

设计含义：

- 固件需要前台 read 优先级。
- 后台 GC 要可节流、可分片、可避开 read burst。
- 应加入 mixed R/W 下 read P99 的测试，而不是只看写吞吐。

风险边界：

- 当前更多是从设备层和系统层现象推导，尚未有固件内部 GC telemetry 直接证明每一次 tail 都由 GC 导致。
- 下一步需要 SMART/NVMe telemetry、温度、SLC 使用、GC 状态协同采集。

### 3.3 需求：长稳态 GC cliff / tail drift 测试

判断：**应保留，P0。**

理由：

1. 2 分钟短测和 20-30 分钟长测排名不同。
2. Biwin X570 短测读带宽领先，但 30 分钟后与 Seagate FC530 基本收敛。
3. 多盘出现 GC cliff：Biwin 2.9 min、Seagate 8.1 min、ZhiTai 5.6 min、WD 7.8 min。
4. 长稳态中 read BW 后期下降、await P95 上升，说明 fresh/burst 结果不能代表在线服务。

逻辑链条：

```text
短测
  -> 更容易测到 SLC / 空盘 / burst 能力
长测
  -> SLC 耗尽 + GC + 写放大 + 温度
  -> tail drift 和 cliff 出现
AI serving
  -> 长会话、多轮、Agent、持续服务
  -> 必须看长稳态
```

设计含义：

- AI SSD benchmark 至少包含 30 / 60 / 120 分钟。
- 报告 early / middle / late 三段指标。
- 规格中应出现 cliff time、drop、recovery time。

风险边界：

- 早期 30 分钟测试存在 autoscaling 混杂，需要固定用户数重跑来隔离 SSD 行为。
- 不能把某次单盘长测结果直接外推到企业盘或多盘节点。

### 3.4 需求：ShareGPT + BurstGPT 双 workload

判断：**应保留，P0。**

理由：

1. ShareGPT 和 BurstGPT 的真实 block I/O 模式差异明显。
2. BurstGPT 的 IOPS/BW 更高，read LBA 更随机，适合作 SSD stress。
3. ShareGPT 更接近真实聊天 replay，保留更多连续/近邻读。
4. 单一 workload 会偏向某类 SSD 行为，导致选型或设计误判。

逻辑链条：

```text
ShareGPT
  -> realistic chat / prefix reuse / mixed behavior
BurstGPT
  -> high pressure / random read stress
两者都需要
  -> 同时覆盖用户体验与压力边界
```

设计含义：

- AI SSD 不能只定义一个“标准 KV cache workload”。
- 产品 scorecard 应至少分为 realistic score 和 stress score。
- fio 只能做 device baseline，不能替代这两类 workload。

风险边界：

- 当前 ShareGPT/BurstGPT 都是本地 forced-NVMe 配置，不等价完整生产 tiering。
- 下一步应增加 GPU/CPU/SSD tier enabled 的生产近似配置。

### 3.5 需求：真实 offload path activation gate

判断：**应保留，P0。**

理由：

1. 旧 Mooncake 报告的主要问题是目录叫 `Mooncake+SSD`，但日志显示 SSD path 没有真实启用。
2. 新复测通过 `Storage root directory`、`IsEnableOffloading`、offload files、read store、O_DIRECT 证明 path 已触发。
3. benchmark 指标本身不能证明 cache hit 来自 SSD。

逻辑链条：

```text
配置名 / benchmark 曲线
  -> 不能证明 SSD 参与
activation logs + read/write evidence
  -> 才能证明 SSD offload path
path 证明成立
  -> 性能指标才有 SSD 归因价值
```

设计含义：

- 所有 offload 测试必须有门禁。
- 没有 activation gate 的性能图只能归为系统 benchmark，不能归因为 SSD。
- 产品演示也需要内置 path evidence，而不是只展示 TTFT 曲线。

风险边界：

- Mooncake 当前 run 仍有 `insufficient space`、duplicate key、write page warning。
- 因此它证明 path 成立和趋势存在，但不证明 clean production benchmark。

### 3.6 需求：GDS / GPU-centric path

判断：**可预研，P1/P2；不应现在作为确定收益承诺。**

合理性理由：

1. 非 GDS 路径通常需要 SSD -> CPU DRAM -> GPU HBM，中间有 CPU bounce buffer。
2. KV cache offload 的目标是把历史 KV 尽快送回 GPU 使用，CPU copy 会增加 latency、CPU 占用和 jitter。
3. LMCache、Mooncake、SGLang 等系统正在向分层 KV cache 和更直接的数据路径发展。

为什么还不能定为 P0：

1. 当前本地数据还没有完成 GDS vs non-GDS 对比。
2. GDS 配置不等于真实 direct path，`cuFile` 可能 fallback 到 POSIX。
3. 当前硬件、驱动、文件系统、mount、GPU/SSD 拓扑都可能影响 GDS 是否有效。

建议定位：

- 作为高端 AI SSD / GPU server integration 的 P1/P2 预研。
- 先验证 CPU utilization、TTFT、read latency、tail 是否改善。
- 必须加入 fallback detection。

合理设计：

| 设计 | 是否合理 | 原因 |
|---|---|---|
| non-GDS baseline | 合理 | 必须有对照 |
| GDS direct path | 合理 | 可能减少 CPU copy 和 jitter |
| 多 NVMe path 绑定 GPU worker | 合理但需测试 | 拓扑相关，不能只靠理论 |
| 把 GDS 写成必然收益 | 不合理 | 当前没有本地实测支撑 |

### 3.7 需求：telemetry / cache-aware hint / eviction hint

判断：**可预研，P1/P2。**

合理性理由：

1. AI serving 的上层调度需要知道 SSD 是否处于 GC、throttle、tail risk。
2. KV cache 数据天然有语义：hot/cold、可重算/不可重算、短期/长期、prefix/cache line。
3. 传统块设备接口看不到这些语义，导致 SSD 只能被动处理。

但当前证据边界是：

- 现有测试证明 tail 和 GC 风险存在；
- 但还没有证明某种具体 hint API 能显著改善性能；
- 也没有验证上层框架愿意或能够传递这些 hint。

建议：

- telemetry 比 hint 更优先，因为可观测性是测试和定位的基础。
- hint 先做研究接口，不要直接作为短期产品承诺。

优先级：

| 能力 | 建议优先级 |
|---|---|
| GC / throttle / temperature / WA / SLC usage telemetry | P1 |
| per-namespace QoS telemetry | P1 |
| prefetch hint | P2 |
| eviction lifetime hint | P2 |
| KV semantic API | P2/P3 |

### 3.8 需求：高容量 QLC cold context tier

判断：**可预研，P1/P2；不能和 hot KV cache performance tier 混为一个产品。**

合理性理由：

1. 长上下文、Agent memory、RAG、历史会话会产生容量需求。
2. 不是所有 context 都是 hot decode path；cold context 更看 TB/$ 和可接受 tail。
3. 行业方向也在区分高性能 context tier 和高容量 context tier。

风险：

1. QLC 的写 tail、GC、endurance 可能不适合 hot KV eviction。
2. 如果把 QLC 用作 hot decode read miss path，P99 风险较高。
3. 需要和 TLC/SLC-like performance tier 分层设计。

合理设计：

```text
Hot context tier: 高性能 TLC / enterprise TLC / GDS / low tail
Cold context tier: 高容量 QLC / RAG / long-term memory / lower cost
```

### 3.9 需求：AI SSD System Kit

判断：**可预研，偏产品化包装；不是当前硬件 P0。**

合理性理由：

1. AI SSD 的价值很难只靠传统 SSD spec 说明。
2. 客户更容易理解 TTFT、cache hit、吞吐、长稳态曲线。
3. 一个包含 benchmark、driver setting、telemetry、报告模板的 kit 有助于销售和验证。

风险：

1. 软件维护成本高。
2. 容易变成 demo 工具，而不是可复用产品能力。
3. 如果底层 SSD tail 不稳，kit 只会更快暴露问题。

建议：

- 在 P0 benchmark SOP 稳定后再做。
- 先内部使用，再考虑外部交付。

## 4. 产品设计合理性评审

### 4.1 固件 / 控制器设计

| 设计方向 | 判断 | 理由 | 调整建议 |
|---|---|---|---|
| Read-priority GC | 合理，P0 | decode read 是核心随机压力，GC 会污染 tail | 增加 mixed R/W read P99 验证 |
| 128 KiB random 优化 | 合理，P0 | request size 有真实 block trace 支撑 | 保留 64/256 KiB 泛化测试 |
| Tail-aware scheduler | 合理，P0 | QD 和长稳态都显示 tail 风险 | 规格写 P99/P999，不只写 IOPS |
| 稳态 SLC / OP | 合理，P0/P1 | GC cliff 说明 fresh 结果不可靠 | 测 near-full 和 preconditioned |
| Mixed R/W isolation | 合理，P0 | eviction write 会影响 read | 设计前台 read QoS |
| Hot/cold data separation | 合理，P1 | workload 有 hot/cold 语义 | 需要上层 hint 或内部识别 |
| Multi-namespace QoS | 合理，P1 | 多模型/多租户会共享盘 | 先做测试，再做产品规格 |

### 4.2 设备规格设计

当前提出的 AI SSD spec 方向合理，但建议把规格分成“必须项”和“探索项”。

必须项：

| 指标 | 理由 |
|---|---|
| 128 KiB random read P99/P999 | 最贴合当前 KV read path |
| 128 KiB mixed R/W read tail | 反映 eviction/writeback 对 decode 的污染 |
| 30/60min preconditioned steady state | 避免 fresh/burst 误导 |
| GC cliff time/drop/recovery | 长服务稳定性核心 |
| temperature/throttle telemetry | 避免热降频混入 GC 判断 |
| write amplification / endurance | eviction write 影响寿命和 tail |

探索项：

| 指标 | 理由 |
|---|---|
| GDS readiness | 需要硬件/驱动/文件系统共同验证 |
| KV semantic hint support | 需要生态配合 |
| multi-worker QoS score | 需要生产近似 workload |
| cold context QLC score | 需要 RAG/Agent memory workload |

### 4.3 系统集成设计

判断：方向合理，但不能把系统问题全部归到 SSD。

合理部分：

- O_DIRECT / io_uring baseline 是必要的 non-GDS 路径。
- GDS 路径值得验证。
- 多盘分片和 GPU worker 绑定是未来节点级扩展必须面对的问题。
- telemetry 对上层调度很有价值。

需要警惕：

- 如果上层 cache manager 不稳定，SSD 再好也无法体现收益。
- 如果 offload path 没触发，所有 SSD 结论无效。
- 如果 CPU copy 是瓶颈，单纯升级 SSD 可能无效。
- 如果数据在 GPU/CPU tier 命中，SSD 差异会被掩盖。

建议：

系统集成测试必须同时报告：

1. SSD activation proof；
2. SSD read/write bytes；
3. CPU utilization；
4. GPU utilization；
5. TTFT / E2E latency；
6. block trace；
7. GDS fallback 状态。

## 5. 当前设计中需要修正或补强的点

### 5.1 不要把“AI SSD”定义得过窄

当前文档以 KV cache 为主，这是合理的，因为现有证据最强。但 AI SSD 产品可能还要覆盖：

- RAG vector index；
- Agent memory；
- checkpoint save/load；
- model weight loading；
- LoRA / adapter switching；
- SQLite/WAL、小文件 metadata；
- 多模型热切换；
- inference + background ingest 混部。

建议表述：

> KV cache 是当前证据最强、最适合切入的 AI SSD 场景；但最终 AI SSD 规格需要扩展到 RAG、Agent memory、checkpoint 和多模型混部。

### 5.2 不要把 consumer SSD 测试直接外推到企业 AI SSD

当前跨盘数据主要来自消费级 NVMe。它可以说明：

- 普通 SSD 指标不足；
- GC cliff 真实存在；
- DRAM、控制器和 firmware 差异很大；
- 长稳态必须测。

但它不能直接说明：

- 企业盘一定表现如何；
- 多盘节点一定如何；
- 24h 生产 SLO；
- 断电保护、端到端数据保护、热插拔等企业特性。

建议下一步加入 enterprise TLC 和高容量 QLC。

### 5.3 Mooncake 结果要继续降级使用

Mooncake 复测已经证明 SSD path 触发，这是重要进展。但因为 storage warning 仍存在，它只能支持：

- SSD offload path 打通；
- 本地收益趋势存在；
- 需要继续 clean benchmark。

不能支持：

- 本地结果等同官方；
- Mooncake+SSD 性能已定型；
- 当前 SSD 产品能力已经充分验证。

### 5.4 GDS 要验证 fallback

GDS 设计方向合理，但必须写清楚：

- 配置 `use_gds=true` 不等于真实 direct path；
- `cuFile` 可能 fallback；
- 文件系统、mount、driver、GPU/SSD topology 都会影响结果；
- 需要 `gdscheck`、日志、CPU utilization、带宽和 latency 联合判断。

## 6. 建议的需求优先级

### P0：立即保留

| 需求 | 理由 |
|---|---|
| 128 KiB random read P99/P999 | 真实 trace 直接支撑 |
| read-priority GC | read-heavy + GC cliff 共同支撑 |
| mixed R/W isolation | eviction write 会污染 serving |
| 30/60min long steady | 短测和长测结论不同 |
| ShareGPT + BurstGPT 双 workload | 覆盖 realistic 与 stress |
| per-I/O block trace | 防止 LBA 误判 |
| offload activation gate | 防止 SSD path 归因错误 |
| preconditioning | 生产不是 fresh 空盘 |

### P1：下一阶段预研

| 需求 | 理由 |
|---|---|
| LMCache/Mooncake/SGLang clean offload | 从设备能力走向系统收益 |
| GDS vs non-GDS | 验证 CPU bounce buffer 是否成为瓶颈 |
| enterprise TLC 对比 | 消费盘结论需要产品级验证 |
| multi-disk sharding | 单盘不足以代表节点 |
| telemetry | 支撑定位和 SLA |
| hot/cold context tier | 支撑产品分层 |

### P2：探索

| 需求 | 理由 |
|---|---|
| KV semantic hint | 需要生态配合 |
| AI SSD System Kit | 先内部固化 benchmark |
| QLC cold context SKU | 需要 RAG/Agent memory 数据 |
| DPU/RDMA context tier | 系统复杂度高，后续验证 |

## 7. 最终评审结论

当前需求和设计方向是合理的，尤其是把 AI SSD 从传统 SSD 规格中拆出来，转向：

1. 128 KiB 大块随机读；
2. read-heavy decode tail；
3. long steady GC cliff；
4. mixed R/W 隔离；
5. GDS / GPU-centric path；
6. telemetry 和系统级 offload 验证。

严谨地说，这些方向不是从市场口号推出来的，而是从现有测试事实推出来的：

```text
真实 block trace
  -> 128 KiB + 大跨度随机 read
  -> 需要 128 KiB random read tail

ShareGPT/BurstGPT 对比
  -> realistic 与 stress 不同
  -> 需要双 workload benchmark

长稳态跨盘测试
  -> GC cliff 和 tail drift 改变结论
  -> 需要 long steady / preconditioning / GC-aware design

Mooncake 复测
  -> SSD path 必须先证明 activation
  -> 需要 offload gate 和系统级验证

GDS 路径分析
  -> CPU bounce buffer 可能成为瓶颈
  -> GDS 值得预研，但必须实测
```

因此，建议把当前设计作为**AI SSD 预研 v1.0 需求框架**采用，但在对外或对老板汇报时明确三条边界：

1. **P0 方向已经有较强数据支撑。**
2. **P1/P2 是合理预研假设，还需要实测确认。**
3. **当前不能直接承诺最终产品规格、最终选型或生产 SLO。**

