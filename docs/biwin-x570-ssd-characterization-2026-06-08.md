# BIWIN X570 1TB SSD 基础介质与 SLC Cache 判断

日期：2026-06-08

目标盘：`/dev/nvme1n1`，型号 `BIWIN X570 1TB`  
测试分区：`/dev/nvme1n1p3`，ext4，挂载为 `/`  
测试脚本：`scripts/characterize_ssd_slc.py`  
结果目录：`results/ssd-characterization/ssd_slc_biwin_x570_200g_20260608_231549/`

## 测试目的

判断这块盘的基础写入行为：

| 问题 | 结论 |
|---|---|
| 能否确认 QLC/TLC | 不能只靠测试绝对确认，但可结合官方规格和持续写行为判断 |
| SLC cache 大小 | 约 71GiB |
| 缓存内写入速度 | 约 5.08GiB/s |
| 出缓存后速度 | 约 1.67GiB/s |
| 稳态尾部速度 | 约 1.60GiB/s |
| 介质倾向 | 强 TLC-like，且官方规格标称 3D TLC NAND |

## 测试命令

```bash
cd /home/ficus/llm/storage

python3 scripts/characterize_ssd_slc.py \
  --target-dir results/ssd-characterization \
  --size-gb 200 \
  --name biwin_x570_200g \
  --yes
```

脚本采用文件级测试，不直接写裸盘。测试完成后自动删除 200GiB 测试文件，只保留小型 JSON/CSV/Markdown 结果。

## fio 配置

| 项 | 值 |
|---|---|
| Workload | sequential write |
| Size | 200GiB |
| Block size | 1MiB |
| iodepth | 32 |
| ioengine | libaio |
| direct | 1 |
| runtime | 101.68s |

## 测试结果

| 指标 | 数值 |
|---|---:|
| Total written | 200.00GiB |
| Average write speed | 2014.20MiB/s |
| Initial/cache-in speed | 5078.54MiB/s |
| Post-cache speed | 1668.83MiB/s |
| Steady tail speed | 1603.10MiB/s |
| P50 per-second speed | 1680.68MiB/s |
| P95 per-second speed | 5078.00MiB/s |
| P99 per-second speed | 5084.08MiB/s |
| Estimated SLC cache size | ~71.36GiB |

## 带宽曲线读法

前 10 秒基本稳定在 5.05-5.08GiB/s，说明正在写入 SLC cache。约 15 秒后开始明显下降，后续主要稳定在 1.4-1.9GiB/s 区间。

代表性采样：

| 时间 | 写入速度 |
|---:|---:|
| 1s | 5050MiB/s |
| 5s | 5064MiB/s |
| 10s | 5078MiB/s |
| 15s | 4759MiB/s |
| 55s | 1676MiB/s |
| 70s | 1722MiB/s |
| 90s | 1611MiB/s |
| 101s | 1463MiB/s |

## 判断

这块盘的写入行为更符合 TLC，而不是典型低端 QLC：

1. 官方规格标称 `3D TLC NAND`。
2. 200GiB 长写后仍能维持约 1.6GiB/s 稳态尾部写入。
3. 若是典型 QLC，出缓存后常见会掉到几百 MiB/s 甚至更低；本盘没有出现这种级别的崩塌。
4. 约 71GiB 的 SLC cache 与消费级高性能 TLC NVMe 的动态 SLC 行为相符。

注意：测试只能给出行为判断，不能物理证明 NAND 类型。最终确认仍应以官方规格、NAND 封装识别或拆解为准。

## 对 AI SSD 产品预研的含义

这块盘的缓存内速度看起来不错，但 AI SSD 产品不能只看前 70GiB 的 SLC cache 表现。更有价值的是出缓存后的 1.6-1.7GiB/s 稳态写入，以及 KV cache mixed workload 下的 object-level tail latency。

因此后续对候选 AI SSD 应固定报告：

| 项 | 原因 |
|---|---|
| SLC cache 大小 | 判断短 burst 写入能力 |
| cache-in speed | 判断峰值写入宣传值 |
| post-cache speed | 判断真实大写入能力 |
| steady tail speed | 判断长期服务能力 |
| KV object read/write P95/P99 | 判断 AI workload 用户侧尾延迟 |
| preconditioned fio sweep | 判断稳态而非空盘性能 |
