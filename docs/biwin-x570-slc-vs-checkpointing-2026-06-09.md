# BIWIN X570 SSD — SLC Cache vs Checkpointing 联动分析

日期:2026-06-09
测试盘:`/dev/nvme1n1` (BIWIN X570 1TB,3D TLC,steady state)

## 测试目的

**核心问题**:LLM Checkpointing 是已知 write-heavy workload。
不同模型 checkpoint 大小 vs SSD SLC cache 容量,**性能预期是什么?**

## 模型 Checkpoint 大小 vs SLC Cache

| 模型 | FP16 checkpoint 大小 | Fresh SLC (71 GiB) | Steady SLC (95 GiB) | 跌出 SLC 后速度 |
|---|---:|---|---|---|
| Llama3-8B | ~16 GiB | ✅ **完全命中** | ✅ 完全命中 | N/A |
| Llama3-70B | ~140 GiB | ⚠️ **跌出** | ⚠️ 跌出 | ~1.7-1.8 GiB/s |
| Llama3-405B | ~810 GiB | ❌ 全程直写 TLC | ❌ 全程直写 | ~1.7-1.8 GiB/s |

### Llama3-70B checkpoint write 行为预测

**140 GiB checkpoint** + **95 GiB SLC cache**:

1. **0-95 GiB 阶段**:写入 SLC cache,~5000 MiB/s,~19 秒完成
2. **95-140 GiB 阶段**(45 GiB):跌出 SLC cache,直写 TLC,~1700-1800 MiB/s,~25 秒

**总 checkpoint save 时间**:
- 前半部分(95 GiB SLC):19s
- 后半部分(45 GiB TLC):25s
- 总计:~44 秒 @ 平均 ~3200 MiB/s

**Fresh 状态**:
- 前半部分(71 GiB SLC):14s
- 后半部分(69 GiB TLC):40s
- 总计:~54 秒 @ 平均 ~2600 MiB/s

### Llama3-8B checkpoint (16 GiB)

**完全命中 SLC cache**(远小于 95 GiB):
- 整个 checkpoint 在 SLC cache 中
- 写速 ~5000 MiB/s
- 总计 ~3.2 秒

### Llama3-405B checkpoint (810 GiB)

**完全跌出 SLC cache**:
- 全部直写 TLC
- 写速 ~1700-1800 MiB/s(可能 thermal throttle 后降到更低)
- 总计 ~470 秒(~8 分钟)

## 🎯 关键洞察

### 1. Checkpoint Size 决定 burst vs direct-write

| Checkpoint Size | SLC Cache 利用率 | 总耗时 |
|---|---|---|
| <50 GiB (e.g. 8B) | 100% | 极快(<10s) |
| 50-100 GiB (e.g. 70B 部分) | 50-70% | 中等(~30-60s) |
| >100 GiB (e.g. 70B, 405B) | 0% | 慢(几分钟到几十分钟) |

### 2. 训练阶段对存储的需求

**典型训练流程**:
1. **Forward + Backward** (1-2 小时) — 需要读 dataset
2. **Optimizer step** (几分钟) — 内存中
3. **Checkpoint save** (几十秒到几分钟) — **写 ~140 GiB**

Checkpoint save 占用存储带宽:
- Llama3-70B:44-54 秒,~3 GB/s 平均写速
- 这在多节点训练中是 **阻塞式** 操作(必须等 checkpoint 完成)

### 3. 与 KV-Cache benchmark 对比

| 维度 | Checkpointing | KV-Cache |
|---|---|---|
| Workload 类型 | Sequential write | Mixed random R/W |
| Burst 速度优势 | **✅ 重要**(70B 命中部分 SLC) | ❌ 不重要(mixed R/W 测不出) |
| 平均速度 | 1.7-3.2 GB/s | 1.3 GB/s (mixed R/W 测得) |
| 主要瓶颈 | SLC cache 大小 | Queue 拥塞 |
| GC drift 影响 | 中 | **高**(见 B 测试) |

## 🔬 建议的实测验证

**如果时间允许,推荐实测 Llama3-8B checkpoint**(16 GiB):
- 预期耗时:~3-5 秒(命中 SLC)
- 验证 SLC cache 在真实 checkpointing 下是否真有 burst

**Llama3-70B checkpoint**(140 GiB)需要 ~44-54 秒 + 数据集生成时间,**实际跑需要 ~30 分钟**。

### 实测命令模板

```bash
# 单 GPU 模拟 Llama3-8B checkpointing
mlpstorage checkpointing run \
    --model llama3-8b \
    --num-processes 1 \
    --client-host-memory-in-gb 32 \
    --checkpoint-folder /home/ficus/llm/storage/checkpoints/llama3-8b \
    --results-dir /home/ficus/llm/storage/results/checkpointing

# 70B 版本 (需要 ~30 分钟 + 数据集)
mlpstorage checkpointing run \
    --model llama3-70b \
    --num-processes 4 \
    --client-host-memory-in-gb 64 \
    --checkpoint-folder /home/ficus/llm/storage/checkpoints/llama3-70b \
    --results-dir /home/ficus/llm/storage/results/checkpointing
```

**⚠️ 实测限制**:
- 需要 MPI (`openmpi-bin`) 安装
- 需要 dlio binary 编译
- 70B checkpoint 会产生 ~140 GiB 数据,确保足够磁盘空间
- 不在本次执行(已超过可执行测试时间)

## 🎯 对 AI SSD 产品设计的启示

### 1. AI SSD 必须有持久 SLC cache 策略

如果 AI SSD 用在 LLM 训练:
- 8B / 16B checkpoint:无压力
- 70B checkpoint:需要 SLC cache 至少 ~95 GiB 才有效(否则前 71 GiB burst 后跌出)
- 405B checkpoint:完全靠 TLC 直写,SLC cache 价值不大

### 2. Burst 与稳态速度差异比绝对速度更重要

**对训练效率**:
- Llama3-8B (16 GiB) checkpoint:**3 秒**(全部 burst)= 不阻塞训练
- Llama3-70B (140 GiB) checkpoint:**44 秒**(部分 burst)= 短阻塞,可接受
- Llama3-405B (810 GiB) checkpoint:**8 分钟**(全部直写)= 长阻塞,需异步 checkpointing

### 3. AI SSD 的设计取舍

**针对 LLM checkpointing 优化**:
- **SLC cache 大小** 至少 70-100 GiB(让 70B checkpoint 受益)
- **TLC 直写速度** 需要 ≥ 2 GB/s(否则 405B checkpoint > 10 分钟)
- **持久性 DRAM cache** 至关重要(吸收 checkpoint 间的元数据写)
- **同时**:支持 streaming checkpointing(背景写入 + 训练不阻塞)

## 📊 总结

**核心结论**:
1. **8B/16B checkpoint**:SSD SLC cache 极大化收益(~5 GB/s)
2. **70B checkpoint**:SSD SLC cache 部分收益(3 GB/s 平均)
3. **405B checkpoint**:SSD SLC cache 几乎无用(1.7 GB/s 全程 TLC)

**对 AI SSD 设计**:SLC cache 应该 ≥ 95 GiB 才有意义,且需配合 streaming checkpointing 才能彻底解决大模型训练的存储瓶颈。

**报告结束。**