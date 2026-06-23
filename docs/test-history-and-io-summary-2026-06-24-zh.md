# 测试历史总表与 IO 重新分析

**生成日期:** 2026-06-24

## 产物

- 总表 CSV: `results/history-summary/test_history_master.csv`
- IO 明细 CSV: `results/history-summary/io_analysis_summary.csv`
- KV profile 去重 CSV: `results/history-summary/io_profile_runs.csv`
- Excel 工作簿: `results/history-summary/test_history_master.xlsx`

## 总览

- 总表共收录 **192** 行历史结果，覆盖 KV cache、FIO KV 仿真、SSD 跨盘表征、checkpoint、训练/object-store Markdown 报告摘要。
- 结构化 KV cache 结果 **101** 行；FIO KV 仿真 **21** 行；SSD 表征 **36** 行。
- K4 16-user 1200s 长稳态中，按 KV summary 的应用层 storage read bandwidth 最高的是 **Biwin X570**（1.92262 GB/s）。
- 设备侧写入 p99 最好的是 **Seagate FC530**（w_await p99=24.1 ms）。

## 重画图

![01_kvcache_read_bw_summary](assets/test-history-io-summary/01_kvcache_read_bw_summary.png)

![02_io_pattern_randomness_summary](assets/test-history-io-summary/02_io_pattern_randomness_summary.png)

![03_profile_latency_summary](assets/test-history-io-summary/03_profile_latency_summary.png)

![04_fio_preconditioning_qd1024](assets/test-history-io-summary/04_fio_preconditioning_qd1024.png)

## IO 重新总结

KV cache offload 的块设备行为不是顺序流式读写，而是 **约 115-125 kB 的稀疏大块随机 IO**。判断依据是 `%rrqm` 中位数为 0，读请求大小在四块盘上几乎一致，说明请求形状由 KV entry 大小决定，而不是由 SSD 决定。

真正拉开差距的是设备如何处理随机写和深队列：Seagate FC530 的写 p99 明显低，队列深度也更浅；Biwin X570 峰值读带宽强，但 GC cliff 来得早；ZhiTai Ti600 和 WD SN570 在长稳态中队列堆积和写尾延迟更明显。

下面的 `*_mb_s` 来自 `iostat -dx -m`，单位是 MB/s；KV summary 表中的 `read_bw_gbps/write_bw_gbps` 来自 benchmark summary，口径是应用层 storage bandwidth。

### K4 GC-drift IO 指标

| disk | cliff_min | read_req_median_kb | write_req_median_kb | rrqm_median_pct | r_await_p99_ms | w_await_p99_ms | aqu_p99 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Biwin X570 | 2.91667 | 124.4 | 113.68 | 0 | 0.67 | 57.23 | 107.98 |
| Seagate FC530 | 8.05 | 124.41 | 113.05 | 0 | 1 | 24.1 | 58.03 |
| ZhiTai Ti600 | 5.61667 | 124.69 | 115.94 | 0 | 1.2 | 511.24 | 328.03 |
| WD SN570 | 7.81667 | 124.82 | 115.67 | 0 | 4.09 | 604.8 | 286.92 |

### 代表性 KV cache 长稳态

| vendor | scenario | model | users | duration_s | read_bw_gbps | write_bw_gbps | read_dev_p99_ms | write_dev_p99_ms | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Biwin X570 | K4-GC-DRIFT | llama3.1-8b | 16 | 1205 | 1.92262 | 0.171115 | 132.754 | 155.673 | PASS |
| Seagate FC530 | K4-GC-DRIFT | llama3.1-8b | 16 | 1204 | 1.91243 | 0.169824 | 185.164 | 111.421 | PASS |
| WD SN570 | K4-GC-DRIFT | llama3.1-8b | 16 | 1209 | 1.24749 | 0.123422 | 406.978 | 451.711 | FAIL |
| ZhiTai Ti600 | K4-GC-DRIFT | llama3.1-8b | 16 | 1206 | 1.01469 | 0.0988969 | 242.843 | 697.98 | PASS |

### FIO QD=1024 preconditioning 对比

| family | scenario | read_mix_pct | read_bw_gbps | write_bw_gbps | read_dev_p99_ms | write_dev_p99_ms |
| --- | --- | --- | --- | --- | --- | --- |
| fresh | sharegpt_8b_cpuhalf | 61 | 0.994727 | 0.770215 | 166.724 | 379.585 |
| fresh | burstgpt_8b_cpurel_spd1000 | 91 | 2.39336 | 0.24043 | 68.6817 | 476.054 |
| fresh | tp8_cpuhalf_generic | 73 | 1.55947 | 0.579688 | 156.238 | 480.248 |
| preconditioned | sharegpt_8b_cpuhalf | 61 | 1.14404 | 0.887793 | 111.673 | 221.25 |
| preconditioned | burstgpt_8b_cpurel_spd1000 | 91 | 2.48691 | 0.248145 | 62.1281 | 337.641 |
| preconditioned | tp8_cpuhalf_generic | 73 | 1.74668 | 0.646875 | 79.1675 | 196.084 |

## 结论

1. **AI SSD 选择不能只看顺序带宽。** KV cache 的关键指标是随机大块读写下的 p99/p999、队列深度和 GC cliff 后的稳态带宽。
2. **短 burst 与长稳态结论不同。** Biwin X570 的短时读带宽很强；长会话/持续 eviction 更看重 Seagate FC530 的写尾延迟和 cliff 延后能力。
3. **preconditioning 后深队列尾延迟改善明显。** QD=1024 下多个 workload 的读/写 p99 都下降，说明 fresh-device 数据会高估实际部署风险或低估稳态差异，具体取决于测试目标。
4. **训练/object-store 历史结果仍需保留但不应混入块设备 IO 结论。** 那些结果更多反映 s3dlio、loopback/s3-ultra、DLIO 参数和 co-located 资源竞争；本次总表把来源分开，便于后续按类别过滤。

## 来源说明

本报告优先使用 JSON/CSV 结构化结果；Markdown 历史报告仅抽取明确表格项作为补充，不从自由文本中推断新数值。
