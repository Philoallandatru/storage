# KV Cache 设备端 LBA Last-Touch 分析

**日期:** 2026-06-25  
**验证更新:** 2026-06-26  
**数据源:** `results/kvcache-profile/bpftrace_sharegpt_8b_tp8_cpu0p5g_users2_300s_profile_20260608_014520.txt` 中的 `@d[dev, sector]: timestamp_ns`  
**脚本:** `scripts/plot_kv_cache_lba_timeline.py`

这份报告分析的是 **bpftrace last-touch LBA map**，不是完整 per-IO LBA 日志。
它可以回答“哪些设备 LBA 被触达过、这些 LBA 的最后访问时间如何分布”，但不能严格回答“每一次 IO 是否顺序”。

## 这份报告修正了什么?

早期版本把 `@d[dev, sector]: timestamp_ns` 按时间排序后称为“设备端 LBA 时间序列”，并进一步推导了：

- `gap < 1MiB` 派生比例 29.0%
- 92.3% forward
- forward run 平均 13.1 events
- dedup heatmap 足以回答顺序 vs 随机

这些说法 **过强**。原因是 `@d[]` 不是事件流，而是 bpftrace map：

```bpftrace
@d[args->dev, args->sector] = nsecs;
```

同一个 `(dev, sector)` 如果被访问多次，map 里只保留最后一次访问时间。也就是说：

- 重复访问被覆盖，看不到 delta=0 / re-read 次数
- 访问顺序被压缩成“每个唯一 sector 的最后访问时间排序”
- 由此计算出的 gap、direction、run length 是 **last-touch map 的派生指标**，不能当成真实 per-IO 顺序率

## 结论级别

### 可以可靠说明

1. **这次 bpftrace 捕获到 969 个唯一 `(dev, sector)` 位置。**
2. **这些位置几乎都在设备高位区间。** 968/969 个非零位置落在 `564.3-952.6 GiB`。
3. **存在一个 `0 GiB` 异常点。** 这很可能是测试结束、清理、元数据或其他非 KV 数据路径，不应拿来推断稳态 KV cache 工作集。
4. **last-touch map 显示触达范围很宽。** 去掉 0 GiB 异常点后，唯一 sector 覆盖约 `388 GiB` 的高位 LBA 范围。
5. **`iostat` 的 `%rrqm≈0` 仍然成立。** 但它说明的是 block scheduler 没有合并相邻请求，不等同于完整 LBA 时间序列证明。

### 不能可靠说明

1. 不能证明真实 per-IO 顺序率是 29.0%。
2. 不能证明真实 IO 是 92.3% forward。
3. 不能证明 forward run 平均 13.1 个 IO。
4. 不能据此设计“预取 13 个 sector 可命中 80%”之类策略。
5. 不能据此断言工作集就是 388 GiB。它只是唯一 touched sector 的高位 LBA 跨度，不是容量占用，也不是访问频率分布。

## 数据验证

对 `results/kvcache-profile/lba_timeline/lba_events.json` 的复核结果：

| 指标 | 值 | 解释 |
|---|---:|---|
| 唯一 `(dev, sector)` 数 | 969 | bpftrace map entry 数，不是 IO 数 |
| 设备 ID 数 | 1 | 捕获到单一 block device |
| LBA 最小值 | 0.0 GiB | 异常点，需排除后再解释 |
| 非零 LBA 最小值 | 564.3 GiB | KV/cache 相关触达区间下界 |
| 非零 LBA 最大值 | 952.6 GiB | 触达区间上界 |
| 非零 LBA 跨度 | 388.3 GiB | 唯一 sector 的 last-touch 覆盖跨度 |
| LBA p50 | 926.3 GiB | 唯一 sector 中位位置，不是 IO 中位位置 |
| LBA p95 | 940.4 GiB | 唯一 sector 分布偏高位 |
| last-touch 时间范围 | 311.8 s | map 中最早/最晚 last-touch 差值 |

最高频的 10 GiB bucket 来自唯一 sector 计数，不是 IO 次数：

| 10 GiB bucket | 唯一 sector 数 |
|---:|---:|
| 930 GiB | 319 |
| 660 GiB | 148 |
| 560 GiB | 119 |
| 920 GiB | 105 |
| 570 GiB | 66 |

## 图 1: Last-Touch LBA 散点

![LBA 时间序列](assets/kvcache-lba-timeline/lba_timeline_scatter.png)

这张图里的每个点是一个 **唯一 `(dev, sector)` 的最后访问时间**，不是一次 IO。

合理解读：

- 大部分 touched sector 位于 `564-953 GiB`
- 颜色代表最后访问时间，可以观察不同 LBA 区域是否在测试后段仍被触达
- 低位 `0 GiB` 点应视为异常/非稳态点

不应解读为：

- 每个点就是一次设备 IO
- 点之间连线代表真实 IO 顺序
- 滑动窗口 LBA range 等价于真实工作集大小

## 图 2: Last-Touch Gap 派生分布

![顺序率分析](assets/kvcache-lba-timeline/lba_timeline_sequentiality.png)

图中 `gap < 1MiB = 29.0%`、`gap < 10MiB = 66.5%`、`gap >= 100MiB = 18.5%`
只适用于 **按 last-touch 时间排序后的唯一 sector 序列**。

它可以作为探索性信号：last-touch map 中既有近邻 LBA，也有跨大范围 LBA。
但它不是 per-IO 顺序率，不能与 `iostat %rrqm` 或真实 block trace 的 sequential ratio 直接等价。

## 图 3: Direction / Run Length 图

![顺序流分析](assets/kvcache-lba-timeline/lba_timeline_runs.png)

这张图保留为探索性可视化，但结论需要降级：

- “92.3% forward” 是 last-touch map 排序后的方向比例
- “Forward run 平均 13.1” 是 last-touch map 的 run length
- 它可能反映文件系统分配、测试结束时 map 状态、bpftrace map 覆盖效应，不一定反映真实 IO 方向

因此不要用它推导设备预取策略。

## 图 4: Window Coverage 图

![窗口覆盖范围](assets/kvcache-lba-timeline/lba_timeline_window_coverage.png)

合理解读：

- 在 last-touch map 中，多个时间窗口内都有高位 LBA 被触达
- 去掉 `0 GiB` 异常点后，触达过的唯一 sector 范围约为 `564-953 GiB`

不应解读为：

- 30 秒真实工作集是 340 GiB
- 60 秒工作集饱和在 388 GiB
- KV cache 文件实际占用 388 GiB

这些需要完整 per-IO log 或文件系统 block mapping 才能确认。

## 跟其他报告的关系

| 报告 | 数据源 | 合理用途 |
|---|---|---|
| `kv-cache-io-randomness-2026-06-25.md` | `iostat` 1s 聚合 | 请求大小、merge ratio、await、队列深度 |
| `kv-cache-io-lba-pattern-2026-06-25.md` | KV trace + 模拟 LBA | 应用层 Key/locality proxy，不是真实 LBA |
| `kv-cache-key-time-locality-2026-06-25.md` | KV trace Key + Timestamp | 同 Key 重读时间局部性 |
| `kv-cache-device-io-analysis-2026-06-25.md` | bpftrace histogram + `@d[]` | block size、D2C latency、last-touch LBA 分布 |
| 本文 | bpftrace `@d[]` last-touch map | 唯一 sector 的空间分布和最后访问时间 |

## 正确的下一步

如果要验证真实 LBA 随机性，需要采 **per-IO 事件流**，而不是 bpftrace aggregate map。
建议输出 CSV 字段：

```text
timestamp_ns,dev,sector,bytes,rwbs,comm,pid
```

可选工具：

- `blktrace` / `blkparse`
- `bpftrace` ring-buffer `printf()` on `tracepoint:block:block_rq_issue`
- `perf trace` / eBPF 程序写 perf buffer

示例 bpftrace 方向：

```bpftrace
tracepoint:block:block_rq_issue
{
  printf("%llu,%u,%llu,%u,%s,%s,%d\n",
         nsecs, args->dev, args->sector, args->bytes,
         args->rwbs, comm, pid);
}
```

拿到完整事件流之后，才能严格计算：

- 相邻 IO 的 LBA delta
- read/write 分开的 sequential ratio
- true forward/backward run length
- per-window working-set coverage
- 与 `iostat %rrqm` 的对应关系

## 复现命令

```bash
cd ~/llm/storage
source /home/ficus/llm/.venv/bin/activate
python3 scripts/plot_kv_cache_lba_timeline.py \
    --bpftrace results/kvcache-profile/bpftrace_sharegpt_8b_tp8_cpu0p5g_users2_300s_profile_20260608_014520.txt \
    --out results/kvcache-profile/lba_timeline/
```

输出：

- `results/kvcache-profile/lba_timeline/lba_events.json`
- `results/kvcache-profile/lba_timeline/lba_timeline_summary.json`
- `results/kvcache-profile/lba_timeline/lba_timeline_scatter.png`
- `results/kvcache-profile/lba_timeline/lba_timeline_sequentiality.png`
- `results/kvcache-profile/lba_timeline/lba_timeline_runs.png`
- `results/kvcache-profile/lba_timeline/lba_timeline_window_coverage.png`
