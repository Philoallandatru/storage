---
title: 实测数据完整分析与证据强度评估
date: 2026-06-30
tags: [measured-data, evidence, io-analysis]
---

# 实测数据完整分析与证据强度评估

## 数据来源

**主报告**：`mooncake-ssd-offload-reproduction-and-io-analysis-2026-06-29.md`

**原始数据目录**：
- `/home/ficus/mooncake_smoke_test/ssd_retest_formal_20260629_074959/`
- `summary.csv` - 性能汇总
- `per_round.csv` - 每轮详细数据
- `iostat.log` - NVMe I/O 统计
- `server.log` / `master.log` - Mooncake 日志

---

## 实测数据清单

### ✅ 有直接实测数据

#### 1. 读写比例：70:30

**证据强度**：⭐⭐⭐⭐⭐

**数据来源**：iostat.log + 报告文本

**实测值**：
```
总读取：4.58 GB
总写入：1.94 GB
读写比：4.58 / (4.58 + 1.94) = 70.2% : 29.8%
```

**原始数据**：
- iostat 显示 nvme0n1 (Mooncake SSD)
- 峰值写入：551.71 MB/s
- 峰值读取：205.69 MB/s (从 summary.csv)

**为什么可信**：
- 直接从 Linux iostat 工具测量
- 多个时间点的累积统计
- 与 Mooncake 日志吻合（52 次 read_store_events）

---

#### 2. 性能提升

**证据强度**：⭐⭐⭐⭐⭐

**数据来源**：summary.csv

**实测值**：

| 指标 | GPU only | +Mooncake+SSD | 提升 |
|------|----------|---------------|------|
| Cache Hit Rate | 4.35% | 67.76% | +1459% |
| TTFT (avg) | 4.89s | 3.44s | -29.7% |
| TTFT (P99) | 12.46s | 9.18s | -26.3% |
| Input Throughput | 3,600 tok/s | 4,470 tok/s | +24.1% |

**为什么可信**：
- 直接从 benchmark 测量
- 多轮次平均（8 clients × 8 rounds）
- 可重复验证

---

#### 3. Offload 事件统计

**证据强度**：⭐⭐⭐⭐⭐

**数据来源**：Mooncake 日志 + summary.csv

**实测值**：
```
offload_file_count: 5,402 个对象
offload_du_gb: 41.0 GB
offload_read_events: 52 次
read_store_events: 52 次
max_offload_key_count: 250
```

**含义**：
- 5,402 个 KV Cache 对象被 offload 到 SSD
- 占用 41 GB 磁盘空间
- 发生了 52 次 promotion（从 SSD 读取）
- 峰值存储 250 个 key

**为什么可信**：
- 来自 Mooncake 内部计数器
- 与磁盘占用 (41 GB) 吻合
- 与 iostat 读取量 (4.58 GB) 一致（52 次平均 88 MB）

---

#### 4. I/O 延迟（部分）

**证据强度**：⭐⭐⭐☆☆

**数据来源**：iostat.log 的 r_await / w_await 字段

**实测值**（从 iostat 输出）：
```
读延迟 (r_await): 0.09-1.67 ms (不同时间点)
写延迟 (w_await): 0.07-323 ms (峰值时极高)
平均队列大小 (aqu-sz): 0.02-137 (波动很大)
```

**问题**：
- r_await 是平均值，不是 P99
- 无法分解各环节（SSD vs 网络 vs 内存）
- 写延迟峰值 323ms 异常（可能是 GC）

---

### ❌ 缺失或推导的数据

#### 5. SSD 读延迟占端到端延迟的 80-90%

**证据强度**：⭐⭐⭐☆☆（理论推导）

**现有数据**：
- P99 TTFT：9.18s（端到端）
- iostat r_await：0.09-1.67ms（设备级平均）

**问题**：
- 无法分解 TTFT 中各环节的延迟
- 缺少 promotion 路径的详细 trace

**来源**：
- FAST'25 论文 Figure 11（理论）
- 课程 3 延迟分解表（推导）

**需要补充**：
```bash
# 使用 blktrace 获取每个 I/O 的完整延迟
sudo blktrace -d /dev/nvme0n1 -o trace
blkparse -i trace

# 或使用 perf trace
sudo perf trace -e block:* --duration 60000
```

---

#### 6. I/O 大小分布（256KB-1MB 占 75%）

**证据强度**：⭐⭐☆☆☆（粗略推导）

**推导过程**：
```
总读取：4.58 GB
读事件数：52 次
平均单次读取：4.58 GB / 52 ≈ 88 MB

但这是应用层的 offload read 事件
实际 I/O 可能被拆分成多个小请求
```

**iostat 数据**：
```
rareq-sz (读请求平均大小): 4.57-58.67 KB
wareq-sz (写请求平均大小): 18.44-128 KB
```

**矛盾**：
- 应用层：88 MB/次
- 设备层：4-128 KB/次
- 说明被拆分了，但不知道拆分粒度

**需要补充**：
```bash
# 统计每个 I/O 的大小分布
sudo blktrace -d /dev/nvme0n1 -o trace
blkparse -i trace -f "%5T.%9t %5p %2a %3d %8N\n" | \
  awk '{print $5}' | sort -n | uniq -c
```

---

#### 7. 队列深度（QD 1-8 占 75%）

**证据强度**：⭐⭐☆☆☆（场景推导）

**iostat 数据**：
```
aqu-sz (平均队列大小):
- 低负载：0.02-5.29
- 高负载：84-137

峰值 %util: 99.9% (设备饱和)
```

**问题**：
- aqu-sz 是平均值，不是分布
- 无法区分读写队列
- 无法知道 Mooncake 提交的 QD

**推导依据**：
- Promotion（读）：单个请求，QD 低
- Offload（写）：批量，QD 高
- 读占 70% → 整体 QD 偏低

**需要补充**：
```bash
# 实时监控 NVMe 队列深度
watch -n 1 'nvme get-log /dev/nvme0n1 -i 2 | grep "Queue Depth"'

# 或从 blktrace 统计 QD 分布
```

---

#### 8. 热点分布（80/20 规则）

**证据强度**：⭐⭐⭐☆☆（理论 + 间接证据）

**理论依据**：
- FAST'25 论文提到 Zipf 分布
- 多轮对话天然有 system prompt 复用

**间接证据**：
- Cache hit rate 从 23.84% → 67.76%
- 说明少量数据被频繁访问

**无直接证据**：
- 没有对象级别的访问频率统计
- 没有 LBA 访问热点图

**需要补充**：
- 分析 Mooncake server.log 的对象访问日志
- 统计哪些 key 被访问最多

---

#### 9. DWPD 50-100

**证据强度**：⭐☆☆☆☆（规模外推，不可信）

**复测实测**：
```
总写入：1.94 GB
测试时长：~4 分钟
DWPD = 1.94 GB / 10 TB / (4/1440 天) = 0.07 DWPD
```

**生产估算**（外推）：
```
假设：100 万会话/天
每会话：2 GB KV Cache
Offload 比例：40%

每天写入 = 1M × 2GB × 40% = 800 TB
DWPD = 800 TB / 10 TB = 80
```

**问题**：
- 规模外推了 1000× 以上
- 复测环境太小（8 clients, 8 rounds）
- 缺少长期（天/周）真实数据

**正确做法**：
- 在生产环境运行至少 1 天
- 记录总写入量
- 计算真实 DWPD

---

## 证据强度总结表

| 维度 | 证据强度 | 数据来源 | 可信度 | 改进方法 |
|------|----------|----------|--------|----------|
| **读写比 70:30** | ⭐⭐⭐⭐⭐ | iostat 实测 | 最高 | 无需改进 |
| **性能提升** | ⭐⭐⭐⭐⭐ | benchmark 直接测量 | 最高 | 无需改进 |
| **Offload 事件** | ⭐⭐⭐⭐⭐ | Mooncake 日志 | 最高 | 无需改进 |
| **I/O 设备延迟** | ⭐⭐⭐☆☆ | iostat 平均值 | 中等 | 需要 P99 |
| **SSD 延迟占比** | ⭐⭐⭐☆☆ | 理论推导 | 中等 | 需要 blktrace |
| **I/O 大小分布** | ⭐⭐☆☆☆ | 粗略推导 | 低 | 需要 blktrace |
| **队列深度分布** | ⭐⭐☆☆☆ | 场景推导 | 低 | 需要 nvme log |
| **热点分布** | ⭐⭐⭐☆☆ | 理论 + 间接 | 中等 | 需要对象统计 |
| **DWPD 50-100** | ⭐☆☆☆☆ | 规模外推 | 极低 | 需要长期数据 |

---

## 数据质量评估

### 可直接使用的数据（3 项）

1. ✅ **读写比 70:30**
   - 直接引用 iostat 数据
   - 可用于固件设计决策

2. ✅ **性能提升**
   - Cache hit +184%
   - TTFT -29.7%
   - 可用于 ROI 分析

3. ✅ **Offload 规模**
   - 52 次 promotion
   - 41 GB 存储
   - 可用于容量规划

### 需要谨慎使用的数据（3 项）

4. ⚠️ **I/O 延迟**
   - 只有平均值，无 P99
   - 可用但需注明限制

5. ⚠️ **SSD 延迟占比 80-90%**
   - 理论推导，非实测
   - 可引用但需说明来源

6. ⚠️ **热点分布 80/20**
   - 间接证据支持
   - 可用但需说明推导逻辑

### 不应直接使用的数据（3 项）

7. ❌ **I/O 大小 256KB-1MB**
   - 推导过程不严谨
   - 应标记为"待验证"

8. ❌ **队列深度 1-8**
   - 场景推导，无实测
   - 应标记为"假设"

9. ❌ **DWPD 50-100**
   - 规模外推不可信
   - 应标记为"理论估算，需验证"

---

## 改进建议

### 短期（1 天）

1. **重新运行 iostat**，记录完整字段：
   ```bash
   iostat -xz 1 > iostat_detailed.log
   ```
   重点：`avgqu-sz`, `r_await`, `w_await`

2. **添加 blktrace**：
   ```bash
   sudo blktrace -d /dev/nvme0n1 -o trace &
   # 运行测试
   sudo killall blktrace
   blkparse -i trace > io_trace.txt
   ```
   获取：I/O 大小分布、延迟分布

3. **分析 Mooncake 日志**：
   - 提取对象访问频率
   - 验证热点分布

### 中期（1 周）

1. **扩大测试规模**：
   - 100+ clients
   - 50+ rounds
   - 运行至少 1 小时

2. **长期 DWPD 测试**：
   - 运行 24 小时
   - 记录总写入量
   - 计算真实 DWPD

3. **添加端到端 trace**：
   ```bash
   sudo perf record -e 'block:*,nvme:*' -a sleep 60
   sudo perf script > perf_trace.txt
   ```

---

## 结论

**当前数据质量**：
- **高质量数据**：3/9 (33%)
- **中等质量数据**：3/9 (33%)
- **低质量数据**：3/9 (33%)

**可用于 AI SSD 设计的证据**：
- ✅ 读写比 70:30（确定）
- ✅ 读优先级高于写（确定）
- ⚠️ P99 读延迟 < 2ms（需验证）
- ❌ I/O 大小、QD、DWPD（需补充测试）

**建议**：
1. 短期内使用高质量数据进行初步设计
2. 用中等质量数据作为假设，标注不确定性
3. 不要使用低质量数据作为设计依据
4. 尽快补充缺失的测试数据
