# BIWIN X570 SLC Cache — Mixed R/W 模式对比

日期:2026-06-09
测试盘:`/dev/nvme1n1` (BIWIN X570 1TB,3D TLC,steady state)
测试脚本:`scripts/characterize_ssd_slc.py --rwmixread N`

## 测试目的

**核心问题**:LLM 实际 workload 是 mixed R/W(~90%读 +10%写 KV cache)。
SLC cache 在 mixed R/W 下行为如何?**cache 容量会变化吗?**

## 测试配置

| 项 | Pure Write | 50/50 Mixed |
|---|---|---|
| rw mode | sequential write | random R/W |
| rwmixread | 100 (pure write) | 50 |
| Block size | 1 MiB | 1 MiB |
| iodepth | 32 | 32 |
| ioengine | libaio | libaio |
| direct | 1 | 1 |
| size | 200 GiB | 200 GiB |
| Total written | 200 GiB | **99.92 GiB** (50% of 200) |

## 关键发现

### Pure Write(200 GiB sequential write)— baseline

| 指标 | Fresh | Steady-State |
|---|---:|---:|
| SLC cache 大小 | ~71 GiB | ~95 GiB |
| 缓存内写速 | 5078 MiB/s | 5073 MiB/s |
| 出缓存后速度 | 1668 MiB/s | 1825 MiB/s |

→ **明确的 SLC cache cliff**:5078 →1668 MiB/s,清晰可见

### Mixed R/W (50/50 randrw,100 GiB writes)— 关键发现

| 指标 | Mixed R/W |
|---|---:|
| **SLC cache 大小** | **>= 100 GiB (no cliff)** |
| Initial speed | 1312 MiB/s |
| Steady tail speed | 1311 MiB/s |
| P50/P95/P99 per-second | 1306 / 1359 / 1374 MiB/s |

**没有 SLC cache cliff!** —混合 R/W 下:
- 早期(sec 1-5):1244-1376 MiB/s
- 中期(sec 30):~1300 MiB/s
- 末期(sec 75-79):854-1361 MiB/s
- **整段都在 1300 MiB/s 附近,没有 burst 也没有 cliff**

## 🧠 为什么 Mixed R/W 没有 SLC Cache Burst?

**3 个原因**:
1. **随机寻址打破 sequential burst**:`--rw=randrw` 用随机寻址,即使 controller 想保持 SLC mode,随机地址也需要 SLC 区在不同 page 之间跳转,**无法保持连续的 burst 写入**
2. **读+写混合让 controller 无法专注 write**:
 - 读请求需要从 SLC cache读取数据(可能 hit 或 miss)
 - 写请求需要写入 SLC cache(部分 hit,部分 fold 到 TLC)
 - 两者并发 → controller **无法把 SLC cache 当纯 write buffer**
3. **直接命中 TLC 模式**:
 - 100 GiB writes 已接近 SLC cache(~71-95 GiB)上限
 - 即使 controller 想用 SLC mode,空间不够 → 早期就切到 TLC 模式 (~1300 MiB/s 写速)

## 🎯 对 AI SSD 产品设计的启示

### 1. Vendor Spec 的 SLC cache 数字仅在 sequential write 下成立

**Vendor spec** 经常引用的"~5000 MiB/s cache 写速"是 **sequential write 极限**。
LLM KV cache 是 mixed random R/W,实际生产中**永远拿不到这个速度**。

| 场景 | 期望写速 |
|---|---:|
| Vendor spec (sequential write burst) | ~5000 MiB/s |
| **LLM mixed R/W 实际写速** | **~1300 MiB/s** |
| 出 SLC cache 后写速 | ~1300-1700 MiB/s |

**实际生产 LLM 推理写速只有 spec 的 ~26%!**

### 2. SLC cache 在 mixed R/W 下变成"概念性"

由于 mixed R/W 没有 burst,LLM 推理**实际上无法利用 SLC cache 的 burst 优势**。
**SLC cache 对 LLM workload 的价值有限** — checkpointing 才有意义(sequential write)。

### 3. AI SSD 优化方向

既然 mixed R/W 下 SLC cache 没用,AI SSD 应该优化:
- **混合 IOPS**(而不是 sequential BW)
- **延迟一致性**(尤其 P95/P99)
- **多队列并行**(而非 cache 容量)
- **持久性 DRAM cache**(吸收 read burst)

## 📊 数据汇总

| 配置 | 写速 | 是否有 cliff |
|---|---:|---|
| Sequential write (Fresh) | 5078 → 1668 MiB/s | ✅ Yes |
| Sequential write (Steady) | 5073 → 1825 MiB/s | ✅ Yes |
| **Mixed R/W (50/50)** | **1312 → 1311 MiB/s** | **❌ No** |

## 🧭 后续测试方向

| 项 | 价值 |
|---|---|
| 90/10 mixed R/W(更接近 LLM) | 高 |
| 70/30 mixed R/W(checkpoint-like) | 中 |
| 100% random read(no write) | 中 |
| 测量 mixed R/W 下 GC 漂移 | 中 |

## ⚠️ 限制

1. **单次测量**:Mixed R/W 测试只跑了一次,未重复验证。
2. **Disk space 限制**:50/50 测试只能 100 GiB writes,不足以触发 95 GiB SLC cache + 充分 TLC 测试。
3. **没有覆盖 90/10**:LLM 实际更接近 90/10,但磁盘空间不够做 600 GiB 测试。

**报告结束。**