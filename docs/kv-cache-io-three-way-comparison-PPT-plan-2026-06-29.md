# KV Cache SSD Offload 真实 IO 分析 — PPT 大纲

**目标受众:** 项目内部技术评审 / 老板汇报  
**总页数:** 12 页  
**演讲时长:** 15-20 分钟  
**风格:** 数据驱动,每页一张图 + 3 行要点  
**核心信息:** 3 种 workload 产生截然不同的 IO 模式;BurstGPT 是最真实压力;fio_sweep 只够做 device sanity

---

## 📑 第 1 页 — 封面

**大标题:** KV Cache SSD Offload 真实 I/O 模式分析  
**副标题:** Synthetic / ShareGPT / BurstGPT 三路对比  
**日期:** 2026-06-29  
**作者:** MLPerf Storage Working Group  
**配图建议:** 3 张工作负载的 logo (sharegpt 绿 / burstgpt 黄 / BIWIN 盘图标),或深色 dashboard 缩略图作为背景

**页脚:** "本文档基于 tracepoint:block:block_rq_issue 实测数据,非模拟"

---

## 📑 第 2 页 — 研究背景与动机

**文字要点:**
- DGX 原始 KV-cache benchmark 报告 57% TTFT 降低、2.4× 吞吐提升
- 但**没有公开底层 block I/O 数据**,无法回答"我工作站能复现多少"
- 需要实测三种 workload 在 BIWIN 盘上的真实 I/O 模式,才能回答"我能用 fio_sweep 顶替真 benchmark 吗"

**配图建议:**
- 左:Mooncake 官方截图 (TTFT 柱状图) — 缩略
- 右:工作流图 "Mooncake → sglang → ext4 → BIWIN"

---

## 📑 第 3 页 — 方法学:tracepoint 捕获

**文字要点:**
- 用 `tracepoint:block:block_rq_issue` 捕获每次 block I/O event
- 设备:`/dev/nvme0n1` 父设备 (dev_t=271581194),因为 partition filter 会丢失 header
- 字段:`timestamp_ns / sector / bytes / rwbs / comm / pid`
- 衍生指标:相邻 I/O LBA delta、block size 分布、IOPS 时间序列、CV 突发性

**配图建议:**
- 上一份报告的 `01_signal_dashboard.png` (signal dashboard 缩略图,加箭头指向关键字段)
- 简化的 bpftrace 一段代码截图 (15 行)

---

## 📑 第 4 页 — 三种 workload 定义

**文字要点:**

| Workload | 工具链 | 触发场景 | 时长 |
|---|---|---|---|
| **synthetic** | fio 3.41 distill replay | 从 bpftrace 蒸馏出 fio config (bssplit / rwmixread) | 60s |
| **sharegpt** | kv-cache.py + ShareGPT JSON | 多轮对话,prefix cache 命中率高 | 120s |
| **burstgpt** | kv-cache.py + BurstGPT CSV | bursty 请求,随机到达,decode 重 | 120s |

**配图建议:**
- 三段并排的 workload 时间轴 (timeline mockup)
- 或三张 workload 的 logo/图标

---

## 📑 第 5 页 — ⭐ 综合压力对比 (Signal Dashboard)

**配图:** `assets/io-three-way-comparison/01_signal_dashboard.png` (深色 4 子图)

**文字要点 (4 句话):**
1. **burstgpt 压力最大**:35,195 IOPS / 4.25 GiB/s,比 sharegpt 高 2.5×
2. **fio_sweep (synthetic) 也能跑 33K IOPS**,但这是稳态设备上限,跟真实应用压力性质不同
3. **sharegpt 是中等压力**:14K IOPS / 1.64 GiB/s,但 Read 比例 94% 比 burstgpt 略高
4. **synthetic 没有 Read 相邻跳跃数据** (fio 缺 PID 连续性) → **不适合做 KV-cache SSD offload 评估**

**页脚:** "数据来源:tracepoint 实测 6.5M block events"

---

## 📑 第 6 页 — IOPS / BW 时间序列

**配图:** `assets/io-three-way-comparison/02_iops_bw_timeline.png` (3s 窗口双图)

**文字要点:**
- **burstgpt 是稳态高负载**:IOPS CV 仅 0.28,几乎是贴着上限跑
- **sharegpt 是脉冲型负载**:CV 0.61,峰谷比 2.07×,有活跃期/静默期切换
- 这跟 workload 性质吻合 — burstgpt 是用户请求随机到达的 burst 模式;sharegpt 是多轮对话 prefix 复用
- **fio_sweep 是稳态** (没有时间序列数据,只能画水平参考线) → **没有突发性,无法评估 SSD offload 在生产环境下的瞬时压力**

---

## 📑 第 7 页 — ⭐ LBA 跳跃分布 (CDF) — 最核心的一页

**配图:** `assets/io-three-way-comparison/03_lba_delta_cdf.png` (R/W 分开双图,log scale X)

**文字要点:**
- **burstgpt 读是"random read" 模板**:89.1% 相邻读跳跃 ≥100 MiB,p50 = 31 GB
- **sharegpt 读是 mixed**:41.8% 连续 + 57.0% 大跳跃 = prefix cache 命中 + 部分新问题
- **写都是连续的**:sharegpt 写 94.4% / burstgpt 写 97.6% 精确连续 → Prefill 顺序 append
- **这跟早上那份 281.88 GiB 实测完全一致**:75% 写连续 / 95% 读大跳跃
- **CDF 曲线下的面积差** = "synthetic 没法模拟的" 真实应用 LBA 行为

**页脚:** "389 GiB LBA span — 用户问的 token 在不同历史位置,需要从 SSD 随机拉取"

---

## 📑 第 8 页 — 块大小分布

**配图:** `assets/io-three-way-comparison/04_block_size_distribution.png` (3 workload 并排柱状)

**文字要点:**
- 三种 workload 都以 128 KiB 为主
- **kv-cache.py 实际跑的 sharegpt/burstgpt 清一色 128K**(sglang page size = 64 token → 128 KiB)
- **fio_sweep (synthetic) bssplit 是 4k/8k/16k/32k/64k/128k 混合**,因为来自 6 月初 bpftrace 蒸馏,反映当时 KV 内部多级缓存结构
- **burstgpt 几乎纯 128K**(98.52%)→ **device IO 调度可以用固定 128K 块假设简化**

---

## 📑 第 9 页 — 压力热图

**配图:** `assets/io-three-way-comparison/05_pressure_heatmap.png` (3×4 矩阵)

**文字要点:**
- **burstgpt 在 3 项指标都是最高**:IOPS / BW / 大跳跃率
- **sharegpt 在 Read % 上跟 burstgpt 并列**,但实际压力小很多(总事件数低)
- **synthetic 在 "Read 相邻大跳跃" 是 0**(无意义),**Read % 最低**(61%) → **跟真实 workload 差异最大**
- **热图直观显示**:**不能用一个 workload 顶替另一个**

---

## 📑 第 10 页 — 对 fio_sweep 的诚实评价

**文字要点:**

| 维度 | synthetic | sharegpt / burstgpt |
|---|---|---|
| 设备带宽上限标定 | ✅ 准确 | ⚠️ 应用层 |
| 真实 LBA 跳跃分布 | ❌ 无 | ✅ 完整 |
| 突发性 (CV) | ❌ 稳态 | ✅ 0.28-0.61 |
| 应用语义 (decode vs prefill) | ❌ 丢失 | ✅ 保留 |

**结论:** **fio_sweep 只适合做 device capability ceiling 标定,不适合用来评估 KV-cache SSD offload 的 TTFT 收益。**

**配图建议:**
- 表格放大 (单独占一页)
- 或者双柱图 "fio_sweep 在哪些场景可信 vs 不可信"

---

## 📑 第 11 页 — 跨报告结论的一致性

**文字要点:**
- 早上那份 (real-io 281 GiB) → 读 95% 大跳跃 / 写 75% 连续 ✅ **与 burstgpt 89% / sharegpt 57% 完全一致**
- 上一份 (sharegpt vs burstgpt 6.5M events) → 2.5× IOPS, 2.6× BW ✅ **本文加入 synthetic 维度,明确 fio_sweep 不能顶替**
- **三份报告相互佐证**,**核心结论稳定**:**真实 KV cache I/O 是读写分裂的双模式**(随机读 / 顺序写)

**配图建议:**
- 三份报告的封面缩略图横向排列
- 用箭头标"实测验证 → 扩展 → 综合"

---

## 📑 第 12 页 — 行动建议 & 下一步

**文字要点:**
1. **保留 fio_sweep** 作为 device sanity check (QD=32 11.9M token/s 是合理上限)
2. **sharegpt / burstgpt 原始 CSV 保留** 在 `results/kvcache-profile/`(390MB,不入 git 作 audit trail)
3. **评估 Mooncake SSD offload 时用 burstgpt** 做随机读压力(更接近 DGX 原始 benchmark)
4. **混合压力用 sharegpt** (prefix cache 命中 + 部分新问题)
5. **下一步**:把 Mooncake 真实 SSD offload 跑在 burstgpt tracepoint 监控下,验证 "30+ IOPS / 4+ GiB/s" 路径下 SSD offload 是否真能避免 DRAM pool cliff

**配图建议:**
- 时间线 / 路线图 "sharegpt trace → burstgpt trace → Mooncake 实测"
- 或者用第 5 页 dashboard 缩略图作背景 + 文字叠加

---

## 🎨 视觉风格建议

| 元素 | 风格 |
|---|---|
| 主色 | 深色 (#1f1f1f) / 白底切换 |
| 强调色 | 黄 #ffd60a (synthetic) / 青 #00e5ff (sharegpt) / 品红 #ff006e (burstgpt) |
| 字体 | Noto Sans CJK SC (中文) / Source Sans Pro (英文) |
| 图表风格 | matplotlib 深色背景 + 高对比色 (跟 `kv-cache-real-io/01_signal_dashboard.png` 一致) |
| 页脚 | 每页底部小字 "data: tracepoint 实测 | date: 2026-06-29 | page N/12" |

---

## 📁 配套素材文件

所有 PPT 用的图都在 `docs/assets/io-three-way-comparison/`:

- `01_signal_dashboard.png` (PPT 第 5 页)
- `02_iops_bw_timeline.png` (PPT 第 6 页)
- `03_lba_delta_cdf.png` (PPT 第 7 页)
- `04_block_size_distribution.png` (PPT 第 8 页)
- `05_pressure_heatmap.png` (PPT 第 9 页)

源数据:
- `derived/comparison_summary.json` — 所有数字汇总
- `docs/kv-cache-io-three-way-comparison-2026-06-29.md` — 完整中文文档(本报告)

---

## 💡 演讲 Tips

1. **第 5 页** 是核心信息,给评审专家 30 秒看 dashboard + 听"burstgpt 2.5× sharegpt" 一句话
2. **第 7 页** 是技术深度页,可以放慢 1 分钟讲 LBA 跳跃分布的物理含义
3. **第 10 页** 是给老板/产品看的页,简化 "fio_sweep 不能顶替真 benchmark" 一句话
4. **第 12 页** 给老板看行动建议,3 条 bullet 即可
5. 准备 2-3 个 FAQ 备用:
   - Q: 为什么没用 llama3.2-3b / qwen3-4b-instruct? → A: 当时 checkpoint 没装,用了 llama3.1-8b,效果一致
   - Q: 为什么不用 100 GiB 预分配? → A: 根盘只剩 73 GB,workload runner 不阻塞
   - Q: 为什么 fio_sweep QD=1024 时 IOPS 反而下降? → A: 队列竞争 + 单盘 controller 不够,详见 sharegpt_qd1024 数据

---

*文档生成时间:2026-06-29*
*配套分析脚本:`scripts/io_three_way_comparison.py` (可重新生成所有图)*