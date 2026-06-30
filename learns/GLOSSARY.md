# Glossary - Mooncake KV Cache & SSD Terms

## Core Concepts

**KV Cache** - Key-Value cache storing attention keys and values from transformer layers to avoid recomputation during LLM decoding phase

**Prefill** - Initial phase of LLM inference where input prompt is processed to generate KV cache

**Decode** - Generation phase where model produces output tokens one at a time, reusing KV cache

**PD Disaggregation** - Prefill-Decode disaggregation; separating prefill and decode workloads onto different GPU clusters

## Mooncake Architecture

**Mooncake Store** - Distributed KV cache storage engine using RDMA for cross-node data transfer

**Transfer Engine** - High-performance data movement framework supporting RDMA, TCP, NVMe-oF and other protocols

**Master Service** - Centralized metadata service managing object allocation, replication, and eviction

**Client** - Dual-role component that both issues requests and hosts memory segments for distributed storage

**Real Client** - Client instance that owns physical memory/SSD resources and handles data I/O

**Dummy Client** - Lightweight client that forwards requests to a real client without owning resources

## Storage Hierarchy

**Tier 1 (GPU VRAM)** - Fastest tier; 40-80GB per GPU; <1μs latency

**Tier 2 (Host DRAM)** - Local CPU memory; 100-500GB per node; ~10μs latency

**Tier 3 (Remote DRAM)** - Distributed memory pool accessed via RDMA; ~50-100μs latency

**Tier 4 (Local SSD)** - NVMe SSD storage; multi-TB capacity; 1-5ms latency

## SSD Offload Components

**FileStorage** - Component managing local SSD offload within real client

**Heartbeat Thread** - Background thread that receives offload tasks from master and executes SSD writes

**ClientBuffer** - Pre-registered staging buffer for zero-copy reads from SSD

**StorageBackend** - Abstract interface for on-disk layout; implemented by BucketStorageBackend, FilePerKey, etc.

**BucketStorageBackend** - Default backend grouping multiple objects into bucket files to reduce file count

**Offload** - Moving data from memory (DRAM) to SSD

**Promotion** - Moving data from SSD back to DRAM for faster access

## I/O Technologies

**io_uring** - Linux async I/O interface providing low-latency, high-throughput SSD access

**O_DIRECT** - File open flag bypassing page cache for deterministic latency; requires 4KB alignment

**Vectored I/O** - preadv/pwritev syscalls allowing multiple buffers in single operation

**Zero-Copy** - Data transfer without intermediate copying (e.g., RDMA, O_DIRECT DMA)

**GPUDirect Storage (GDS)** - NVIDIA technology for direct GPU-to-SSD transfer; NOT used in Mooncake's SSD offload

**Fixed Buffer Registration** - io_uring optimization pre-registering buffers to avoid per-I/O pinning overhead

## Memory Management

**BufferAllocator** - Component managing memory allocation within registered segments

**OffsetBufferAllocator** - Default allocator with O(1) allocation and minimal fragmentation

**Replica** - One copy of an object stored in a specific segment

**Segment** - Contiguous memory region registered with master for allocation

**Slice** - Contiguous chunk of memory; objects may be split into multiple slices

## Eviction & Lifecycle

**LRU Eviction** - Least Recently Used policy; evicts objects with oldest access time

**Lease** - Time-limited protection preventing object removal during active reads

**Soft Pin** - Priority protection; soft-pinned objects evicted only when no alternatives

**Hard Pin** - Permanent protection; hard-pinned objects never evicted (e.g., model weights)

**Zombie Object** - Object in incomplete state after client crash; cleaned up via timeout

## Performance Metrics

**TTFT** - Time To First Token; measures prefill latency

**Throughput** - Tokens per second generated across all requests

**Cache Hit Rate** - Percentage of KV cache queries satisfied without recomputation

**Bandwidth Utilization** - Fraction of theoretical maximum bandwidth achieved (e.g., 87 GB/s on 4×200 Gbps RDMA)

## Protocols & Transport

**RDMA** - Remote Direct Memory Access; zero-copy network transfer via InfiniBand or RoCE

**RoCE** - RDMA over Converged Ethernet

**NVMe-oF** - NVMe over Fabrics; remote NVMe access over network

**Multi-NIC Aggregation** - Using multiple network interfaces for bandwidth pooling

**Topology-Aware Routing** - Selecting optimal network path based on NUMA affinity
