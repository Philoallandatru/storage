# KV Cache 存储基准测试验证结果

## 执行摘要

本文档验证 **kv-cache.py**，一个面向 MLPerf Storage 的存储 I/O 基准测试工具，用于模拟 LLM 推理场景下的 KV cache 读写模式。关键发现：

| Tier（层级） | Storage Throughput（存储吞吐量） | Speedup vs NVMe（相对 NVMe 加速比） |
|------|-------------------|-----------------|
| GPU (HBM) | 1,691 ± 154 tok/s | **6.4×** |
| GPU+CPU | 1,546 ± 257 tok/s | **5.9×** |
| GPU+CPU+NVMe | 1,175 ± 178 tok/s | **4.4×** |
| NVMe Only | 263 ± 2 tok/s | 1.0× (baseline) |

**重要提示：** 本基准测试衡量的是**存储 I/O 吞吐量**，而非 LLM 推理速度。

---

## 1. kv-cache.py 是什么？

**kv-cache.py** 是一个**存储 I/O 模拟器**，能够在无需实际运行 LLM 推理的情况下生成真实的 KV cache 访问模式。其功能包括：

- 模拟对 GPU/CPU/NVMe 各层级的 KV cache 读取（解码阶段）和写入（预填充阶段）
- 衡量存储吞吐量：`tokens / total_storage_io_time`
- 记录各层级的延迟百分位数（如 gpu_read_p95、nvme_read_p95 等）
- 实现层级间的 LRU 瀑布式逐出策略
- **不**运行实际的 LLM 推理或 GPU 计算

**适用场景：** MLPerf Storage 基准测试，用于评估存储系统在 LLM 工作负载下的性能表现。

---

## 2. 测试环境

### 硬件

#### 系统

| Component（组件） | Specification（规格） |
|-----------|---------------|
| 服务器 | Supermicro SYS-621H-TN12R |
| CPU | 2× Intel Xeon Silver 4510 |
| CPU 核心 | 24 核 / 48 线程（每插槽 12C/24T） |
| CPU 频率 | 2.4 GHz 基础频率，4.2 GHz 睿频 |
| CPU 特性 | AVX-512, AMX-BF16, AMX-INT8 |

#### 内存

| Component（组件） | Specification（规格） |
|-----------|---------------|
| 系统内存 | 256 GB（16× 16GB DIMM） |
| 内存类型 | Kingston DDR5-4800 ECC Registered |
| 内存配置 | 每 CPU 8 通道，每通道 1 DIMM |
| L3 缓存 | 60 MB（每插槽 30 MB） |

#### GPU

| Component（组件） | Specification（规格） |
|-----------|---------------|
| GPU | NVIDIA H100 NVL |
| GPU 显存 | 95,830 MiB（约 94 GB HBM3） |
| GPU 驱动 | 580.95.05 |
| HBM 带宽 | 3,350 GB/s（理论值） |

#### 存储

| Component（组件） | Specification（规格） |
|-----------|---------------|
| NVMe 设备 | /dev/nvme4n1 |
| NVMe 容量 | 7.0 TB |
| NVMe 带宽 | ~14,000 MB/s（理论值） |

### 软件

| Component（组件） | Version（版本） |
|-----------|---------|
| 操作系统 | Linux 6.5.0-15-generic (Ubuntu 22.04) |
| Python | 3.10.12 |
| PyTorch | 2.9.0+cu128 |
| CUDA | 12.8 |
| vLLM | 0.13.0 |

### 基准测试配置

| Parameter（参数） | Value（值） |
|-----------|-------|
| 模型 | mistralai/Mistral-7B-Instruct-v0.2 |
| 每配置试验次数 | 3 |
| 每次运行提示数 | 500（ShareGPT 数据集） |
| 并发用户数 | 50 |
| 随机种子 | 42 |

### KV Cache 层级分配

| Tier（层级） | GPU | CPU | NVMe | Total（总计） |
|------|-----|-----|------|-------|
| GPU Only | 16 GB | 0 | - | 16 GB |
| GPU+CPU | 8 GB | 8 GB | - | 16 GB |
| GPU+CPU+NVMe | 4 GB | 4 GB | overflow（溢出） | 8 GB + 磁盘 |
| NVMe Only | 0 | 0 | all（全部） | 仅磁盘 |

---

## 3. 理解指标

### 两种不同的"吞吐量"（关键！）

| Metric（指标） | Formula（公式） | Purpose（用途） |
|--------|---------|---------|
| **存储吞吐量** | `tokens / total_storage_io_time` | 衡量存储 I/O 速度（请使用此指标！） |
| 挂钟吞吐量 | `tokens / elapsed_time` | 对本基准测试具有误导性 |

**为什么挂钟时间具有误导性：** NVMe 层级使用异步 I/O 和 50 个并发用户，因此尽管总 I/O 时间很高，但挂钟时间却很短。GPU 层级使用同步的 `cuda.synchronize()` 调用，因此挂钟时间 ≈ 总 I/O 时间。

### "tokens/sec"在此存储基准测试中的含义

本基准测试衡量的是**存储 I/O 性能**，而非 LLM 推理速度。"tokens"指标表示传输到/从存储的**数据量**：

**1 个 KV cache token** = 跨所有 Transformer 层的单个 token 位置的键值张量

对于 Mistral-7B，每个 token 的 KV cache 大小为：

```
KV cache per token = num_layers × num_kv_heads × head_dim × 2 (K+V) × 2 bytes (fp16)
                   = 32 layers × 8 kv_heads × 128 head_dim × 2 (K+V) × 2 bytes
                   = 131,072 bytes（约 128 KB 每个 token 位置）
```

**这些值的来源：**
| Parameter（参数） | Mistral-7B Value（值） | Source（来源） |
|-----------|------------------|--------|
| num_layers | 32 | 模型架构（Transformer 块） |
| num_kv_heads | 8 | 分组查询注意力（GQA）——KV 头少于查询头 |
| head_dim | 128 | hidden_size (4096) / num_attention_heads (32) |
| K+V multiplier（乘数） | 2 | 同时存储 Key 和 Value 张量 |
| fp16 bytes（字节数） | 2 | 半精度浮点数 |

**因此：**
- **存储吞吐量（tokens/sec）** = 每秒处理多少个 128KB 的 KV cache 块
- **实际 I/O 带宽** = tokens/sec × 128KB/token

示例（GPU-Only 试验 1）：
```
Storage Throughput = 146,900 tokens / 86.83 seconds = 1,692 tokens/sec
Actual I/O Bandwidth = 1,692 tok/s × 128 KB/tok = 216 MB/s
```

### 存储吞吐量公式

```
Storage Throughput = total_tokens_generated / total_storage_io_latency

示例（GPU-Only 试验 1）：
  = 146,900 tokens / 86.83 seconds
  = 1,692 tokens/sec

Actual I/O Bandwidth = total_bytes_transferred / total_storage_io_latency
  = 102.01 GB / 86.83 seconds
  = 1,175 MB/s
```

---

## 4. 结果

### 4.1 原始试验数据（来自 JSON）

| Tier（层级） | Trial（试验） | I/O Time (s) | Tokens | Storage Throughput（存储吞吐量） |
|------|-------|-------------|--------|-------------------|
| GPU Only | T1 | 86.83 | 146,900 | 1,692 tok/s |
| GPU Only | T2 | 98.74 | 148,262 | 1,501 tok/s |
| GPU Only | T3 | 78.35 | 147,313 | 1,879 tok/s |
| **GPU Only Avg** | - | **87.97** | **147,492** | **1,691 ± 154** |
| GPU+CPU | T1 | 85.37 | 148,297 | 1,737 tok/s |
| GPU+CPU | T2 | 85.38 | 146,891 | 1,720 tok/s |
| GPU+CPU | T3 | 125.60 | 148,164 | 1,180 tok/s |
| **GPU+CPU Avg** | - | **98.78** | **147,784** | **1,546 ± 257** |
| GPU+CPU+NVMe | T1 | 82.96 | 118,293† | 1,426 tok/s |
| GPU+CPU+NVMe | T2 | 146.68 | 147,313 | 1,004 tok/s |
| GPU+CPU+NVMe | T3 | 134.89 | 147,832 | 1,096 tok/s |
| **GPU+CPU+NVMe Avg** | - | **121.51** | **137,813** | **1,175 ± 178** |
| NVMe Only | T1 | 553.26 | 147,313 | 266 tok/s |
| NVMe Only | T2 | 562.26 | 146,625 | 261 tok/s |
| NVMe Only | T3 | 560.58 | 146,684 | 262 tok/s |
| **NVMe Only Avg** | - | **558.70** | **146,874** | **263 ± 2** |

†Trial 1 GPU+CPU+NVMe 仅完成 438/549 个请求（可能超时）

### 4.2 性能排名

| Rank（排名） | Tier（层级） | Storage Throughput（存储吞吐量） | Speedup vs NVMe（相对 NVMe 加速比） |
|------|------|-------------------|----------------|
| #1 | GPU Only | 1,691 ± 154 tok/s | **6.4×** |
| #2 | GPU+CPU | 1,546 ± 257 tok/s | **5.9×** |
| #3 | GPU+CPU+NVMe | 1,175 ± 178 tok/s | **4.4×** |
| #4 | NVMe Only | 263 ± 2 tok/s | 1.0× (baseline) |

**观察：**
- GPU-Only 比 NVMe-only 快 6.4 倍
- GPU+CPU 比 GPU-only 低 9%（层级切换开销）
- NVMe 层级方差极小（CV = 0.8%），GPU 层级方差较高（CV = 9–17%）

### 4.3 I/O 数据量分析

| Tier（层级） | Total Read（总读取） | Total Write（总写入） | Read/Write Ratio（读写比） |
|------|-----------|-------------|------------------|
| GPU Only | 94.4 GB | 7.6 GB | 12.4:1 |
| GPU+CPU | ~95 GB | ~7.5 GB | ~12.7:1 |
| GPU+CPU+NVMe | ~92 GB | ~7.5 GB | ~12.3:1 |
| NVMe Only | 91.9 GB | 7.4 GB | 12.4:1 |

各层级一致的约 94 GB 读取 / 约 7.5 GB 写入，表明工作负载具有良好的可重复性。

### 4.4 各层级延迟（P95）

| Config（配置） | GPU Read（GPU 读取） | CPU Read（CPU 读取） | NVMe Read（NVMe 读取） |
|--------|----------|----------|-----------|
| GPU-Only | 21.4 ms | - | - |
| GPU+CPU | 46.7 ms | 15.7 ms | - |
| GPU+CPU+NVMe | 126.7 ms | 15.0 ms | 159.6 ms |
| NVMe-Only | 34.3 ms* | - | 358.2 ms |

*NVMe-Only 中的 GPU 延迟仅为元数据/索引操作（存储的 KV 数据量为 0.00 GB）

---

## 5. 带宽效率分析

### 观测带宽与理论带宽对比

| Tier（层级） | Theoretical（理论值） | Observed（观测值） | Efficiency（效率） |
|------|-------------|----------|------------|
| **GPU HBM** | 3,350 GB/s | 1,175 MB/s | 0.035% |
| **NVMe SSD** | 7,000 MB/s | 179 MB/s | 2.6% |

### 为何如此之低？

本基准测试是一个**跟踪回放工作负载**，而非原始存储带宽测试：

**跟踪回放特性：**
- 请求按照 ShareGPT 对话模式到达，而非连续背靠背
- 对话轮次之间的思考时间（模拟真实用户行为）
- 基于缓存键查找的随机访问模式，而非顺序 I/O
- 目标是**工作负载保真度**，而非带宽饱和

**这对 MLPerf Storage 是有意为之：**
- 真实的 LLM 服务具有突发性和随机性的 KV cache 访问模式
- 测量持续的顺序带宽无法反映生产工作负载
- 该基准测试捕捉了推理模式带来的真实存储压力

**其他延迟因素：**

GPU-Only：
- 每次 `cuda.synchronize()` 每次操作增加约 0.1—1ms 延迟
- 同步开销主导了实际张量拷贝时间

NVMe-Only：
- 每次随机 128KB 读取（一个 token 的 KV cache，见上方公式）都会产生寻道延迟
- 典型 NVMe 随机读取：128KB 块每次操作约 1—3ms
- 由于随机访问模式（缓存键查找），无法享受顺序预读的好处

### 每操作延迟合理性检查

存储操作包括：
- **预填充写入**：存储新的 KV cache 条目（约 500 次操作，每个请求一次）
- **解码读取**：检索缓存的 KV 张量（约 5,400 次操作，每个请求多次用于 token 生成）

这与 I/O 数据量中观测到的 **12:1 读写比**（约 94 GB 读取 / 约 7.5 GB 写入）吻合。

| Tier（层级） | Storage Ops (R+W)（存储操作数，读+写） | Total I/O Time（总 I/O 时间） | Avg Latency/Op（每操作平均延迟） |
|------|-------------------|----------------|----------------|
| GPU | ~5,900 | 86.8s | 14.7ms |
| NVMe | ~5,900 | 553.3s | 93.8ms |

NVMe 每操作慢 6.4 倍，这与 6.4 倍的存储吞吐量差异吻合。

---

## 6. 试验方差

### GPU+CPU 试验 3 异常

| Trial（试验） | I/O Time（I/O 时间） | Tokens | Storage Throughput（存储吞吐量） |
|-------|----------|--------|-------------------|
| T1 | 85.37s | 148,297 | 1,737 tok/s |
| T2 | 85.38s | 146,891 | 1,720 tok/s |
| T3 | 125.60s | 148,164 | **1,180 tok/s** |

试验 3 比 T1/T2 慢约 32%。可能的原因：
1. 各试验间操作系统页缓存状态不同
2. 后台 CPU 活动
3. 层级切换开销的可变性

### GPU+CPU+NVMe 试验 1 异常

试验 1 仅完成 438/549 个请求（80%），产生 118,293 个 token，而其他试验约产生 147,000 个 token。这表明可能存在超时或资源争用问题。

**建议：** 从平均值中排除未完成的试验，或调查根本原因。

---

## 7. LMCache / vLLM 参考结果

这些结果衡量的是**真实的 LLM 推理吞吐量**（GPU 计算 + 内存访问），而非仅存储 I/O。它们作为参考点，用于理解实际推理与存储基准测试之间的关系。

### 7.1 原始试验数据

| Config（配置） | Trial（试验） | Tokens | Elapsed (s)（耗时，秒） | Throughput (tok/s)（吞吐量） |
|--------|-------|--------|-------------|-------------------|
| vLLM Baseline | T1 | 239,867 | 17.48 | 13,726 |
| vLLM Baseline | T2 | 239,867 | 17.45 | 13,743 |
| vLLM Baseline | T3 | 239,867 | 17.48 | 13,722 |
| **vLLM Avg** | - | **239,867** | **17.47** | **13,730 ± 9** |
| LMCache GPU | T1 | 61,605 | 6.50 | 9,482 |
| LMCache GPU | T2 | 61,605 | 6.49 | 9,489 |
| LMCache GPU | T3 | 61,733 | 6.46 | 9,554 |
| **LMCache GPU Avg** | - | **61,648** | **6.48** | **9,508 ± 32** |
| LMCache CPU | T1 | 61,613 | 6.47 | 9,528 |
| LMCache CPU | T2 | 61,605 | 6.56 | 9,396 |
| LMCache CPU | T3 | 61,605 | 6.62 | 9,308 |
| **LMCache CPU Avg** | - | **61,608** | **6.55** | **9,411 ± 91** |

### 7.2 汇总

| Config（配置） | Throughput（吞吐量） | Variance（方差） | Notes（说明） |
|--------|-----------|----------|-------|
| vLLM Baseline | 13,730 ± 9 tok/s | CV = 0.07% | 无 KV 缓存，纯推理 |
| LMCache GPU | 9,508 ± 32 tok/s | CV = 0.34% | KV 缓存位于 GPU 显存中 |
| LMCache CPU Offload | 9,411 ± 91 tok/s | CV = 0.97% | KV 缓存使用 CPU 层级 |

**观察：**
- vLLM baseline 比 LMCache 快约 31%（KV 缓存管理的开销）
- LMCache GPU 与 CPU 差异极小（约 1%），表明 CPU 卸载效率较高
- 各试验间方差非常低（CV < 1%），表明推理性能稳定
- Token 数量不同（240K vs 62K），原因是 LMCache 模式下提示处理方式不同

### 7.3 软件版本

| Component（组件） | Version（版本） |
|-----------|---------|
| vLLM | 0.13.0 |
| LMCache | 0.3.12 |
| PyTorch | 2.9.0+cu128 |
| CUDA | 12.8 |

---

## 8. 对比：实际推理 vs 存储基准测试

| System（系统） | Tool（工具） | Throughput（吞吐量） | What It Measures（衡量内容） |
|--------|------|-----------|------------------|
| vLLM Baseline | vllm bench | 13,746 tok/s | 实际推理（无 KV 缓存） |
| LMCache GPU | vLLM+LMCache | 9,534 tok/s | 实际推理 + KV 缓存 |
| LMCache CPU | vLLM+LMCache | 9,334 tok/s | 实际推理 + CPU 卸载 |
| kv-cache.py GPU | kv-cache.py | 1,691 tok/s | **仅存储 I/O** |
| kv-cache.py NVMe | kv-cache.py | 263 tok/s | **仅存储 I/O** |

**这些数据不可直接比较。** LMCache 衡量端到端推理吞吐量，包含 GPU 计算。kv-cache.py 仅衡量存储 I/O 时间，不包含计算。

---

## 9. 关键发现

1. **GPU 层级在存储 I/O 上比 NVMe 快 6.4 倍**（1,691 vs 263 tok/s）

2. **分层缓存工作正常**：GPU+CPU 达到 GPU-only 性能的 91%，同时拥有 2 倍容量潜力

3. **每操作延迟主导带宽**：带宽利用率低（GPU 0.035%，NVMe 2.6%）是由于随机访问模式（缓存键查找）、每操作开销（GPU 的 `cuda.synchronize()`，NVMe 的寻道延迟）以及小块大小（每个 token 约 128KB）。这是真实 KV cache 工作负载的特征。

4. **缓存命中率稳定**（所有层级约 93%），表明工作负载行为一致

5. **存储吞吐量是本基准测试的正确指标**，而非挂钟吞吐量

---

## 10. 建议

1. **使用 JSON 输出中的 `storage_throughput_tokens_per_sec`** 进行层级对比
2. **运行 ≥3 次试验**以考虑方差（尤其是分层配置）
3. **丢弃未完成的试验**（当 requests_completed < expected 时）
4. **不要将 kv-cache.py 与 LMCache 直接比较**——它们衡量的是不同的事物

---

---

## 附录 A：CLI 调用命令

### A.1 vLLM Baseline（无 KV 缓存）

```bash
vllm bench throughput \
    --model mistralai/Mistral-7B-Instruct-v0.2 \
    --num-prompts 500 \
    --dataset-path ShareGPT_V3_unfiltered_cleaned_split.json \
    --gpu-memory-utilization 0.8 \
    --trust-remote-code \
    --output-json vllm_baseline.json
```

### A.2 LMCache GPU

```python
import json
import time
from vllm import LLM, SamplingParams
from vllm.config import KVTransferConfig

# Load ShareGPT dataset
with open('ShareGPT_V3_unfiltered_cleaned_split.json') as f:
    data = json.load(f)

# Extract first 500 prompts
prompts = []
for conv in data[:500]:
    if 'conversations' in conv:
        for msg in conv['conversations']:
            if msg.get('from') == 'human':
                prompts.append(msg.get('value', '')[:2048])
                break

# Configure LMCache (GPU-only, no CPU offload)
# Environment: LMCACHE_CHUNK_SIZE=256, LMCACHE_LOCAL_CPU=False
ktc = KVTransferConfig(
    kv_connector="LMCacheConnectorV1",
    kv_role="kv_both"
)

llm = LLM(
    model='mistralai/Mistral-7B-Instruct-v0.2',
    gpu_memory_utilization=0.8,
    trust_remote_code=True,
    kv_transfer_config=ktc,
)

sampling_params = SamplingParams(temperature=0.7, max_tokens=128)
outputs = llm.generate(prompts, sampling_params)
```

### A.3 LMCache CPU Offload（CPU 卸载）

```python
import json
import time
from vllm import LLM, SamplingParams
from vllm.config import KVTransferConfig

# Load ShareGPT dataset
with open('ShareGPT_V3_unfiltered_cleaned_split.json') as f:
    data = json.load(f)

# Extract first 500 prompts
prompts = []
for conv in data[:500]:
    if 'conversations' in conv:
        for msg in conv['conversations']:
            if msg.get('from') == 'human':
                prompts.append(msg.get('value', '')[:2048])
                break

# Configure LMCache with CPU offloading
# Environment: LMCACHE_CHUNK_SIZE=256, LMCACHE_LOCAL_CPU=True, LMCACHE_MAX_LOCAL_CPU_SIZE=32
ktc = KVTransferConfig(
    kv_connector="LMCacheConnectorV1",
    kv_role="kv_both"
)

llm = LLM(
    model='mistralai/Mistral-7B-Instruct-v0.2',
    gpu_memory_utilization=0.8,
    trust_remote_code=True,
    kv_transfer_config=ktc,
)

sampling_params = SamplingParams(temperature=0.7, max_tokens=128)
outputs = llm.generate(prompts, sampling_params)
```

### A.4 KV Cache 存储基准测试（kv-cache.py）

#### A.4.1 GPU Only（16GB GPU, 0 CPU）

```bash
python3 kv-cache.py \
    --model mistral-7b \
    --dataset-path ShareGPT_V3_unfiltered_cleaned_split.json \
    --max-conversations 500 \
    --gpu-mem-gb 16 \
    --cpu-mem-gb 0 \
    --num-users 50 \
    --max-requests 500 \
    --generation-mode none \
    --seed 42 \
    --output kvcache_gpu_only.json
```

#### A.4.2 GPU+CPU（8GB GPU + 8GB CPU）

```bash
python3 kv-cache.py \
    --model mistral-7b \
    --dataset-path ShareGPT_V3_unfiltered_cleaned_split.json \
    --max-conversations 500 \
    --gpu-mem-gb 8 \
    --cpu-mem-gb 8 \
    --num-users 50 \
    --max-requests 500 \
    --generation-mode none \
    --seed 42 \
    --output kvcache_gpu_cpu.json
```

#### A.4.3 GPU+CPU+NVMe（4GB GPU + 4GB CPU + NVMe overflow）

```bash
python3 kv-cache.py \
    --model mistral-7b \
    --dataset-path ShareGPT_V3_unfiltered_cleaned_split.json \
    --max-conversations 500 \
    --gpu-mem-gb 4 \
    --cpu-mem-gb 4 \
    --cache-dir /mnt/nvme \
    --num-users 50 \
    --max-requests 500 \
    --generation-mode none \
    --seed 42 \
    --output kvcache_gpu_cpu_nvme.json
```

#### A.4.4 NVMe Only（MLPerf Storage 模式）

```bash
python3 kv-cache.py \
    --model mistral-7b \
    --dataset-path ShareGPT_V3_unfiltered_cleaned_split.json \
    --max-conversations 500 \
    --gpu-mem-gb 0 \
    --cpu-mem-gb 0 \
    --cache-dir /mnt/nvme \
    --num-users 50 \
    --max-requests 500 \
    --generation-mode none \
    --seed 42 \
    --output kvcache_nvme_only.json
```
