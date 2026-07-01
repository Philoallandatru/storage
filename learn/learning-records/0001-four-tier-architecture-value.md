---
title: 理解四层存储架构的价值主张
date: 2026-06-30
tags: [architecture, storage-hierarchy, core-concept]
---

# 理解四层存储架构的价值主张

## Context
在学习 Mooncake 的第一节课时，我理解了为什么需要四层存储架构，以及每一层的作用。

## Key Insight
**SSD 的价值不是"快"，而是"比重新计算快 10,000 倍"**

这个洞察改变了我对 AI SSD 设计目标的理解。

## What I Learned

### 1. 延迟的相对性
- SSD (1-5ms) 比 DRAM (10μs) 慢 1000×
- 但 SSD (1-5ms) 比重新 prefill (10-30s) 快 10,000×
- 在 AI 推理场景中，避免重新计算是比绝对延迟更重要的目标

### 2. 容量驱动架构
- GPU VRAM: 40-80GB → 太小，只能放活跃数据
- Host DRAM: 100-500GB → 中等，但多请求时仍不够
- Remote DRAM: TB级 → 大，但成本高
- SSD: 多TB → 成本效益的容量扩展方案

### 3. 性能数据验证了架构价值
- Cache 命中率从 36% 提升到 84%（+133%）
- TTFT 从 16s 降到 9.4s（-41%）
- 吞吐量提升 2.4×

这些数字证明了四层架构不是过度设计，而是必要的。

## Why This Matters (For AI SSD)

对于 AI SSD 预研，这意味着：

1. **优化目标不同**：
   - 传统 SSD：追求更低的延迟（10ms → 1ms）
   - AI SSD：确保延迟可预测且稳定在 1-5ms 范围内

2. **工作负载特征**：
   - 大块顺序读取（256MB buckets）
   - 异步后台写入
   - 读多写少

3. **关键性能指标**：
   - P99 延迟 > 平均延迟
   - 带宽饱和能力 > 峰值带宽
   - O_DIRECT 性能 > 缓存 I/O 性能

## Questions Remaining

- [ ] 为什么选择 256MB 作为 bucket 大小？是否有 trade-off 分析？
- [ ] io_uring 的线程本地环比全局环性能提升多少？
- [ ] GPU → SSD 直接路径（GDS）未来是否值得？

## How to Apply

在设计 AI SSD 时：
1. 优先优化顺序大块读取性能
2. 确保 O_DIRECT 路径没有额外开销
3. 提供可预测的延迟而非极致的峰值性能
4. 考虑与 io_uring 的集成优化

## Related Resources
- FAST'25 论文 Section 4.3: Performance Evaluation
- docs/source/design/ssd-offload.md: Architecture
- 课程 0001: 四层存储架构
