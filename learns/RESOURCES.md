# Learning Resources - Mooncake KV Cache & SSD

## Primary Sources (High Trust)

### 1. Academic Papers
- **[FAST'25 Paper](https://www.usenix.org/system/files/fast25-qin.pdf)** - "Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving"
  - Best Paper Award winner
  - Sections 4-6 cover storage architecture and evaluation
  - Figure 8: Multi-tier storage hierarchy
  - Table 3: Performance comparison with/without SSD offload

### 2. Official Documentation (In This Repo)
- **[docs/source/design/ssd-offload.md](docs/source/design/ssd-offload.md)** - Complete SSD offload design spec
  - Architecture diagrams
  - Data flow (offload & promotion paths)
  - Storage backend comparison
  - io_uring optimization details
  
- **[docs/source/design/mooncake-store.md](docs/source/design/mooncake-store.md)** - Mooncake Store architecture
  - Master-Client model
  - Buffer allocator design
  - Eviction policies
  - Multi-layer storage support

- **[docs/research/kv-cache-data-path-2026-06-29.md](docs/research/kv-cache-data-path-2026-06-29.md)** - Deep-dive analysis
  - Complete data path from GPU to SSD
  - GPUDirect Storage investigation (conclusion: NOT used)
  - Performance characteristics table
  - Source code references

### 3. Performance Benchmarks
- **docs/source/performance/ssd-offload-benchmark-results.md** - Multi-turn conversation results
  - Cache hit rate: 36% → 84% with SSD
  - TTFT improvement: 16s → 9.4s (41% reduction)
  - Throughput: 2.4× improvement

- **docs/source/performance/allocator-benchmark-result.md** - Memory allocator comparison
  - Utilization rates under various workloads
  - Allocation latency (O(1) vs O(log n))

### 4. Source Code (Ground Truth)
Key files for data path understanding:
- `mooncake-store/src/file_storage.cpp` - Main SSD offload logic
  - Lines 364-567: OffloadObjects() with GPU staging detection
  - Lines 687-833: ProcessPromotionTasks() (SSD→DRAM)
  
- `mooncake-store/src/storage_backend.cpp` - Bucket backend implementation
  - BatchOffload/BatchLoad methods
  
- `mooncake-store/src/uring_file.cpp` - io_uring optimized file I/O
  - Thread-local rings
  - Fixed buffer registration
  
- `mooncake-store/include/gpu_staging_utils.h` - GPU pointer detection
  - IsDevicePointer() using cudaPointerGetAttributes()

## Technical Background

### Linux I/O Stack
- **[io_uring Documentation](https://kernel.dk/io_uring.pdf)** - Jens Axboe's whitepaper
- **[O_DIRECT Performance](https://www.kernel.org/doc/Documentation/filesystems/direct-io.txt)** - Kernel docs on direct I/O

### GPU-Storage Interaction
- **[NVIDIA GPUDirect Storage Docs](https://docs.nvidia.com/gpudirect-storage/)** - GDS programming guide
  - Note: Mooncake does NOT use GDS for local SSD, but understanding it helps
- **[CUDA Memory Management](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#memory-management)** - cudaMemcpy behavior

### RDMA & Networking
- **[RDMA Aware Networks Programming Guide](https://www.rdmamojo.com/)** - Community resource
- **Transfer Engine design docs** in `mooncake-transfer-engine/`

## Related LLM Serving Systems

### Integration Examples
- **[SGLang HiCache](https://lmsys.org/blog/2025-09-10-sglang-hicache/)** - Multi-tier KV caching
- **[vLLM Disaggregated Prefill](https://docs.vllm.ai/en/latest/features/disagg_prefill.html)** - PD separation
- **[LMCache Blog](https://blog.lmcache.ai/)** - Alternative KV cache sharing approach

### Academic Context
- **[Orca (OSDI'22)](https://www.usenix.org/conference/osdi22/presentation/yu)** - Batch scheduling for LLM
- **[PagedAttention (SOSP'23)](https://arxiv.org/abs/2309.06180)** - Memory management in vLLM

## Storage System Context

### SSD Architecture
- **[LightNVM Paper](https://www.usenix.org/conference/fast17/technical-sessions/presentation/bjorling)** - Open-channel SSD
- **[F2FS Design](https://www.usenix.org/conference/fast15/technical-sessions/presentation/lee)** - Flash-friendly filesystem
- **[ZNS (Zoned Namespaces)](https://zonedstorage.io/)** - Modern SSD interface

### AI Storage Research
- **[FlashNeuron (FAST'21)](https://www.usenix.org/conference/fast21/presentation/bae)** - Training with SSD offload
- **[ZeRO-Infinity (SC'21)](https://arxiv.org/abs/2104.07857)** - NVMe offload for model training

## Hands-On Resources

### Build & Run
- **README.md** - Quick start guide
- **.claude/skills/mooncake-troubleshoot** - Diagnostic skill for deployment issues

### Profiling Tools
- **[perf](https://perf.wiki.kernel.org/)** - Linux perf for I/O profiling
- **[iostat](https://linux.die.net/man/1/iostat)** - I/O statistics
- **[nvme-cli](https://github.com/linux-nvme/nvme-cli)** - NVMe device introspection

## Community

### Discussion Channels
- **[Mooncake Slack](https://join.slack.com/t/mooncake-project/shared_invite/zt-3qx4x35ea-zSSTqTHItHJs9SCoXLOSPA)**
- **[GitHub Issues](https://github.com/kvcache-ai/Mooncake/issues)** - Bug reports and features
- **[Zhihu Blog Series](https://zhuanlan.zhihu.com/p/705754254)** - Chinese technical deep-dives (7 posts)

### Related Projects
- **[checkpoint-engine](https://github.com/MoonshotAI/checkpoint-engine)** - P2P model weight transfer
- **[TorchSpec](https://pytorch.org/blog/torchspec-speculative-decoding-training-at-scale/)** - Training/inference decoupling

## For AI SSD Pre-Research

### Workload Characterization
Priority resources for understanding AI storage workload:
1. FAST'25 paper Section 4 (Workload analysis)
2. `FAST25-release/traces/` - Real Kimi traces
3. `docs/research/kv-cache-data-path-2026-06-29.md` Section 8 (Performance characteristics)

### Design Space Exploration
Questions to explore with these resources:
- Object size distribution → impacts page allocation strategy
- Read/write ratio → affects wear leveling, over-provisioning
- Temporal locality → informs cache hierarchy design
- Latency sensitivity → P99 tail latency vs throughput tradeoff
