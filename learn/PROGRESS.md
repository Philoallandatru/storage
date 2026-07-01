# 学习进度报告

**日期**: 2026-06-30  
**主题**: Mooncake 数据通路与 KV Cache 在 NVMe SSD 上的读写  
**目标**: AI SSD 预研

---

## 📊 已完成课程

### ✅ 课程 0001: 四层存储架构
**时间**: 15 分钟 | **难度**: ⭐⭐☆☆☆

**核心收获**:
- 理解了 GPU VRAM → Host DRAM → Remote DRAM → SSD 的四层结构
- 关键洞察: SSD 的价值不是"快"，而是"比重新计算快 10,000×"
- 性能数据: Cache 命中率 +133%, TTFT -41%, 吞吐量 +140%

**对 AI SSD 的启示**:
1. 延迟可预测性 > 极致低延迟
2. 大块顺序读写优化
3. O_DIRECT 性能保障

---

### ✅ 课程 0002: SSD Offload 写路径
**时间**: 20 分钟 | **难度**: ⭐⭐⭐☆☆

**核心收获**:
- 掌握了 5 步 offload 流程: 心跳 → GPU 检测 → 暂存 → 写入 → 通知
- 关键发现: 不使用 GPUDirect Storage，通过 cudaMemcpy 暂存
- Bucket 聚合: 256MB 批量写入，减少文件数量
- io_uring 优化: 线程本地环，批量异步 I/O

**对 AI SSD 的启示**:
1. 大块顺序写优化 (64-512MB)
2. O_DIRECT 路径无额外开销
3. 异步写缓冲 (DRAM + SLC)
4. QoS: 写不阻塞读

---

### ✅ 课程 0003: SSD Promotion 读路径
**时间**: 25 分钟 | **难度**: ⭐⭐⭐⭐☆

**核心收获**:
- 理解了三方协作: Requesting Client ↔ Master ↔ Target Client
- 完整的 6 步流程: Cache miss → 查询 → RPC → SSD 读取 → RDMA → DRAM
- ClientBuffer 双重注册: io_uring + Transfer Engine
- 性能瓶颈: SSD 读延迟占 80-90%

**对 AI SSD 的启示**:
1. **最关键**: P99 读延迟优化 (目标 < 2ms)
2. 高 QD 支持 (QD=32 不降低延迟)
3. 智能预读 (Bucket 识别)
4. QoS: 读优先级 > 后台 GC

---

## 🎯 关键洞察总结

### 1. 性能瓶颈明确
**SSD 读延迟 (1-5ms) 是整个系统的主要瓶颈**
- 占 promotion 总延迟的 80-90%
- P99 延迟比平均延迟更重要
- 读优化 > 写优化 (读是实时的，写是异步的)

### 2. 零拷贝边界清晰
| 路径 | 零拷贝？ | 延迟 |
|------|---------|------|
| GPU → Host | ❌ (cudaMemcpy) | ~10 μs |
| Host → SSD | ✅ (O_DIRECT DMA) | 1-5 ms |
| SSD → Host | ✅ (O_DIRECT DMA) | 1-5 ms |
| Host ↔ Remote | ✅ (RDMA) | 50-100 μs |

### 3. 设计选择的原因
- **不用 GDS**: 数据大多在 DRAM，暂存更简单
- **256MB Bucket**: 平衡文件数量与读取粒度
- **线程本地 io_uring**: 避免锁竞争
- **ClientBuffer 预注册**: 一次分配，多次使用

---

## 📝 学习记录

### 0001-four-tier-architecture-value.md
- SSD 的相对价值分析
- 容量驱动的架构设计
- AI SSD 优化目标与传统 SSD 的差异

### 0002-offload-write-path-design.md
- GDS 决策分析
- Pinned memory 的作用
- io_uring 线程本地环优化
- 写路径特征与 AI SSD 设计

### 0003-promotion-read-path-bottleneck.md
- 延迟分解与瓶颈识别
- Offload vs Promotion 不对称性
- Bucket 预读代价分析
- 读优化的重要性

---

## 🎓 已掌握的知识

### 架构理解
- [x] 四层存储层次与延迟梯度
- [x] 控制平面 / 数据平面分离
- [x] Master-Client 协作模型
- [x] Transfer Engine 零拷贝机制

### 数据通路
- [x] GPU → SSD 完整写路径
- [x] SSD → Remote DRAM 完整读路径
- [x] GPU 指针自动检测
- [x] ClientBuffer 生命周期管理

### 性能优化
- [x] io_uring 批量异步 I/O
- [x] O_DIRECT 4KB 对齐
- [x] BucketStorageBackend 设计
- [x] RDMA 多 NIC 聚合

### AI SSD 设计方向
- [x] P99 读延迟优化 (< 2ms)
- [x] 大块顺序 I/O (64-512MB)
- [x] QoS 隔离 (读 > 写 > GC)
- [x] 高 QD 支持 (QD=32)

---

## 🚀 下一步学习计划

### 课程 0004: io_uring 深度解析
**内容**:
- io_uring 架构 (SQ/CQ/环形缓冲区)
- 线程本地环实现
- 固定缓冲区优化
- 批量提交策略

### 课程 0005: 工作负载 Trace 分析
**内容**:
- 真实 Kimi trace 数据分析
- 对象大小分布
- 读写比例与访问模式
- 热点数据识别

### 课程 0006: Benchmark 与验证
**内容**:
- 性能测试方法
- 延迟分布分析
- 带宽利用率测试
- AI SSD 原型验证

---

## ❓ 待解答问题

### 架构相关
- [ ] 256MB bucket 的选择是否有基准测试验证？
- [ ] ClientBuffer 的典型大小配置？
- [ ] 多 Client 同时请求同一对象的去重机制？

### 性能相关
- [ ] io_uring 线程本地环 vs 全局环的性能对比数据？
- [ ] cudaMemcpy 是否是瓶颈？GDS 能改善多少？
- [ ] P99 延迟的主要贡献: 队列等待 vs 实际读取？

### 优化相关
- [ ] Bucket 部分读取的元数据开销 vs 带宽节省？
- [ ] 预读算法的命中率？
- [ ] NVMe 多 namespace 是否有帮助？

---

## 📚 参考资源使用情况

### 已深入阅读
- ✅ FAST'25 论文 Section 3-5
- ✅ `docs/source/design/ssd-offload.md`
- ✅ `docs/source/design/mooncake-store.md`
- ✅ `docs/research/kv-cache-data-path-2026-06-29.md`

### 已查看源代码
- ✅ `mooncake-store/src/file_storage.cpp` (offload/promotion)
- ✅ `mooncake-store/src/storage_backend.cpp` (Bucket)
- ✅ `mooncake-store/src/uring_file.cpp` (io_uring)
- ✅ `mooncake-store/include/gpu_staging_utils.h` (GPU 检测)

### 待深入
- [ ] `FAST25-release/traces/` - 真实工作负载数据
- [ ] `mooncake-transfer-engine/` - RDMA 实现
- [ ] io_uring 内核文档
- [ ] NVMe 规范相关部分

---

## 💡 对 AI SSD 预研的实际价值

### 明确的优化目标
1. **读延迟**: P99 < 2ms (当前 ~5ms)
2. **读带宽**: > 30 GB/s (匹配 PCIe)
3. **QD 支持**: QD=32 延迟 < 3ms
4. **QoS**: 读请求延迟不受写入影响

### 清晰的设计方向
1. **硬件层**: 多 die 并行、独立读写队列、大 DRAM 缓存
2. **固件层**: QoS 调度、智能预读、低延迟路径
3. **接口层**: 高 QD 优化、批量支持、NVMe 命令优化

### 验证方案
1. 使用 Mooncake trace 作为 benchmark
2. 模拟 256MB bucket 访问模式
3. 测试 io_uring QD=32 场景
4. P99 延迟分布分析

---

**总学习时间**: ~60 分钟  
**完成度**: 30% (3/10 课程)  
**下次学习**: 课程 0004 - io_uring 深度解析
