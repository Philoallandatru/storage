# AI SSD 预研汇报 PPT 大纲：KV Cache I/O 证据链与固件设计方向

**日期:** 2026-07-02  
**形式:** Markdown 版 PPT 草稿，每个主题 1-2 页  
**目标听众:** 老板 / 产品 / 固件 / 测试团队  
**核心目标:** 用实测数据证明 AI SSD 不是“普通高性能 SSD 改名”，而是需要围绕 KV cache / LBA 随机读 / 写入 GC / SLC / QoS / telemetry 重新定义固件策略。

---

## 总体主线

> KV cache offload 的真实压力不是传统 4K random，也不是单纯顺序写，而是 **128KiB 为主的大块随机读 + 顺序/近邻写 + 长稳态 GC 干扰 + workload 级突发队列**。  
> AI SSD 固件设计应围绕 **Read Priority、固定/可配置 pSLC、multiple namespace / stream 隔离、GC 可控、telemetry 可观测** 展开。

**必须先讲清楚的证据口径:**

| 口径 | 数据源 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| KV benchmark 逻辑层 | `result.json/cache_stats` | KV 逻辑读写量、token/s、cache hit、应用层延迟 | 不能证明 SSD 物理读写一定发生 |
| 设备聚合层 | `iostat -dx -m 1` | 每秒设备 read/write MB/s、IOPS、`aqu-sz`、util | 不能看 LBA 跳跃和每个 I/O |
| block per-I/O 层 | `bpftrace block_rq_issue` CSV | 真实 block-layer read/write、LBA、I/O size、时间顺序 | 不是 SSD 内部 NAND 物理地址 |

---

# 主题 1：为什么要重新定义 AI SSD

## Slide 1. AI SSD 的问题不是“平均带宽不够”，而是“读尾延迟 + GC 不可预测”

**建议图:** `docs/assets/io-three-way-comparison/01_signal_dashboard.png`

**页面要点:**

- 三种 KV workload 的 block I/O 模式差异很大，不能用一个 fio 曲线替代。
- 这里的 `default/synthetic` 指 `kv-cache.py` 默认 mixed prefill+decode baseline；不是旧版 fio synthetic。旧 fio synthetic 只能做设备能力标定，不能做真实 KV LBA 结论。
- BurstGPT 是压力上界：`35.2K Block IOPS`，`4.25 GiB/s Block BW`，read `>=100MiB jump` 为 `89.11%`。
- ShareGPT 更接近聊天：`14.1K IOPS`，`1.64 GiB/s`，read events `94%`，但读连续性更强。
- Default mixed workload 接近 BurstGPT 量级：`30.8K IOPS`，`3.75 GiB/s`。

**实验数据:**

| Workload | 定位 | Block IOPS | Block BW | Read events | Write events | Read `>=100MiB` jump |
|---|---|---:|---:|---:|---:|---:|
| default / synthetic baseline | runner 默认 mixed | 30,806 | 3.75 GiB/s | 88% | 12% | 79.16% |
| ShareGPT | 多轮聊天 | 14,063 | 1.64 GiB/s | 94% | 6% | 56.97% |
| BurstGPT | 突发压力上界 | 35,195 | 4.25 GiB/s | 92% | 8% | 89.11% |

**分析结论:**

- AI SSD 的核心指标应包含 `128KiB random read P99/P999`、mixed R/W 下 read tail、GC cliff，而不是只看顺序读写峰值。
- BurstGPT 用于压力上限；ShareGPT 用于真实聊天行为；default 用于 runner baseline。

**固件设计方向:**

- Read Priority 调度。
- 128KiB random read fast path。
- Mixed R/W 隔离。
- GC/fold 可抢占。

**推理依据:**

```text
block trace 证明 read-heavy + 大跨度 LBA jump
  -> 前台 decode read 是用户体验关键路径
  -> 写入/GC 如果抢占 read，会放大 TTFT/P99
  -> 固件必须优先保护 read tail，而不只是提高平均带宽
```

---

## Slide 2. Synthetic/default、ShareGPT、BurstGPT：三类 workload 各自回答不同问题

**建议图:** `docs/assets/io-three-way-comparison/02_iops_bw_timeline.png`

**页面要点:**

- `default/synthetic baseline`：用于确认 runner 默认 mixed prefill+decode 的设备压力，不等于 fio synthetic。
- `ShareGPT`：用于模拟多轮聊天和长上下文，吞吐低但排队可能更重。
- `BurstGPT`：用于压力上界和突发到达，读随机性、IOPS、带宽都更高。
- 三者不能互相替代；产品测试需要同时覆盖“真实聊天 tail”和“突发压力上限”。

**实验配置口径，6/29 三路 bpftrace:**

| Workload | 命令口径 | model / users / duration | cache tier | tracepoint |
|---|---|---|---|---|
| default / synthetic baseline | `kv-cache.py` 默认 mixed | `llama3.1-8b`, 8 users, 120s, TP=1 | GPU/CPU `0/0 GiB`，forced NVMe | `block:block_rq_issue` |
| ShareGPT | ShareGPT multi-turn dataset | `llama3.1-8b`, 8 users, 120s, TP=1 | GPU/CPU `0/0 GiB`，forced NVMe | `block:block_rq_issue` |
| BurstGPT | `--use-burst-trace` | `llama3.1-8b`, 8 users, 120s, TP=1 | GPU/CPU `0/0 GiB`，forced NVMe | `block:block_rq_issue` |

**模式对比:**

| Workload | I/O 形态 | 适合验证 | 不适合验证 |
|---|---|---|---|
| default / synthetic baseline | high IOPS，大跨度随机读，近邻写 | 默认 runner 压力、baseline | 不能代表聊天上下文分布 |
| ShareGPT | read-heavy，部分连续读，QD 更容易堆积 | 聊天 tail、cache hit 变化、长上下文 | 不适合作为最大带宽上界 |
| BurstGPT | 最大 IOPS/BW，读跳跃最大 | 突发压力、读优先调度极限 | 不代表所有真实聊天 |
| fio synthetic | 可控 QD/size/rw mix | 设备能力边界、回归测试 | 不能证明真实 KV LBA 和 token/s 收益 |

**分析结论:**

- 老板汇报不能只放一张 fio 图；fio 是“设备标尺”，KV trace 是“业务证据”。
- AI SSD 规格定义应同时包含 microbench 指标和 KV trace 指标。

**推理依据:**

```text
fio synthetic 可控但缺少真实请求到达和 LBA 生命周期
kv-cache trace 不可完全控但保留真实读写时序
  -> 两者互补
  -> 产品结论必须以真实 KV trace 为主，以 fio 做边界和回归
```

---

## Slide 3. 证据分层：不能把 KV 逻辑读误当成 SSD 物理读

**建议图:** `docs/assets/kvcache-0629-iostat-repro/0629_5min_iostat_dashboard.png`

**页面要点:**

- 6/29 5min 配置复现显示：KV 逻辑层读多写少，但本轮 `/mnt/ai_ssd0` 的 `iostat` 看到的是写主导。
- 这不是否定 bpftrace LBA 读；而是说明不同测试路径、文件系统、page cache 会改变物理设备观测。

**实验数据，2026-07-02 5min iostat 复现:**

| 指标 | BurstGPT 5min | ShareGPT 5min |
|---|---:|---:|
| KV 逻辑读 | 433.9 GiB | 349.7 GiB |
| KV 逻辑写 | 37.1 GiB | 55.1 GiB |
| KV 读占比 | 92.1% | 86.4% |
| iostat 设备读 | 0.16 GiB | 0.68 GiB |
| iostat 设备写 | 37.20 GiB | 54.12 GiB |
| iostat 设备读占比 | 0.4% | 1.2% |

**分析结论:**

- 5min `result.json` 的 `Storage Read BW` 是 `tier_storage_kv_bytes_read / duration`，不是设备层 read bandwidth。
- 如果要证明 SSD 真实读路径，必须用 `iostat/bpftrace` 验证。
- Mooncake / LMCache / SGLang 这类系统测试必须先证明 offload path 真触发。

**固件设计方向:**

- 产品测试必须内置 path activation gate。
- 固件/驱动要暴露可观测 telemetry，而不是只让系统侧猜。
- AI SSD benchmark 规范要分应用层、系统层、设备层三类指标。

**推理依据:**

```text
同一 workload 下 cache_stats read 很高
  但 iostat read 很低
  -> page cache / filesystem / FUSE 可能吸收 read
  -> 不能只凭 benchmark JSON 做 SSD 物理结论
  -> AI SSD 测试必须有 block-layer evidence
```

---

# 主题 2：5min / 180s 复现实验数据如何汇报

## Slide 4. 同配置 5min 复现：逻辑读写比例成立，QD 差异显著

**建议图:** `docs/assets/kvcache-0629-iostat-repro/0629_5min_runtime_timeline.png`

**测试配置:**

| 参数 | 值 |
|---|---|
| model | `llama3.1-8b` |
| users | `16` 起始 + autoscaling |
| duration | `300s` |
| GPU/CPU tier | `0/0 GiB` |
| TP | `8` |
| generation | `none` |
| max concurrent allocs | `2` |
| cache dir | `/mnt/ai_ssd0/...` |

**实验数据:**

| 指标 | BurstGPT 5min | ShareGPT 5min |
|---|---:|---:|
| Avg token/s | 3195.6 | 372.1 |
| Requests | 3926 | 600 |
| Total tokens | 958,685 | 111,641 |
| Cache hit | 97.9% | 72.2% |
| KV read/write | 433.9 / 37.1 GiB | 349.7 / 55.1 GiB |
| KV read share | 92.1% | 86.4% |
| KV read BW | 1.45 GiB/s | 1.17 GiB/s |
| KV write BW | 0.12 GiB/s | 0.18 GiB/s |
| QD mean / p95 / max | 30.1 / 62.0 / 94.9 | 78.2 / 198.8 / 292.9 |

**分析结论:**

- BurstGPT token/s 高，但 QD 低于 ShareGPT；ShareGPT token/s 低，但排队压力更大。
- ShareGPT 的低 cache hit、大上下文、多轮对话特征更容易造成 tail latency 和 queue buildup。
- token/s 不能单独代表 SSD 压力。

**固件设计方向:**

- 支持 read QoS 和 queue isolation。
- 针对 ShareGPT 类低吞吐高 QD 场景优化 tail，而不是只优化吞吐。
- namespace / stream 分离让聊天 KV 与后台写入分离。

**推理依据:**

```text
ShareGPT token/s 低
  但 QD p95 约 199，高于 BurstGPT 62
  -> 系统等待不是简单吞吐问题
  -> 固件要优化排队与 tail，而不是只看平均带宽
```

---

## Slide 5. 180s 快速复验：趋势稳定，可作为快速回归用例

**建议图:** `docs/assets/kvcache-0629-iostat-repro-3min/0629_180s_iostat_dashboard.png`

**实验数据:**

| 指标 | BurstGPT 180s | ShareGPT 180s |
|---|---:|---:|
| Avg token/s | 2950.1 | 363.0 |
| Requests | 2204 | 355 |
| Total tokens | 531,021 | 65,341 |
| Cache hit | 97.8% | 63.1% |
| KV read/write | 239.2 / 20.4 GiB | 241.9 / 32.1 GiB |
| KV read share | 92.2% | 88.3% |
| KV read BW | 1.33 GiB/s | 1.34 GiB/s |
| KV write BW | 0.11 GiB/s | 0.18 GiB/s |
| QD mean / p95 / max | 25.6 / 54.9 / 78.8 | 77.4 / 211.5 / 332.5 |

**分析结论:**

- 180s 的 KV 读写比例与 300s 方向一致。
- 180s 可以作为快速 regression / smoke，用于确认配置、读写比例、QD 差异。
- 不能用 180s 代替长稳态 GC 测试。

**固件设计方向:**

- 测试矩阵分层：
  - 180s：功能和 workload 形态验证。
  - 5min：短时压力与 QD。
  - 30-120min：SLC/GC/热稳定性。

**推理依据:**

```text
180s 与 300s 的 read share 接近
  -> workload 形态稳定
但 GC cliff 通常在 15-30min 以后暴露
  -> 180s 不能证明生产稳态
```

---

# 主题 3：LBA 时间顺序和空间分布说明什么

## Slide 6. bpftrace 方法：LBA 数据来自 block layer per-I/O trace

**建议图:** 可用一页采集链路图：`kv-cache.py -> VFS/FS -> Linux block layer -> NVMe driver -> SSD`

**采集方法，6/29 三路 LBA 数据:**

| 项 | 内容 |
|---|---|
| tracepoint | `tracepoint:block:block_rq_issue` |
| 采集粒度 | 每个 block request issue 事件 |
| 字段 | `timestamp_ns, dev, sector, bytes, rwbs, comm, pid` |
| LBA 推导 | `host LBA byte offset = sector * 512` |
| 方向判断 | `rwbs` 中包含 `R` 归为读，包含 `W` 归为写 |
| 后处理 | `scripts/analyze_sharegpt_burstgpt_io.py` / `scripts/analyze_block_lba_trace.py` |
| 输出 | `block_lba_trace.csv`, `lba_trace_summary.json`, timeline / CDF / block size 图 |

**原理解释:**

- `block_rq_issue` 是 Linux block layer 向块设备派发请求时触发的 tracepoint。
- 这里看到的是 host 侧 block request：时间、设备号、起始 sector、大小、读写方向。
- `sector * 512` 是 host-visible LBA byte offset；它不是 SSD 内部 NAND page/block，也不是 FTL 映射后的物理地址。
- 因为采的是 per-I/O issue stream，所以可以按时间顺序画 read/write LBA timeline，也可以计算相邻 I/O 的 LBA jump。

**和上次错误 LBA 分析的区别:**

| 口径 | 旧 6/25 LBA last-touch | 6/29 per-I/O bpftrace |
|---|---|---|
| 数据结构 | `@d[dev, sector] = timestamp` map | 每个 I/O 一行 CSV |
| 同一 sector 多次访问 | 只保留最后一次 | 每次访问都保留 |
| 能否证明真实时间顺序 | 不能严格证明 | 可以 |
| 能否算 sequential ratio / jump CDF | 不能严谨计算 | 可以按相邻 I/O 计算 |
| 适合用途 | 空间触达范围探索 | 真实 block-layer I/O 模式分析 |

**分析结论:**

- 6/29 的 LBA 图不是模拟数据，也不是 benchmark JSON 推导；它来自 Linux block layer 实际派发事件。
- 但它仍不是 SSD 内部物理 NAND 地址，所以不能直接推断 die/page 级磨损和 FTL 内部搬移。

**推理依据:**

```text
block_rq_issue per-I/O event
  -> 真实进入 Linux block layer 的 read/write 请求
sector * 512
  -> host LBA byte offset
按 timestamp 排序
  -> 可观察时间顺序上的读写分布
但 SSD FTL 内部映射不可见
  -> 不能说这是 NAND 物理地址
```

---

## Slide 7. 时间顺序读写分布：读确实落到 block layer

**建议图:**

- `docs/assets/lba-rw-timeline/burstgpt_rw_lba_timeline.png`
- `docs/assets/lba-rw-timeline/sharegpt_rw_lba_timeline.png`

**实验数据，6/29 bpftrace LBA CSV:**

| Workload | Duration | Read events | Write events | Read GiB | Write GiB |
|---|---:|---:|---:|---:|---:|
| ShareGPT | 140.9s | 1,860,197 | 121,488 | 216.6 | 14.1 |
| BurstGPT | 129.8s | 4,202,656 | 363,971 | 507.3 | 43.7 |

**观察:**

- BurstGPT 大部分秒级窗口读占比在 90% 以上，读 IOPS 和读带宽持续高位。
- ShareGPT 更脉冲化，读写混合比例随时间变化更大。
- LBA 散点显示 read/write 在 host LBA 空间反复跳转，不是单纯顺序扫描。

**分析结论:**

- bpftrace CSV 证明那次测试的 read 确实进入 Linux block layer。
- 这与 7/2 iostat 复现实验“设备读少”不矛盾；它们是不同测试路径和数据源。

**固件设计方向:**

- 需要 read/write 时间片级调度，而不是只根据总体比例做静态策略。
- 读路径要能在写入穿插时保持低 P99。
- telemetry 需要秒级或更细粒度暴露 read/write mix、queue、GC pressure。

**推理依据:**

```text
秒级读占比高 + LBA 跳转
  -> 前台读是高频随机访问
写入穿插
  -> 后台写 / GC 有机会干扰读
  -> read-priority scheduler 必要
```

---

## Slide 8. LBA 跳跃：KV cache 是大跨度随机读，不是普通顺序读

**建议图:** `docs/assets/io-three-way-comparison/03_lba_delta_cdf.png`

**实验数据:**

| 指标 | default | ShareGPT | BurstGPT |
|---|---:|---:|---:|
| Read exact contiguous | 0.0% | 41.77% | 10.08% |
| Read `<1MiB` | 0.1% | 42.27% | 10.30% |
| Read `>=100MiB` jump | 79.16% | 56.97% | 89.11% |
| Read delta p50 | 5,033 MiB | 2,675 MiB | 31,056 MiB |
| Read delta p95 | 88,607 MiB | 154,298 MiB | 126,769 MiB |
| Write exact contiguous | 0.9% | 94.37% | 97.63% |
| Write `<1MiB` | 95.1% | 96.36% | 98.40% |

**分析结论:**

- Read 是大跨度随机访问；write 是连续或近邻追加。
- 这是一种非对称 I/O：随机读压力 + 顺序写/GC 压力。
- SSD 固件不能用“写连续所以简单”来理解，因为写会触发 GC，GC 会影响随机读。

**固件设计方向:**

- Read path：优化 128KiB random read tail。
- Write path：顺序写聚合到 pSLC / append region。
- FTL：按 stream/namespace 识别 KV hot/cold，降低热冷混写。
- GC：优先搬冷数据，降低前台 read 干扰。

**推理依据:**

```text
读：大跨度随机
写：近邻/连续
  -> FTL 热冷数据混在一起会放大 GC
  -> namespace/stream hint 可以帮助固件分离生命周期
```

---

## Slide 9. Block size：AI SSD 测试必须增加 128KiB random read

**建议图:** `docs/assets/io-three-way-comparison/04_block_size_distribution.png`

**实验数据:**

| Workload | 128KiB 占比 | 次主导 |
|---|---:|---|
| default | 99.6% | 其他 <1% |
| ShareGPT | 93.9% | 64KiB 约 6% |
| BurstGPT | 98.5% | 其他 <1% |

**分析结论:**

- KV cache 的设备侧 block size 不是传统数据库的 4KiB random 为主。
- 128KiB 是当前路径下的主导 I/O size。
- 测试如果只做 4K randread / seqread，会错过真实压力。

**固件设计方向:**

- 增加 128KiB read command fast path。
- 读合并/预取不能假设顺序性；需要面向大跨度随机的 channel 并行。
- 评估指标增加：
  - `128KiB randread P99/P999`
  - `128KiB mixed R/W read tail`
  - preconditioned 30min+。

**推理依据:**

```text
block trace 中 128KiB 占 94%-99%
  -> 真实瓶颈不是 4K benchmark
  -> 产品规格和固件 tuning 必须加入 128KiB 粒度
```

---

# 主题 4：SLC / GC / 长稳态风险

## Slide 10. 短测优势会被长稳态 GC 抹平

**建议图:** `docs/assets/charts/08_duration_bars.png` 或 `docs/assets/charts/07_long_drift_compare.png`

**实验数据，KV Cache 30min drift:**

| Disk | 120s | 20min | 30min | 20->30min |
|---|---:|---:|---:|---:|
| Biwin X570 | 3.14 GB/s | 1.92 GB/s | 1.57 GB/s | -18% |
| Seagate FC530 | 2.34 GB/s | 1.91 GB/s | 1.54 GB/s | -19% |
| WD SN570 | 1.55 GB/s | 1.25 GB/s | 1.38 GB/s | +10% |
| ZhiTai Ti600 | 2.46 GB/s | 1.01 GB/s | 1.16 GB/s | +15% |

**关键现象:**

- Biwin / Seagate 在 20-25min 附近出现约 5min 低带宽窗口。
- 文档判断这是 GC stall，而不是瞬时噪声。
- Biwin 短测领先，但 30min 后与 Seagate 基本收敛：1.57 vs 1.54 GB/s。

**分析结论:**

- 消费级动态 SLC / GC 策略对 AI serving 风险很大。
- 平均吞吐不能代表生产稳定性；最坏窗口更重要。

**固件设计方向:**

- GC 可切片、可暂停、read-priority。
- 预留 OP / pSLC 降低 GC cliff。
- 多 namespace 隔离 checkpoint 写与 KV read。
- telemetry 暴露 GC pressure 和 cliff risk。

**推理依据:**

```text
短测高 BW
  -> 可能来自 SLC / fresh 状态
30min 出现 BW cliff
  -> SLC fold + GC + 写放大进入稳态
AI serving 长时间运行
  -> 必须优化 GC tail，而不是只优化 peak
```

---

## Slide 11. 固定 pSLC：不是为了宣传峰值，而是为了控制 tail

**建议图:** 可用一页结构图，文字描述即可。

**已有 SLC 数据，BIWIN X570 1TB:**

| 状态 | 估算 SLC cache | SLC 内写速 | 出 SLC 后写速 |
|---|---:|---:|---:|
| Fresh | ~71 GiB | ~5.08 GiB/s | ~1.67 GiB/s |
| Steady-state | ~95 GiB | ~5.07 GiB/s | ~1.82 GiB/s |

**Checkpoint 推算:**

| 模型 | FP16 checkpoint | SLC 覆盖 | 预期 |
|---|---:|---|---|
| 8B | ~16 GiB | 完全命中 | 约 3.2s |
| 70B | ~140 GiB | 部分命中 | 约 44-54s |
| 405B | ~810 GiB | 基本无用 | 约 8min |

**分析结论:**

- 消费级动态 SLC 对短 burst 有用，但长稳态不可预测。
- AI SSD 的 pSLC reserve 应作为可预测 context buffer，而不是普通文件复制 cache。
- 对 KV cache，pSLC 的直接价值不是加速 decode read，而是吸收 eviction/write、降低 GC 对 read 的干扰。

**固件设计方向:**

| 模式 | 用户容量 | 固定 pSLC reserve | 目标 |
|---|---:|---:|---|
| Capacity mode | 最大 | 小 | 冷数据 / 普通 PC |
| Balanced AI mode | 中 | 64-128 GiB | AI PC / workstation |
| Performance context mode | 较低 | 128-256 GiB | KV hot tier / checkpoint burst |

**推理依据:**

```text
5min ShareGPT KV write 55.1GiB
180s ShareGPT KV write 32.1GiB
70B checkpoint 约 140GiB
  -> 64-128GiB pSLC 能覆盖大量 KV eviction / 中模型 checkpoint
  -> 但必须配合 fold/GC read-priority
```

---

# 主题 5：AISSD 固件设计方向

## Slide 12. Multiple Namespace / Stream：把 AI 数据按语义隔离

**建议图:** 建议画 4 个 namespace 的分区示意。

**设计提案:**

| Namespace / Stream | 数据类型 | 固件策略 | 原因 |
|---|---|---|---|
| NS0 Capacity | 模型权重、冷 context、RAG cold data | TLC/QLC 容量优先 | 容量大，访问频率低 |
| NS1 KV Hot | KV eviction、recent context、decode reload | pSLC + read-priority | 低延迟、高复用、前台关键 |
| NS2 Checkpoint | checkpoint / safetensors save | 顺序写聚合，限速 fold | 大顺序写，避免污染 KV read |
| NS3 Metadata/WAL | SQLite/WAL/log/agent memory | 高耐久小写优化 | 小写频繁，影响交互 |

**实验依据:**

- KV read 是大跨度随机读；write 是顺序/近邻追加。
- ShareGPT/BurstGPT 的 read/write 时间结构不同。
- Checkpoint 写大小与 SLC 容量强相关。
- 长稳态 GC 会制造分钟级 stall。

**分析结论:**

- 一个单一 namespace 内混放 KV、checkpoint、RAG compaction、WAL，会让 FTL 无法区分生命周期。
- 多 namespace / stream hint 可以降低热冷混写，减少 GC 放大。

**固件设计方向:**

- 每个 namespace 有独立 QoS / GC budget / pSLC quota。
- 支持 host 通过 mount path 或 API 把 KV/cache/checkpoint 放到不同 namespace。
- 提供 namespace-level telemetry：pSLC free、GC pressure、read P99、write amp。

**推理依据:**

```text
不同 AI 数据生命周期不同
  KV hot: 短期热、可能重读
  checkpoint: 大顺序写、低读频
  RAG/WAL: 小写和 compaction
混在一起 -> FTL 热冷不分 -> GC 放大
namespace/stream 分离 -> 固件可做差异化策略
```

---

## Slide 13. Read Priority：前台 decode read 必须压过后台写入和 GC

**建议图:** 读优先调度队列示意。

**实验依据:**

| 证据 | 数据 |
|---|---|
| BurstGPT bpftrace | Read events 4,202,656，Write 363,971 |
| ShareGPT bpftrace | Read events 1,860,197，Write 121,488 |
| BurstGPT read `>=100MiB` jump | 89.11% |
| 30min drift | 出现约 5min GC stall |
| ShareGPT 5min QD p95 | 198.8 |
| ShareGPT 180s QD max | 332.5 |

**设计提案:**

```text
priority 0: foreground decode read
priority 1: metadata / WAL read
priority 2: user-visible write completion
priority 3: checkpoint streaming write
priority 4: SLC fold / GC / compaction
```

**固件功能:**

- GC/fold preemptible。
- read burst 到来时降低 fold 强度。
- 为 read queue 保留通道和 die 资源。
- 写入不无限期饿死：采用 aging 和 bandwidth floor。

**产品指标:**

| 指标 | 目标 |
|---|---|
| mixed R/W read P99 | 写入存在时不显著恶化 |
| GC cliff duration | 从分钟级降到秒级 |
| read starvation | 不出现 |
| write progress | 有最低保证 |

**推理依据:**

```text
用户体验关键路径 = decode read / TTFT
后台写和 GC 可延迟
  -> read 优先能保护 P99
但 checkpoint 不能完全饿死
  -> 需要 read priority + aging + write floor
```

---

## Slide 14. 固定 pSLC + GC 策略：把不可控 burst cache 变成可预测 context buffer

**建议图:** pSLC reserve / TLC capacity / GC fold backlog 三层图。

**设计提案:**

1. **固定 pSLC reserve:**
   - 64-128GiB：AI PC / workstation。
   - 128-256GiB：server / large context。
2. **pSLC quota 按 namespace 分配:**
   - KV hot reserve。
   - checkpoint burst reserve。
   - metadata/WAL small write reserve。
3. **fold policy:**
   - read idle 时 fold。
   - read burst 时暂停。
   - fold backlog 过高时通知 host 限速。

**实验依据:**

- 1TB X570 SLC 约 71-95GiB。
- 5min ShareGPT KV write 55.1GiB，BurstGPT 37.1GiB。
- 70B checkpoint 约 140GiB，现有 SLC 只能部分覆盖。
- 30min GC drift 出现 5min 级 stall。

**分析结论:**

- 固定 pSLC 的价值是 predictable tail，不是单纯峰值写速。
- pSLC 不够大时，checkpoint 会打穿；pSLC 过大时牺牲容量。
- 最合理是提供 mode / namespace quota，让系统按场景选择。

**推理依据:**

```text
消费级 dynamic SLC
  -> fresh/empty 测试好看
  -> 长稳态不可预测
AI serving
  -> 需要稳定 P99
固定 pSLC + telemetry
  -> 上层可以调度和限流
```

---

## Slide 15. Telemetry：AI SSD 必须告诉系统“现在还能不能承接 KV/Checkpoint”

**建议图:** telemetry -> runtime scheduler -> workload routing 的闭环。

**建议暴露指标:**

| Telemetry | 用途 |
|---|---|
| pSLC free / used | 判断是否还能承接 KV eviction / checkpoint burst |
| fold backlog | 判断后台搬运压力 |
| GC pressure level | 是否降低 checkpoint / RAG compaction |
| read P99 risk | 是否迁移请求或提升 HBM/DRAM cache |
| media busy / channel busy | 判断瓶颈是否在 NAND/controller |
| temperature / throttle | 区分热降速与 GC |
| write amplification | 判断 endurance 和 GC 健康 |
| namespace-level read/write tail | 找出哪个 workload 污染前台 |

**实验依据:**

- 5min/180s 中 QD 与 token/s 不线性。
- 30min drift 中 cliff 周期性出现。
- iostat 与 cache_stats 口径可能冲突，需要设备层观测补齐。

**分析结论:**

- 没有 telemetry，上层只能看到 token/s 下降，无法判断是 GC、page cache、温度、还是 offload path 没触发。
- AI SSD 不只是设备，还应成为系统调度的信号源。

**推理依据:**

```text
系统层 token/s/QD 发现异常
  但无法归因
SSD telemetry 暴露 GC/pSLC/fold/throttle
  -> runtime 可以暂停 checkpoint、迁移 KV、提升内存缓存
  -> 形成闭环控制
```

---

# 主题 6：GDS / 非 GDS 路径与产品定位

## Slide 16. GDS 是高端方向，但不能先承诺收益

**建议图:** Non-GDS vs GDS data path。

**路径对比:**

| 路径 | 数据流 | 风险 |
|---|---|---|
| Non-GDS | SSD -> page cache / CPU DRAM -> GPU | CPU copy、jitter、host 内存压力 |
| GDS | SSD -> cuFile DMA -> GPU HBM | 配置复杂，可能 fallback |

**当前证据边界:**

- 本地已有 GDS/非 GDS 路径分析，但尚缺严格同 workload、同设备、同拓扑的 A/B 数据。
- `enable GDS` 不等于真正走 direct path，必须检查 cuFile/fallback/log。
- 当前 kv-cache.py 逻辑路径仍会受 Python/NumPy/VFS 影响，不能直接代表生产 GDS。

**分析结论:**

- GDS 是 P1/P2 高端 server integration 方向。
- P0 仍应先做：block trace、cold-cache、direct path activation gate、read tail 和 GC 优先级。

**固件设计方向:**

- GDS-friendly namespace：对齐、O_DIRECT、低尾延迟。
- GPU topology-aware namespace binding。
- telemetry 支持 host 判断是否 fallback。

**推理依据:**

```text
KV reload 最终要进入 GPU 使用
  -> 跳过 CPU bounce 可能降低 jitter
但 direct path 配置复杂
  -> 没有 fallback evidence 不能承诺收益
```

---

# 主题 7：测试体系和产品路线

## Slide 17. AI SSD 测试矩阵：必须从 fio 扩展到真实 KV trace

**建议图:** 三层测试金字塔。

**测试矩阵:**

| 层级 | 测试 | 目的 | 必备证据 |
|---|---|---|---|
| Device microbench | fio 128KiB randread/randrw, QD sweep, preconditioned | 设备能力边界 | iostat / fio latency |
| KV trace replay | ShareGPT / BurstGPT / default + bpftrace | 真实 LBA、块大小、read/write 时间结构 | block_lba_trace.csv |
| System offload | Mooncake / LMCache / SGLang | 证明真实业务收益 | path logs + iostat/bpftrace + token/s |
| Long steady | 30/60/120min | GC drift / SLC cliff / thermal | time-series + telemetry |

**必须固定的门禁:**

1. cache dir 在目标设备上。
2. offload path 日志证明启用。
3. iostat 证明目标设备有 I/O。
4. bpftrace 证明 block-layer read/write/LBA。
5. 每轮清理空间，避免满盘污染。
6. 结果按应用层、设备层、block per-I/O 分开报告。

**分析结论:**

- fio 只能做 device ceiling，不能替代真实 KV LBA trace。
- 只有 system offload path 证明成立后，token/s 图才有 SSD 产品归因价值。

---

## Slide 18. 产品设计路线图：从 P0 固件能力到 P2 系统生态

**P0：必须做，直接来自实测数据**

| 方向 | 依据 | 验证 |
|---|---|---|
| 128KiB random read P99/P999 | 128KiB 占 94-99% | fio + bpftrace |
| Read-priority GC | read-heavy + GC stall | mixed R/W read P99 |
| 固定/可配置 pSLC | SLC 71-95GiB，长稳态 cliff | checkpoint + KV write burst |
| Long steady anti-cliff | 30min BW 下滑/5min stall | 60/120min run |
| path activation gate | cache_stats 与 iostat 可能不一致 | logs + iostat + bpftrace |

**P1：产品差异化**

| 方向 | 价值 | 风险 |
|---|---|---|
| Multiple namespace / stream hint | 热冷隔离、生命周期感知 | host 侧需要配合 |
| namespace-level QoS | KV read 与 checkpoint 写隔离 | 固件复杂度提高 |
| telemetry API | runtime 可调度 | 需要标准化 |
| pSLC quota mode | 容量 vs 稳定性可选 | 牺牲容量 |

**P2：高端系统集成**

| 方向 | 价值 | 前提 |
|---|---|---|
| GDS / cuFile path | 降 CPU copy/jitter | 必须证明无 fallback |
| GPU topology aware SSD | 多 GPU/多 SSD 绑定 | 服务器拓扑配合 |
| AI runtime SDK | LMCache/Mooncake/SGLang 集成 | 生态投入 |

**建议最终产品定位:**

> AI Context SSD：面向 KV cache、RAG、checkpoint、agent memory 的可观测、可调度、低 read-tail SSD，而不是只宣传顺序读写峰值的普通消费级 SSD。

---

## 附录 A：本大纲引用的关键图表

| 图 | 路径 | 用途 |
|---|---|---|
| 三路压力 dashboard | `docs/assets/io-three-way-comparison/01_signal_dashboard.png` | 说明 workload 差异 |
| IOPS/BW timeline | `docs/assets/io-three-way-comparison/02_iops_bw_timeline.png` | 秒级压力 |
| LBA CDF | `docs/assets/io-three-way-comparison/03_lba_delta_cdf.png` | 随机读 / 顺序写 |
| block size | `docs/assets/io-three-way-comparison/04_block_size_distribution.png` | 128KiB 主导 |
| 5min QD dashboard | `docs/assets/kvcache-0629-iostat-repro/0629_5min_iostat_dashboard.png` | QD / 读写口径 |
| 180s QD dashboard | `docs/assets/kvcache-0629-iostat-repro-3min/0629_180s_iostat_dashboard.png` | 快速复验 |
| ShareGPT LBA timeline | `docs/assets/lba-rw-timeline/sharegpt_rw_lba_timeline.png` | 时间顺序读写 |
| BurstGPT LBA timeline | `docs/assets/lba-rw-timeline/burstgpt_rw_lba_timeline.png` | 时间顺序读写 |

---

## 附录 B：汇报时避免踩坑的话术

**不要说:**

- “所有 KV read 都已经落到 SSD 物理读。”
- “iostat 没读，所以 LBA 图是错的。”
- “支持 GDS 就一定提升性能。”
- “加大 SLC 就能解决 KV cache offload。”
- “fio replay 可以替代真实 KV trace。”

**建议说:**

- “KV 逻辑读和 block-layer 物理读是两个口径，必须同时验证。”
- “6/29 bpftrace LBA 证明那次测试确实有大量 block-layer read。”
- “7/2 iostat 复现实验暴露了 page cache/FUSE 路径对归因的影响。”
- “AI SSD 的关键是 read-tail 可控、GC 可控、SLC 可预测、路径可证明。”
- “multiple namespace / pSLC / read priority / telemetry 是从实测 workload 推导出的固件方向。”
