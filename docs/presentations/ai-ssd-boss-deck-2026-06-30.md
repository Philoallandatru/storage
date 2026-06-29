# AI SSD Boss Deck

Generated deck: `docs/presentations/ai-ssd-boss-deck-2026-06-30.pptx`

## Slide Outline

### 1. AI SSD 产品预研

开场只讲一个判断：AI SSD 的卖点不是峰值顺序带宽，而是上下文数据在长时间服务中的稳定性。

### 2. 为什么需要 AI SSD

这页解释战略背景：KV cache 从临时显存状态变成可迁移、可复用的 context memory。

### 3. 真实 I/O 画像

数据页：读写分裂。read 是随机压力源，write 是 GC 污染源。

### 4. 三类 workload

这页避免老板把 fio、ShareGPT、BurstGPT混为一谈。

### 5. 长稳态 token/s

这页按你之前问的 token/s 曲线做：一页只讲长稳态会拖垮吞吐。

### 6. GC cliff

这页讲选型逻辑：短测排名会失真。

### 7. SLC cache

这页回应 TLC/QLC 消费级 SLC cache：方向有价值，但要从 burst buffer 变成 context buffer。

### 8. Mooncake path proof

这页讲方法论：系统级收益必须先证明数据真的走 SSD。

### 9. GDS

这页讲未来路径：值得做，但必须实测，不能把配置当结果。

### 10. 产品设计

这页把设计收敛成三类产品路线。

### 11. AI SSD v1.0 需求

这页给出需求清单，适合老板拍下一阶段资源。

### 12. 下一步

收尾：建议继续投入，但不要过早承诺型号或最终 SLO。
