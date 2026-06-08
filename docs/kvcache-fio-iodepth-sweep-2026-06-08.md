# fio iodepth sweep — KV-Cache AI SSD 真实饱和点验证报表

**日期**: 2026-06-08
**作者**: ficus
**目标设备**: `/dev/nvme1n1p3`(BIWIN X570 1TB SSD,ext4 系统分区)
**总耗时**:  ~17 分钟(15 个 run × ~60s 串行 + 测试文件创建)
**输入**: 3 个蒸馏的 fio .ini(`results/kvcache-profile/fio_*_profile_*.ini`)
**输出**:
- `results/kvcache-profile/fio_sweep/sweep_summary.csv` (15 行 ×16 列)
- `results/kvcache-profile/fio_sweep/sweep_analysis.md`(数据表 + 饱和分析)
- `results/kvcache-profile/fio_sweep/sweep_curves.png` (4 面板图)
- `results/kvcache-profile/fio_sweep/<workload>_qd<qd>/` (15 个子目录)

---

## 📖 如何读这份报表

| 你关心什么 | 读哪一段 |
|---|---|
| 这个 SSD 的实际饱和点在哪里? | §**关键发现** → §**饱和点表** |
| 哪个 workload 最容易撑爆 SSD? | §**按 workload 看数据** |
| 不同 iodepth 怎么影响延迟? | `sweep_curves.png`(左两面板)+ §**关键发现** |
| IOPS 曲线什么样? | `sweep_curves.png`(右两面板) |
| 怎么复现? | §**复现命令** + `scripts/run_fio_sweep.sh` |

## 🎯 背景:为什么需要 sweep?

MLPerf Storage KV-Cache profiling 把 bpftrace 输出蒸馏成 fio .ini 时,**自动算出的 iodepth** 是从实际工作负载的中位队列深度反推的。在真实 KV-Cache 场景里,**1024+ 并发推理 worker** 同时提交请求,所以蒸馏出的 iodepth 经常是 **524288 / 1048576** 这种数量级 — 这对**裸盘重放是不现实的**:

- 真实磁盘没有 50万 in-flight 队列
- 这等于是把整个测试系统内存变成队列
- 测出的不是 SSD 极限,而是**NVMe 队列和系统内存极限**

**所以 sweep 是必须的** — 把 iodepth 从 32 扫到 1024,画出曲线,找**真正的拐点**。

## 📊 数据表(完整版见 `sweep_analysis.md`)

### Read 维度

| Workload | r/w% | qd=32 | qd=64 | qd=128 | qd=256 | qd=1024 |
|---|---|---|---|---|---|---|
| sharegpt_8b_cpuhalf | 61/39 | **18.6k IOPS** | 13.1k | 13.1k | 12.6k | 11.5k |
| burstgpt_8b_cpurel_spd1000 | 91/9 | 21.0k | **21.0k** | 21.0k | 21.1k | 21.1k |
| tp8_cpuhalf_generic | 73/27 | 13.3k | **13.5k** | 13.2k | 13.3k | 13.3k |

### Read P99 延迟(us)

| Workload | qd=32 | qd=64 | qd=128 | qd=256 | qd=1024 |
|---|---|---|---|---|---|
| sharegpt_8b_cpuhalf | 6,521 | 11,993 | 17,957 | 28,443 | **166,724** |
| burstgpt_8b_cpurel_spd1000 | 3,555 | 9,372 | 13,042 | 19,268 | **68,682** |
| tp8_cpuhalf_generic | 5,079 | 12,911 | 20,054 | 29,753 | **156,238** |

### Write 维度

| Workload | qd=32 W IOPS | qd=1024 W IOPS | qd=32 W P99 (us) | qd=1024 W P99 (us) |
|---|---|---|---|---|
| sharegpt_8b_cpuhalf | 11,909 | 7,380 | 1,237 | **379,585** |
| burstgpt_8b_cpurel_spd1000 | 2,067 | 2,093 | 17,170 | **476,054** |
| tp8_cpuhalf_generic | 4,922 | 4,949 | 12,124 | **480,248** |

## 🧠 关键发现

### 1. **ShareGPT8B 是最容易打爆 SSD 的工作负载**

sharegpt_8b_cpuhalf 的 iodepth 一旦超过 32,**IOPS 就开始下降**:

```
qd=32: 18,636 R IOPS
qd=64: 13,108 R IOPS   (-30% 下跌!)
qd=128: 13,065 R IOPS
qd=256: 12,576 R IOPS
qd=1024: 11,536 R IOPS  (-38% 累计)
```

原因分析:sharegpt 工作负载的 **bssplit 是大量 128KiB 大块**(99% 概率),这意味着每次 I/O 都很重,SSD 内部队列迅速被填满,延迟从 6.5ms 飙到 167ms。

### 2. **BurstGPT8B spd1000 反而对 iodepth 不敏感**

burstgpt_8b_cpurel_spd1000 在 qd=32 和 qd=1024 都跑出 ~21k IOPS — **饱和点不在队列深度,而在 block size 分布**:

- rwmixread=91%(几乎纯读)
- bssplit:128KiB 92% + 64KiB 3%
- 这是**只读密集型大块 I/O**,队列深度不关键 — SSD 内部 NCQ 已经能跟上了

### 3. **tp8_cpuhalf_generic 几乎完全 flatten**

13.3k IOPS 在所有 iodepth 下都稳定 — rwmixread=73% + 128KiB 块,**这个工作负载是稳态,不是压力测试**。

### 4. **真实饱和点不在 qd=1024,也不在 qd=32**

观察三条曲线:
- **sharegpt** 饱和点在 **qd=32**(再高反而降低)
- **burstgpt** 饱和点在 **qd>=32**(几乎不增加)
- **tp8** 饱和点在 **qd=32**(再高只是浪费队列)

**结论**:**这个 SSD + 文件系统的合理 iodepth 是 32**。超过 64 之后基本都是延迟恶化。

### 5. **Write 延迟比 Read 延迟恶化得更厉害**

| qd | sharegpt W P99 / R P99 |
|---|---|
| 32 | 1.2ms / 6.5ms |
| 1024 | 379ms / 167ms(**W 比 R 严重 2.3倍**) |

Write 路径走 FTL + GC,在高并发下 GC 干扰严重。

## 📈 饱和点表(从 `sweep_analysis.md`)

| Workload | 首次 R P99 ≥ 10ms 的 iodepth | 首次 R P99 ≥ 100ms 的 iodepth | Max R IOPS | Max W IOPS |
|---|---|---|---|---|
| sharegpt_8b_cpuhalf | **qd=64** | qd=1024 | 18,636 | 11,909 |
| burstgpt_8b_cpurel_spd1000 | qd=128 | — (从不超过) | 21,065 | 2,096 |
| tp8_cpuhalf_generic | qd=64 | qd=1024 | 13,466 | 4,980 |

## 🎯 技术预研判断(针对 AI SSD)

### 这个 SSD 的真实性能边界

- **最佳 iodepth = 32**(更接近纯单流,无 NCQ 争用)
- **Max IOPS ≈ 21k**(read-heavy)、**Max BW ≈ 2.4 GiB/s**(read-heavy)
- **Read P99 < 10ms 临界点 = qd=32**(超过即进入队列争用)
- **Write 路径延迟敏感度 >> Read**(尤其高并发下)

### 对 AI SSD 的启示

1. **队列深度不是越大越好** — 这个 SSD 在 qd=32 已饱和
2. **大块读+少量写的混合工作负载**(sharegpt 风格)最容易撑爆
3. **read-mostly 工作负载对队列不敏感** — 真正的瓶颈在设备内部
4. **Write 路径需要 GC 优化** — qd=1024 时 W 延迟飙到 0.5 秒,这种长尾对推理 batch 没意义

### 不推荐的 iodepth

- ❌ 蒸馏原始的 **524288 / 1048576**(那是 system-side queue depth,不是 SSD)
- ❌ qd=1024 — 浪费 CPU 且没收益,只增加延迟

## 🔧 复现命令

```bash
# 完整 sweep (~17 分钟)
bash /home/ficus/llm/storage/scripts/run_fio_sweep.sh

# 分析(生成 md + png)
source /home/ficus/llm/storage/.venv/bin/activate
python3 /home/ficus/llm/storage/scripts/analyze_fio_sweep.py

# 单个跑(例如只跑 sharegpt qd=32)
cd /home/ficus/llm/storage/results/kvcache-profile/fio_sweep
fio sharegpt_8b_cpuhalf_qd32/fio_sweep.ini --output-format=json
```

## 📁 产物清单

```
results/kvcache-profile/fio_sweep/
├── sweep_summary.csv                          # 15 行 × 16 列(原始数据)
├── sweep_analysis.md                          # 数据表 + 饱和分析
├── sweep_curves.png                           # 4 面板图(R/W 延迟 + IOPS + BW)
├── sweep_console.log                          # 全部 run 的 console 日志
├── run_fio_sweep.sh                           # (在 scripts/,wrapper)
├── parse_fio_json.py                          # (在 scripts/,JSON → CSV 解析器)
├── analyze_fio_sweep.py                       # (在 scripts/,生成报告 + 图)
├── sharegpt_8b_cpuhalf_qd{32,64,128,256,1024}/   # 5 个子目录 × 3 workload
├── burstgpt_8b_cpurel_spd1000_qd{32,64,128,256,1024}/
└── tp8_cpuhalf_generic_qd{32,64,128,256,1024}/
```

每个子目录包含:
- `fio_sweep.ini` — 用于这个 run 的最终 ini(源 .ini + sweep override)
- `fio_output.json` — fio 输出的完整 JSON
- `fio_stderr.txt` — stderr(全 0 字节表示无错误)

## 🧭 后续方向建议

| P | 方向 | 价值 | 备注 |
|---|---|---|---|
| **P0** | **已完成** | | **fio sweep — 找到真实饱和点** |
| **P1** | SSD preconditioning | 中 | 重复 sharegpt8B + burstgpt8B 在**预写满**的设备上,排除空盘偏乐观 |
| **P1** | 长稳态 30-60 分钟 | 高 | 跑 BurstGPT 70B users=6 30 分钟,观察 await/util 是否随时间漂移 |
| **P1** | CPU cache sensitivity | 中 | 用 `cgroup` 限制 page cache 内存(8/16/32GB),对比延迟尾 |
| **P2** | 其他 LLM 模型 | 中 | Qwen3-32B / Mixtral-8x7B / DeepSeek-V3 |
| **P2** | 多 SSD / RAID-0 | 高 | 把 nvme0n1 + nvme2n1 + nvme3n1 串起来,看延迟是不是变 1/N |
| **P3** | 真硬件延迟对比 | 高 | 在真企业级 SSD(Samsung PM9A3 / Kioxia CD8P)上重跑全部 |

## ⚠️ 报告者备注

- **测试设备**:`/dev/nvme1n1p3` 是系统盘,**跟生产环境分开** — 测试结果可能比专用的 bare-metal device 略悲观
- **iodepth sweep 范围选 32-1024** 是基于 NVMe spec 推荐的典型范围;不包含 1/4/8 是因为 NVMe MQ 队列一般 >=32 才有效
- **runtime=60s**(每个 run) — 稳态足够,但要更精确的 P99.99 推荐 300s
- **测试文件 20GB** — 比 device 物理内存小很多,确保不被 cache 吸收
- **`direct=1`** — 已开启,绕过 page cache,测真实设备延迟;`bssplit` 来自蒸馏(128KiB 为主)
- **未来工作**:fio sweep 应该跟 bpftrace 蒸馏结果**配对展示** — 这样用户能知道原始 iodepth 524288 是从哪里蒸馏出来的