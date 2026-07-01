---
title: SSD Offload 写路径的设计选择
date: 2026-06-30
tags: [offload, write-path, gpu-staging, design-decision]
---

# SSD Offload 写路径的设计选择

## Context
第二节课深入学习了 Mooncake 的 SSD Offload 写路径，从 GPU/DRAM 到 SSD 的完整数据流。

## Key Insight
**Mooncake 选择不使用 GPUDirect Storage (GDS) 进行本地 SSD offload**

这是一个重要的架构决策，反映了工程实践中"简单可靠优于理论最优"的原则。

## What I Learned

### 1. 为什么不用 GDS？

虽然 GDS 可以实现 GPU ↔ SSD 的直接传输（零拷贝），但 Mooncake 选择了传统的暂存模型：

**三个实际原因：**
- **批处理语义**：FileStorage 处理来自不同 tenants/segments 的对象批次，不是单一大块传输
- **数据源多样性**：数据可能在 GPU、Host DRAM 或 Remote DRAM，大部分已在 DRAM
- **复杂度成本**：GDS 需要 CUDA context 管理、cuFile 驱动、设备指针跨进程追踪

**工程启示**：
零拷贝不是目标，而是手段。如果数据源本来就在 Host DRAM，引入 GDS 反而增加复杂度。

### 2. GPU 指针自动检测

Mooncake 的聪明之处：使用 `cudaPointerGetAttributes()` 自动检测指针类型

```cpp
if (IsDevicePointer(slice.ptr, &device_id)) {
    // GPU 指针 → 先暂存到 Host
    cudaMemcpy(host_buf, device_ptr, size, cudaMemcpyDeviceToHost);
} else {
    // Host 指针 → 直接使用
}
```

这使得上层代码无需关心数据在哪里，FileStorage 自动处理。

### 3. Pinned Memory 的作用

Offload 使用 pinned memory 作为暂存缓冲区：

- 通过 `cudaHostAlloc()` 分配页锁定内存
- 不会被 OS 换出
- cudaMemcpy 性能更高（~30 GB/s vs ~10 GB/s）
- 为未来可能的 GDS 优化预留空间

### 4. Bucket 聚合策略

**256MB / 500 个对象** 是经过权衡的选择：

| 考虑因素 | 影响 |
|---------|------|
| 文件系统开销 | 更大的 bucket → 更少的文件 |
| 读取延迟 | 更小的 bucket → 更快的单对象读取 |
| 驱逐灵活性 | 更小的 bucket → 更细粒度的 LRU |
| 顺序 I/O 效率 | 更大的 bucket → 更好的 SSD 性能 |

256MB 是一个经验值，对于 AI SSD 设计可能需要重新评估。

### 5. io_uring 的线程本地环

关键优化：每个线程一个 io_uring 环，避免锁竞争

```cpp
auto* ring = GetThreadLocalRing();  // thread_local
io_uring_submit_and_wait(ring, batch);
```

对比全局环的方案，延迟降低了数量级（锁竞争 > 1ms → 无锁 ~50ns）。

## Why This Matters (For AI SSD)

### 写路径特征

1. **大块顺序写**：256MB buckets
2. **异步后台**：不阻塞前台读取
3. **批量操作**：io_uring 批量提交
4. **O_DIRECT**：绕过页缓存

### AI SSD 优化方向

**高优先级：**
1. **大块写入优化**：针对 64-512MB 范围优化固件缓冲策略
2. **O_DIRECT 性能**：确保 4KB 对齐的 DMA 无额外开销
3. **QoS 隔离**：后台写入不影响前台读延迟

**中优先级：**
4. **预分配连续块**：识别顺序写入流，减少碎片
5. **写缓冲容量**：支持批量异步写（DRAM + SLC cache）

**低优先级（未来）：**
6. **GDS 支持**：如果 GPU-resident 数据比例上升到 >50%

## Questions Remaining

- [ ] 256MB bucket 的选择是否有基准测试验证？
- [ ] io_uring 线程本地环 vs 全局环的性能对比数据？
- [ ] cudaMemcpy 的 ~10μs 延迟是瓶颈吗？如果是，GDS 能改善多少？
- [ ] BucketStorageBackend 的写放大（Write Amplification）是多少？

## How to Apply

在 AI SSD 预研中：

1. **不要盲目追求零拷贝**：分析数据流，如果大部分数据已在 Host，暂存模型更简单
2. **优化常见路径**：Host → SSD 是最频繁的路径，优先优化
3. **固件层预读**：由于使用 O_DIRECT，智能预读应在固件层实现
4. **测试真实工作负载**：256MB 可能不是最优，需要用 Mooncake trace 数据测试

## Related Resources
- 课程 0002: SSD Offload 写路径
- `mooncake-store/src/file_storage.cpp:492-518` - GPU 暂存逻辑
- `mooncake-store/src/uring_file.cpp:595-638` - io_uring 实现
- FAST'25 论文 Figure 10: SSD offload 性能分析
