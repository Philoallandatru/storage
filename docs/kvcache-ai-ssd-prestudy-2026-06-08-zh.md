# KV Cache AI SSD 预研报告

日期: 2026-06-08

工作目录: `/home/ficus/llm/storage`

基准测试: `kv_cache_benchmark`

## 执行摘要

本报告总结了为 AI SSD 产品预研而运行的 KV cache 实验。测试涵盖了合成压力工作负载、ShareGPT 真实对话回放、BurstGPT 生产 API 追踪回放、张量并行对象大小缩放、CPU 缓存灵敏度、用户饱和度，以及使用 `bpftrace`、`iostat` 和蒸馏 `fio` 工作负载进行的 Linux I/O 性能分析。

最重要的结果是：**工作负载形态主导了 SSD 需求**。合成长上下文工作负载会创建较大的 KV cache 对象，并能找到失效边界。ShareGPT 对于聊天场景是现实的，但其上下文较小且缓存局部性非常高，因此对 SSD 而言是轻量级工作负载。BurstGPT 配合 `--trace-speedup 1000` 和 `--cpu-mem-gb 0` 是目前最佳的生产追踪 SSD 基线：它将所有 KV I/O 推向存储，同时保留了生产环境的请求/令牌分布。

当前基线结论：

- 合成 `llama3.1-8b`，TP8，CPU 缓存 0.5GB，300 秒：最大稳定并发度为 `users=2`；`users=3` 是第一个明显失效点。
- ShareGPT `llama3.1-8b`，TP8，CPU 缓存 0.5GB，`users=2`，300 秒：以较大余量通过，但存储压力较轻。
- BurstGPT `llama3.1-8b`，TP8，CPU 缓存 0GB，`--trace-speedup 1000`，300 秒：`users=8` 仍通过；SSD 利用率有意义但未饱和。
- BurstGPT `llama3.1-70b-instruct`，TP8，CPU 缓存 0GB，`users=2`，300 秒：通过。这是第一个较大模型的验证点，应进一步扩展。

### 相关产物

以下产物与本报告一同发布在仓库中。尽管 `results/` 目录大部分被 `.gitignore` 排除，它们被有意追踪：

| 产物 | 追踪原因 |
|---|---|
| [`docs/kvcache-io-profiling-visual-analysis-2026-06-08.md`](../kvcache-io-profiling-visual-analysis-2026-06-08.md) 及 `docs/assets/kvcache-io-profiling/*` | 最终 I/O 性能分析报告 + 5 张图表 (PNG/SVG) + 3 个蒸馏 CSV。此为 burstgpt 阶段后的视图。 |
| [`../results/kvcache-profile/report/kvcache_ai_ssd_baseline_report.pdf`](../results/kvcache-profile/report/kvcache_ai_ssd_baseline_report.pdf) (及 `.html`, `.md`) | 早期 `users=10` 基线，生成于 2026-06-07 15:39。该次运行**失败**（`Storage I/O P95 ≈ 19.6 s`，`read device P95 ≈ 3.2 s`，仅 1/4 标准通过），并促使了 TP + 并发度重构，最终得出上述稳定的 `users=2` 基线。作为历史参考有用；已被当前报告取代。 |
| [`../results/kvcache-profile/report/`](../results/kvcache-profile/report/) (早期基线运行的 PNG/SVG/CSV 图表) | 早期 `users=10` 基线报告的配套图表。 |
| [`../results/kvcache-profile/visualizations/kvcache_io_profile_visual_summary.xlsx`](../results/kvcache-profile/visualizations/kvcache_io_profile_visual_summary.xlsx) | 配套 Excel 文件，将可视化分析图表整理至单个工作簿。 |

## KV Cache 为何给存储带来压力

LLM 推理将注意力状态存储在 KV cache 中。cache 随序列长度增长。上下文 token 越多的请求会写入更大的 KV 对象；解码阶段随后在生成输出 token 时重复读取该对象。

在此基准测试中，每个 KV cache 条目存储为一个 `.npy` 对象。基准中的存储延迟数值是**每个 KV 对象**的延迟，而非每个 4KiB 磁盘页面的延迟。单个对象的大小可以从数十 MiB 到数个 GiB 不等，具体取决于模型、序列长度和张量并行度。随后 Linux 块层将该对象拆分为许多较小的 NVMe 命令，通常以 128KiB 请求为主。

这一区别解释了主要观察结果：

- NVMe 命令延迟可以非常低，例如 D2C 读 P99 低于 1ms。
- KV 对象延迟仍可能达到数十或数百毫秒，因为它包含多个块 I/O 操作以及文件系统、VFS、Python 和 NumPy 对象处理的开销。

## 关键术语

- KV cache：LLM 推理期间保存的 Key/Value 注意力状态，以避免重新计算之前的 token。
- Prefill（预填充阶段）：处理用户提示的阶段。写密集，因为它创建新的 KV cache 条目。
- Decode（解码阶段）：生成 token 的阶段。读密集，因为它重复读取已有的 KV cache 条目。
- TP / 张量并行：将模型张量分配到多个 rank 上。在此基准中，TP 划分了每个 rank 的 KV 对象大小。TP8 使每个 rank 的 KV 对象大小约为 TP1 的八分之一。
- CPU cache：DRAM 溢出层。更大的 CPU cache 可以隐藏 SSD 压力。
- Storage tier（存储层）：通过 `--cache-dir` 传递的文件系统路径。文档称之为 NVMe，但可以是任何已挂载的存储设备。
- 基准测试中的 Device P95：每个 KV 对象的"设备"计时，而非纯 NVMe 控制器延迟。对于读取，它包括 `np.load()` 和文件 I/O。对于写入，它包括刷新和 `fsync()`。
- D2C：bpftrace 中的设备到完成延迟。更接近实际每命令块设备延迟。
- Q2D：Linux I/O 调度器中的队列到分发延迟。
- VFS latency：应用程序可见的文件系统系统调用延迟。
- bssplit：fio 使用的块大小分布。在这些测试中，128KiB 主导了大多数实际存储流量。

## 测试矩阵汇总

| 测试用例（Case） | 状态（Status） | 请求数（Requests） | tok/s | req/s | 存储 IO P95 (ms) | 读取设备 P95 (ms) | 写入设备 P95 (ms) | 存储读取 (GiB) | 存储写入 (GiB) | 命中率（Hit rate） |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Synthetic baseline TP1 users10 | FAIL | 125 | 217.62 | 1.04 | 19635.46 | 3167.48 | 924.69 | 334.99 | 13.12 | 72.79 |
| Synthetic TP8 users4 clean 120s | PASS | 648 | 1356.02 | 5.40 | 902.16 | 163.66 | n/a | 71.34 | 0.00 | 78.98 |
| Synthetic TP8 CPU0.5 users4 300s | FAIL | 1290 | 1100.78 | 4.30 | 1500.16 | 233.84 | n/a | 328.00 | 0.00 | 79.32 |
| Synthetic TP8 CPU0.5 users1 300s | PASS | 438 | 437.10 | 1.46 | 823.67 | 74.33 | n/a | 156.51 | 0.00 | 76.80 |
| Synthetic TP8 CPU0.5 users2 300s | PASS | 1137 | 755.96 | 3.79 | 771.46 | 198.74 | 116.44 | 140.78 | 0.20 | 81.39 |
| Synthetic TP8 CPU0.5 users3 300s | FAIL | 1051 | 684.73 | 3.50 | 1452.01 | 255.07 | 141.83 | 253.49 | 0.25 | 73.29 |
| Synthetic TP8 CPU0.5 users4 300s | FAIL | 1104 | 953.49 | 3.68 | 2151.83 | 277.23 | n/a | 322.02 | 0.00 | 76.51 |
| ShareGPT io trace users2 | PASS | 11185 | 11531.07 | 37.14 | 0.00 | 0.00 | n/a | 203.14 | 0.00 | 98.20 |
| ShareGPT real IO users2 | PASS | 1724 | 1510.56 | 5.74 | 937.41 | 62.47 | n/a | 9.79 | 0.00 | 97.74 |
| ShareGPT profile users2 | PASS | 1678 | 1460.33 | 5.58 | 927.11 | 67.56 | n/a | 9.10 | 0.00 | 97.91 |
| BurstGPT sparse profile CPU0.5 users2 | PASS | 8 | 12.79 | 0.03 | 23.45 | n/a | n/a | 0.00 | 0.00 | 97.78 |
| BurstGPT speedup1000 CPU0.5 users2 | PASS | 9263 | 7418.91 | 30.88 | 33.50 | n/a | n/a | 0.00 | 0.00 | 97.79 |
| BurstGPT speedup1000 CPU0 users2 | PASS | 6515 | 5239.66 | 21.72 | 230.56 | 12.62 | 9.18 | 692.68 | 59.78 | 97.77 |
| BurstGPT speedup1000 CPU0 profile users2 | PASS | 5748 | 4632.68 | 19.16 | 282.58 | 17.96 | 18.90 | 614.97 | 52.48 | 97.75 |
| BurstGPT speedup1000 CPU0 users4 | PASS | 7118 | 5685.54 | 23.73 | 451.45 | 31.54 | 55.64 | 754.29 | 65.63 | 97.74 |
| BurstGPT speedup1000 CPU0 users6 | PASS | 7056 | 5631.62 | 23.52 | 647.24 | 41.54 | 114.54 | 756.74 | 65.52 | 97.73 |
| BurstGPT speedup1000 CPU0 users8 | PASS | 7339 | 5859.44 | 24.46 | 705.99 | 46.48 | 118.44 | 781.09 | 67.74 | 97.77 |
| BurstGPT 70B speedup1000 CPU0 users2 | PASS | 2421 | 1975.81 | 8.07 | 815.83 | 41.85 | 18.68 | 648.39 | 55.06 | 97.86 |

## 合成工作负载发现

合成测试的优势在于可以刻意制造高压力。虽然它们不太能代表正常聊天流量，但却是找到失效边界的最佳方法。

初始的 TP1、users=10 运行严重失败：

- 存储读取设备 P95：3167.48ms。
- 存储写入设备 P95：924.69ms。
- 存储 I/O P95：19635.46ms。

这对本地 PC 来说并非合理的配置目标。KV 对象过大。

TP 缩放是最有力的改进手段。切换至 TP8 减少了每个 rank 的对象大小，使读取延迟接近或低于 200ms 目标。然而，300 秒测试表明，短时间运行可能具有误导性。TP8、CPU0.5GB、users=4 在部分短时测试中通过，但在 300 秒稳态下失败：

- 存储读取设备 P95：233.84ms。
- 存储 I/O P95：1500.16ms。

最终的合成并发边界是：

- users=1：以较大余量通过。
- users=2：通过，经三次重复 300 秒运行确认。
- users=3：失败。
- users=4：失败。

因此，对于合成长上下文压力，当前系统基线为：

```text
model: llama3.1-8b
TP: 8
CPU cache: 0.5GB
duration: 300s
maximum stable concurrency: users=2
first failure point: users=3
```

## ShareGPT 发现

ShareGPT 提供了真实的对话结构。它适用于检查实际的聊天行为，而非最坏情况下的 SSD 压力。

逻辑追踪运行产生了 127,477 次 KV 操作，显示出非常高的局部性：

- 缓存命中率：98.20%。
- 平均 KV 块大小：约 2.1MiB。
- P95 KV 块大小：约 12.5MiB。
- 最大 KV 块大小：约 113.6MiB。

实际 I/O 基线和性能分析运行均以较大余量通过：

- 存储读取设备 P95：62.47ms 至 67.56ms。
- 存储读取总延迟 P95：约 100ms 至 109ms。
- 存储读取量：300 秒内约 9GiB 至 10GiB。

bpftrace/iostat 性能分析确认 SSD 未饱和：

- D2C 读 P99：128us。
- D2C 写 P99：4096us。
- iostat r_await P95：1.5ms。
- iostat w_await P95：2.6ms。
- 设备利用率 P95：8.0%。

解读：ShareGPT 是一个好的"真实聊天轻松通过"测试，但不应用于单独的 AI SSD 产品认证，因为它通过小对象和高缓存局部性隐藏了存储压力。

## BurstGPT 发现

第一个未使用加速的 BurstGPT 运行过于稀疏：

- 300 秒内仅完成 8 个请求。
- 未记录任何存储层的读取或写入。

添加 `--trace-speedup 1000` 后，请求密度变得可用。当 CPU 缓存仍启用时，工作集留在 CPU 内存中，未测试 SSD。设置 `--cpu-mem-gb 0` 强制所有 KV I/O 落到存储，产生了有效的存储工作负载。

关键的 BurstGPT 配置为：

```text
model: llama3.1-8b
TP: 8
CPU cache: 0GB
users: 2
duration: 300s
trace-speedup: 1000
```

此运行通过：

- 存储读取设备 P95：17.96ms。
- 存储写入设备 P95：18.90ms。
- 存储读取：614.97GiB。
- 存储写入：52.48GiB。
- 来自 fio 蒸馏器的读混合比例：91%。

块层性能分析显示：

- 总计追踪 I/O：5,856,651。
- D2C 读 P99：256us。
- D2C 写 P99：4096us。
- 读取块大小：128KiB 占 92%。
- 写入块大小：128KiB 占 94%。

活动设备 `nvme1n1` 的 iostat 显示：

- 读取 IOPS 平均：17,694。
- 读取 IOPS P95：25,449。
- 读取带宽平均：约 2.04GiB/s。
- 读取带宽 P95：约 2.96GiB/s。
- 写入带宽平均：约 203MiB/s。
- 写入带宽 P95：约 303MiB/s。
- r_await P95：0.16ms。
- w_await P95：6.6ms。
- 利用率平均：55.0%。
- 利用率 P95：69.2%。

在 CPU0、TP8、speedup1000 配置下，users 梯度在 users=8 时仍保持通过：

- users=2：读设备 P95 12.62ms，写设备 P95 9.18ms。
- users=4：读设备 P95 31.54ms，写设备 P95 55.64ms。
- users=6：读设备 P95 41.54ms，写设备 P95 114.54ms。
- users=8：读设备 P95 46.48ms，写设备 P95 118.44ms。

这是最强有力的证据，表明当前存储在生产类 API 追踪且 KV 对象经 TP8 分片后仍具有充裕的余量。

## 更大模型探针

首次 `llama3.1-70b-instruct` 的 BurstGPT 运行旨在增加每 token 的 KV 字节数：

```text
model: llama3.1-70b-instruct
TP: 8
CPU cache: 0GB
users: 2
duration: 300s
trace-speedup: 1000
```

此运行通过：

- 请求数：2421。
- 吞吐量：1975.81 tokens/s。
- 存储 I/O P95：815.83ms。
- 存储读取设备 P95：41.85ms。
- 存储写入设备 P95：18.68ms。
- 存储读取：648.39GiB。
- 存储写入：55.06GiB。

这应以 users=4、users=6 和 users=8 进一步扩展。它对于 AI SSD 产品定位比单独 8B 更相关，因为每 token 的 KV cache 更大。

## 产品解读

对于 AI SSD 预研，不应仅使用单一工作负载评估存储产品。需要三类工作负载：

- 合成工作负载：发现最坏情况下的对象大小和并发限制。
- ShareGPT：证明实际聊天场景轻松通过，并验证完整流水线。
- BurstGPT：提供生产类 API 追踪行为，及更好的 SSD 利用率。

当前数据表明：

- 本地 SSD 不受限于单次 NVMe 命令延迟。在有效的配置下，D2C 读 P99 通常为数百微秒。
- 合成失败的根源是对象级别的 KV cache 延迟和主机路径聚合，而非原始的 4KiB/128KiB NVMe 命令延迟。
- TP 是一阶调优旋钮，因为它减少了每个 rank 的 KV 对象大小。
- CPU cache 可以完全隐藏 SSD 流量。对于 SSD 产品测试，CPU cache 应设为 0 或严格受限。
- ShareGPT 应报告为实际聊天验证，而非最大 SSD 压力。
- BurstGPT CPU0 speedup1000 当前是最佳的可重复产品基线。

## 推荐的下一步测试

在得出最终产品级结论之前运行以下测试：

1. BurstGPT 70B 用户梯度：users=4、6、8。
2. 使用 bpftrace 和 iostat 分析 70B 梯度中最终通过点和首个失败点。
3. 至少对 BurstGPT CPU0 和合成 users=2/3 测试添加 SSD 预条件化。
4. 针对 BurstGPT CPU0 运行仅 prefill 和仅 decode 模式，以分离写入和读取行为。
5. 将蒸馏后的 fio 配置转换为受控的 fio 扫描，使用实际的 iodepth 值（如 32、64、128 和 256）。不要盲目使用生成的 iodepth 值（如 524288）。

## 可复现性说明

重要的本地输出文件有意未添加到 Git：

- `results/kvcache-profile/*.json`
- `results/kvcache-profile/*.xlsx`
- `results/kvcache-profile/bpftrace*.txt`
- `results/kvcache-profile/iostat*.txt`
- `results/kvcache-profile/fio*.ini`
- `datasets/`

原始 bpftrace 文件体积较大，部分文件约 1.2GiB 每个。它们在本地有用，但不应上传至仓库。本报告包含审查所需的蒸馏结果。

## 对话记录摘要

本节将工作对话导出为紧凑的时间线。

1. 该项目被检查为 LLM 推理存储卸载的 MLPerf Storage KV cache 基准测试。
2. 首次运行因 `/mnt/ai-ssd` 不可写而失败。缓存目录移至项目本地的结果路径。
3. 初始 users=10 合成运行显示内存风险和高存储延迟。
4. bpftrace 设置最初因 sudo 需要终端而失败；使用了独立的 bpftrace 命令。
5. 运行了合成基线、仅 prefill、仅 decode、用户梯度、TP 梯度和 CPU 缓存梯度。
6. 关键的合成发现是：TP8 可减少对象大小，且 TP8 CPU0.5 users=2 是稳定的 300 秒边界。
7. 磁盘空间因原始缓存目录和 `/tmp` 追踪文件而耗尽。缓存目录被清理，后续命令使用了项目本地路径。
8. 之前讨论了报告/PDF 工作流；较后的重点转向了 I/O 性能分析和生产追踪工作流。
9. 增加了 ShareGPT 数据集回放。io-trace 模式生成了紧凑的逻辑追踪；实际 I/O 和性能分析运行显示了高缓存局部性和较轻的 SSD 压力。
10. 增加了 BurstGPT。初始运行过于稀疏，因此引入了 `--trace-speedup 1000`。
11. BurstGPT 在 CPU 缓存 0.5GB 时未触碰存储；CPU 缓存设为 0 以强制 SSD 流量。
12. BurstGPT CPU0 speedup1000 产生了最佳的生产类 SSD 基线，并使用 bpftrace 和 iostat 进行了分析。
13. 用户随后请求更大模型；首次 70B BurstGPT CPU0 users=2 运行完成并通过。
14. 本文档旨在保存实验历史、结论和后续步骤，同时将较大的本地产物排除在 Git 之外。
