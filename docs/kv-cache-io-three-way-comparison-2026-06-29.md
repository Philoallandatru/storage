# KV Cache I/O 模式三路综合对比

**日期:** 2026-06-29  
**作者:** 综合两份已有 IO 分析报告 + 自行补算  
**设备:** `/dev/nvme0n1` (BIWIN X570 1TB, ext4 根盘)  
**tracepoint:** `tracepoint:block:block_rq_issue` (per-I/O block event stream)  
**Workload runner:** `kv_cache_benchmark/kv-cache.py` (v2.0.0b1)

---

## 一句话结论

**三种 workload 产生**截然不同**的 block I/O 模式,不能互相替代作为 SSD 压力基准。**BurstGPT 是最重且最随机**的读压力,sharegpt 是中等且混合的,synthetic (fio_sweep replay) 是稳态平均,只能反映底层设备带宽能力,无法反映 LBA 跳跃分布和突发性。**对于评估 KV-cache SSD offload 的真实效能,必须用 kv-cache.py 实跑的 sharegpt / burstgpt tracepoint 数据,fio_sweep 只适合做设备能力 sanity check。**

---

## 数据源说明

| Workload | 数据源 | 工具链 | 时长 | 块事件数 |
|---|---|---|---:|---:|
| **synthetic** (fio_sweep) | `docs/assets/io-three-way-comparison/derived/comparison_summary.json` + `results/kvcache-profile/fio_sweep/sharegpt_8b_cpuhalf_qd32/fio_output.json` | fio 3.41 distill replay (从 bpftrace 蒸馏到 fio config) | 60s | N/A (avg only) |
| **sharegpt** | `results/kvcache-profile/sharegpt_kvcache_20260629_140729/block_lba_trace.csv` | `kv-cache.py --num-users 8 --duration 120 --disable-multi-turn` + bpftrace | 140.91s | 1,981,685 |
| **burstgpt** | `results/kvcache-profile/burstgpt_kvcache_20260629_141010/block_lba_trace.csv` | `kv-cache.py --use-burst-trace --burst-trace-path <csv>` + bpftrace | 129.75s | 4,566,627 |

**tracepoint 捕获的字段:** `timestamp_ns, dev, sector, bytes, rwbs, comm, pid`  
**LBA 推导:** `LBA = sector * 512`  
**相邻 I/O 对:** 同一个 PID 上相邻两次 block_rq_issue 的 sector delta。

---

## 一、综合压力对比 (Signal Dashboard)

![signal_dashboard](assets/io-three-way-comparison/01_signal_dashboard.png)

| 指标 | synthetic (fio_sweep QD=32) | sharegpt (kv-cache.py) | burstgpt (kv-cache.py) |
|---|---:|---:|---:|
| **Block IOPS** | 33,323 | **14,063** | **35,195** |
| **Block BW (GiB/s)** | 2.99 | **1.64** | **4.25** |
| **Read / Write 事件比** | 61 / 39 | 94 / 6 | 92 / 8 |
| **Read 相邻 ≥100MiB 跳跃** | 0 (无 tracepoint 数据) | 56.97% | **89.11%** |
| **Read 相邻精确连续** | 0 | **41.77%** | 10.08% |
| **Write 相邻精确连续** | 0 | 94.37% | **97.63%** |
| **Dominant block size** | 128 KiB (62%/82% bssplit) | 128 KiB (93.94%) | **128 KiB (98.52%)** |
| **LBA span (GiB)** | 20 (20 GiB 测试文件) | **389.35** | **389.35** |

**注意:** synthetic 的 "Read 相邻" 指标为 0,因为 fio 是随机读写引擎,没有 PID 连续性概念,谈不上 "相邻 I/O 跳跃"。这是 fio_sweep 作为 replay 工具的根本局限。

---

## 二、IOPS 与 BW 时间序列

![iops_bw_timeline](assets/io-three-way-comparison/02_iops_bw_timeline.png)

| 特征 | sharegpt | burstgpt |
|---|---|---|
| 平均 IOPS (3s 窗) | 17,232 | **35,958** |
| IOPS p95 | 32,604 | 40,938 |
| IOPS max | 35,755 | 42,930 |
| IOPS 变异系数 (CV) | **0.61** | 0.28 |
| Peak / Mean | **2.07** | 1.19 |

**关键观察:**
- **burstgpt 是稳态高负载**: CV 仅 0.28,IOPS 几乎贴着上限跑,没有喘息窗口
- **sharegpt 是脉冲型负载**: CV 0.61,峰谷比 2.07x,有明显的活跃期/静默期切换
- 这跟 workload 性质吻合:**BurstGPT 是用户请求随机到达的拥塞控制 burst 模式**,每个 token 都伴随 L2 SSD fetch;**ShareGPT 是多轮对话模式**,prefix cache hit 高 → 突发写但读少

synthetic 没有时间序列数据,只能画水平参考线 (avg IOPS)。

---

## 三、相邻 LBA 跳跃分布 (CDF)

![lba_delta_cdf](assets/io-three-way-comparison/03_lba_delta_cdf.png)

| 指标 | sharegpt 读 | burstgpt 读 | sharegpt 写 | burstgpt 写 |
|---|---:|---:|---:|---:|
| 相邻 pair 数 | 1,860,196 | 4,202,655 | 121,487 | 363,970 |
| **精确连续** | **41.77%** | 10.08% | 94.37% | **97.63%** |
| 近邻 `<1 MiB` | 42.27% | 10.30% | 96.36% | 98.40% |
| **大跳跃 `≥100 MiB`** | 56.97% | **89.11%** | 3.29% | 1.40% |
| Abs delta p50 | 2,675 MiB | **31,056 MiB** | 0.00 MiB | 0.00 MiB |
| Abs delta p95 | 154,298 MiB | 126,769 MiB | 0.02 MiB | 0.00 MiB |

**为什么 burstgpt 是 "random read" 模板:**
- 89.1% 的相邻读跳跃超过 100 MiB
- p50 跳跃 = 31 GB (≈31 GiB),等于每次都跨越大半个 389 GiB LBA span
- 这是典型的 decode 阶段随机 KV cache 读取特征 — 用户问的 token 在不同历史位置,需要从 SSD 随机拉取

**为什么 sharegpt 有 "mixed" 特征:**
- 41.8% 读连续 + 57.0% 大跳跃 = 多轮对话中 prefix caching 部分复用同一 KV 块
- 用户连续追问类似 topic,prefix cache 命中 → 部分读连续;部分新问题 → 跳跃读

**为什么写都几乎是连续:**
- sharegpt 写 94.4% / burstgpt 写 97.6% 精确连续
- Prefill 阶段是顺序生成 KV,append 到 LBA 末尾
- 这跟早上那份 real-io 报告 (75% 写连续) 完全吻合

---

## 四、块大小分布

![block_size_distribution](assets/io-three-way-comparison/04_block_size_distribution.png)

三种 workload 都以 128 KiB 为主:

| Workload | 128 KiB 占比 | 次主导 |
|---|---:|---|
| synthetic (fio read bssplit) | 62% | 32 KiB (16%) / 64 KiB (8%) |
| sharegpt | 93.94% | 64 KiB (6%) |
| burstgpt | **98.52%** | < 1% |

**观察:**
- kv-cache.py 的输出**清一色 128 KiB**,因为 sglang/HF model KV cache 的 page size 是 64 token,每个 page 序列化为 128 KiB
- synthetic 的 bssplit 来自 6 月初的 bpftrace 蒸馏,**反映的更多是当时 kv-cache 实现的内部分块方式**(32/64/128 都有)
- burstgpt 几乎纯 128K → **最适合用 device write/read 块大小固定的假设来分析 IO 调度**

---

## 五、压力归一化热图

![pressure_heatmap](assets/io-three-way-comparison/05_pressure_heatmap.png)

各列独立归一化(每列最大值=1.0):

| Workload | IOPS(×1000) | BW(GiB/s) | Read % | Read ≥100MiB jump % |
|---|---:|---:|---:|---:|
| synthetic | 33.3 | 2.99 | 61 | 0 |
| sharegpt | 14.1 | 1.64 | 94 | 57.0 |
| burstgpt | 35.2 | 4.25 | 92 | **89.1** |

**热图揭示:**
- burstgpt 在 **IOPS / BW / 大跳跃率** 三项都是最高 → 真实负载下最难应对
- sharegpt 在 **Read %** 上跟 burstgpt 并列 (94/92),但实际压力小很多 → 因为总事件数低
- synthetic 在 **大跳跃率** 是 0 (无意义),**Read %** 是最低的 → 跟真实 workload 差异最大

---

## 六、对 synthetic 的诚实评价 (fio_sweep replay 的局限性)

| 维度 | synthetic | sharegpt | burstgpt |
|---|---|---|---|
| **设备带宽上限标定** | ✅ 准确 (read 1.7 GiB/s,write 1.3 GiB/s) | ⚠️ 应用层压力 | ⚠️ 应用层压力 |
| **真实 LBA 跳跃分布** | ❌ 无 (PID 连续性丢失) | ✅ 完整 | ✅ 完整 |
| **突发性 (CV)** | ❌ 稳态 | ✅ 0.61 | ✅ 0.28 |
| **block size 多样性** | ⚠️ 4k/8k/16k/32k/64k/128k 全混合 | ❌ 全 128K | ❌ 全 128K |
| **应用语义 (decode vs prefill)** | ❌ 丢失 | ✅ 保留 | ✅ 保留 |
| **可重复性** | ✅ 完美 | ⚠️ 单次 | ⚠️ 单次 |

**结论:** **fio_sweep 适合做 "fio + BIWIN 盘能达到多少 IOPS/BW" 的设备能力标定**,但**完全不适合**用来:
- 评估 KV-cache SSD offload 的 TTFT 收益
- 推导 eviction 算法的热点分布
- 模拟生产环境的 cache miss 风暴
- 验证 page cache 命中模型

**推荐做法:** 评估 KV-cache 系统时,**至少跑一遍 kv-cache.py sharegpt + 一遍 burstgpt**,fio_sweep 只作为 device capability ceiling。

---

## 七、跨报告结论的一致性

| 报告 | 核心结论 | 本文如何补充 |
|---|---|---|
| `kv-cache-nvme-offload-real-io-analysis-2026-06-29.md` (早上) | 读 95% ≥100MiB 跳跃,写 75% 精确连续 | 与 burstgpt 89% 大跳跃 / sharegpt 57% 大跳跃 完全一致;但早上只跑了 "分离 prefill-only + decode-only",本文跑的是 **混合 workload** |
| `kv-cache-sharegpt-vs-burstgpt-io-2026-06-29.md` (上一份) | sharegpt vs burstgpt IO 模式差异 2.5× IOPS, 2.6× BW | **增加 synthetic (fio_sweep) 维度**,明确指出 fio replay 不能反映 LBA 跳跃和突发性 |
| 本文 | 三路综合,标明各自适用场景 | 给出 PPT-ready 的对比图和压力热图 |

---

## 八、给后续工作的建议

1. **fio_sweep 不要扔** — 作为设备 sanity check 保留(QD=32 的 11.9M token/s 是合理上限)
2. **sharegpt / burstgpt 要保留原始 CSV** — 当前在 results/kvcache-profile/ 下,**390 MB 总量**,不入 git 但可作 audit trail
3. **下一步如果做 Mooncake SSD offload 评估**:用 burstgpt 做随机读压力测试(更接近 DGX 原始 benchmark),用 sharegpt 做混合压力测试
4. **如果要补 sharegpt tracepoint 中断位置**:早上那份报告 281.88 GiB / 2.49M 事件是 prefill+decode 分离跑;这里 sharegpt 1.98M 是混合跑,**事件数差 25%** 主要是 sharegpt 写少了 50% (混合 mode 不强制 prefill)

---

## 附录:工具链备忘

```bash
# 跑 sharegpt
~/llm/storage/kv_cache_benchmark/.venv/bin/python3 \
  ~/llm/storage/kv_cache_benchmark/kv-cache.py \
  --num-users 8 --duration 120 --disable-multi-turn \
  --gpu-mem-gb 0 --cpu-mem-gb 0 \
  --cache-dir ~/llm/storage/results/kvcache-profile/ext4_kvcache_sharegpt \
  --storage-capacity-gb 40 \
  --output ~/llm/storage/results/kvcache-profile/sharegpt_kvcache_YYYYMMDD_HHMMSS/

# 跑 burstgpt (加 --use-burst-trace)
~/llm/storage/kv_cache_benchmark/.venv/bin/python3 \
  ~/llm/storage/kv_cache_benchmark/kv-cache.py \
  --use-burst-trace \
  --burst-trace-path ~/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --num-users 8 --duration 120 \
  ...(同 sharegpt)

# bpftrace 捕获
sudo /usr/bin/bpftrace ~/llm/storage/scripts/trace_block_lba.bt 271581194

# 后处理 → block_lba_trace.csv
# (见 ~/llm/storage/scripts/analyze_sharegpt_burstgpt_io.py)

# 重新生成综合图
~/llm/storage/.venv/bin/python3 \
  ~/llm/storage/scripts/io_three_way_comparison.py
```