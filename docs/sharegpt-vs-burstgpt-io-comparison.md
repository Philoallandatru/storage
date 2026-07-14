# ShareGPT vs BurstGPT I/O 读写总量对比分析

**日期:** 2026-07-14  
**数据源:** kv-cache-io-three-way-comparison-2026-06-29.md  
**测试配置:** llama3.1-8b, 8 users, 120s, TP=1, GPU/CPU cache 0/0 GiB (强制 NVMe)

---

## 1. 读写总量对比概览

### 核心数据汇总

| 指标 | ShareGPT | BurstGPT | 比值 (B/S) | 说明 |
|---|---:|---:|---:|---|
| **测试时长** | 140.91s | 129.75s | 0.92× | BurstGPT 更快完成 |
| **Block events** | 1,981,685 | 4,566,627 | **2.30×** | 事件数 2.3 倍 |
| **Block IOPS** | 14,063 | 35,195 | **2.50×** | IOPS 2.5 倍 |
| **Block BW** | 1.64 GiB/s | 4.25 GiB/s | **2.59×** | 带宽 2.6 倍 |
| **Total bytes** | **42.74 GiB** | **72.16 GiB** | **1.69×** | 总传输量 1.7 倍 |

### 读写分解

#### 读操作

| 指标 | ShareGPT | BurstGPT | 比值 (B/S) |
|---|---:|---:|---:|
| Read events | 1,860,196 | 4,202,655 | **2.26×** |
| Read 占比 | **94%** | 92% | - |
| Read bytes（估算） | ~40.17 GiB | ~66.39 GiB | **1.65×** |

#### 写操作

| 指标 | ShareGPT | BurstGPT | 比值 (B/S) |
|---|---:|---:|---:|
| Write events | 121,489 | 363,972 | **3.00×** |
| Write 占比 | 6% | 8% | - |
| Write bytes（估算） | ~2.56 GiB | ~5.77 GiB | **2.25×** |

---

## 2. 关键发现

### 2.1 BurstGPT 总量更大的原因

**原因 1：更高的 IOPS（2.5 倍）**
- BurstGPT 短 prompt 突发，请求密集
- 单位时间处理更多请求 → 更多 I/O

**原因 2：更高的吞吐量**
```
ShareGPT: 42.74 GiB / 140.91s = 0.303 GiB/s
BurstGPT: 72.16 GiB / 129.75s = 0.556 GiB/s
差异: 1.83×
```

**原因 3：请求处理速度**
- Token/s（5min 测试）: ShareGPT 372.1 vs BurstGPT 3195.6（8.6 倍）
- 虽然 BurstGPT cache hit 更高（98% vs 72%），但请求总数多

### 2.2 读占比的差异

| Workload | Read % | Write % | Read:Write 比 |
|---|---:|---:|---:|
| ShareGPT | **94%** | 6% | **15.7:1** |
| BurstGPT | 92% | 8% | 11.5:1 |

**ShareGPT 读占比更高的原因：**
- 多轮对话，上下文累积更长
- 每轮 Decode 需要读取所有前面轮次的 KV cache
- Decode 步数远多于 Prefill

---

## 3. 读操作详细对比

### 3.1 读模式差异

| 指标 | ShareGPT | BurstGPT | 差异 |
|---|---:|---:|---|
| Read ≥100 MiB 跳跃 | 56.97% | **89.11%** | BurstGPT 更随机 |
| Read 精确连续 | **41.77%** | 10.08% | ShareGPT 更连续 |
| Read LBA delta p50 | 2,675 MiB | **31,056 MiB** | BurstGPT 跳跃 11.6× |

**关键差异：**
- **BurstGPT 读极度随机**（89% 大跨度，中位数跳跃 31 GB）
- **ShareGPT 有 42% 连续读**（多轮对话 prefix cache 命中）

### 3.2 读带宽

```
ShareGPT Read BW ≈ 0.285 GiB/s
BurstGPT Read BW ≈ 0.512 GiB/s
比值: 1.80×
```

---

## 4. 写操作详细对比

### 4.1 写模式对比

| 指标 | ShareGPT | BurstGPT |
|---|---:|---:|
| Write 精确连续 | 94.37% | **97.63%** |
| Write LBA delta p50 | 0.00 MiB | 0.00 MiB |

**共同特征：**
- 两者的写都是高度连续（94-98%）
- 追加式写入（sequential append）

### 4.2 写带宽

```
ShareGPT Write BW ≈ 0.018 GiB/s
BurstGPT Write BW ≈ 0.044 GiB/s
比值: 2.44×
```

---

## 5. 对 AI SSD 设计的启示

### 5.1 不能只看单一 Workload

| 维度 | ShareGPT | BurstGPT | AI SSD 需要 |
|---|---|---|---|
| IOPS | 低（14K） | 高（35K） | 支持 30K+ IOPS |
| 读随机性 | 中（57%） | 高（89%） | 优化 128KiB 随机读 |
| QD（5min） | 高（78） | 中（30） | 支持 QD 200+ |

### 5.2 总量不代表压力

**反直觉发现：**
- ShareGPT 总量小（42.74 GiB），但 QD 更高（78 vs 30）
- BurstGPT 总量大（72.16 GiB），但 QD 更低

**原因：** ShareGPT 低吞吐导致请求堆积

### 5.3 读写分离必要性

| 维度 | 读 | 写 |
|---|---|---|
| 占比 | 90%+ | <10% |
| 模式 | 大跨度随机 | 高度连续 |
| 优化 | Random read latency | Sequential write |

---

## 6. 核心结论

✅ **BurstGPT 总传输量（72.16 GiB）是 ShareGPT（42.74 GiB）的 1.69 倍**
- 读：1.65 倍（66.39 vs 40.17 GiB）
- 写：2.25 倍（5.77 vs 2.56 GiB）

✅ **吞吐量差异是根本原因**
- IOPS: 2.5 倍
- 带宽: 2.6 倍

✅ **总量小不等于压力小**
- ShareGPT 总量小但 QD 高

✅ **必须同时覆盖两种极端场景**
- ShareGPT: 低吞吐高 QD
- BurstGPT: 高吞吐高 IOPS
