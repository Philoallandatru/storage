# Learning Mission: Mooncake KV Cache & NVMe SSD Data Path

## Primary Goal
**AI SSD预研** - 为AI工作负载专用的SSD进行技术预研

## Context
- **Role**: SSD预研工程师/研究员
- **Target**: 理解AI工作负载（特别是LLM KV cache）对SSD的需求
- **Output**: 为AI SSD设计提供技术输入和优化方向

## Why This Matters
Mooncake是业界领先的KVCache-centric架构（FAST'25 Best Paper），其SSD offload机制代表了LLM推理场景下存储系统的最佳实践。理解其数据通路对于设计AI专用SSD至关重要。

## Key Questions to Answer

### 1. 工作负载特征
- LLM KV cache的对象大小分布是什么？
- 读写比例和访问模式是什么（sequential/random）？
- 热数据和冷数据的区分特征？
- 延迟要求（P50/P99/P999）是多少？

### 2. I/O栈分析
- 从GPU到SSD的完整数据通路是什么？
- 哪些环节存在拷贝？哪些是零拷贝？
- io_uring、O_DIRECT等技术如何应用？
- 批处理（batching）策略是什么？

### 3. 性能瓶颈
- 当前SSD offload的主要瓶颈在哪里？
- 带宽利用率如何？延迟分布如何？
- 哪些场景下SSD是性能关键路径？

### 4. AI SSD优化机会
- 相比通用SSD，AI SSD可以在哪些方面专门优化？
- 固件层面可以做什么优化？
- 硬件层面（如缓存、并发度）需要什么特性？
- 与主机协同（如GPUDirect Storage）的机会？

## Success Criteria
- ✅ 能够画出完整的KV cache数据通路图（GPU→DRAM→SSD）
- ✅ 理解Mooncake的I/O优化技术（io_uring, O_DIRECT, vectored I/O等）
- ✅ 量化分析SSD在LLM推理中的性能影响
- ✅ 提出至少3个AI SSD的设计优化方向

## Timeline
预研阶段学习，预计需要深入理解核心技术细节

## Related Projects/Products
- Mooncake (开源LLM serving platform)
- 可能的内部AI SSD项目
