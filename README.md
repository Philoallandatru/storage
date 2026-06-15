# MLPerf Storage Benchmark Suite
MLPerf® Storage is a benchmark suite to characterize the performance of storage systems that support machine learning workloads.

- [Overview](#overview)
- [Submission Rules](#submission-rules)
- [Normalizing Factors For Comparisons](#normalizing-factors-for-comparisons)
- [Usage](#usage)
  - [Prerequisite](#prerequisite)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Workload Categories](#workload-categories)
- [Theory of Operations](#theory-of-operations)
  - [General Rules](#general-rules)
  - [CLOSED: virtually all changes are disallowed](#closed-virtually-all-changes-are-disallowed)
  - [OPEN: changes are allowed but must be disclosed](#open-changes-are-allowed-but-must-be-disclosed)
  - [System Description YAML - Structured Description](#system-description-yaml---structured-description)
  - [System Description PDF - Graphical and Prose Text](#system-description-pdf---graphical-and-prose-text)


## Overview

Two README files cover the full project in detail — read both before diving into the
code or running benchmarks:

| Document | What it covers |
|----------|----------------|
| **[docs/README.md](docs/README.md)** | Complete project overview: all four benchmark workloads, document reference, object storage library guides, and quick-link index to every test script |
| **[docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md](docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md)** | AI-SSD integrated pre-study: 4-disk cross-vendor recommendations + **14 visualization charts in [docs/assets/](docs/assets/)** |
| **[tests/README.md](tests/README.md)** | Everything needed to run tests: environment setup, unit tests, integration tests, object-store performance scripts, and how pytest is configured |

Additional quick links:

| Document | What it covers |
|----------|----------------|
| **[docs/OBJECT_STORAGE_GUIDE.md](docs/OBJECT_STORAGE_GUIDE.md)** | All settings required to run against S3-compatible storage with `--object` — `.env` setup, env vars, URI schemes, multi-endpoint |
| **[tests/object-store/bench-results-retinanet-20260425.md](tests/object-store/bench-results-retinanet-20260425.md)** | April 25, 2026 benchmark results: RetinaNet write_threads sweep on s3-ultra (loopback) |

The top-level sections below give the official MLCommons parameter reference and
are retained for submission compliance.

## Submission Rules

MLPerf™ Storage Benchmark submission rules are described in the
[Rules.md](https://github.com/mlcommons/storage/blob/main/Rules.md) file.
If you have questions, please contact the [Storage WG chairs](https://mlcommons.org/en/groups/research-storage/).


## Normalizing Factors For Comparisons

To compare the performance of two storage solutions that have very different architectures,
we must have a divisor that is independent of the storage system's architecture but is also present for all architectures.

### Rack Units Requirements (Mandatory)

If the system requires the physical deployment of dedicated hardware, ie: is not a cloud-based deployment or a hyperconverged deployment,
the SystemDescription.yaml will include the total number of rack units (RU's) that will be consumed by the storage system under test,
including any supporting gear that is required for the configuration being tested.
That supporting gear could include, for example, network switches for a "backend" or private network that is required for the storage system to operate.
The rack units measure does not need to include any of the gear that connects the storage system to the ``host nodes``.

This will show GB/s/RU or IOPs/RU.

### Power Requirements (Mandatory)

If the system requires the customer provisioning of power (for example, systems intended to be deployed in on-premises data centers or in co-located data centers)
the SystemDescription.yaml will include all hardware devices required to operate the storage system.
Shared network equipment also used for client network communication and optional storage management systems do not need to be included.

This will show GB/s/KW or IOPs/KW.

## Usage
For an overview of how this benchmark suite is used by submitters to compare the performance of storage systems supporting an AI cluster, see the MLPerf® Storage Benchmark submission rules here: [doc](https://github.com/mlcommons/storage/blob/main/Submission_guidelines.md). 

### Prerequisite

The installation and the configuration steps described in this README are validated against clients running Ubuntu 24.04 server with python 3.12.3. The benchmark script has to be run only in one participating client host(any) which internally calls `mpirun` to launch the distributed workloads across multiple client hosts. The launcher client host also participates in the distributed training process.

Following prerequisites must be satisfied

1. Pick one host to act as the launcher client host. Passwordless ssh must be setup from the launcher client host to all other participating client hosts.  `ssh-copy-id` is a useful tool.
2. The code and data location(discussed in further sections) must be exactly same in every client host including the launcher host. This is because, the same benchmark command is automatically triggered in every participating client host during the distributed training process.

#### Running as root
When the launcher client is root (common in container or bare-metal benchmark setups), `mpirun` will refuse to launch unless `--allow-run-as-root` is passed to every `mlpstorage` sub-command that triggers MPI (`training datasize`, `training datagen`, `training run`, `checkpointing run`, `kvcache run`). Add it explicitly:

```bash
mlpstorage training datagen --hosts 127.0.0.1 --model unet3d \
  --num-processes 8 --data-dir unet3d_data --allow-run-as-root \
  --param dataset.num_files_train=42000
```

### Installation 
**The following installation steps must be run on every client host that will participate in running the benchmarks.**

#### uv (Required)

[`uv`](https://docs.astral.sh/uv/) is a fast Python package and project manager that handles virtual environment creation, dependency resolution, and Python version management automatically — no manual `venv` or `pip` steps required. It will install into your virutal environment exactly the versions of supporting libraries and tools that the benchmark has been tested with.

**Install uv** (if not already installed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install the MPI runtime (still required for distributed execution):

```bash
sudo apt install libopenmpi-dev openmpi-common
```

Clone the repo:

```bash
git clone https://github.com/mlcommons/storage.git
cd storage
```

Verify the installation:

```bash
mlpstorage --help
```

The `mlpstorage` script executes `uv run` every time you invoke the benchmark, keeping your virtual environment up to date.
`uv` creates a `.venv` virtual environment and installs all dependencies — including DLIO benchmark — automatically based upon the contents of the the `uv.lock` file.

> **Note:** `uv` installs the CPU-only version of PyTorch.
> GPU-accelerated training or checkpointing workloads are not supported, there is no need to have GPUs in your benchmark test gear, they will not be used.

The benchmark simulation will be performed through the [dlio_benchmark](https://github.com/mlcommons/DLIO_local_changes) code, a benchmark suite for emulating I/O patterns for deep learning workloads. The DLIO configuration of each workload is specified through a yaml file. You can see the configs of all MLPerf Storage workloads in the `configs` folder. 

#### Testing the Installation

See **[tests/README.md](tests/README.md)** for the complete test guide — environment
setup, unit tests (no infrastructure required), integration tests, and object-store
performance scripts for all three supported object storage libraries.

- **StreamingCheckpointing Demo**: Run `./tests/checkpointing/demo_checkpoint_methods.sh` to see:
  - dgen-py integration (155× faster data generation)
  - StreamingCheckpointing (192× memory reduction)
  - Comparison of old vs new checkpoint methods

- **Backend Validation**: Test multi-library support:
  ```bash
  python tests/checkpointing/test_streaming_backends.py --backends s3dlio minio
  ```

- **Unit tests** (no infrastructure required):
  ```bash
  pytest tests/unit/
  ```

### Workload Categories
The benchmark uses nested commands to select the workload category, workload, and workload parameters.
The first argument is the workload category:
 - training
 - checkpointing
 - vectordb
 - kvcache

```bash
[root@localhost ]#  mlpstorage -h
usage: mlpstorage [-h] [--version] {training,checkpointing,vectordb,kvcache} ...

Script to launch the MLPerf Storage benchmark

positional arguments:
  {training,checkpointing,vectordb,kvcache}
    training            Training benchmark options
    checkpointing       Checkpointing benchmark options
    vectordb            VectorDB benchmark options
    kvcache             KVCcache benchmark options

optional arguments:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```
### Storage Backend Selection (--file/--object)
The `training`,`checkpointing`, `vectordb` and `kvcache` workloads require you to declare the storage backend under test. Exactly one of the following must be passed to the run sub-command:

| Flag | Backend | When to use |
|---|---|---|
| `--file` | POSIX/parallel filesystem (local, NFS, Lustre, GPFS, WekaFS, etc.) accessed via the checkpoint-folder path. | Block storage, file storage, parallel filesystem submissions. |
| `--object` | S3-compatible object store, accessed via one of the three supported object-store libraries (see `tests/README.md`). | Object-storage submissions. Requires endpoint/bucket env vars (see backend-specific notes). |

These flags are mutually exclusive and one is required. Omitting both produces:
```
error: one of the arguments --file --object is required
```

#### Training Category
The training category supports emulation of the training of 3 models (FLUX.1, RetinaNet, and DLRMv2).

See [training/README.md](training/README.md) for more details.

#### Checkpointing Category
The checkpointing category supports emulation of taking a checkpoint of an LLM foundation training task,
specifically the Llama3 LLM at four different scales: 8B, 70B, 405B, and 1250B parameters.

See [checkpointing/README.md](checkpointing/README.md) for more details.

#### VectorDB Category
The vectordb category supports emulation of a vector database as used in an LLM RAG pipeline,
specifically the Milvus VDB using one of three different algorithms: DiskANN, HNSW, and AiSAQ.

See [vdb_benchmark/README.md](vdb_benchmark/README.md) for more details.

#### KVCache Category
The kvcache category supports emulation of a context cache as used by an LLM.

See [kv_cache_benchmark/README.md](kv_cache_benchmark/README.md) for more details.

#### KV-Cache Visualization (cross-vendor 4-disk)

> 14 张 IO profiling 图, 全部已 commit 入 `docs/assets/` (本地可访问)。

**Cross-vendor 4 盘对比图** ([docs/assets/charts/](docs/assets/charts/)):

| # | 文件 | 故事 |
|---|---|---|
| 01 | [01_k4_k5_bw_compare.png](docs/assets/charts/01_k4_k5_bw_compare.png) | **核心叙事**: K4/K5/K4-GC-drift read BW (GB/s) 4 盘 — Biwin X570 第一 |
| 02 | [02_k4_gc_p99_drift.png](docs/assets/charts/02_k4_gc_p99_drift.png) | K4 GC-drift 1200s read p99 latency 漂移 — 揭示长稳态退化 |
| 03 | [03_cliff_detection.png](docs/assets/charts/03_cliff_detection.png) | read BW 时序 + cliff marker (SLC cache 跌落点) |
| 04 | [04_io_pattern_boxplots.png](docs/assets/charts/04_io_pattern_boxplots.png) | request size + await boxplots 4 盘 |
| 05 | [05_summary_ranking.png](docs/assets/charts/05_summary_ranking.png) | **决策图**: 6-metric 4 盘 ranking heatmap |
| 06 | [06_write_p99_drift.png](docs/assets/charts/06_write_p99_drift.png) | write service-time 漂移 (GC 影响最显著的指标) |
| 07 | [07_long_drift_compare.png](docs/assets/charts/07_long_drift_compare.png) | K4 30-min 4 盘长稳态对比 — **Biwin/Seagate 30 min 后实际 TIED** |
| 08 | [08_duration_bars.png](docs/assets/charts/08_duration_bars.png) | K4 多窗口 BW 柱状图 |

**IO profiling / 业务级图** ([docs/assets/kvcache-io-profiling/](docs/assets/kvcache-io-profiling/)):

| # | 文件 | 故事 |
|---|---|---|
| 01 | [burstgpt_users_gradient_latency.png](docs/assets/kvcache-io-profiling/burstgpt_users_gradient_latency.png) | BurstGPT users × latency 渐变 |
| 02 | [iostat_await_utilization.png](docs/assets/kvcache-io-profiling/iostat_await_utilization.png) | iostat await / util 时间序列 |
| 03 | [kv_object_device_p95_comparison.png](docs/assets/kvcache-io-profiling/kv_object_device_p95_comparison.png) | KV object vs device p95 latency 对比 |
| 04 | [object_latency_vs_d2c_read.png](docs/assets/kvcache-io-profiling/object_latency_vs_d2c_read.png) | object latency vs D2C read |
| 05 | [storage_traffic_workload_comparison.png](docs/assets/kvcache-io-profiling/storage_traffic_workload_comparison.png) | storage traffic × workload 对比 |

**复现**:

```bash
# 图 01-06: 4 盘 K4/K5 决策图
source .venv/bin/activate
python ~/.hermes/skills/mlperf-storage-bench/scripts/render_kv_cache_charts.py
# 输出: docs/assets/charts/01-06 (覆盖式重生成, 可重复)
```

> 注: 07/08 (30-min drift) 不是脚本出的, 来自 commit `2060baa` (K4 30-min 长稳态测试)。

**对应的文字报告**:
- [docs/kv-cache-4disk-K4-headline-2026-06-10.md](docs/kv-cache-4disk-K4-headline-2026-06-10.md) — K4 4 盘 headline (图 01/05)
- [docs/kv-cache-4disk-K5-headline-2026-06-10.md](docs/kv-cache-4disk-K5-headline-2026-06-10.md) — K5 4 盘 headline (70B 模型)
- [docs/kv-cache-4disk-K4-30min-drift-2026-06-10.md](docs/kv-cache-4disk-K4-30min-drift-2026-06-10.md) — K4 30-min drift (图 07/08)
- [docs/kv-cache-cross-vendor-2026-06-10.md](docs/kv-cache-cross-vendor-2026-06-10.md) — 跨 vendor 综合报告 (图 02/03/06)
- [docs/kv-cache-io-pattern-analysis-2026-06-10.md](docs/kv-cache-io-pattern-analysis-2026-06-10.md) — IO pattern 分析 (图 04)
- [docs/kvcache-io-profiling-visual-analysis-2026-06-08.md](docs/kvcache-io-profiling-visual-analysis-2026-06-08.md) — IO profiling 业务级图
- [docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md](docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md) — AI SSD 集成预研报告 (推荐起点)



## Theory of Operations

MLPerf™ Storage is a benchmark suite to characterize the performance of storage systems that support machine learning workloads.

This benchmark attempts to balance two goals. First, we aim for **comparability** between benchmark submissions to enable decision making by the AI/ML Community. Second, we aim for **flexibility** to enable experimentation and to show off unique storage system features that will benefit the AI/ML Community. To that end we have defined two classes of submissions: CLOSED and OPEN. 

The MLPerf name and logo are trademarks of the MLCommons® Association ("MLCommons"). In order to refer to a result using the MLPerf name, the result must conform to the letter and spirit of the rules specified in this document. MLCommons reserves the right to solely determine if a use of its name or logos is acceptable.

This version of the benchmark does not include offline or online data pre-processing. We are aware that data pre-processing is an important part of the ML data pipeline and we will include it in a future version of the benchmark.

### General Rules
 
The following apply to all results submitted for this benchmark.

Benchmarking should be conducted to measure the framework and storage system performance as fairly as possible. Ethics and reputation matter.

- **Available Systems**. To be called an ``available system`` all components of the system must be publicly available. If any components of the system are not available at the time of the benchmark results submission, those components must be included in an ``available system`` submission that is submitted in the next round of MLPerf Storage benchmark submissions.  Otherwise, the results for that submission may be retracted from the MLCommons results dashboard.
- **RDI Systems**. If you are measuring the performance of an experimental framework or system, you must make the system and framework you use available upon demand for replication by MLCommons. This class of systems will be called RDI (research, development, internal). 

The data generator in DLIO uses a fixed random seed that must not be changed, to ensure that all submissions are working with the same dataset. Random number generators may be seeded from the following sources:
- Clock
- System source of randomness, e.g. /dev/random or /dev/urandom
- Another random number generator initialized with an allowed seed
Random number generators may be initialized repeatedly in multiple processes or threads. For a single run, the same seed may be shared across multiple processes or threads.

The storage system must not be informed of the random seed or the source of randomness.  This is intended to disallow submissions where the storage systen can predict the access pattern of the data samples.

Public results should be rounded normally, to two decimal places.

For all workloads stable storage must be used, but there are some differences in the specifics.

Results that cannot be replicated are not valid results. Replicated results should be within 5% within 5 tries.

Each of the benchmarks described in this document have a requirement for multiple runs. This is to ensure consistency of operation of the system under test as well as ensure statistical significance of the measurements.

Unless otherwise noted, the multiple runs for a workload need to be run consecutively. To ensure this requirement is met, the time between runs (from the stop time of one run and the start time to the next run) needs to be less than the time to execute a single run. This is to discourage cherry-picking of results which is expressly forbidden and against the spirit of the rules.

### CLOSED: virtually all changes are disallowed
CLOSED represents a level playing field where all results are **comparable** across submissions. CLOSED explicitly forfeits flexibility in order to enable easy comparability. 

In order to accomplish that, most of the optimizations and customizations to the AI/ML algorithms and framework that might typically be applied during benchmarking or even during production use must be disallowed.  Optimizations and customizations to the storage system are allowed in CLOSED.

For CLOSED submissions of this benchmark, the MLPerf Storage codebase takes the place of the AI/ML algorithms and framework, and therefore cannot be changed. The sole exception to this rule is if the submitter decides to apply the code change identified in PR#299 of the DLIO repo in github, the resulting codebase will be considered "unchanged" for the purposes of this rule. 

### OPEN: changes are allowed but must be disclosed

OPEN allows more **flexibility** to tune and change both the benchmark and the storage system configuration to show off new approaches or new features that will benefit the AI/ML Community. OPEN explicitly forfeits comparability to allow showcasing innovation.

The essence of OPEN division results is that for a given benchmark area, they are “best case” results if optimizations and customizations are allowed.  The submitter has the opportunity to show the performance of the storage system if an arbitrary, but documented, set of changes are made to the data storage environment or algorithms.

Changes to DLIO itself are allowed in OPEN division submissions.  Any changes to DLIO code or command line options must be disclosed. 

While changes to DLIO are allowed, changing the workload itself is not.  Ie: how the workload is processed can be changed, but those changes cannot fundamentally change the purpose and result of the training.  For example, changing the workload imposed upon storage by a ResNet-50 training task into 3D-Unet training task is not allowed.

### System Description YAML - Structured Description

The purpose of the system description is to provide sufficient detail on the storage system under test, and the ``host nodes`` running the test, plus the network connecting them, to enable full reproduction of the benchmark results by a third party. 

Each submission must contain a ``<system-name>.yaml`` file and a ``<system-name>.pdf`` file.  If you submit more than one benchmark result, each submission must have a unique ``<system-name>.yaml`` file and a ``<system-name>.pdf`` file that documents the system under test and the environment that generated that result, including any configuration options in effect.

The system description yaml is a hybrid human-readable and machine-readable description of the total system under test. It contains fields for the System overall, the Nodes that make up the solution (clients and storage), as well as Power information of the nodes.

An example can be found [HERE](https://github.com/mlcommons/storage/blob/main/system_configuration.yaml)

### System Description PDF - Graphical and Prose Text

The goal of the pdf is to complement the YAML file, providing additional detail on the system to enable full reproduction by a third party. We encourage submitters to add details that are more easily captured by diagrams and text description, rather than a YAML.

This file is should include everything that a third party would need in order to recreate the results in the submission, including product model numbers or hardware config details, unit counts of drives and/or components, system and network topologies, software used with version numbers, and any non-default configuration options used by any of the above.
