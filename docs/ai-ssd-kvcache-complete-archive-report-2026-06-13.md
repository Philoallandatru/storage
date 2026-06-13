# AI SSD / KV Cache 完整实验归档报告

日期：2026-06-13

本文是当前 AI SSD / KV Cache 预研的完整归档报告。它补充 `docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md` 中没有展开的支线实验，包括 ShareGPT、BurstGPT、Synthetic、saturation sweep、prefill/decode 拆分、4 层 profiling、fio iodepth sweep、preconditioning、page cache sensitivity、BIWIN X570 介质画像、SLC cache、checkpointing 推演、K1-K5、跨盘 KV Cache 和长稳态测试。

本文的定位是技术档案，不是简短决策摘要。读者应先读整合决策报告，再用本文追溯每个结论来自哪个测试。

## 0. 报告分层

| 文档 | 定位 |
|---|---|
| `docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md` | 当前主决策报告，适合对外汇报和选型讨论 |
| `docs/ai-ssd-kvcache-complete-archive-report-2026-06-13.md` | 本文，完整实验归档，适合复盘和后续补测 |
| `docs/kv-cache-final-selection-2026-06-10.md` | 四盘 K4/K5/长稳态最终选型报告 |
| `docs/ai-ssd-multidisk-validation-plan-2026-06-10.md` | 多盘对比和产品验证计划 |
| `docs/ai-ssd-report-index-and-verification-2026-06-10.md` | 报告索引与部分数据核验 |

## 1. 实验路线图

本轮预研可以分成 8 个阶段：

| 阶段 | 目标 | 代表报告 | 当前状态 |
|---|---|---|---|
| S0 项目理解与跑通 | 理解 KV Cache benchmark、确认本机可跑 | 早期对话和命令记录 | 完成 |
| S1 ShareGPT 流程验证 | 真实聊天数据集，验证流程和 trace | `kvcache-ai-ssd-product-prestudy-complete` | 完成，压力较轻 |
| S2 BurstGPT 产品 baseline | 生产 trace，CPU0/TP8，放大 SSD 压力 | `kvcache-full-profiling-results` | 完成 |
| S3 Synthetic/TP/并发边界 | 找极限 object size 和 first FAIL | `kvcache-ai-ssd-product-prestudy-complete` | 完成 |
| S4 I/O profiling | L4/L3/L2/L1 四层定位 | `kvcache-full-profiling-results` | 完成 |
| S5 fio/介质画像 | distill workload、测 iodepth、preconditioning、SLC | `kvcache-fio-iodepth-sweep`, `biwin-x570-*` | 完成第一轮 |
| S6 跨盘单盘横评 | 四块 NVMe 单盘比较 | `cross-vendor-nvme-comparison`, `kv-cache-*` | 完成 |
| S7 长稳态与产品判断 | K4 20/30min，GC cliff，最终选型 | `kv-cache-final-selection` | 完成阶段性结论 |

## 2. 测试对象与硬件

### 2.1 SSD 列表

| Vendor ID | 型号 | 定位 | 关键特征 |
|---|---|---|---|
| `biwin_x570` | BIWIN X570 1TB | mainstream consumer NVMe | Gen5 x4，DRAM，TLC-like，burst 强 |
| `seagate_fc530` | Seagate ZP1000GV30012 | high-end consumer NVMe | Phison E18，DRAM，mixed R/W 和长稳态强 |
| `zhitai_ti600` | ZhiTai Ti600 1TB | domestic consumer NVMe | YMTC NAND，短时可看，长稳态写尾风险大 |
| `wd_sn570` | WD SN570 960GB | entry-level consumer NVMe | DRAM-less，低成本，主力 KV Cache 不推荐 |

### 2.2 重要限制

| 限制 | 影响 |
|---|---|
| 消费级 SSD | 不能直接等价为企业级 AI SSD 结论 |
| 多数测试 single run | 不能给严格统计置信区间 |
| 部分分区可用容量不同 | ZhiTai/WD 的 30min 对照只跑 900s |
| 多数 KV 压力测试强制 `--gpu-mem-gb 0 --cpu-mem-gb 0` | 能放大 SSD 差异，但不是生产真实 tiering |
| `trace-speedup=1000` | 适合压测，不适合作为唯一生产预测 |

## 3. Workload 分类与结论

| Workload | 数据来源 | 代表用途 | 当前结论 |
|---|---|---|---|
| Synthetic | benchmark 随机生成 | 压力边界、长上下文、大 object | 适合找 first FAIL，不是真实生产 |
| ShareGPT | 真实聊天数据 | 完整流程验证 | 上下文短、cache hit 高、SSD 压力轻 |
| BurstGPT | API trace | 产品 baseline | 当前最有价值的 SSD 压测主线 |
| K1-K5 | 四盘跨盘 KV Cache 矩阵 | 单盘横评 | 短测 BIWIN 强，长测 Seagate 稳 |
| fio distilled | 从 bpftrace/trace 蒸馏 | 可复现 SSD synthetic | 合理 qd 约 32，超大 qd 不应直接用 |
| Checkpoint 推演 | SLC cache + 模型大小估算 | 训练写入 | SLC 对 8B/70B checkpoint 有价值，对 405B 有限 |

## 4. ShareGPT 完整流程测试

ShareGPT 是真实聊天数据集，最早用于验证完整链路、dataset parser、trace mode、真实 I/O mode 和结果导出。

| 项 | 结果 |
|---|---|
| conversations | 319 |
| turns | 973 |
| context tokens mean | 约 123-137 |
| generation tokens mean | 约 264-310 |
| 真实 I/O read device P95 | 约 62ms |
| storage read | 约 9.79GiB |
| cache hit | 约 97.7%-98.2% |

结论：

| 结论 | 说明 |
|---|---|
| 流程验证价值高 | dataset、trace、real I/O、结果导出都能跑通 |
| SSD 压力价值低 | 上下文短、KV object 小、cache hit 高 |
| 不适合容量规划 | 不能用 ShareGPT 直接判断 AI SSD 上限 |

当前有效性：仍有效，但应定位为 smoke test / real-chat baseline，不是产品压力上限。

## 5. BurstGPT baseline 与 70B 扩展

BurstGPT 使用生产 API trace，配合 `--trace-speedup 1000`、TP8、CPU0/GPU0，用于放大 SSD 压力。

### 5.1 8B BurstGPT 梯度

| Run | 结果 | 关键数据 | 当前解读 |
|---|---|---|---|
| users2 | PASS | Read P95 17.96ms，Write P95 18.90ms | 轻压力 baseline |
| users4 | PASS | Read P95 31.54ms，Write P95 55.64ms | 写 tail 开始上升 |
| users6 | PASS | Read P95 41.54ms，Write P95 114.54ms | 写路径更敏感 |
| users8 | PASS | Read P95 46.48ms，Write P95 118.44ms | 仍有余量 |
| users32 saturation | device PASS / service FAIL | Read P95 43.86ms，Write P95 112.67ms，E2E P95 129.36s | device 未饱和，但排队导致服务不可用 |

### 5.2 70B BurstGPT 梯度

| Run | 结果 | 关键数据 | 当前解读 |
|---|---|---|---|
| users2 | PASS | Read P95 41.85ms，Write P95 18.68ms | 70B 起点健康 |
| users4 | PASS | Read P95 92.67ms，Write P95 125.53ms | tail 明显上升 |
| users6 full | PASS | Read P95 96.53ms，Write P95 114.02ms | 稳定可用 |
| users8 full | PASS | Read P95 164.63ms，Write P95 175.41ms | 接近 read 200ms 目标 |
| users12 saturation | service saturation | Read P95 128.26ms，Write P95 154.63ms，E2E P95 141.31s | 服务级已不可接受 |

关键判断：

1. 70B TP8 的实用边界在 users8 到 users12 之间。
2. 8B users32 的 device-level 仍轻，但 service-level 不健康。
3. 模型 KV bytes/token 是 SSD 压力的核心变量。70B object size 约为 8B 的 2.5 倍。

## 6. Synthetic 与 TP 扩展

Synthetic workload 主要用于找失败边界。它不是真实用户 trace，但可以构造长上下文和大 KV object。

| 测试 | 结果 | 关键数据 | 结论 |
|---|---|---|---|
| 8B TP1 users10 | FAIL | Read Device P95 3167ms，Write Device P95 925ms | TP1 object 太大 |
| 8B TP8 CPU0.5 users2 | PASS | Read Device P95 199ms | 接近安全边界 |
| 8B TP8 CPU0.5 users3 | FAIL | Read Device P95 255ms | 首个失败点 |
| 8B TP8 CPU0.5 users4 | FAIL | Storage I/O P95 1500ms | 并发增加导致 object tail 恶化 |

结论：TP 会显著影响单 rank KV object size。AI SSD 报告必须标注 TP，否则性能数字不可比较。

## 7. Trace mode vs real hardware I/O

`--io-trace-log` 会启用 trace mode，使用 NullBackend，不执行真实 GPU/CPU/NVMe I/O。

| 模式 | 适合 | 不适合 |
|---|---|---|
| Trace mode | 分析 workload shape、读写比例、object size、phase、tier | 容量规划、latency 判断 |
| Real hardware I/O | 判断 device P95/P99、E2E、QoS、队列和真实吞吐 | 快速大规模 trace 预演 |

关键例子：

| Run | Trace mode | Real hardware |
|---|---:|---:|
| 70B users12 Read Device P95 | 0ms | 128.26ms |
| 8B users32 Read Device P95 | 0ms | 43.86ms |

结论：trace mode 会系统性高估容量，产品容量规划必须使用真实硬件 I/O。

## 8. 4 层 I/O Profiling 归档

完整 profiling 同时采集 L4/L3/L2/L1：

| 层 | 产物 | 价值 |
|---|---|---|
| L4 KV object | benchmark JSON/XLSX | read/write device P95/P99、E2E、cache hit |
| L3 trace | `kv_trace.csv.zst` | ops、phase、tier、object size |
| L2 block | bpftrace `storage_latency_stack.bt` | Q2D/D2C、bssplit、fio distillation |
| L1 device/process | iostat/pidstat/perf | await、IOPS、BW、util、CPU |

代表性结果：

| Run | 关键产物 | 结论 |
|---|---|---|
| 70B users6 full | 94883 ops，887GiB read，78GiB write | profiling 数据完整且可信 |
| 70B users8 full | Read P95 164.63ms，util avg 30.4% | 更接近边界 |
| 8B users8 full | Read P95 67.60ms，Write P95 180.22ms | 8B object 小，读更轻 |

I/O pattern 早期发现：

| 配置 | total ops | mean size | P95 size |
|---|---:|---:|---:|
| 8B users8 | 94801 | 12.5MiB | 31.2MiB |
| 70B users6 | 94883 | 31.2MiB | 77.9MiB |
| 70B users8 | 94883 | 31.2MiB | 77.9MiB |

这些是 logical KV object 级别；后续 iostat 进一步揭示 block/device 层请求约 115-125kB。

## 9. Prefill-only / Decode-only 拆分

拆分测试用于分离写路径和读路径。

| 模式 | Requests | Read Dev P95 | Write Dev P95 | Read GB | Write GB | 解读 |
|---|---:|---:|---:|---:|---:|---|
| prefill-only | 6608 | n/a | 117.93ms | 0 | 152 | 纯写路径健康 |
| decode-only | 1772 | 88.92ms | n/a | 1266 | 0 | 纯读路径健康 |
| mixed 对照 | 3422 | 96.53ms | 114.02ms | 887 | 78 | 更接近真实压力 |

结论：

1. prefill-only 和 decode-only 有诊断价值。
2. 真正产品验收应以 mixed workload 为主，因为读写互扰、GC 和队列调度同时发生。

## 10. fio iodepth sweep

fio sweep 使用从 KV Cache/bpftrace 蒸馏出的 workload，人工扫合理 iodepth。

| Workload | 读写比例 | 最佳/合理 qd | 关键现象 |
|---|---|---:|---|
| ShareGPT 8B CPU0.5 | 61/39 | 32 | qd>32 后 IOPS 下降，P99 快速变差 |
| BurstGPT 8B CPU0 speedup1000 | 91/9 | 32-64 | IOPS 基本持平，高 qd 增加 write tail |
| TP8 CPU0.5 generic | 73/27 | 32 | qd>64 后延迟恶化 |

代表性数据：

| Workload | qd32 R IOPS | qd1024 R IOPS | qd32 R P99 | qd1024 R P99 |
|---|---:|---:|---:|---:|
| ShareGPT | 18.6k | 11.5k | 6.5ms | 166.7ms |
| BurstGPT | 21.0k | 21.1k | 3.6ms | 68.7ms |
| Generic | 13.3k | 13.3k | 5.1ms | 156.2ms |

结论：蒸馏出来的超大 iodepth 代表系统侧堆积，不应直接作为 fio 产品规格。当前合理 qd 约为 32。

## 11. SSD preconditioning

对 BIWIN X570 做约 570GiB sequential write 后，重复部分 fio sweep。

| 现象 | 结果 |
|---|---|
| R IOPS | 多数提升 4%-15% |
| R P99 | 高 qd 下改善 10%-49% |
| W P99 | 改善最大，部分 workload 下降 90%+ |
| 产品含义 | 生产规格应使用 preconditioned/steady-state，而不是空盘数字 |

重要 caveat：当前测试设备是系统盘分区，不是裸企业 SSD；preconditioning 的方向性有价值，但数值应在目标盘上复验。

## 12. Page cache sensitivity

Page cache sweep 用 distilled fio 比较 DRAM 策略。

| Cell | READ BW | READ P99 | 解读 |
|---|---:|---:|---|
| dram_unlimited | 1071MiB/s | 277us | 首轮 cold/order effect |
| dram_32gb | 1294MiB/s | 202us | warm/order effect 明显 |
| dram_8gb | 1231MiB/s | 269us | cgroup v2 未限制共享 page cache |
| dram_8gb_evict | 1158MiB/s | 258us | 近似 cold-cache baseline |

结论：

1. cgroup v2 `memory.max` 不能有效限制共享 page cache。
2. 在这个测试中，page cache 对读吞吐改善约 6%，对 P99 有一定改善。
3. order effect 明显，需要 randomized order + median-of-3 才能做强结论。

## 13. BIWIN X570 介质画像

### 13.1 基础 SLC / TLC-like 判断

| 指标 | 值 |
|---|---:|
| PCIe link | Gen5 x4 |
| 总写入 | 200GiB |
| 缓存内速度 | 5078MiB/s |
| 出缓存速度 | 1669MiB/s |
| 稳态尾部速度 | 1603MiB/s |
| 估算 SLC cache | 约 71GiB |
| 介质倾向 | strong TLC-like |

结论：测试不能物理证明 NAND 类型，但结合官方规格和出缓存速度，行为更像 TLC，不像典型低端 QLC。

### 13.2 Fresh vs steady-state

| 指标 | Fresh | Steady | 变化 |
|---|---:|---:|---:|
| SLC cache | 71GiB | 95GiB | +33% |
| cache-in speed | 5079MiB/s | 5073MiB/s | 持平 |
| post-cache speed | 1669MiB/s | 1825MiB/s | +9.4% |
| steady tail | 1603MiB/s | 1757MiB/s | +9.6% |

结论：BIWIN 的 SLC 行为是状态相关的，不能用单一固定 cache size 概括。

### 13.3 Mixed R/W 下 SLC cache

| 配置 | 结果 |
|---|---|
| sequential write | 5078 -> 1668MiB/s，有清晰 cliff |
| 50/50 mixed R/W | 约 1312 -> 1311MiB/s，无明显 burst/cliff |

结论：LLM KV Cache 这种 mixed random R/W 不能直接享受 sequential SLC burst。AI SSD 不能只宣传顺序写入 SLC 峰值。

## 14. Checkpointing 推演

基于 BIWIN X570 SLC cache 估算：

| 模型 | FP16 checkpoint | SLC 命中 | 预期 |
|---|---:|---|---|
| Llama3-8B | 约 16GiB | 完全命中 | 约 3-5s |
| Llama3-70B | 约 140GiB | 部分命中 | 约 44-54s |
| Llama3-405B | 约 810GiB | 基本无效 | 约 8min+ |

结论：SLC cache 对 checkpointing 更有价值，对 KV Cache mixed random R/W 价值有限。训练和推理应分开定义 AI SSD 指标。

## 15. fio 四盘横评 T1-T7

早期跨盘 fio 横评给出硬件基础画像。

| 场景 | 最优 | 结论 |
|---|---|---|
| Sequential burst | BIWIN X570 | 8.57GB/s read，7.96GB/s write |
| 4K QD64 random | BIWIN X570 | 约 495k read IOPS，511k write IOPS |
| Mixed R/W 90/10 | Seagate FC530 | 1.27GB/s read，明显领先 |
| Page cache sensitivity | WD 受益最大 | DRAM-less 依赖 host page cache |
| 15min sustained random read | ZhiTai end BW 最高，但后续 KV 长稳态不支持“主力推荐” | fio 与 KV Cache 要分开解释 |

重要修正：fio T4 的“ZhiTai 持续读更稳”不能直接推导为“ZhiTai 适合 KV Cache 主力盘”。后续真实 KV Cache K4 20/30min 显示 ZhiTai 写尾和 GC 后表现不可接受。

## 16. K1-K5 四盘 KV Cache 短测

K1-K5 是四盘跨盘 KV Cache 短测矩阵。

| 场景 | 模型 | users | duration | 用途 |
|---|---|---:|---:|---|
| K1 | 8B | 1 | 120s | 单用户 latency floor |
| K2 | 8B | 4 | 120s | 典型服务 |
| K3 | 8B | 8 | 120s | 高并发 |
| K4 | 8B | 16 | 120s | saturation probe |
| K5 | 70B | 4 | 180s | 大 object 压力 |

短测结论：

| 场景 | Winner | 结论 |
|---|---|---|
| K4 120s | BIWIN X570 | 3.14GB/s，read P99 72.9ms |
| K5 180s | BIWIN X570 | 2.77GB/s，read P99 93.8ms |
| 70B runner-up | Seagate FC530 | write P99 接近 BIWIN |
| 短时 8B runner-up | ZhiTai Ti600 | 读侧可看，写尾已高 |

方法论 caveat：早期 K1-K5 使用 CPU0/GPU0、`trace-speedup=1000`、`max-concurrent-allocs=2`、无 bounded cache capacity，适合作为 worst-case 横评，不应直接当生产预测。

## 17. K4 20/30 分钟长稳态

长稳态是当前最关键的新证据。

| Disk | K4 120s Read GB/s | K4 1200s Read GB/s | K4 30min Read GB/s | 结论 |
|---|---:|---:|---:|---|
| BIWIN X570 | 3.14 | 1.92 | 1.57 | burst 强，长稳态与 Seagate 收敛 |
| Seagate FC530 | 2.34 | 1.91 | 1.54 | 短测较弱，长稳态稳定 |
| ZhiTai Ti600 | 2.46 | 1.01 | 1.16 (900s) | 长稳态明显退化 |
| WD SN570 | 1.55 | 1.25 | 1.38 (900s) | 慢且多次 FAIL |

GC cliff：

| Disk | Cliff time | Drop |
|---|---:|---:|
| BIWIN X570 | 2.9min | -40.6% |
| ZhiTai Ti600 | 5.6min | -77.8% |
| WD SN570 | 7.8min | -40.6% |
| Seagate FC530 | 8.1min | -32.0% |

结论：2 分钟 winner 不是 20/30 分钟 serving winner。长稳态下 Seagate 的写尾和 GC stall 更适合 sustained serving。

## 18. I/O pattern 最终画像

来自 K4 GC-drift iostat 分析：

| 指标 | 结果 |
|---|---|
| read request median | 约 124-125kB |
| write request median | 约 113-116kB |
| `%rrqm` median | 0% |
| `%wrqm` median | 约 0.1% |
| 类型 | sparse-large-block random I/O |

盘间差异：

| Disk | r_await median | w_await median | w_await P99 | aqu_sz P99 |
|---|---:|---:|---:|---:|
| BIWIN X570 | 0.38ms | 14.3ms | 57.2ms | 108 |
| Seagate FC530 | 0.80ms | 7.1ms | 24.1ms | 58 |
| ZhiTai Ti600 | 0.61ms | 119.5ms | 511.2ms | 328 |
| WD SN570 | 1.57ms | 59.0ms | 604.8ms | 287 |

结论：Seagate 的核心优势不是最高 read peak，而是写服务时间和队列控制。ZhiTai/WD 的写服务时间和队列堆积是主风险。

## 19. 当前有效结论与被替代结论

| 旧结论/中间结论 | 当前状态 | 更新后结论 |
|---|---|---|
| BIWIN 是通用 all-rounder | 需要细分 | BIWIN 是短时 burst 冠军 |
| ZhiTai fio sustained read 更稳，适合 sustained serving | 被 KV 长稳态修正 | ZhiTai 不推荐作 KV Cache 主力 |
| 8B users32 SLA PASS | 已修正 | device-level 轻，但 service-level 已排队失败 |
| ShareGPT 可代表真实压力 | 限定 | 只代表真实聊天流程，不代表 SSD 压力上限 |
| Trace mode 可用于容量规划 | 错误 | trace mode 只能做 workload 形态分析 |
| SLC cache 大就是 KV Cache 好 | 限定 | SLC 对 sequential checkpoint 更有价值，对 mixed KV 有限 |

## 20. 数据与产物索引

| 类型 | 路径 |
|---|---|
| KV Cache 早期结果 | `results/kvcache-profile/*.json` |
| 4 层 profiling | `results/kvcache-profile/profiling/*` |
| fio sweep | `results/kvcache-profile/fio_sweep*` |
| page cache sweep | `results/kvcache-profile/pagecache_sweep/` |
| SSD characterization | `results/ssd-characterization/` |
| 四盘 fio | `results/cross_vendor/{t1,t2,t3,t4,t5,t6,t7}*` |
| 四盘 KV K1-K5 | `results/cross_vendor/kv_cache*` |
| K4/K5 headline docs | `docs/kv-cache-4disk-*` |
| charts | `docs/assets/charts/` |
| profiling charts | `docs/assets/kvcache-io-profiling/` |

不应上传/提交的内容：

| 类型 | 原因 |
|---|---|
| 原始 bpftrace 大日志 | 文件可到 GB 级 |
| 原始 iostat/pidstat 全量日志 | 可由摘要和脚本再生成 |
| datasets | 体积和授权风险 |
| cache-dir 测试文件 | 临时大文件 |

## 21. 完整不足清单

| 不足 | 影响 | 补救 |
|---|---|---|
| single run 多 | 无统计置信度 | 关键 cell 做 3-run median |
| 30min 仍偏短 | 不知道 GC cycle 是否长期稳定 | 做 60/120min/24h |
| CPU0/GPU0 worst-case | 不代表生产 tiering | 加 HBM/DRAM tier 对照 |
| trace-speedup=1000 | 改变真实时间尺度 | 加 10/100/1000 sweep |
| 无 bounded cache | eviction 不真实 | 设置 storage capacity |
| 无 mixed checkpoint + inference | 写互扰不足 | 联合 workload |
| 多盘系统未测 | 无法判断 scaling 和最慢盘效应 | RAID0 vs 应用级分片 |
| 消费级盘 | 不能代表最终 AI SSD | 加企业级 SSD/PLP/DWPD 验证 |
| cgroup page cache 限制不彻底 | DRAM 结论偏弱 | 用 invalidate、v1 cgroup 或 benchmark tier 参数 |

## 22. 后续执行优先级

| 优先级 | 测试 | 目的 |
|---|---|---|
| P0 | BIWIN/Seagate K4 30min 3-run median | 确认二者是否真等价 |
| P0 | K4 60/120min steady | 判断 GC stall 是否继续 |
| P0 | Production-like tiering | 加 HBM/DRAM，避免只看 worst-case |
| P1 | Bounded cache capacity | 测真实 eviction |
| P1 | Mixed checkpoint + KV Cache | 测写放大和读写互扰 |
| P1 | 2 盘 RAID0 vs 应用级分片 | 启动多盘系统验证 |
| P2 | 企业级 SSD 对照 | 判断消费级结论能否迁移 |
| P2 | ShareGPT + longer real-time replay | 验证真实低压聊天服务 |

## 23. 归档结论

本轮实验已经从“项目能否跑起来”推进到“可以定义 AI SSD 产品验证框架”。完整结论如下：

1. ShareGPT 证明流程可行，但不是压力上限。
2. BurstGPT CPU0/TP8 是当前最有价值的产品 baseline。
3. Synthetic 用于找边界，不能代表真实 trace。
4. 70B TP8 users8 到 users12 是当前本地 NVMe 的服务边界区间。
5. prefill-only/decode-only 有诊断价值，但 mixed workload 才是验收主线。
6. fio sweep 证明合理 qd 约 32，超大蒸馏 qd 不能直接使用。
7. preconditioning 和 SLC 测试证明空盘/fresh 数字不足以定义产品。
8. page cache 对读有帮助，但本轮 cgroup 方法有局限，需重测。
9. BIWIN X570 是短时 burst 强盘；Seagate FC530 是长稳态和 mixed R/W 更稳的候选。
10. ZhiTai Ti600 和 WD SN570 不适合作为 KV Cache 主力盘。
11. AI SSD 的产品指标应围绕 KV object P95/P99、GC drift、mixed R/W、长稳态和多盘扩展，而不是顺序峰值。

这份归档报告应作为后续补测、产品规格定义和对外汇报材料的事实底稿。
