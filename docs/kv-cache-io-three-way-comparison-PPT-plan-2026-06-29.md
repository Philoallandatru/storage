# KV Cache SSD Offload 真实 IO 分析 — PPT 大纲 (更新版)

**目标受众:** 项目内部技术评审 / 老板汇报
**总页数:** 12 页
**演讲时长:** 15-20 分钟
**风格:** 数据驱动,每页一张图 + 3 行要点
**核心信息:** 3 种 workload 产生截然不同的 IO 模式;default (workload runner 真实默认 mixed prefill+decode) 是 baseline,burstgpt 是最重压力,sharegpt 是混合压力;fio_sweep 不参与三路对比

> **v3 修订 (2026-07-01):** 把"default-kvcache (morning two-stage)"列替换为"default (real mixed-mode TP=1)",**三种 workload 现在用统一方法学** (TP=1, 8u, 120s, llama3.1-8b, forced NVMe)。删除了 v2 的"方法学不一致"声明。详见主报告 §1-3。

---

## 📑 第 1 页 — 封面

**大标题:** KV Cache SSD Offload 真实 I/O 模式分析
**副标题:** default (real mixed-mode TP=1) / ShareGPT / BurstGPT 三路对比
**日期:** 2026-06-29 (v2 修订 2026-06-30)
**作者:** MLPerf Storage Working Group
**配图建议:** 3 种 workload 的缩略图,或深色 dashboard 缩略图作为背景

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

| Workload | 工具链 | 触发场景 | 时长 | 模型 | TP |
|---|---|---|---:|---|---:|
| **default** | kv-cache.py 默认 mixed 模式 (prefill+decode 自动切换) | workload runner 的真实默认行为 | 132.78s | llama3.1-8b | **1** |
| **sharegpt** | kv-cache.py + ShareGPT JSON | 多轮对话,prefix cache 命中率高 | 140.91s | llama3.1-8b | 1 |
| **burstgpt** | kv-cache.py + BurstGPT CSV | bursty 请求,随机到达,decode 重 | 129.75s | llama3.1-8b | 1 |

**配图建议:**
- 三段并排的 workload 时间轴 (timeline mockup)
- 或三张 workload 的 logo/图标

**v3 关键更新:** 三种 workload 现在**统一方法学** — 全部 TP=1,8 users,120s,forced NVMe (0/0 GiB GPU/CPU cache)。v2 的 TP=8 two-stage 拼接已废弃。

---

## 📑 第 5 页 — ⭐ 综合压力对比 (Signal Dashboard)

**配图:** `assets/io-three-way-comparison/01_signal_dashboard.png` (深色 2x3 KPI 卡片)

**文字要点 (4 句话):**
1. **burstgpt 压力最大**:35,195 IOPS / 4.25 GiB/s,比 sharegpt 高 2.5×
2. **default 跟 burstgpt 量级接近**:30,806 IOPS / 3.75 GiB/s (burstgpt 1.1×),是真实 mixed prefill+decode 服务的典型负载
3. **sharegpt 是中等压力**:14K IOPS / 1.64 GiB/s,但 Read 比例 94% (最高)
4. **三种 workload LBA span 完全相同 (389.35 GiB)** — 跟盘本身容量相关,跟 workload 类型无关

**页脚:** "数据来源:tracepoint 实测 9M+ block events"

---

## 📑 第 6 页 — IOPS / BW 时间序列

**配图:** `assets/io-three-way-comparison/02_iops_bw_timeline.png` (per-second 双图)

**文字要点:**
- **burstgpt 是稳态高负载**:IOPS CV 仅 0.28,几乎是贴着上限跑
- **sharegpt 是脉冲型负载**:CV 0.61,峰谷比 2.07×,有活跃期/静默期切换
- **default 是脉冲型 (跟 sharegpt 同量级)**:CV 0.61,峰谷比 2.07×,写顺序 + 读跨块随机的混合行为
- 这跟 workload 性质吻合 — burstgpt 是用户请求随机到达的 burst 模式;sharegpt 是多轮对话 prefix 复用;default 是 LLM 标准 prefill+decode 流程
- **注意:** v3 起三种 workload 都用 **1s 窗**的 per-second time-series (从 `iops_per_sec` 字段读出),时间序列可直接在 timeline 图上叠加对比

---

## 📑 第 7 页 — ⭐ LBA 跳跃分布 (CDF) — 最核心的一页

**配图:** `assets/io-three-way-comparison/03_lba_delta_cdf.png` (R/W 分开双图,log scale X)

**文字要点:**
- **default 读是 mixed**:0% 精确连续 + 79.16% 大跳跃,p50 = 5 GB — 真实 mixed prefill+decode 服务的典型读
- **sharegpt 读是 mixed**:41.8% 连续 + 57.0% 大跳跃 = prefix cache 命中 + 部分新问题
- **burstgpt 读 89.1% 大跳跃** (p50 = 31 GB),典型 random read 模板
- **写都是顺序追加**:default 95% 在 <1 MiB / sharegpt 94% / burstgpt 98% 精确连续 → Prefill 都是顺序 append KV 块
- **CDF 曲线下的面积差** = "synthetic 没法模拟的" 真实应用 LBA 行为

**页脚:** "389 GiB LBA span — 用户问的 token 在不同历史位置,需要从 SSD 随机拉取"

---

## 📑 第 8 页 — 块大小分布

**配图:** `assets/io-three-way-comparison/04_block_size_distribution.png` (3 workload 并排柱状)

**文字要点:**
- 三种 workload 都以 128 KiB 为主
- **default 块大小分布集中 (99.6% 128K)** — 默认 mixed workload 没有 prefix cache 命中的小块混杂,纯 page 写
- **sharegpt 有少量 64 KiB** (6%) — 可能来自 prefix cache 命中时的 half-block promotion
- **burstgpt 几乎纯 128K** (98.5%) → **device IO 调度可以用固定 128K 块假设简化**

---

## 📑 第 9 页 — 压力热图

**配图:** `assets/io-three-way-comparison/05_pressure_heatmap.png` (4×3 矩阵)

**文字要点:**
- **burstgpt 在 IOPS / BW / Read ≥100MiB jump 三项都是最高** (35K / 4.25 GiB/s / 89.11%) — 最重压力
- **default 跟 burstgpt 量级接近** (30.8 vs 35.2K IOPS, 3.75 vs 4.25 GiB/s) — 默认 mixed workload 不是轻量级
- **sharegpt 在 Read % 上最高** (94%) — 因为写很少 (只 6%),全部事件几乎都是读
- **三种 workload 各自在不同维度称王**,**不能用一个顶替另一个**

---

## 📑 第 10 页 — 对 fio_sweep 的诚实评价 (新加入)

**文字要点:**

| 维度 | fio_sweep (旧"synthetic") | default / sharegpt / burstgpt (三路) |
|---|---|---|
| 设备带宽上限标定 | ✅ 准确 | ⚠️ 应用层 |
| 真实 LBA 跳跃分布 | ❌ 无 | ✅ 完整 |
| 突发性 (CV) | ❌ 稳态 | ✅ 0.28-0.61 |
| 应用语义 (decode vs prefill) | ❌ 丢失 | ✅ 保留 |

**结论:** **fio_sweep 只适合做 device capability ceiling 标定,不适合用来评估 KV-cache SSD offload 的 TTFT 收益。**因此本三路对比**只放 kv-cache.py 实跑的数据**。

**配图建议:**
- 表格放大 (单独占一页)
- 或者双柱图 "fio_sweep 在哪些场景可信 vs 不可信"

---

## 📑 第 11 页 — 跨报告结论的一致性

**文字要点:**
- v3 报告 (default) → 4.09M events / 30.8K IOPS / 79.16% 大跳跃 ✅ **方法学统一后,与 burstgpt 89% / sharegpt 57% 形成连续光谱**
- v2 报告 (default-kvcache morning two-stage) → 95% 大跳跃 ✅ **v3 修正为 79% 真实 mixed workload,降低了虚高**
- 上一份 (sharegpt vs burstgpt) → 2.5× IOPS, 2.6× BW ✅ **本文加入 default 维度,明确 fio_sweep 不能顶替**
- **三份报告相互佐证**,**核心结论稳定**:**真实 KV cache I/O 是读写分裂的双模式**(随机读 / 顺序写)

**配图建议:**
- 三份报告的封面缩略图横向排列
- 用箭头标"实测验证 → 扩展 → 综合"

---

## 📑 第 12 页 — 行动建议 & 下一步

**文字要点:**
1. **保留 fio_sweep** 作为 device sanity check (QD=32 11.9M token/s 是合理上限)
2. **sharegpt / burstgpt / default 原始 CSV 保留** 在 `results/kvcache-profile/`(390MB+,不入 git 作 audit trail)
3. **评估 Mooncake SSD offload 时**:
   - **稳态 + 随机读压力** → 用 burstgpt (更接近 DGX 原始 benchmark)
   - **混合压力** → 用 sharegpt (有 prefix cache 命中)
   - **baseline (workload runner 默认行为)** → 用 default (mixed prefill+decode, 4.09M events)
4. **下一步**:把 Mooncake 真实 SSD offload 跑在 burstgpt tracepoint 监控下,验证 "30+ IOPS / 4+ GiB/s" 路径下 SSD offload 是否真能避免 DRAM pool cliff
5. **v3 收尾**:三路对比方法学已统一,不再需要后续校准工作

**配图建议:**
- 时间线 / 路线图 "default trace (TP=1) → sharegpt trace → burstgpt trace → Mooncake 实测"
- 或者用第 5 页 dashboard 缩略图作背景 + 文字叠加

---

## 🎨 视觉风格建议

| 元素 | 风格 |
|---|---|
| 主色 | 深色 (#0d1117 页面 / #161b22 卡片) |
| 强调色 | 蓝 #7fbcff (default) / 浅蓝 #a5d6ff (sharegpt) / 黄 #ffd60a (burstgpt) |
| 字体 | Noto Sans CJK JP (中文) / Source Sans Pro (英文) |
| 图表风格 | matplotlib 深色背景 + 高对比色 (跟 `kv-cache-real-io/01_signal_dashboard.png` 一致) |
| 页脚 | 每页底部小字 "data: tracepoint 实测 | date: 2026-06-29 | v2 2026-06-30 | page N/12" |

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
   - Q: 三种 workload 都用 TP=1,跟我之前看到的 default TP=8 有什么区别? → A: v3 之前 default 是两段跑 (prefill-only TP=8 + decode-only TP=8 拼起来);v3 改成单次 mixed run TP=1,跟 sharegpt/burstgpt 同方法学,数据可直接比较
   - Q: 为什么 v2 显示 95% 读大跳跃,v3 是 79%? → A: v2 的两段跑人为把 prefill 阶段 35s 写跟 decode 阶段 60s 读切开,decode 阶段读全是随机,所以虚高。v3 真实 mixed workload 写读交织,读大跳跃比例降到 79%
   - Q: 为什么 fio_sweep 不能顶替? → A: (1) 没有 PID 连续性,无 LBA 跳跃分布;(2) 块大小多样不符;(3) 稳态负载无突发性;(4) 应用语义丢失

---

*文档版本:* v3 (2026-07-01,default 替换为真实 mixed-mode TP=1)
*配套分析脚本:* `scripts/io_three_way_comparison.py` (可重新生成所有图)