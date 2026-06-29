# Mooncake 源码研究文档

**目录:** `docs/mooncake-source-research/`  
**目的:** 存放对 Mooncake (`https://github.com/kvcache-ai/Mooncake.git`) 源码的研究文档  
**作者:** Claude (Opus 4) 通过 `--dangerously-skip-permissions` 模式在本机 `~/llm/Mooncake/` clone 上完成

---

## 当前文档

| 文件 | 来源 | 行数 | 状态 |
|---|---|---:|---|
| `mooncake-kv-cache-data-path-2026-06-29.md` | `~/llm/Mooncake/docs/research/kv-cache-data-path-2026-06-29.md` | 557 | ✅ 完成 |

---

## 关于图文件 (Notes on figures)

Claude 在研究过程中声明生成 4 张 PNG 图(data_path_overview / data_path_sequence / ssd_io_stack / offload_state_machine),但实际**保存到磁盘时遇到权限错误,图未持久化**。当前 markdown 报告**只用 ASCII art + mermaid diagram 表达架构**,没有 PNG 引用。

如需补图:可重跑 `claude-mooncake` 提示词并显式要求写入 `~/llm/storage/docs/mooncake-source-research/assets/`,或基于本报告 ASCII art 自行 matplotlib 重画。

---

## 报告 9 章结构

1. Multi-Tier Architecture Overview (4 tier cache hierarchy)
2. SSD Offload Write Path (Prefill → SSD)
3. SSD Promotion Read Path (Decode → SSD → DRAM)
4. Remote RDMA Transfer Path (Cross-Node KV Cache)
5. **GPUDirect Storage Investigation** (本报告核心)
6. Data Path Boundaries and Zero-Copy Analysis
7. I/O Optimization Techniques (O_DIRECT / io_uring / vectored I/O)
8. Performance Characteristics (latency / cache hit rate impact)
9. Configuration Reference (env vars / tuning params)

---

## 关键结论 (Executive Summary)

1. **生产 SSD offload 路径不用 GPUDirect Storage** — 用 `cudaMemcpy` 做 GPU→Host staging 后再写 SSD
2. **GDS 只在 Transfer Engine 的 NVMe-oF 路径出现**,本地 SSD offload 没有
3. **生产路径是 cudaMemcpy + io_uring/pwritev** — 针对 batching 和 O_DIRECT alignment 优化
4. **Zero-copy 只在 Host↔SSD 和 Host↔RDMA 边界**,GPU↔SSD 一定有 1 次 cudaMemcpy

---

## 重新生成流程 (如果需要重跑)

```bash
# 1. 确保 Mooncake 源码已 clone
test -d ~/llm/Mooncake || git clone https://github.com/kvcache-ai/Mooncake.git ~/llm/Mooncake

# 2. 启动 Claude (already running at session `claude-mooncake`)
tmux attach -t claude-mooncake

# 3. 给 Claude 提示词 (示例)
#    "Read ~/llm/Mooncake/mooncake-store/src/file_storage.cpp, draw the
#     data path diagram as PNG into ~/llm/storage/docs/mooncake-source-research/assets/"

# 4. 或者直接用 mermaid + ASCII art 替代 (当前方案)
```