# AI SSD 多盘对比与产品性能验证计划

日期：2026-06-10

本文是在现有 KV Cache、fio、bpftrace、iostat 和跨盘测试结果基础上，对报告正确性、多盘对比设计、AI SSD 产品性能验证计划、产品设计方向给出的核验与建议。它不替代已有单项报告，而是作为后续产品预研执行入口。

## 当前报告核验结论

现有报告在 `docs/ai-ssd-report-index-and-verification-2026-06-10.md` 修正后，核心数字与本地 JSON/CSV 结果基本一致。仍需注意三点：

| 项目 | 核验结论 | 产品解读 |
|---|---|---|
| KV Cache saturation | 70B TP8 CPU0 users12 是当前最有价值的服务边界点；8B users32 是 device-level 轻但 service-level 已排队 | AI SSD 不能只看 device P95，必须同时看 E2E、队列和 QoS |
| Long steady-state | 30 分钟测试 device health PASS，但 E2E P95 已到 838s | 稳态读写还能承载 object I/O，不代表服务系统仍健康 |
| Cross-vendor fio | BIWIN 是 burst 和 QD64 random 强；Seagate 是 mixed R/W 强；ZhiTai 是 15 分钟持续读更稳 | 产品定位应区分 burst、mixed、steady 三类冠军 |
| BIWIN X570 characterization | Gen5 x4、TLC-like、SLC cache 条件相关、出缓存约 1.6 到 1.7GiB/s | 不能把 fresh SLC 峰值当作 AI serving 稳态规格 |
| bpftrace/iostat | 可用于定位 I/O 层级，但原始日志巨大，不应入库 | 报告应保存摘要、图表和复现命令，原始日志本地归档 |

已复核的关键 KV Cache 数字：

| Run | Requests | Req/s | Storage I/O P95 | Read Device P95 | Write Device P95 | E2E P95 | Storage Read | Storage Write | Device health |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 70B TP8 CPU0 users12 | 3363 | 11.21 | 2295.21ms | 128.26ms | 154.63ms | 141.31s | 911.89GiB | 77.55GiB | PASS |
| 8B TP8 CPU0 users32 | 7726 | 25.75 | 661.39ms | 43.86ms | 112.67ms | 129.36s | 823.89GiB | 71.77GiB | PASS |
| 70B long steady 30min | 24285 | 13.49 | 1656.59ms | 160.75ms | 148.22ms | 838.05s | 3678.84GiB | 439.33GiB | PASS |

已复核的跨盘摘要：

| Vendor | Seq R | Seq W | 4K R QD64 | 4K W QD64 | 90/10 Mixed R | 50/50 Mixed R | 15min End BW | 15min Drift |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WD SN570 | 2275 MB/s | 1936 MB/s | 337255 IOPS | 331012 IOPS | 437 MB/s | 139 MB/s | 557 MB/s | -5.9% |
| BIWIN X570 | 8573 MB/s | 7965 MB/s | 494891 IOPS | 510840 IOPS | 902 MB/s | 460 MB/s | 777 MB/s | -30.5% |
| ZhiTai Ti600 | 6345 MB/s | 3696 MB/s | 392477 IOPS | 444001 IOPS | 846 MB/s | 313 MB/s | 941 MB/s | -12.8% |
| Seagate FC530 | 4989 MB/s | 4600 MB/s | 454003 IOPS | 457291 IOPS | 1271 MB/s | 862 MB/s | 765 MB/s | -22.1% |

说明：T4 文件中的 `r_await_first_us` / `r_await_last_us` 字段名可能与 iostat 原始单位不一致，因此本计划只把 T4 的带宽和 drift 作为强结论。

## 当前测试的不足

当前测试已经能回答“单盘在 KV Cache workload 下大致能撑到哪里”，但还不能完整回答“AI SSD 产品应该怎么设计、怎么验收、怎么扩成多盘系统”。

| 不足 | 影响 | 后续补法 |
|---|---|---|
| 大多是 single run | 无法区分真实差异和运行波动 | 关键 cell 做 3 次，报告 median/P95 区间 |
| 跨盘测试是串行单盘 | 不能推断多盘扩展效率 | 增加 1/2/4 盘 scaling test |
| 文件系统和挂载状态不同 | 可能混入 filesystem、free space、温度差异 | 统一格式化、挂载参数、空闲比例、预处理流程 |
| 只测 RAID/单盘还不够 | KV object tail 可能被最慢盘拖累 | 同时测 RAID0、mdraid/LVM、应用级分片 |
| bpftrace 原始日志过大 | 复盘困难，且不适合上传 | 生成摘要 JSON/CSV 和图表，原始日志只本地保存 |
| page cache 影响仍需隔离 | DRAM 可能掩盖 SSD 差异 | 固定 CPU cache、drop cache、cgroup memory 三种口径 |

## 多盘对比设计

多盘测试不应该只测“总吞吐是否翻倍”。AI SSD serving 关心的是 object-level tail latency、跨盘负载均衡和最慢盘放大效应。

### 测试矩阵

| 层级 | 配置 | 目的 | 必看指标 |
|---|---|---|---|
| 单盘 baseline | 每块盘独立跑 T1/T2/T4/T5/T6/T7 + KV 70B users8/10/12 | 建立每盘能力画像 | object P95/P99、drift、mixed R/W |
| 2 盘 RAID0 | 同型号 2 盘，mdraid 或 LVM stripe | 测吞吐扩展和 tail 是否恶化 | scaling efficiency、P99、per-disk util |
| 4 盘 RAID0 | 同型号 4 盘 | 测产品最大吞吐形态 | total BW、tail、热降频、CPU overhead |
| 异构盘 RAID0 | 不同型号混合 | 验证最慢盘拖累程度 | per-disk skew、最慢盘 await、P99 |
| 应用级分片 | cache-dir 按 user/request/hash 分配到多盘 | 对比 RAID0 与软件调度 | 负载均衡、故障隔离、tail |
| 多盘并发单盘 | 多个 benchmark 实例分别打不同盘 | 判断 PCIe/root complex/CPU 是否成为共享瓶颈 | 总吞吐、NUMA/CPU、iostat per device |

### 多盘关键指标

| 指标 | 计算方式 | 合格方向 |
|---|---|---|
| Scaling efficiency | 多盘吞吐 / 单盘吞吐 / 盘数 | 2 盘 > 1.7x，4 盘 > 3.0x 作为初始目标 |
| Tail amplification | 多盘 P99 / 最强单盘 P99 | 越接近 1 越好，>2 需要定位 |
| Per-disk skew | max(per-disk BW) / mean(per-disk BW) | <1.2 较健康，>1.5 说明分布不均 |
| Slowest-disk dominance | 最慢盘 await 与 object P99 的相关性 | 高相关说明需要应用级分片或 QoS |
| Thermal drift | 后 10 分钟 BW / 前 10 分钟 BW | >0.9 较健康，<0.8 需散热或 firmware 优化 |
| Write interference | 混合写入时读 P99 增幅 | 增幅越小越适合 KV serving |

### 推荐执行顺序

1. 先用同型号 2 盘做 RAID0 与应用级分片 A/B，对比 tail latency，而不是先追 4 盘峰值。
2. 再做 4 盘同型号 scaling，确认 PCIe/root complex、CPU 和文件系统没有成为新瓶颈。
3. 最后做异构盘混合，验证产品是否能容忍盘间差异；如果 tail 被最慢盘主导，产品方案应偏应用级调度而不是透明 RAID0。

## AI SSD 产品性能验证计划

### P0：硬件基础画像

| 测试 | 方法 | 输出 |
|---|---|---|
| PCIe link | `lspci -vv`, `nvme list`, `nvme smart-log` | Gen、lane、firmware、温度、功耗状态 |
| NAND 倾向 | 大文件持续写、出缓存速度、公开规格交叉判断 | TLC-like / QLC-like 倾向，不能宣称物理证明 |
| SLC cache | fresh、steady、mixed R/W 三种状态 | cache-in speed、post-cache speed、cache size 区间 |
| 热稳定性 | 30/60/120 分钟持续读写 | BW drift、温度、throttle 点 |
| 空间占用敏感性 | 20%、50%、80%、90% used | GC 和 tail latency 是否恶化 |

### P1：合成 I/O 基准

| 测试 | 推荐参数 | 产品意义 |
|---|---|---|
| Sequential burst | 128KiB, QD32, direct=1 | 冷启动、模型/KV 大块加载 |
| Random 4K | QD1/4/16/64/256 | metadata、小块压力和控制器并行度 |
| KV block mix | bssplit 4K 到 128K，read 90% | 贴近 bpftrace 蒸馏 workload |
| Mixed R/W | 90/10、70/30、50/50 | prefill 写与 decode 读互相干扰 |
| iodepth sweep | QD 1 到 1024，重点 16/32/64 | 找合理队列深度，避免只堆高 QD |
| Preconditioned rerun | 写入 1 到 2 倍盘容量后重跑 | 得到稳态产品规格 |

### P2：KV Cache 产品 workload

| Workload | 配置 | 目的 |
|---|---|---|
| ShareGPT | 8B TP8 CPU0.5 users2/4 | 真实聊天流程和 trace 工具验证 |
| BurstGPT 8B | TP8 CPU0 users8/16/32 | 轻模型生产 trace baseline |
| BurstGPT 70B | TP8 CPU0 users8/10/12/16 | 产品边界主线 |
| Synthetic long-context | 8B/70B, users 梯度 | 找极限 object size 和 first FAIL |
| Prefill-only | 固定 users，关闭 decode | 诊断写路径 |
| Decode-only | 固定 users，重放读路径 | 诊断读路径 |
| Full profiling | first PASS 与 first FAIL | 绑定 KV object、block layer、device telemetry |

### P3：长稳态与可靠性

| 测试 | 时长 | 判定重点 |
|---|---:|---|
| 30 分钟 smoke | 30min | 快速观察 GC drift |
| 2 小时 steady | 120min | 热、GC、page cache、host memory 漂移 |
| 24 小时 soak | 24h | firmware 稳定性、错误、SMART、tail outlier |
| Power cycle 后复测 | 重启后重复代表性 cell | SLC 恢复、FTL 状态、可复现性 |
| Near-full test | 80% 到 90% used | AI SSD 最差可用容量下表现 |

## 产品验收门槛建议

以下是用于 AI SSD 预研的初始门槛，后续应根据目标模型、目标 GPU 数和服务 SLA 调整。

| 类别 | 指标 | 建议门槛 |
|---|---|---|
| KV object | Read Device P95 | <200ms |
| KV object | Write Device P95 | <500ms |
| KV object | Storage I/O P99 | 不超过 P95 的 2 到 3 倍 |
| Service | E2E P95 | 不出现分钟级排队 |
| Service | QoS compliance | interactive/responsive 不应接近 0 |
| Steady | 30min BW drift | 优先 <10%，可接受 <20%，>30% 需标红 |
| Mixed R/W | 90/10 read BW | 不低于单纯 random read 的合理比例，且 P99 不失控 |
| Multi-disk | 2 盘 scaling | >1.7x |
| Multi-disk | 4 盘 scaling | >3.0x |
| Multi-disk | per-disk skew | <1.2 优先，>1.5 需要解释 |
| Firmware | thermal throttle | 长稳态不得频繁掉速 |
| Endurance | TBW/DWPD | 需要按 KV write/day 估算，而不是只看消费级保修 |

## AI SSD 产品设计方向

### 1. 固件方向

AI SSD 应优先优化稳定 tail，而不是只优化 fresh SLC 峰值。

| 方向 | 原因 |
|---|---|
| 稳定 pSLC 或 reserved SLC | KV serving 需要长时间稳定，不是短时间跑分 |
| Read-priority mixed scheduling | decode 读路径直接影响服务尾延迟 |
| GC QoS 控制 | 后台 GC 不应在高峰期制造 P99 outlier |
| 大 object 顺序化 | KV object 常由大量 128KiB I/O 组成，控制器应提升连续大块效率 |
| 热管理可预测 | 降频可以接受，但不能突然 cliff |

### 2. 系统软件方向

| 方向 | 原因 |
|---|---|
| 应用级分片优先评估 | 比 RAID0 更容易做 per-disk QoS 和故障隔离 |
| KV object placement | 按模型、用户、session、hotness 分层放置 |
| 冷热分层 | 热 KV 留 DRAM/HBM，冷 KV 下沉 SSD |
| 读写隔离 | prefill 写与 decode 读可用不同盘组或不同队列 |
| Backpressure | 当 SSD tail 恶化时限制新请求，避免 E2E 分钟级排队 |

### 3. 产品叙事方向

面向 AI SSD，建议避免只宣传“顺序读写峰值”。更可信的产品卖点应是：

| 卖点 | 应配套证据 |
|---|---|
| KV Cache object P95/P99 稳定 | BurstGPT/70B TP8 first PASS/FAIL |
| Mixed R/W 下读尾延迟低 | 90/10 fio + KV mixed profile |
| 长稳态无明显 GC cliff | 30/120 分钟 drift |
| 多盘线性扩展 | 1/2/4 盘 scaling 和 per-disk skew |
| 低 page cache 依赖 | CPU0 / drop cache / cgroup memory 对比 |
| 可复现 fio workload | 从 bpftrace 蒸馏的 bssplit/rwmixread，并固定合理 QD |

## 下一步建议

优先级最高的下一轮测试：

1. 对目标候选盘做 70B TP8 CPU0 BurstGPT users8/10/12 的 3-run median。
2. 对同型号 2 盘做 RAID0 vs 应用级分片对比，必须采集 per-disk `iostat -x 1`。
3. 对 BIWIN、ZhiTai、Seagate 各做一次 120 分钟 KV steady-state，验证 15 分钟 T4 drift 是否会继续扩大。
4. 对 first PASS 和 first FAIL 统一产出四层 profiling 摘要：benchmark JSON、io trace summary、bpftrace summary、iostat/pidstat summary。
5. 把报告生成流程固化为脚本：输入 result JSON/log，输出小型 markdown/CSV/PNG，不提交原始大文件。

当前最稳妥的产品判断是：BIWIN X570 适合展示 burst 能力，Seagate FC530 更适合 mixed R/W，对长稳态 serving 更应重视 ZhiTai Ti600 的低 drift 特征。真正的 AI SSD 产品验证不能用单一 fio 峰值下结论，必须用 70B KV Cache object tail、长稳态 drift 和多盘扩展效率共同判断。
