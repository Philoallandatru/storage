# LMCache 学习资源 - AI SSD 预研

本目录包含完整的 LMCache 学习资源，专为 AI SSD 预研准备。

## 📚 文档索引

### 核心学习文档
- **[INDEX.md](INDEX.md)** - 完整资源导航和学习路径
- **[MISSION-AI-SSD.md](MISSION-AI-SSD.md)** - AI SSD 预研学习目标
- **[GLOSSARY.md](GLOSSARY.md)** - 术语表

### LMCache 存储后端
1. **[lmcache-storage-backends.md](lmcache-storage-backends.md)** (23KB) - 10+ 种存储后端完整指南
2. **[architecture-diagrams.md](architecture-diagrams.md)** (31KB) - 架构图表集
3. **[gds-quick-reference.md](gds-quick-reference.md)** - GDS 快速参考

### PCIe P2P 专题
1. **[pcie-p2p-quick-reference.md](pcie-p2p-quick-reference.md)** - 快速参考卡片
2. **[pcie-p2p-learning-summary.md](pcie-p2p-learning-summary.md)** - 完整学习总结
3. **[html/pcie-p2p-guide.html](html/pcie-p2p-guide.html)** - 精美 HTML 版本 ⭐

### 学习记录
- **[learning-records/0001-lmcache-storage-backends-overview.md](learning-records/0001-lmcache-storage-backends-overview.md)**
- **[learning-records/0002-gds-backend-hardware-setup.md](learning-records/0002-gds-backend-hardware-setup.md)** (14KB)
- **[learning-records/0003-pcie-p2p-deep-dive.md](learning-records/0003-pcie-p2p-deep-dive.md)**

## 🚀 快速开始

### 查看 HTML 版本（推荐）
```bash
# 在浏览器中打开
xdg-open /home/ficus/llm/storage/lmcache-learning/html/pcie-p2p-guide.html

# 或直接访问
file:///home/ficus/llm/storage/lmcache-learning/html/pcie-p2p-guide.html
```

### 命令行阅读
```bash
# 快速参考
cat pcie-p2p-quick-reference.md

# 完整指南
less lmcache-storage-backends.md

# 学习总结
less pcie-p2p-learning-summary.md
```

## 📊 内容总览

| 主题 | 文档数 | 总大小 | 关键内容 |
|------|--------|--------|----------|
| 存储后端 | 3 | ~58 KB | 10+ 种后端详解，数据流图 |
| PCIe P2P | 4 | ~40 KB | 工作原理，硬件要求，CMB |
| GDS 配置 | 2 | ~18 KB | 硬件配置，故障排查 |
| 学习记录 | 3 | ~24 KB | 核心洞察，非显而易见知识 |

## 🎯 学习路径

### 快速入门（30 分钟）
1. 阅读 `pcie-p2p-quick-reference.md`
2. 浏览 `architecture-diagrams.md` 图表 1-6
3. 打开 `html/pcie-p2p-guide.html` 查看可视化内容

### 深入理解（2-3 小时）
1. 完整阅读 `lmcache-storage-backends.md`
2. 学习 `learning-records/0003-pcie-p2p-deep-dive.md`
3. 阅读 `learning-records/0002-gds-backend-hardware-setup.md`

### AI SSD 预研专项（1 天）
1. 研读所有学习记录
2. 理解 CMB、P2P、GDS 的关系
3. 制定 AI SSD 技术路线图

## ✅ 核心知识点

### PCIe P2P
- 延迟降低：**10-200 倍**（1-10ms → 50-100μs）
- 带宽提升：**2-3 倍**（2-3 GB/s → 5-7 GB/s）
- CPU 开销降低：**30 倍**（10-30% → <1%）

### AI SSD 必需条件
- ✅ PCIe Gen4 x4 或更高
- ✅ 支持 P2PDMA
- ✅ 1-4 GB CMB
- ✅ 兼容 cuFile/hipFile

### 性能目标
- 延迟：< 100 μs（理想 < 50 μs）
- 带宽：> 5 GB/s（理想 > 7 GB/s）
- IOPS：> 100K (4KB 随机读)

## 📞 文档说明

这些文档由 Claude Opus 4.8 创建于 2026-06-30，专为 AI SSD 预研提供技术支持。

所有内容基于 LMCache 开源项目的实际代码和设计文档：
- 源代码：`/home/ficus/llm/LMCache`
- 官方文档：`/home/ficus/llm/LMCache/docs`

## 🔗 相关资源

- **LMCache GitHub**: https://github.com/LMCache/LMCache
- **NVIDIA GPUDirect Storage**: https://docs.nvidia.com/gpudirect-storage/
- **Linux P2PDMA**: https://www.kernel.org/doc/html/latest/driver-api/pci/p2pdma.html
- **NVMe 规范**: https://nvmexpress.org/specifications/

---

**最后更新**: 2026-06-30
