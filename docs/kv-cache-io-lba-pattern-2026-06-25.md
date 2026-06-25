# KV Cache IO 模式 - 到底有多随机?

**日期:** 2026-06-25
**分析对象:** 真实推理负载下的 KV cache 数据移动
**数据来源:** `results/kvcache-profile/io_trace_sharegpt_8b_tp8_cpu0p5g_users2_300s.csv.zst`
**分析脚本:** `scripts/plot_kv_cache_io_lba_pattern.py`
**输出位置:** `results/kvcache-profile/io_lba_pattern/`

---

## 这份报告回答什么问题?

上次报告 (`a77dcd8`, 2026-06-25) 用设备级 iostat 数据得出结论:

> "KV cache 工作负载是 **application-locked 的大块随机 IO**,`%rrqm` 全程为 0,
> 真正影响性能的是 `r_await` 和 `w_await`。"

但那个报告自己留了个口子:

> "原始 iostat 日志 **没有 per-request LBA**,只有设备聚合统计。
> 最接近的空间信号是 bpftrace 的 10 GiB 分桶 heatmap。"

这份报告就是来**补这个口子** — 用 per-request trace 把每个 IO 画在 (时间, LBA) 平面上,
量化"70% 顺序 + 30% 随机"的双峰结构。

---

## 三句话结论

1. **不是 100% 随机** — 70% 的连续 SSD 读访问的是**同一块 KV cache** (delta = 0 字节)
2. **但也不是顺序** — 剩下的 30% 在 2 GiB 范围内跳来跳去,平均跳 200-700 MB
3. **这就是为什么 iostat 看到 `%rrqm=0`** — 即使同一个 block 反复读,因为每次都是 304 KB 整块,内核也没法合并

---

## 数据是怎么来的 (一张流程图)

```
真实推理请求流 (ShareGPT 数据集, 2 个并发用户, LLaMA-3.1-8B)
        ↓
LMCache 多层缓存决策 (CPU RAM 0.5 GiB → NVMe SSD)
        ↓ (每次 KV cache 移动都钩一行)
kv-cache.py --io-trace-log  ← kv_cache_benchmark 工具,trace 模式
        ↓
io_trace_sharegpt_*.csv.zst (127,477 行, zstd 压缩)
        ↓ (今天跑)
解压 + 模拟 LBA + matplotlib 出图
```

**重要前提:**
- trace 文件里 Tier 字段由 LMCache 工具的源码定义 (`tracer.py:23-25`):
  - **Tier-0 = GPU VRAM**(本次测试 GPU 容量=0,所以**没有真实数据**)
  - **Tier-1 = CPU 内存 (系统 RAM)**
  - **Tier-2 = NVMe SSD**
- LBA 是我**模拟**的 — 按 Key 首次出现时间顺序,在 0 起点累加 KV block 大小,得到"假设的 LBA 偏移"

---

## 图 1: 散点图 — 127K 次 IO 全画出来

![KV cache LBA 散点图](assets/kvcache-io-lba-pattern/kvcache_lba_scatter.png)

**坐标轴:**
- X 轴: 时间 (0-300 秒,5 分钟测试)
- Y 轴: 模拟 LBA (0-2.02 GiB,973 个 Key 的 KV cache 总大小)

**怎么读这张图:**
- **每个点 = 一次 IO**,颜色代表类型
- 圆点 = 读,方块 = 写
- 🔴 红 = 从 SSD 读 KV (decode 阶段)
- 🔵 蓝 = 从 CPU 内存读 KV (decode 阶段)
- 🟢 绿 = 写入 CPU 内存 (Prefill 阶段,新请求的初始写入)
- 🟠 橙 = 从 CPU 内存读出 (准备淘汰)
- 🟤 棕 = 写入 SSD (淘汰后的持久化)

**两个时间区:**

| 时间段 | 现象 | 含义 |
|---|---|---|
| **0-50 秒** | 绿点沿对角线阶梯爬升,蓝/红点紧跟 | **冷启动阶段**:973 个新请求陆续到达,每个请求先 Prefill 写入 CPU 内存,然后开始 decode |
| **50-300 秒** | 红点占绝对主导,均匀铺满 0-2 GiB 整个范围 | **稳态运行**:CPU 内存容量满,KV cache 主要从 SSD 读取,**完全随机分布** |

**一眼能看出的事:**
- **没有"一条带从左扫到右"的顺序流式 pattern** — 这就是真随机
- **CPU 内存里的数据 (蓝点) 在 50s 后只剩高位区** — 说明低位的旧 Key 已经被淘汰出 CPU
- **红点在 50s 后均匀散布整个 2 GiB** — SSD 访问完全是随机的,没有任何 locality 优化

---

## 图 2: CDF + 直方图 — "70% 同位置 + 30% 跳很远" 的证据

![KV cache LBA delta 分布](assets/kvcache-io-lba-pattern/kvcache_lba_delta_histogram.png)

**这张图回答的核心问题:**
> "连续两次 SSD 读之间,LBA 跳了多远?"

**只看中间那根孤零零的红色高柱:**
- 位置 X=0(最左)
- 高度 = **58,956 次** IO
- **其他柱子全贴底**
- 翻译:**70% 的连续 SSD 读访问的是同一字节位置** — 也就是说,GPU 在反复读同一个 KV cache 块

**为什么?** LLM decode 阶段每生成一个 token 都要读 KV cache。生成 100 个 token = 读同一个 block 100 次。

**看右边 inset 的尾巴:**
- 主峰在 **X = 200-700 MB** (紫色最高柱)
- 这是跨请求的"跳跃" — 上一个请求结束,下一个请求开始,KV cache 位置从 A 跳到 B
- 整个 KV cache 库只有 2 GiB,所以最远跳不超过 ~1.4 GB

**最关键的数字 (在底部文字框里):**

```
Same-key (delta=0):         58,956 (69.6%)   ← 同一 KV 块反复读
Sequential (<1MB):          59,296 (70.0%)   ← 几乎就靠那 70% 撑顺序性
Random (>=100MB):           22,481 (26.5%)   ← 跨请求跳跃
Median delta:                0.000 MB        ← 中位数就是 0
p95 / p99 delta:             998 / 1431 MB   ← 95% / 99% 分位跳几百 MB 到 1.4 GB
```

---

## 图 3: 4 子图 — Decode 阶段占绝对主导

![KV cache Prefill vs Decode 对比](assets/kvcache-io-lba-pattern/kvcache_phase_comparison.png)

**4 个子图分别回答 4 个问题:**

### 左上: IOPS 时序 (1 秒一个 bin)

- 🟢 绿线 = Prefill IO 速率 (平均几乎 0)
- 🔴 红线 = Decode IO 速率 (平均 413/s,峰值 1019/s)
- 🟠 橙线 = Evict IO 速率 (平均几乎 0)

**翻译: 整个 5 分钟里,99% 的 IO 都是 Decode 阶段的读。Prefill 和 Evict 加起来不到 1%。**

### 右上: 操作 × Tier 柱状图

| 操作 | Tier | 次数 | 实际是什么 |
|---|---|---:|---|
| Read | Tier-2 (SSD) | **84,752** | 从 SSD 读 KV block |
| Read | Tier-1 (CPU) | 36,798 | 从 CPU 内存读 KV block |
| Read | Tier-0 (GPU) | 3,512 | metadata 操作 (0 字节) |
| Write | Tier-1 (CPU) | 973 | Prefill 写入 CPU 内存 |
| Read | Tier-1 (CPU) | 721 | 淘汰时从 CPU 读出 |
| Write | Tier-2 (SSD) | 721 | 淘汰时写入 SSD |

**结论: SSD 读 (84K) 是绝对主角,占比 67%。CPU 内存读 (37K) 是缓存命中部分,占 29%。**

### 左下: IO 大小分布 (对数坐标)

- Decode IO 大小 = **320 KB (中位数)**
- 长尾到 100 MB(很少出现,是驱逐过程)
- Prefill 和 Evict 大小类似 (288-304 KB)

**翻译: 每个 KV cache 块大约 300 KB。固定大小,不是流式连续读。**

### 右下: 读 / 写比例随时间变化

- 0-50s: 读比例 ~0.89(冷启动期,Prefill 写入多)
- 50s 后: 读比例稳定在 ~1.0(纯稳态,几乎全是读)
- 整体读比例 = **0.987**

**翻译: KV cache 是个**读多写少**的工作负载 — 每 1000 次 IO 里 987 次是读。**

---

## 数据量总结 (这张图背后的真实数字)

| 层级 | 真实读写量 | 占总 IO 比例 |
|---|---:|---:|
| **Tier-2 (NVMe SSD)** | 读 203 GiB + 写 1.6 GiB | **67% IO** |
| **Tier-1 (CPU 内存)** | 读 36 GiB + 写 36 GiB | **30% IO** |
| Tier-0 (GPU VRAM) | 0 字节 (metadata) | 3% IO |
| **总传输量** | **277 GiB / 301 秒** = **920 MB/s** | 100% |

---

## 这跟前几次报告的关系

| 报告 | 数据源 | 结论 |
|---|---|---|
| `kv-cache-io-randomness-2026-06-25.md` (a77dcd8) | iostat 设备聚合 | "100% 大块随机 IO,`%rrqm=0`,关键指标是 `r_await`" |
| **本文 (011cb06)** | **per-request trace** | **"70% 同位置读 + 30% 跨请求跳跃,bimodal 双峰"** |

**两份报告不冲突,是互补的**:
- iostat 看到的是 **设备视角**:每次 IO 都是独立请求,`%rrqm=0` 是因为 304 KB 块太大没法合并
- trace 看到的是 **应用视角**:大部分 IO 是同 Key 反复读,所以**应用层有强 locality**
- 性能瓶颈在 **那 30% 的跨请求跳跃** — 这部分 SSD 必须真随机读,所以 Biwin X570 (低 `r_await`) 比 ZhiTai Ti600 (高 `r_await`) 快 5-10 倍

---

## 方法说明

### LBA 是怎么算出来的?

trace 里**没有 LBA 字段**,只有 Key。我的启发式:

```python
key_lba = {}
cur_lba = 0
for io in sorted_by_time(ios):
    if io['op'] == 'Write' and io['key'] not in key_lba:
        key_lba[io['key']] = cur_lba    # 第一次见这个 Key,分配新 LBA
        cur_lba += io['size']            # 累加 size
# 后续这个 Key 的所有 IO 都复用这个 LBA
```

**假设:** Key 按写入顺序在 SSD 上**连续分配**(vLLM/LMCache 的常见布局策略)。这是**下限估计** — 如果实际 allocator 更分散,真实随机比例会更高。

### 为什么用 CDF 而不是纯直方图?

纯 log-scale 直方图会把 70% 同位置读全压到 X=0.001 那个 bin 里,**看起来像 100% 随机**,误导观者。**CDF + linear 放大 + log 尾部**三个子图一起,才能把双峰讲清楚。

### Tier 过滤规则

- **Tier-0** (GPU) → 全部是 0 字节 metadata,**不算数据 IO**,LBA 不分配
- **Tier-1** (CPU 内存) → 真 KV data,参与散点图
- **Tier-2** (SSD) → 真 KV data,参与散点图 + 是 delta 直方图唯一的分析对象

---

## 文件清单 (本次提交的所有产出)

- `scripts/plot_kv_cache_io_lba_pattern.py` (绘图脚本)
- `docs/kv-cache-io-lba-pattern-2026-06-25.md` (本文档)
- `docs/assets/kvcache-io-lba-pattern/kvcache_lba_scatter.png` (图 1)
- `docs/assets/kvcache-io-lba-pattern/kvcache_lba_delta_histogram.png` (图 2)
- `docs/assets/kvcache-io-lba-pattern/kvcache_phase_comparison.png` (图 3)
- `results/kvcache-profile/io_lba_pattern/*` (数据副本)

---

## 复现命令

```bash
cd ~/llm/storage
source .venv/bin/activate
python3 scripts/plot_kv_cache_io_lba_pattern.py \
    --trace results/kvcache-profile/io_trace_sharegpt_8b_tp8_cpu0p5g_users2_300s.csv.zst \
    --out   results/kvcache-profile/io_lba_pattern
```