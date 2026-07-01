---
title: LLM 工作负载特征与 AI SSD 需求
date: 2026-06-30
tags: [workload, trace-analysis, requirements, dwpd]
---

# LLM 工作负载特征与 AI SSD 需求

## Context
第五节课分析了真实的 Kimi trace 数据，量化了 LLM 推理工作负载的特征，为 AI SSD 设计提供了数据依据。

## Key Insight
**AI 工作负载与传统存储完全不同：大对象、读多写少、短生命周期、超高 DWPD**

这不是增量优化的问题，而是需要重新设计存储架构。

## What I Learned

### 1. 对象大小分布

**数据**：
- < 1 GB: 45%（短会话）
- 1-5 GB: 35%（中等会话）
- 5-20 GB: 15%（长会话）
- > 20 GB: 5%（超长会话）

**关键发现**：
- 中位数：~2 GB
- P90：~8 GB
- P99：~25 GB

**vs 传统存储**：
- 数据库：4KB-64KB（小 1000×）
- 文件系统：几 KB 到几 MB

**启示**：
- 优化目标：1-5 GB（覆盖 70%）
- 必须支持：20+ GB 单对象
- 变长优化：不能假设固定大小

### 2. 读写比例：70:20

**为什么读多写少？**
- Cache 命中率 84%（大部分在 DRAM）
- 只有 cache miss 才读 SSD
- Offload 是异步批量的

**vs 传统存储**：
- 数据库：50:50（读写均衡）
- 文件系统：30:70（写多读少）

**启示**：
- 读性能 > 写性能
- P99 读延迟是关键
- 写可以异步，但读必须低延迟

### 3. 访问模式：顺序大块

**I/O 大小分布**：
- 256 MB: 60%（完整 bucket）
- 64-256 MB: 25%（部分 bucket）
- < 64 MB: 15%（元数据）

**vs 传统存储**：
- 随机 4KB I/O 占主导
- Mooncake：顺序 256MB 占主导

**启示**：
- 针对大块顺序优化
- 预读策略（bucket 级别）
- 减少随机访问开销

### 4. 时间局部性强

**重访问间隔**：
- < 1 分钟: 50%（多轮对话）
- 1-10 分钟: 30%（会话内）
- 10-60 分钟: 15%
- > 1 小时: 5%（冷数据）

**结论**：
- 80% 的重访问在 10 分钟内
- 超过 1 小时的数据几乎不再访问

**启示**：
- SSD 内置 DRAM 缓存（用于 1-10 分钟热点）
- 快速识别冷数据（> 1 小时未访问）
- 批量删除优化（会话结束）

### 5. 超高 DWPD 需求：50-100

**计算**：
```
100 万会话/天 × 2 GB/会话 × 40% offload = 800 TB/天
对于 10 TB SSD → 80 DWPD
```

**震撼的发现**：
- 企业级 SSD：1-3 DWPD
- 高性能 SSD：5-10 DWPD
- **AI SSD 需要：50-100 DWPD**（高 10-20×！）

**解决方案**：
1. 高耐久度 NAND（3D TLC/QLC + SLC 缓存）
2. 大容量 OP：30-50%（vs 传统 7-15%）
3. 智能 GC：识别短生命周期数据
4. 生命周期感知：短暂数据写入 SLC

### 6. 写放大因子（WAF）可控

**Mooncake 的优势**：
- 大块顺序写入 → 减少碎片
- 批量删除 → 整 bucket 失效
- 短生命周期 → 数据快速过期

**预期 WAF：2-3**（vs 传统随机写的 10-20）

这是 AI SSD 能在 50-100 DWPD 下生存的关键！

## Why This Matters (For AI SSD)

### 核心需求量化

**性能**：
- 顺序读：> 30 GB/s（PCIe Gen4）
- 顺序写：> 15 GB/s（异步后台）
- P99 读延迟：< 2 ms
- QD=32 延迟：< 3 ms

**容量**：
- 单盘：10-30 TB
- DRAM 缓存：64-128 GB
- OP 比例：30-50%

**耐久度**：
- DWPD：50-100（5 年）
- 总写入：100+ PB（10 TB 盘）
- 目标 WAF：< 3

### 设计验证清单

**必须回答的问题**：
- [ ] 如何实现 50-100 DWPD？
- [ ] DRAM 缓存如何管理？
- [ ] 生命周期感知 GC 算法？
- [ ] 大对象（20+ GB）的布局策略？
- [ ] P99 延迟如何保证？

## Questions Remaining

- [ ] 80 DWPD 的 SSD 现在市场上存在吗？成本？
- [ ] 30-50% OP 对成本的影响？
- [ ] 如何在固件中实现生命周期感知？
- [ ] 短期热点缓存的命中率预期？
- [ ] Bucket 删除如何触发 TRIM？

## Benchmark Ideas

### 模拟 Mooncake 工作负载

**使用 fio 配置**：
```ini
[global]
ioengine=io_uring
direct=1
bs=256m
iodepth=32
numjobs=4
runtime=3600

[read-heavy]
rw=randrw
rwmixread=70
size=10g

[large-objects]
rw=write
bs=1g-5g
```

**关键指标**：
- P99 读延迟
- 总吞吐量
- DWPD 模拟（写入总量）
- WAF 测量

## How to Apply

在 AI SSD 预研中：

1. **架构设计**：
   - 3D NAND + 大容量 SLC 缓存
   - 64-128 GB DRAM（热点 + 元数据）
   - 30-50% OP 预留

2. **固件优化**：
   - 生命周期感知 GC
   - 短期热点识别（< 10 分钟）
   - 批量删除快速路径

3. **验证方案**：
   - 使用 Kimi trace 回放
   - 模拟 80 DWPD 写入
   - 测量 5 年寿命下的性能衰减

## Related Resources
- 课程 0005: 工作负载 Trace 分析
- FAST'25 论文 Section 4: Workload Characterization
- `FAST25-release/traces/` - 真实 trace 数据
- FAST'25 演讲视频
