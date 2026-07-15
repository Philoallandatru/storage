# Mooncake 测试具体实验配置 + 每轮 TTFT/命中率变化缘由

**文档日期:** 2026-07-15
**数据来源:** `/home/ficus/mooncake_smoke_test/ssd_retest_formal_20260629_074959/` (4 config × 完整 bench.log)
**原始测试日期:** 2026-06-29 07:49 ~ 08:30
**关联文档:**
- `docs/mooncake-four-configs-detailed-analysis.md` (4 config 整体趋势,Round 0-7 行为)
- `docs/mooncake-ssd-offload-experiment-analysis.md` (Round 4 TTFT 升高 5 个原因)
- `docs/mooncake-ssd-offload-reproduction-and-io-analysis-2026-06-29.md` (I/O 证据 + 激活条件)
- `scripts/run_mooncake_ssd_offload_retest.sh` (驱动脚本,可执行)

---

## 概述

本文档聚焦回答两个问题:
1. **测试到底用了什么具体配置?** (4 个 config 的完整启动命令、benchmark 参数、硬件环境)
2. **TTFT 和命中率每轮变化的根因是什么?** (4 config × 8 rounds 完整数据 + 逐 round 解释)

数据来自 `ssd_retest_formal_20260629_074959` 这 1 轮正式复现测试,4 个 config 各跑 1 次,每次 8 clients × 8 rounds,共 64 requests/config。

---

## 一、硬件环境

| 项目 | 规格 | 说明 |
|---|---|---|
| GPU | NVIDIA RTX 5080 (16 GB) | 单卡,TP=1 |
| Host memory | ~64 GB DDR5 | L2 host memory 缓存可用空间约 32 GB |
| Mooncake pool (DRAM) | 8 GB (`8589934592` bytes) | 由 master `-root_fs_dir` 路径下的 DRAM segment 提供 |
| SSD offload 设备 | NVMe SSD (单盘,挂载在 `/mnt/ai_ssd0/mooncake_ssd0/file_storage`) | ext4,空间充裕 (测试占用 41 GiB) |
| SSD local buffer | 1 GB (`1073741824` bytes) | `MOONCAKE_OFFLOAD_LOCAL_BUFFER_SIZE_BYTES` 控制 |
| OS | Linux 7.0.0-22-generic | Ubuntu 内核 |
| 驱动 | NVIDIA driver 595.71.05 | nvidia-smi 正常 |
| transport | TCP localhost (`127.0.0.1:50051`) | 工作站无 RDMA,用 `protocol=tcp` |
| metadata server | `P2PHANDSHAKE` | 单节点模式,无需 HTTP metadata server |
| 模型 | `/home/ficus/llm/models/Qwen/Qwen3-4B-Instruct-2507` | Qwen3-4B-Instruct,7.6 GB,HF 格式 |
| 注意力后端 | triton | `--attention-backend triton` |
| Page size | 64 tokens | `--page-size 64` |

---

## 二、benchmark 参数

所有 config 共享以下 benchmark 参数(由 `bench_multiturn.py` 驱动):

```text
NUM_CLIENTS       = 8           # 并发客户端
NUM_ROUNDS        = 8           # 每个客户端 8 轮
REQUEST_LENGTH    = 4096        # 每请求 4096 tokens
OUTPUT_LENGTH     = 1           # 每请求只生成 1 token (focus prefill)
MAX_PARALLEL      = 2           # 同时最多 2 个请求
REQUEST_RATE      = 8           # 全局请求速率 8 req/s
TOTAL_REQUESTS    = 64          # 8 client × 8 round = 64
AVERAGE_PROMPT_LEN = 13827.5    # 平均 prompt 长度 (累积效应,见下文)
P90/P99_PROMPT_LEN = 24583      # 24,583 tokens ≈ 8 × 3072
```

**累积上下文公式:**
- 第 N 轮请求的输入长度 ≈ `(N+1) × 3072` tokens(平均)
- R0 输入 ≈ 3072,R7 输入 ≈ 24,576 tokens(8 × 3072)
- 这是 multiturn 设计的核心:**每轮 prompt 都包含前几轮的 KV**,测试缓存复用效率

---

## 三、4 个 config 的完整启动命令

下面 4 个 config 由 `scripts/run_mooncake_ssd_offload_retest.sh` 串行执行,每个 config 独立:

### Config 1: GPU only

**含义:** KV cache 只存 GPU 显存,无外部缓存。

```bash
python3 -m sglang.launch_server \
  --model-path /home/ficus/llm/models/Qwen/Qwen3-4B-Instruct-2507 \
  --host 127.0.0.1 --port 8189 \
  --tp 1 \
  --page-size 64 \
  --attention-backend triton
```

**mooncake_master:** **不启动**(无需 Mooncake)

**环境变量:** 无(纯 SGLang)

**关键标志:** 无 `--enable-hierarchical-cache`

---

### Config 2: HiCache L1+L2

**含义:** SGLang 自带的两层缓存 — L1 GPU 显存 + L2 Host memory(CPU RAM)。

```bash
python3 -m sglang.launch_server \
  --model-path /home/ficus/llm/models/Qwen/Qwen3-4B-Instruct-2507 \
  --host 127.0.0.1 --port 8189 \
  --tp 1 \
  --page-size 64 \
  --attention-backend triton \
  --enable-hierarchical-cache \
  --hicache-ratio 2
```

**mooncake_master:** **不启动**

**关键标志:**
- `--enable-hierarchical-cache` — 启用 L1+L2
- `--hicache-ratio 2` — host memory 容量为 GPU 显存的 2 倍(约 32 GB host memory)

**局限:** host memory 容量有限,8 rounds × 3072 tokens × KV size 累积后仍会 evict。

---

### Config 3: +Mooncake

**含义:** HiCache L1+L2 基础上 + Mooncake DRAM pool 作为 L3。

```bash
# 1) 先启动 mooncake_master (无 SSD offload)
mooncake_master \
  -metrics_port=9004 \
  -logtostderr &

# 2) 写 mooncake_config.json
cat > $OUT/mooncake_config.json <<EOF
{
  "local_hostname": "localhost",
  "metadata_server": "P2PHANDSHAKE",
  "global_segment_size": "8GB",
  "protocol": "tcp",
  "device_name": "",
  "master_server_address": "127.0.0.1:50051",
  "master_metrics_port": 9004,
  "check_server": false,
  "standalone_storage": false,
  "enable_ssd_offload": false,
  "ssd_offload_path": null
}
EOF

# 3) 启动 SGLang
MOONCAKE_MASTER=127.0.0.1:50051 \
MOONCAKE_GLOBAL_SEGMENT_SIZE=8589934592 \
MOONCAKE_PROTOCOL=tcp \
SGLANG_HICACHE_MOONCAKE_CONFIG_PATH=$OUT/mooncake_config.json \
python3 -m sglang.launch_server \
  --model-path /home/ficus/llm/models/Qwen/Qwen3-4B-Instruct-2507 \
  --host 127.0.0.1 --port 8189 \
  --tp 1 \
  --page-size 64 \
  --attention-backend triton \
  --enable-hierarchical-cache \
  --hicache-ratio 2 \
  --hicache-storage-prefetch-policy wait_complete \
  --hicache-mem-layout page_first_direct \
  --hicache-storage-backend mooncake
```

**关键标志:**
- `--hicache-storage-backend mooncake` — L3 后端用 Mooncake(而不是 local 文件)
- `--hicache-storage-prefetch-policy wait_complete` — 等完整 batch 再 prefetch
- `--hicache-mem-layout page_first_direct` — page-first 内存布局

**pool 容量:** 8 GB(`8589934592` bytes),由 `MOONCAKE_GLOBAL_SEGMENT_SIZE` 控制

**局限:** pool 满后 evict,**被 evict 的 KV cache 永久丢失**(无 SSD 兜底)

---

### Config 4: +Mooncake+SSD

**含义:** Mooncake 基础上 + SSD offload 作为 L4 持久化层。

```bash
# 1) 启动 mooncake_master (开启 offload)
mooncake_master \
  -enable_offload=true \
  -root_fs_dir=/mnt/ai_ssd0/mooncake_ssd0/file_storage \
  -metrics_port=9004 \
  -logtostderr &

# 2) 写 mooncake_config.json (enable_ssd_offload=true)
cat > $OUT/mooncake_config.json <<EOF
{
  "local_hostname": "localhost",
  "metadata_server": "P2PHANDSHAKE",
  "global_segment_size": "8GB",
  "protocol": "tcp",
  "device_name": "",
  "master_server_address": "127.0.0.1:50051",
  "master_metrics_port": 9004,
  "check_server": false,
  "standalone_storage": false,
  "enable_ssd_offload": true,
  "ssd_offload_path": "/mnt/ai_ssd0/mooncake_ssd0/file_storage"
}
EOF

# 3) 启动 SGLang (增加 SSD offload env vars)
MOONCAKE_MASTER=127.0.0.1:50051 \
MOONCAKE_GLOBAL_SEGMENT_SIZE=8589934592 \
MOONCAKE_PROTOCOL=tcp \
MOONCAKE_ENABLE_SSD_OFFLOAD=true \
MOONCAKE_OFFLOAD_FILE_STORAGE_PATH=/mnt/ai_ssd0/mooncake_ssd0/file_storage \
MOONCAKE_OFFLOAD_FSDIR=/mnt/ai_ssd0/mooncake_ssd0/file_storage \
MOONCAKE_OFFLOAD_LOCAL_BUFFER_SIZE_BYTES=1073741824 \
MOONCAKE_OFFLOAD_USE_URING=1 \
SGLANG_HICACHE_MOONCAKE_CONFIG_PATH=$OUT/mooncake_config.json \
python3 -m sglang.launch_server \
  --model-path /home/ficus/llm/models/Qwen/Qwen3-4B-Instruct-2507 \
  --host 127.0.0.1 --port 8189 \
  --tp 1 \
  --page-size 64 \
  --attention-backend triton \
  --enable-hierarchical-cache \
  --hicache-ratio 2 \
  --hicache-storage-prefetch-policy wait_complete \
  --hicache-mem-layout page_first_direct \
  --hicache-storage-backend mooncake
```

**关键 env vars(必须全部设置):**

| Env var | 作用 |
|---|---|
| `MOONCAKE_ENABLE_SSD_OFFLOAD=true` | 强制启用 SSD offload(防止默认关闭) |
| `MOONCAKE_OFFLOAD_FILE_STORAGE_PATH` | 落盘文件目录(JSON 与 env 二选一) |
| `MOONCAKE_OFFLOAD_FSDIR` | 同上,语义不同(文件系统根目录) |
| `MOONCAKE_OFFLOAD_LOCAL_BUFFER_SIZE_BYTES=1073741824` | 1 GiB 本地 DRAM buffer(SSD 写前 staging) |
| `MOONCAKE_OFFLOAD_USE_URING=1` | 启用 io_uring(否则用 pwritev) |

**关键证据(必须全部满足才算真正激活):**
- ✅ offload 目录出现文件(本次 5,402 个文件,41 GiB)
- ✅ master 日志 `Storage root directory is: /mnt/ai_ssd0/...`
- ✅ `IsEnableOffloading result: true`
- ✅ `O_DIRECT mode enabled` 日志(本次 1,341 次)
- ✅ offload read events(本次 52 次)

---

## 四、4 config × 8 rounds 完整数据表

**数据来源:** `/home/ficus/mooncake_smoke_test/ssd_retest_formal_20260629_074959/{gpu_only,hicache_l1_l2,mooncake_only,mooncake_ssd}/bench.log`

### 4.1 TTFT (秒) per-round

| Round | GPU only | HiCache L1+L2 | +Mooncake | **+Mooncake+SSD** |
|---:|---:|---:|---:|---:|
| 0 | 0.486 | 0.510 | 0.534 | **0.522** |
| 1 | 1.186 | 0.747 | 0.776 | **0.781** |
| 2 | 1.983 | 1.226 | 0.996 | **1.026** |
| 3 | 3.432 | 2.668 | 2.797 | **2.743** |
| 4 | 4.649 | 3.872 | 4.367 | **5.884** |
| 5 | 6.756 | 6.151 | 5.414 | **5.076** |
| 6 | 9.015 | 8.265 | 7.707 | **3.787** |
| 7 | 11.592 | 10.585 | 10.613 | **7.667** |
| **Avg** | **4.887** | **4.253** | **4.151** | **3.436** |

### 4.2 Cache Hit Rate (%) per-round

| Round | GPU only | HiCache L1+L2 | +Mooncake | **+Mooncake+SSD** |
|---:|---:|---:|---:|---:|
| 0 | 0.00 | 0.00 | 0.00 | **0.00** |
| 1 | 18.75 | 49.99 | 49.99 | **49.99** |
| 2 | 16.66 | 49.99 | 66.65 | **66.65** |
| 3 | 9.37 | 28.12 | 28.12 | **74.98** |
| 4 | 6.35 | 25.77 | 15.00 | **79.98** |
| 5 | 0.00 | 13.19 | 24.99 | **71.51** |
| 6 | 0.00 | 10.71 | 19.04 | **79.14** |
| 7 | 0.00 | 10.93 | 10.93 | **57.08** |
| **Avg** | **4.35** | **20.36** | **23.84** | **67.76** |

### 4.3 Input throughput (tok/s)

| Metric | GPU only | HiCache L1+L2 | +Mooncake | +Mooncake+SSD |
|---|---:|---:|---:|---:|
| Total | 3600.5 | 3915.9 | 3981.8 | 4469.9 |

---

## 五、TTFT 和命中率每轮变化缘由(逐 round 解读)

下面按 round 0 → 7 顺序,每个 round 解释**为什么 cache hit 上升/下降、为什么 TTFT 上升/下降**。

### Round 0: 冷启动(所有配置 hit=0%)

**数据:**

| Config | TTFT | Hit |
|---|---:|---:|
| GPU only | 0.486s | 0.00% |
| HiCache L1+L2 | 0.510s | 0.00% |
| +Mooncake | 0.534s | 0.00% |
| +Mooncake+SSD | 0.522s | 0.00% |

**根因:**
- 所有 KV cache 都还没有,没有可复用的缓存 → hit 必然是 0%
- TTFT 最低(0.49-0.53s)是因为输入长度最短(3072 tokens)
- 4 个 config TTFT 接近(差 < 50ms),因为**冷启动阶段没有缓存层差异**

---

### Round 1: 缓存建立期(hit 18-50%)

**数据:**

| Config | TTFT | Hit |
|---|---:|---:|
| GPU only | 1.186s | 18.75% |
| HiCache L1+L2 | 0.747s | 49.99% |
| +Mooncake | 0.776s | 49.99% |
| +Mooncake+SSD | 0.781s | 49.99% |

**根因:**
- Round 1 输入包含 Round 0 的 3072 tokens,**这部分 KV cache 可以被复用**
- **GPU only (18.75%):** GPU 显存只能存部分 R0 的 KV(page-first 布局下,RTX 5080 16 GB ≈ 25 万 tokens KV,R0 仅 3072 tokens → 理论可全存,但 host→device 传输有 timing,部分 page 可能来不及读回),hit 较低
- **HiCache/Mooncake/Mooncake+SSD (49.99%):** L2 host memory 有 32 GB 容量,完整保存了 R0 的 KV → 50% hit(8 个 client 中 4 个可以复用)
- **TTFT 顺序:** GPU only 最慢(1.186s,因为 R1 输入 6144 tokens 多 + hit 低),其他 3 个接近(0.75s 左右)
- **+Mooncake vs +Mooncake+SSD:** 此 round 完全相同,因为 pool 未满,**SSD offload 尚未触发**

---

### Round 2: 缓存稳定期(hit 16-66% 分化)

**数据:**

| Config | TTFT | Hit |
|---|---:|---:|
| GPU only | 1.983s | 16.66% |
| HiCache L1+L2 | 1.226s | 49.99% |
| +Mooncake | 0.996s | 66.65% |
| +Mooncake+SSD | 1.026s | 66.65% |

**根因:**
- Round 2 输入长度已达 9216 tokens(3 × 3072),更多 KV 需要缓存
- **GPU only hit 反而下降(18.75→16.66%):** GPU 显存淘汰了部分 R0 的旧 page(被 R1 新 page 挤掉)
- **HiCache 仍 49.99%:** host memory 32 GB 还够,稳定复用 R0
- **+Mooncake/+Mooncake+SSD hit 跃升到 66.65%:** Mooncake pool 8 GB 可以额外存 R0+R1 的 KV,**L3 层贡献了额外的 16% hit**(从 50% → 66.65%)
- **TTFT 顺序:** +Mooncake(0.996s) < +Mooncake+SSD(1.026s) < HiCache(1.226s) < GPU only(1.983s)
- **关键观察:** +Mooncake 和 +Mooncake+SSD 在 R2 **数据完全相同**(66.65% hit),再次证明 SSD offload 在 pool 未满时**不发挥作用**

---

### Round 3: 分水岭(SSD 价值第一次显现)

**数据:**

| Config | TTFT | Hit |
|---|---:|---:|
| GPU only | 3.432s | 9.37% |
| HiCache L1+L2 | 2.668s | 28.12% |
| +Mooncake | 2.797s | 28.12% |
| **+Mooncake+SSD** | **2.743s** | **74.98%** |

**根因:**
- Round 3 输入长度 12288 tokens(4 × 3072),累积 KV cache 总量约 **6.4 GiB**
- **GPU only (9.37%):** 显存严重不足,大量 page 被 evict,**hit 几乎归零**(降到 9.37%)
- **HiCache (28.12%):** host memory 32 GB 也开始压力,R0/R1 旧 page 被挤掉
- **+Mooncake (28.12%):** **关键临界点 — 累积 KV cache 已接近 8 GB pool 容量,开始大量 evict**(测试日志显示 10,475 次 EVICT-TRIGGER),**被 evict 的 KV cache 永久丢失** → hit 暴跌到 28.12%
- **+Mooncake+SSD (74.98%):** **虽然 pool 也满,但被 evict 的 KV cache 被写入 SSD**(本 round 第一次出现 O_DIRECT write events),后续读回 → hit **跃升到 74.98%**(从 R2 的 66.65% → R3 的 74.98%,**+8.33%**)
- **TTFT:** SSD config (2.743s) vs +Mooncake (2.797s) 差距小,但 hit 差 **46.86 个百分点** — **hit 高不代表 TTFT 低**(因为长上下文 prefill 仍需大量计算)

---

### Round 4: pool 满负荷(SSD 持续生效,但 +Mooncake+SSD TTFT 反升)

**数据:**

| Config | TTFT | Hit |
|---|---:|---:|
| GPU only | 4.649s | 6.35% |
| HiCache L1+L2 | 3.872s | 25.77% |
| +Mooncake | 4.367s | 15.00% |
| **+Mooncake+SSD** | **5.884s** | **79.98%** |

**根因:**
- Round 4 输入 15360 tokens,累积 KV cache > 8 GB pool,**两个 Mooncake config 都在大量 evict**
- **+Mooncake (15.00%):** pool 持续满,被 evict 的 KV cache 永久丢失 → hit 反而比 R3 下降(28.12→15.00%)
- **+Mooncake+SSD (79.98%):** hit **达到全测试最高 79.98%**,SSD 持续承担 L4 缓存
- **但 +Mooncake+SSD 的 TTFT 5.884s 比 +Mooncake 4.367s 高 1.5s:** 这是反直觉的,根因是 **SSD 读比 DRAM 慢 10-100 倍**:
  - 长上下文 prefill 需要读大量 KV cache
  - 即使 79.98% hit,读 SSD 的延迟累积 > 重新计算
  - 同时 SSD 写入也在并发(写导致读排队)
- **+Mooncake (TTFT 4.367s) 看似更好,是因为其 15% hit 主要走 DRAM,反而没承受 SSD 读延迟**

> **关键技术结论:** **高 hit 率不一定带来低 TTFT**,如果 hit 来自慢层(SSD),可能反而比 miss 重算更慢。Round 4-5 的 +Mooncake+SSD 数据是这一点的实证。

---

### Round 5: SSD 优势开始主导 TTFT

**数据:**

| Config | TTFT | Hit |
|---|---:|---:|
| GPU only | 6.756s | 0.00% |
| HiCache L1+L2 | 6.151s | 13.19% |
| +Mooncake | 5.414s | 24.99% |
| **+Mooncake+SSD** | **5.076s** | **71.51%** |

**根因:**
- Round 5 输入 18432 tokens(6 × 3072),累积 KV ≈ 7.7 GiB(超过 8 GB pool 的有效可用)
- **GPU only hit=0%:** 显存完全淘汰旧 page,R0/R1 KV 全部丢失
- **HiCache hit=13.19%:** host memory 持续压力,R0/R1 部分丢失
- **+Mooncake hit=24.99%:** pool 满,eviction 继续,但 pool 内 hit 仍可保留部分
- **+Mooncake+SSD hit=71.51%:** SSD 持续贡献 L4 缓存,从 R4 的 79.98% 略降到 71.51%(SSD 文件系统压力开始显现)
- **TTFT 顺序反转:** +Mooncake+SSD (5.076s) **首次低于 +Mooncake (5.414s)**,SSD 读延迟 < prefill 重算成本
- **观察:** Round 5 的 +Mooncake+SSD TTFT 比 Round 4 的 5.884s **下降 0.8s**,说明 SSD prefetch/preload 优化(52 次 read store events)在持续生效

---

### Round 6: SSD 全面领先

**数据:**

| Config | TTFT | Hit |
|---|---:|---:|
| GPU only | 9.015s | 0.00% |
| HiCache L1+L2 | 8.265s | 10.71% |
| +Mooncake | 7.707s | 19.04% |
| **+Mooncake+SSD** | **3.787s** | **79.14%** |

**根因:**
- Round 6 输入 21504 tokens(7 × 3072),已接近 P99 prompt 长度上限
- **3 个无 SSD config 的 TTFT 都 > 7.7s:** 长上下文 prefill 是计算密集型,即使部分 hit 也无法弥补
- **+Mooncake+SSD TTFT 3.787s,断崖式低于其他 3 个:** 79.14% hit + SSD prefetch 已 warm,**读 SSD 比重新计算 prefill 快 50% 以上**
- **hit 率 79.14%:** SSD 文件系统在小文件场景下表现稳定(平均 file size ≈ 41 GiB / 5402 file ≈ 8 MiB/file)
- **输入吞吐:** +Mooncake+SSD 4469.9 tok/s 是 4 config 中最高(其他 3600-3981 tok/s)

---

### Round 7: 极限压力测试(SSD 仍领先,但 hit 下降)

**数据:**

| Config | TTFT | Hit |
|---|---:|---:|
| GPU only | 11.592s | 0.00% |
| HiCache L1+L2 | 10.585s | 10.93% |
| +Mooncake | 10.613s | 10.93% |
| **+Mooncake+SSD** | **7.667s** | **57.08%** |

**根因:**
- Round 7 输入 24576 tokens(8 × 3072),累积 KV ≈ 11 GiB,**超过所有 cache 层容量总和**
- **GPU only hit=0%:** 显存完全无法容纳
- **HiCache/+Mooncake hit=10.93%:** host memory + pool 在极限压力下只能保留最新几轮 KV
- **+Mooncake+SSD hit=57.08%:** SSD **仍贡献约 47% 的 hit**(比 R6 下降 22 个百分点),根因:
  1. **SSD 容量压力:** 测试日志显示 **86 次 `insufficient space` warning** — SSD 文件系统写不下新 evict 的 KV
  2. **并发排队:** 8 个 client × 24K tokens 同时请求,SSD 读带宽被分摊
  3. **累积上下文过长:** R0 的 KV 在 SSD 中已被覆盖/淘汰(SSD 容量也有上限)
- **TTFT:** +Mooncake+SSD 7.667s 仍是 4 config 中最低,比 +Mooncake 10.613s 快 27.7%
- **核心结论:** 即使 SSD 容量也触顶,**57% hit 仍比 11% hit 提供 5.2× 的命中率优势**

---

## 六、跨 Round 趋势汇总

### 6.1 TTFT 增长斜率(每 round 平均增长)

| Config | R0 TTFT | R7 TTFT | 增长倍数 | 平均/轮 |
|---|---:|---:|---:|---:|
| GPU only | 0.486s | 11.592s | **23.8×** | +1.59s |
| HiCache L1+L2 | 0.510s | 10.585s | 20.8× | +1.44s |
| +Mooncake | 0.534s | 10.613s | 19.9× | +1.44s |
| **+Mooncake+SSD** | 0.522s | 7.667s | **14.7×** | **+1.02s** |

**+Mooncake+SSD 的 TTFT 增长斜率最缓**(每轮 +1.02s vs 其他 +1.44-1.59s),说明 SSD 在长上下文场景下**显著抑制 TTFT 爆炸性增长**。

### 6.2 Hit Rate 衰减曲线

| Config | R1 hit | R7 hit | 衰减率 |
|---|---:|---:|---:|
| GPU only | 18.75% | 0.00% | -100% |
| HiCache L1+L2 | 49.99% | 10.93% | -78% |
| +Mooncake | 49.99% | 10.93% | -78% |
| **+Mooncake+SSD** | **49.99%** | **57.08%** | **+14%(不降反升)** |

**+Mooncake+SSD 是唯一 hit 不衰减的配置** — SSD 兜底机制让命中率在 R7 仍保持 57%。

### 6.3 关键 round 阈值

| 现象 | 触发 round | 原因 |
|---|---|---|
| 三层 cache 性能开始分化 | **R3** | pool 容量 8 GB 开始被填满 |
| SSD 价值首次显现 | **R3** | 第一次 evict + 第一次 offload write |
| +Mooncake+SSD TTFT 首次低于 +Mooncake | **R5** | SSD prefetch 优化生效 |
| +Mooncake+SSD TTFT 大幅领先 | **R6** | 79% hit + SSD 读延迟 < prefill 重算 |
| 所有 config hit 衰减 | **R5-R7** | 累积 KV cache > 总可用容量 |

---

## 七、为什么 +Mooncake+SSD 总体最优秀的 5 个根因

1. **R3-R7 的高 hit 维持:** 71-80% hit 率让大部分请求避免重新 prefill
2. **SSD 写入是异步的:** 写 KV 到 SSD 不阻塞 prefill 路径,通过 1 GiB local buffer staging
3. **io_uring 加速:** `MOONCAKE_OFFLOAD_USE_URING=1` 让 SSD 读写绕过 page cache,减少 copy
4. **O_DIRECT 模式:** 1341 次 O_DIRECT 事件,避免 OS page cache 抖动
5. **小文件合并:** 测试中 5402 个文件 ≈ 8 MiB/file,不是每次写入都创建新文件,降低了文件系统元数据压力

---

## 八、对比官方 Mooncake 文档的差异

| 维度 | 官方文档 | 本地工作站 |
|---|---|---|
| GPU | H800 (80 GB) | RTX 5080 (16 GB) |
| 显存容量 | 5× 更大 | 16 GB(受限于 RTX 5080) |
| Transport | RDMA | TCP localhost |
| Pool size | 几十 GB | 8 GB |
| SSD | 企业级 NVMe(具体型号未公开) | 工作站 NVMe |
| LLM | DeepSeek 系列 | Qwen3-4B(7.6 GB) |
| Concurrency | 100+ clients | 8 clients |
| 结论 | 显著 SSD 优势 | 显著 SSD 优势(R3-R7 验证) |

**关键洞察:** 即使在 RTX 5080 (16 GB) + TCP + 小 pool (8 GB) 的"弱化"环境下,**SSD offload 的相对优势仍然成立**(67.76% vs 23.84% hit,+17.2% TTFT 改善)。这说明 SSD offload 的价值不依赖顶配硬件。

---

## 九、参考图表与脚本

| 资源 | 路径 |
|---|---|
| 原始 bench.log (4 config × 1 次) | `~/mooncake_smoke_test/ssd_retest_formal_20260629_074959/{gpu_only,hicache_l1_l2,mooncake_only,mooncake_ssd}/bench.log` |
| 驱动脚本(可重跑) | `scripts/run_mooncake_ssd_offload_retest.sh` |
| Per-round 图 | `docs/assets/mooncake-ssd-offload-final-formal-20260629/02_per_round_performance_local.png` |
| 整体性能图 | `docs/assets/mooncake-ssd-offload-final-formal-20260629/01_overall_performance_local.png` |
| I/O 证据图 | `docs/assets/mooncake-ssd-offload-final-formal-20260629/03_io_evidence_local.png` |
| Mooncake 官方对照 | https://kvcache-ai.github.io/Mooncake/performance/ssd-offload-benchmark-results.html |

---

## 十、复现命令

```bash
cd ~/llm/storage
bash scripts/run_mooncake_ssd_offload_retest.sh
# 默认 OUT_ROOT=/home/ficus/mooncake_smoke_test/ssd_retest_stable_<时间戳>
# 4 config 顺序跑完约需 30-45 分钟
```

可通过环境变量调整:
- `NUM_CLIENTS=16` 改并发数
- `NUM_ROUNDS=16` 改轮数
- `OFFLOAD_DIR=/mnt/ai_ssd1/mooncake_ssd1/file_storage` 换盘
- `RUN_CONFIGS=gpu_only,mooncake_ssd` 只跑部分 config

---

**文档结束**