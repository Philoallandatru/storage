# AI SSD 产品预研简报：面向 LLM KV Cache 的机会、实验结论与下一步方向

日期：2026-06-15

本文面向管理层汇报，尽量避免过多底层细节。核心问题是：随着大模型上下文变长、并发变高，GPU 显存放不下所有 KV Cache，SSD 会逐步进入推理链路。AI SSD 的机会不是做一块“顺序读写更快的盘”，而是做一块能稳定承载 LLM KV Cache 的存储设备。

## 1. 一句话结论

**AI SSD 的关键价值在于：在 GPU/CPU 内存不够时，把长上下文和多用户推理产生的 KV Cache 稳定、低延迟地放到 SSD 上，同时不让用户感受到明显卡顿。**

我们现有实验说明：

| 结论 | 对产品的含义 |
|---|---|
| KV Cache I/O 不是普通顺序读写，而是约 115-125kB 的离散大块随机读写 | 不能只看 SSD 标称顺序带宽 |
| 2 分钟短测和 20-30 分钟长测结论不同 | 产品验证必须加入长稳态和 GC 测试 |
| BIWIN X570 短时性能强，Seagate FC530 长稳态更稳 | AI SSD 需要区分 burst 能力和持续服务能力 |
| ZhiTai Ti600、WD SN570 不适合作为主力 KV Cache SSD | 低成本盘或普通消费级盘不一定适合 AI serving |
| 用户体验受 P95/P99 尾延迟影响，而不是平均速度 | 产品指标应强调 tail latency 和服务稳定性 |

## 2. 通俗解释：KV Cache 是什么，为什么会压到 SSD

大模型生成答案时，每生成一个 token 都要参考前面的上下文。为了避免反复计算，系统会把历史上下文的中间状态保存下来，这就是 KV Cache。

可以把 KV Cache 理解成：

| 类比 | 含义 |
|---|---|
| 会议纪要 | 模型不用重新听完整会议，只查前面已经整理好的要点 |
| 浏览器缓存 | 重复访问相同内容时，不用重新下载 |
| 推理过程中的“短期记忆” | 上下文越长、用户越多，短期记忆越大 |

问题是：这份“短期记忆”很大。短上下文可以放在 GPU 显存里；长上下文、多轮对话、多用户并发时，就需要分层放到 GPU、CPU 内存、SSD，甚至远端节点。

## 3. 我们实验看到的 I/O 特点

从 iostat 和 KV Cache benchmark 结果看，KV Cache offload 的 I/O 形态非常明确：

| 指标 | 实验结果 |
|---|---|
| 读请求大小 | 约 124-125kB |
| 写请求大小 | 约 113-116kB |
| 读请求合并率 | `%rrqm ≈ 0%` |
| I/O 类型 | sparse-large-block random I/O，离散大块随机读写 |
| 长稳态风险 | GC cliff 和周期性卡顿 |

这说明它不是传统的“连续读大文件”，也不是传统数据库的“小 4K 随机读”。它更像是：系统不断从 SSD 的不同位置取出一块块比较大的 KV Cache，再写入新的 cache 块。

对 SSD 产品的直接要求：

| 产品能力 | 为什么重要 |
|---|---|
| 随机大块读稳定 | decode 阶段要持续读历史 KV |
| mixed R/W 稳定 | prefill 写和 decode 读会同时发生 |
| GC 不阻塞前台读 | 后台整理不能让用户请求卡住 |
| P99 延迟稳定 | 用户感受到的是最慢那几次请求 |
| 长时间不掉速 | 推理服务不是 2 分钟跑分，而是长期在线 |

## 4. 当前实验结果对产品方向的启发

### 4.1 单盘对比结论

| 盘 | 短时表现 | 长稳态表现 | 产品判断 |
|---|---|---|---|
| BIWIN X570 | 最强，K4 120s 读 3.14GB/s | 30min 后约 1.57GB/s | 适合 burst 和短会话 |
| Seagate FC530 | 短时不如 BIWIN | 30min 后约 1.54GB/s，写尾更稳 | 更适合 sustained serving |
| ZhiTai Ti600 | 短时读侧可看 | 写 P99 可到 600-850ms | 不推荐作主力 |
| WD SN570 | 整体偏弱 | DRAM-less，tail 差 | 只适合低压 overflow |

重点不是“谁绝对第一”，而是：**短时冠军和长期服务冠军可能不是同一块盘。**

### 4.2 30 分钟测试带来的新认识

在 2 分钟短测中，BIWIN 明显领先；但到了 20-30 分钟，BIWIN 和 Seagate 收敛到接近水平。原因是 SSD 的 SLC cache 和 GC 会逐步进入稳态，短时高峰值不能代表长期服务。

这对 AI SSD 很关键：

| 如果只测 | 会误判 |
|---|---|
| 顺序读写峰值 | 以为带宽越高越好 |
| 2 分钟短测 | 以为 burst 盘就是 serving 盘 |
| 平均吞吐 | 忽略 P99 卡顿 |
| 空盘测试 | 忽略真实生产的 GC 和磨损状态 |

## 5. 结合真实 LLM KV Cache 系统看行业趋势

外部系统和论文也在指向同一个方向：KV Cache 正在成为 LLM serving 的核心数据层。

| 系统/方向 | 主要思想 | 对 AI SSD 的启发 |
|---|---|---|
| vLLM / PagedAttention | 把 KV Cache 切成固定块管理，减少显存浪费 | KV 会天然碎片化，SSD 要适应非连续访问 |
| Mooncake | Kimi 使用的 KVCache-centric 解耦架构，分离 prefill 和 decode，并利用 CPU/DRAM/SSD 做分布式 KV Cache | SSD 不再只是本地盘，而是 serving 系统的一层 cache |
| LMCache | 面向 vLLM/SGLang 的 KV Cache 层，支持 prefix reuse、跨 engine 共享、offload 和 prefill-decode disaggregation | AI SSD 应支持高效批量迁移、缓存命中、显存/内存/SSD 协同 |
| SGLang HiCache / Strata 类层级缓存 | 面向长上下文的分层缓存和 cache-aware scheduling | 需要测“缓存加载时间”对 TTFT 的影响 |
| Tutti | 关注 SSD-backed KV Cache 的 CPU 瓶颈和碎片 I/O，提出 GPU-centric KV object store | 未来 AI SSD 可能要配合 GDS/GPU io_uring 等 GPU 直连路径 |
| TENT / Mooncake TE | 在解耦式 serving 中优化跨节点数据搬运 | 多盘和网络传输会一起决定 KV Cache 性能 |

通俗地说，未来 LLM serving 不是“GPU 算完就结束”，而是一个围绕 KV Cache 搬运、复用、淘汰、调度的系统。AI SSD 如果要进入这个系统，必须从“硬盘跑分”变成“KV Cache 数据层能力”。

## 6. AI SSD 应该怎么定义产品指标

建议不要把 AI SSD 的核心卖点写成“顺序读 14GB/s、顺序写 12GB/s”。这些指标有用，但不足以说明它适合 LLM。

更适合的指标：

| 指标 | 建议表达 |
|---|---|
| KV object read P95/P99 | 真实 LLM KV Cache 读尾延迟 |
| KV object write P95/P99 | prefill/eviction 写尾延迟 |
| mixed R/W 稳定性 | 90/10、70/30、50/50 混合读写 |
| 长稳态 drift | 30/60/120 分钟吞吐和延迟是否下滑 |
| GC stall | 是否出现分钟级掉速或卡顿 |
| cache reload TTFT | 从 SSD 恢复长上下文对首 token 延迟的影响 |
| 多盘扩展效率 | 2/4/8 盘是否接近线性扩展 |
| page cache/HBM 协同 | GPU/CPU/SSD 分层后实际减少多少 SSD 压力 |

## 7. 下一阶段测试建议

### 7.1 必做测试

| 测试 | 目的 | 业务价值 |
|---|---|---|
| 30min 3-run median | 确认 BIWIN/Seagate 是否真的等价 | 避免单次波动误导选型 |
| 60/120min 长稳态 | 看 GC stall 是否持续恶化 | 判断是否可用于在线服务 |
| HBM/DRAM tier enabled | 模拟真实 GPU/CPU/SSD 分层 | 从 worst-case 转向真实部署 |
| Bounded cache capacity | 限制 cache 池大小，触发真实 eviction | 更接近生产 |
| mixed checkpoint + KV Cache | 模拟训练/推理节点同时写 checkpoint 和服务请求 | 验证写放大风险 |

### 7.2 结合 Mooncake / HiCache / LMCache 的测试

| 场景 | 怎么测 | 重点指标 |
|---|---|---|
| Prefill-decode disaggregation | 分离 prefill 写和 decode 读，再加入 KV transfer | TTFT、decode latency、cache transfer BW |
| Prefix cache reuse | 多用户共享相同系统 prompt 或长文档前缀 | cache hit rate、SSD read P99、吞吐提升 |
| Long-context reload | 从 SSD 恢复 32K/64K/128K 上下文 | 首 token 延迟、GPU stall 时间 |
| KV cache migration | 跨 GPU/跨节点迁移 cache | 网络+SSD 共同瓶颈 |
| Cache eviction pressure | 限制 SSD cache 容量，强制淘汰 | miss rate、write P99、服务抖动 |
| Compression + SSD | 模拟 KV cache 量化/压缩后再落盘 | 容量节省 vs 解压延迟 |
| Multi-tenant serving | 多租户/多模型同时访问 KV cache | tail latency 隔离、QoS |

### 7.3 多盘测试

| 测试 | 为什么要做 |
|---|---|
| 1/2/4 盘 scaling | 看 AI SSD 是否能按盘数扩展 |
| RAID0 vs 应用级分片 | 判断透明条带还是 KV-aware placement 更好 |
| 异构盘混合 | 验证最慢盘是否拖垮整体 |
| 读写分盘 | prefill 写和 decode 读隔离，降低互扰 |
| GC stall overlap | 多盘是否会同时掉速 |

## 8. 产品预研方向建议

### 方向一：KV Cache 专用 SSD 指标体系

建立一套不同于普通 SSD 的 AI SSD benchmark：

| 层级 | 指标 |
|---|---|
| 设备层 | 100-128kB random read/write P99、mixed R/W、GC drift |
| KV 层 | KV object P95/P99、cache reload TTFT、eviction write P99 |
| 系统层 | HBM/DRAM/SSD hit rate、E2E latency、QoS compliance |
| 多盘层 | scaling efficiency、per-disk skew、slowest-disk tail |

### 方向二：面向长上下文服务

长上下文是 AI SSD 的天然场景。普通聊天的 KV Cache 不一定压到 SSD，但 32K、64K、128K 长上下文会明显放大 SSD 价值。

建议重点测试：

| 长上下文场景 | 价值 |
|---|---|
| 长文档问答 | prefix cache 重用明显 |
| 代码仓库问答 | 大上下文、多轮访问 |
| agent 工具调用 | 长对话、历史状态复用 |
| 企业知识库 | 多用户共享相同文档前缀 |

### 方向三：和推理框架协同

AI SSD 单独快不够，必须和推理框架协同：

| 框架能力 | SSD 需要支持的方向 |
|---|---|
| vLLM PagedAttention | 非连续 KV block 的高效读取 |
| LMCache | 批量 KV movement、pin/load/evict 控制 |
| SGLang HiCache / Strata | 分层缓存、cache-aware scheduling |
| Mooncake | prefill/decode 分离后的跨层 KV cache 数据面 |
| GDS/Tutti 类路径 | 减少 CPU 参与，降低 GPU stall |

### 方向四：固件与系统联合优化

AI SSD 的差异不只是 NAND，还包括 controller、firmware、队列策略和系统软件。

建议关注：

| 方向 | 说明 |
|---|---|
| read-priority GC | 后台整理不能阻塞 decode 读 |
| predictable tail | P99/P999 比峰值更重要 |
| reserved SLC / stable pSLC | 长稳态比 fresh 空盘更重要 |
| KV object batch I/O | 支持批量读取 100-128kB KV blocks |
| telemetry | 暴露 GC、throttle、write amplification、temperature |
| QoS isolation | 多租户、多模型下隔离 tail |

## 9. 建议老板关注的决策点

| 决策问题 | 建议 |
|---|---|
| 是否值得继续做 AI SSD 预研 | 值得，KV Cache 正在成为 LLM serving 的关键数据层 |
| 现在是否能直接定产品规格 | 不能，还需要 production-like tiering、多盘、长稳态和企业盘验证 |
| 当前最有价值的候选方向 | 长上下文 KV Cache offload、sustained serving、mixed R/W 稳定性 |
| 当前实验最强结论 | AI SSD 不能只看顺序峰值，必须看 KV object tail 和长稳态 GC |
| 下一阶段投入 | 先做 60/120min + HBM/DRAM tier + 多盘分片，再考虑企业级样盘 |

## 10. 建议的对外表述

可以这样对外或对老板概括：

> 我们已经完成第一轮 AI SSD / KV Cache 预研。实验表明，LLM KV Cache 对 SSD 的压力不是传统顺序读写，而是 100KB 级随机大块读写，并且 2 分钟短测和 30 分钟稳态结果会显著不同。因此 AI SSD 的产品指标应从“峰值带宽”转向“KV object tail latency、长稳态 GC、mixed R/W、多盘扩展”。下一阶段建议围绕真实推理框架中的分层 KV Cache、长上下文恢复、prefill-decode 解耦和多盘系统展开验证。

## 参考资料

| 资料 | 说明 |
|---|---|
| Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving, arXiv 2407.00079, <https://arxiv.org/abs/2407.00079> | Mooncake/Kimi 的 KVCache-centric 解耦式 serving 架构 |
| LMCache: An Efficient KV Cache Layer for Enterprise-Scale LLM Inference, arXiv 2510.09665, <https://arxiv.org/abs/2510.09665> | vLLM/SGLang KV Cache offload、共享和 orchestration |
| PagedAttention / vLLM, <https://arxiv.org/abs/2309.06180> | KV Cache block 化管理，是当前主流 serving 机制之一 |
| Strata: Hierarchical Context Caching for Long Context Language Model Serving, arXiv 2508.18572, <https://arxiv.org/abs/2508.18572> | SGLang 上的长上下文层级缓存和 cache-aware scheduling |
| Tutti: Making SSD-Backed KV Cache Practical for Long-Context LLM Serving, arXiv 2605.03375, <https://arxiv.org/abs/2605.03375> | SSD-backed KV Cache 的 GPU-centric I/O 方向 |
| TENT: A Declarative Slice Spraying Engine for Disaggregated LLM Serving, arXiv 2604.00368, <https://arxiv.org/abs/2604.00368> | Mooncake/SGLang HiCache 相关的跨互联数据搬运方向 |
