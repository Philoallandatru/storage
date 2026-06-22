# Storage 基准测试项目测试介绍

日期: 2026-06-22

本文介绍当前 `mlp-storage` / MLPerf Storage Benchmark Suite 项目的测试体系。目标读者是第一次接触本仓库的工程师、评测人员和汇报读者。它解释这个项目测什么、为什么测、有哪些 benchmark 模块、如何执行、结果应该怎么看，以及本仓库已经沉淀了哪些测试报告。

## 1. 项目定位

MLPerf Storage Benchmark Suite 用于刻画支撑机器学习工作负载的存储系统性能。它不是单纯的 `fio` 裸盘跑分，而是把 AI 系统里常见的数据访问模式抽象成可复现 benchmark:

| 场景 | 存储压力来源 | 典型问题 |
|---|---|---|
| AI 训练数据加载 | 训练进程持续读取样本、图片、Parquet、NPZ 等数据 | 存储能否跟上模拟加速器消耗速度 |
| Checkpoint 保存/恢复 | 大模型训练周期性写入和读取 checkpoint | 写入吞吐、恢复吞吐、fsync、对象存储 multipart 能力 |
| LLM KV Cache offload | 推理时 KV cache 从 GPU/CPU 溢出到 SSD | object 级读写尾延迟、长稳态、GC drift |
| Vector DB / RAG | 向量加载、建索引、检索查询 | Milvus index 构建、查询延迟、召回率和存储后端影响 |

项目的核心价值是: 用更接近 AI 软件栈的工作负载测试存储，而不是只用顺序读写或 4KiB random I/O 判断设备好坏。

## 2. 项目测试范围

本仓库覆盖四大 benchmark 类别:

| Benchmark | CLI 类别 | 目录 | 测试内容 |
|---|---|---|---|
| Training I/O | `mlpstorage training` | `training/`, `configs/`, `dlio_benchmark/` | 训练样本读取吞吐、Accelerator Utilization |
| Checkpointing | `mlpstorage checkpointing` | `checkpointing/`, `tests/checkpointing/` | Llama3 系列 checkpoint write/read |
| KV Cache | `mlpstorage kvcache` 或 `kv_cache_benchmark/kv-cache.py` | `kv_cache_benchmark/` | LLM 推理 KV cache offload |
| Vector DB | `mlpstorage vectordb` 或 `vdb_benchmark/` | `vdb_benchmark/` | Milvus vector load/index/query |

统一 CLI 入口:

```bash
mlpstorage --help
```

主要子命令:

```text
mlpstorage training ...
mlpstorage checkpointing ...
mlpstorage vectordb ...
mlpstorage kvcache ...
```

## 3. 支持的存储后端

项目把 benchmark 工作负载和存储后端解耦。同一个 workload 可以跑在 POSIX 文件系统、本地 NVMe、并行文件系统、NFS/Lustre、S3 兼容对象存储或 KV cache 指定目录上。

| 后端类型 | 入口参数/配置 | 适用场景 |
|---|---|---|
| POSIX / local file | `--file`, `--data-dir`, `--checkpoint-folder` | 本地 NVMe、NFS、Lustre、GPFS、WekaFS |
| Object storage | `--object`, `storage.storage_type=s3dlio/minio/s3torchconnector` | S3、MinIO、Ceph RGW、Vast 等 |
| Direct I/O | `storage_library: direct`, `direct://`, O_DIRECT 配置 | 绕过 page cache，测裸设备路径 |
| KV cache directory | `--cache-dir` | 指定 KV cache offload 的落盘位置 |
| Vector DB storage | Docker volume / Milvus MinIO / 外部 S3 | 测数据库存储层对向量检索的影响 |

对象存储三种库:

| Library | 定位 |
|---|---|
| `s3dlio` | 推荐主路径，支持多协议、多 endpoint、较适合 benchmark |
| `minio` | MinIO Python SDK，对 S3 兼容服务直接测试 |
| `s3torchconnector` | PyTorch 生态路径，主要用于 PyTorch 数据加载 |

## 4. 测试环境与安装

推荐使用 `uv` 管理 Python 环境:

```bash
cd /home/ficus/llm/storage
uv sync --all-extras
```

或使用本仓库现有环境:

```bash
cd /home/ficus/llm/storage
source .venv/bin/activate
```

分布式训练类 benchmark 还需要 MPI:

```bash
sudo apt install libopenmpi-dev openmpi-common
```

如果用 root 或容器环境运行触发 MPI 的命令，需要显式加:

```bash
--allow-run-as-root
```

对象存储测试需要配置环境变量或 `.env`:

```bash
export AWS_ENDPOINT_URL=http://your-server:9000
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
export AWS_REGION=us-east-1
```

## 5. Training I/O benchmark

Training I/O 使用 DLIO benchmark 模拟 AI 训练样本加载。它不是训练真实模型，而是用模型配置模拟训练进程对数据的消费速度和访问模式。

支持的训练 workload:

| Workload | 数据类型 | 特征 |
|---|---|---|
| RetinaNet | JPEG 图片 | 图像训练样本读取，适合验证 page cache / O_DIRECT / S3 GET 路径 |
| FLUX.1 | Parquet | 生成式模型相关数据形态，样本组织更大 |
| DLRMv2 | Parquet / embedding-like | 极低 compute time，容易变成纯 I/O bound |

标准流程有三步:

| 步骤 | 命令 | 作用 |
|---|---|---|
| 1. datasize | `mlpstorage training datasize ...` | 根据模拟 accelerator、host memory、host 数量计算数据集大小 |
| 2. datagen | `mlpstorage training datagen ...` | 生成合成训练数据 |
| 3. run | `mlpstorage training run ...` | 执行训练 I/O benchmark |

本地文件系统示例:

```bash
mlpstorage training datagen \
  --model retinanet \
  --file \
  --num-processes 4 \
  --data-dir /tmp/mlperf-test/retinanet

mlpstorage training run \
  --model retinanet \
  --accelerator-type b200 \
  --num-accelerators 4 \
  --client-host-memory-in-gb 64 \
  --file \
  --data-dir /tmp/mlperf-test/retinanet
```

对象存储示例:

```bash
mlpstorage training datagen \
  --model retinanet \
  --params storage.storage_type=s3dlio \
  --params storage.storage_root=s3://mlperf-data/retinanet

mlpstorage training run \
  --model retinanet \
  --accelerator-type b200 \
  --num-processes 8 \
  --params storage.storage_type=s3dlio \
  --params storage.storage_root=s3://mlperf-data/retinanet
```

主要指标:

| 指标 | 含义 |
|---|---|
| samples/sec | 全局样本读取吞吐 |
| epoch wall time | 每轮训练模拟耗时 |
| AU% | Accelerator Utilization，模拟 accelerator 没有被 I/O 饿住的比例 |
| pass/fail | 是否达到 workload 对应 accelerator profile 的目标 AU |

已记录结果见:

| 文档 | 内容 |
|---|---|
| `tests/RetinaNet_test_results.md` | RetinaNet POSIX/S3/O_DIRECT 对比 |
| `tests/Flux_test_results.md` | Flux 结果 |
| `tests/DLRM_test_results.md` | DLRM 结果 |

## 6. Checkpointing benchmark

Checkpointing benchmark 模拟大模型训练保存和恢复 checkpoint。它关注的是大对象并发写入、读回、fsync、对象存储 multipart pipeline 等路径。

支持模型规模:

| 模型 | checkpoint 总规模 |
|---|---:|
| Llama3 8B | 约 105 GB |
| Llama3 70B | 约 912 GB |
| Llama3 405B | 约 5.29 TB |
| Llama3 1T | 约 18 TB |

基本写读一体命令:

```bash
mlpstorage checkpointing run \
  --client-host-memory-in-gb 512 \
  --model llama3-8b \
  --num-processes 8 \
  --checkpoint-folder /mnt/checkpoint_test
```

标准提交流程通常拆成写和读:

```bash
# write phase
mlpstorage checkpointing run \
  --client-host-memory-in-gb 512 \
  --model llama3-8b \
  --num-processes 8 \
  --checkpoint-folder /mnt/checkpoint_test \
  --num-checkpoints-read 0

# clear cache if required
sync
echo 3 > /proc/sys/vm/drop_caches

# read phase
mlpstorage checkpointing run \
  --client-host-memory-in-gb 512 \
  --model llama3-8b \
  --num-processes 8 \
  --checkpoint-folder /mnt/checkpoint_test \
  --num-checkpoints-write 0
```

主要指标:

| 指标 | 含义 |
|---|---|
| checkpoint save duration | 写一个 checkpoint 的耗时 |
| checkpoint load duration | 读回一个 checkpoint 的耗时 |
| write throughput | 写入吞吐，通常 GiB/s |
| read throughput | 恢复吞吐，通常 GiB/s |
| rank-level min/max | 提交指标按最慢 rank / 最低吞吐归约 |

已有结果示例:

| 后端 | 写吞吐 | 读吞吐 | 说明 |
|---|---:|---:|---|
| POSIX NVMe | 1.416 GiB/s | 2.827 GiB/s | 本地 NVMe 路径 |
| S3 object via s3-ultra | 2.213 GiB/s | 8.401 GiB/s | loopback fake-S3，读来自内存，写受 multipart pipeline 影响 |

详细见 `tests/Checkpoint_test_results.md` 和 `docs/Streaming-Chkpt-Guide.md`。

## 7. KV Cache benchmark

KV Cache benchmark 模拟 LLM 推理时 KV cache 从 GPU VRAM 到 CPU DRAM 再到 NVMe 的 offload 过程。它重点测试对象级读写延迟，而不是单条 NVMe 命令延迟。

关键概念:

| 概念 | 含义 |
|---|---|
| Prefill | 处理 prompt，通常写 KV cache |
| Decode | 生成 token，通常读 KV cache |
| Tier | GPU/CPU/NVMe 三层存储 |
| KV object | 一个请求、层、head 对应的 KV 数据对象，可达 MiB 到 GiB |
| Tensor parallel | 模型张量并行，影响单 rank KV object 大小 |

快速命令:

```bash
cd kv_cache_benchmark

python3 kv-cache.py \
  --config config.yaml \
  --model llama3.1-8b \
  --num-users 50 \
  --duration 120 \
  --gpu-mem-gb 0 \
  --cpu-mem-gb 4 \
  --cache-dir /mnt/nvme \
  --output results.json
```

本仓库 AI SSD 预研常用主线命令见:

```bash
bash scripts/run_full_profiling.sh burstgpt_70b_users6_full llama3.1-70b-instruct 6 300
bash scripts/run_fio_sweep.sh
bash scripts/run_long_steady_state.sh 30
bash scripts/cross_vendor_kv_cache_k4_30min_drift.sh
```

主要 workload:

| Workload | 作用 |
|---|---|
| synthetic | 构造压力边界和 first FAIL |
| ShareGPT | 真实聊天数据，流程验证和轻压力 |
| BurstGPT | 生产 API trace，更适合 AI SSD 压测 |
| fio distilled | 从 KV/bpftrace 蒸馏成可复现裸盘 workload |

主要指标:

| 指标 | 含义 |
|---|---|
| read/write device P95/P99 | KV object 级存储读写尾延迟 |
| cache hit rate | KV cache 命中率 |
| storage read/write bytes | 实际落到存储层的读写量 |
| SLA/QoS compliance | 请求是否满足服务级目标 |
| iostat await/util | 设备层延迟和利用率 |
| bpftrace D2C/Q2D | block 层命令服务时间和排队时间 |

KV Cache 相关报告:

| 文档 | 内容 |
|---|---|
| `docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md` | AI SSD / KV Cache 集成预研决策报告 |
| `docs/ai-ssd-kvcache-complete-archive-report-2026-06-13.md` | 完整实验归档 |
| `docs/kvcache-main-report-experiment-commands-2026-06-22.md` | 主要 KV Cache 报告实验命令索引 |
| `docs/kv-cache-final-selection-2026-06-10.md` | 四盘 KV Cache 最终选型 |

## 8. Vector DB benchmark

Vector DB benchmark 测试 Milvus 向量数据库的 load、index build 和 query 路径。它面向 RAG / vector search 场景，不只看存储吞吐，还需要同时看查询延迟和召回率。

支持 index 类型:

| Index | 特征 |
|---|---|
| DiskANN | 磁盘型 ANN，适合测试存储路径 |
| HNSW | 内存图索引，更多测试内存/CPU |
| AISAQ | quantization 路径，测试压缩索引策略 |

启动 Milvus:

```bash
cd vdb_benchmark
docker compose -f stacks/milvus/standalone/minio/docker-compose.yml up -d
```

估算容量:

```bash
./mlpstorage vectordb datasize \
  --dimension 1536 \
  --num-vectors 10000000 \
  --index-type DISKANN \
  --num-shards 10
```

加载数据示例:

```bash
python vdbbench/load_vdb.py \
  --config vdbbench/configs/10m_diskann.yaml \
  --collection-name mlps_500k_10shards_1536dim_uniform_diskann \
  --num-vectors 500000
```

Vector DB 主要指标:

| 指标 | 含义 |
|---|---|
| load throughput | 向量导入速度 |
| index build time | 建索引耗时 |
| query latency | 查询延迟，通常看 P50/P95/P99 |
| QPS | 查询吞吐 |
| recall | 检索准确性 |
| storage footprint | 原始向量和索引占用空间 |

详细见 `vdb_benchmark/README.md`。

## 9. 测试层级

项目测试不只包含 benchmark 跑分，也包含软件正确性测试和基础设施测试。

| 层级 | 目录/命令 | 目的 |
|---|---|---|
| Unit tests | `pytest tests/unit/` | 快速验证 CLI、参数、benchmark wrapper、mock 执行逻辑 |
| Integration tests | `pytest tests/integration/` | 验证对象存储、MPI、外部服务连接 |
| Object-store tests | `tests/object-store/` | 验证 s3dlio/minio/s3torchconnector 功能和吞吐 |
| Checkpoint demos | `tests/checkpointing/` | 验证 streaming checkpoint 和 backend 行为 |
| Benchmark reports | `tests/*_test_results.md`, `docs/ai-ssd-*.md` | 固化性能结论和复现实验 |

常用测试命令:

```bash
# unit tests only
pytest tests/unit/ -v

# integration tests
pytest tests/integration/ -v

# object storage connectivity
python tests/integration/test_s3_connectivity.py \
  --libraries s3dlio minio \
  --s3dlio-bucket mlp-s3dlio \
  --minio-bucket mlp-minio

# object storage performance
python tests/object-store/test_direct_write_comparison.py
python tests/object-store/test_s3lib_get_bench.py
```

## 10. 结果怎么看

不同 benchmark 的结论不能混在一起解释。

| Benchmark | 首要指标 | 常见误读 |
|---|---|---|
| Training I/O | AU%、samples/sec、epoch time | 把 page cache 暖缓存结果当裸盘能力 |
| Checkpointing | GiB/s、save/load duration、rank-level bottleneck | 只看平均吞吐，不看最慢 rank 和 fsync |
| KV Cache | object 级 P95/P99、E2E P95、iostat drift | 把 NVMe D2C 微秒级延迟等同于 KV object 毫秒级延迟 |
| Vector DB | recall + latency + QPS + build time | 只看 QPS，不看召回率和 index/storage footprint |

特别注意:

1. `fio` 是底层设备补充测试，不等价于 AI workload 结果。
2. KV Cache 的 `read device P95` 是对象级指标，可能远大于单条 block I/O D2C。
3. Training I/O 的 AU% 由模拟 compute time 和 epoch wall time共同决定。
4. Checkpointing 读测试前是否清 page cache 会显著影响结果。
5. 对象存储 loopback 测试适合验证软件栈，不等价于真实远端网络环境。

## 11. 本仓库已有代表结果

2026-04-26 的标准 training/checkpointing 结果:

| Workload | POSIX NVMe | AU% | S3 Object | AU% | 说明 |
|---|---:|---:|---:|---:|---|
| RetinaNet | 1,866 samples/s | 92.8% | 1,919 samples/s | 95.4% | POSIX 和 S3 都达标 |
| Flux | 141 samples/s | 99.7% | 121 samples/s | 85.4% | POSIX 达标，S3 loopback 略低 |
| DLRM | 389K samples/s | 0.48% | 106K samples/s | 0.11% | 极端 I/O bound，未达目标 |
| Checkpointing | 1.416 GiB/s write | - | 2.213 GiB/s write | - | S3 multipart pipeline 写入更快 |

KV Cache / AI SSD 预研代表结论:

| 方向 | 结论摘要 |
|---|---|
| BurstGPT 70B baseline | 70B users=6/users=8 可用于主报告压力基线 |
| fio iodepth sweep | 蒸馏出的超大 qd 不应直接用，合理 qd 约 32 |
| 长稳态 | 消费级 SSD 短测和长测表现可能差异很大 |
| 跨盘选择 | 短时 burst 和长期 GC 稳定性要分开判断 |

## 12. 推荐阅读路径

第一次看项目:

1. `docs/README.md`
2. `docs/QUICK_START.md`
3. 本文档
4. `tests/README.md`

要跑 training/object storage:

1. `training/README.md`
2. `docs/Object_Storage.md`
3. `docs/STORAGE_LIBRARIES.md`
4. `tests/RetinaNet_test_results.md`

要跑 checkpoint:

1. `checkpointing/README.md`
2. `docs/Streaming-Chkpt-Guide.md`
3. `tests/Checkpoint_test_results.md`

要看 KV Cache / AI SSD:

1. `kv_cache_benchmark/README.md`
2. `docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md`
3. `docs/ai-ssd-kvcache-complete-archive-report-2026-06-13.md`
4. `docs/kvcache-main-report-experiment-commands-2026-06-22.md`

要跑 Vector DB:

1. `vdb_benchmark/README.md`
2. `vdb_benchmark/tests/README.md`

## 13. 推荐最小验证流程

如果只想确认环境和项目基本可用:

```bash
cd /home/ficus/llm/storage
source .venv/bin/activate
pytest tests/unit/ -v
```

如果要做一个本地文件系统 training smoke test:

```bash
mlpstorage training datagen \
  --model retinanet \
  --file \
  --num-processes 4 \
  --data-dir /tmp/mlperf-test/retinanet

mlpstorage training run \
  --model retinanet \
  --accelerator-type b200 \
  --num-accelerators 4 \
  --client-host-memory-in-gb 64 \
  --file \
  --data-dir /tmp/mlperf-test/retinanet
```

如果要做 KV Cache smoke test:

```bash
cd /home/ficus/llm/storage/kv_cache_benchmark
source ../.venv/bin/activate

python3 kv-cache.py \
  --config config.yaml \
  --model llama3.1-8b \
  --num-users 4 \
  --duration 60 \
  --gpu-mem-gb 0 \
  --cpu-mem-gb 4 \
  --cache-dir /tmp/kvcache-smoke \
  --output /tmp/kvcache-smoke.json
```

如果要复现 AI SSD 主报告核心路径:

```bash
cd /home/ficus/llm/storage
source .venv/bin/activate

bash scripts/run_full_profiling.sh burstgpt_70b_users6_full llama3.1-70b-instruct 6 300
bash scripts/run_fio_sweep.sh
bash scripts/run_long_steady_state.sh 30
```

## 14. 文档和结果产物组织

| 位置 | 内容 |
|---|---|
| `docs/` | 项目文档、架构说明、实验报告 |
| `tests/` | 单元测试、集成测试、对象存储测试、结果记录 |
| `results/` | 本地实验输出，包含 KV Cache / cross-vendor / fio 结果 |
| `docs/assets/` | 报告图表、CSV 摘要、可视化资产 |
| `configs/` | DLIO / MLPerf workload 配置 |
| `scripts/` | KV Cache、cross-vendor、fio、分析脚本 |

新增报告或测试时建议同时记录:

1. 运行命令。
2. 环境和硬件。
3. 数据集或 trace 来源。
4. 参数解释。
5. 原始结果路径。
6. 核心指标表。
7. 结论边界和不可外推的地方。

