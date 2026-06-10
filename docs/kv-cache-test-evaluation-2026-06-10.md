# KV Cache Cross-Vendor Test — Critical Evaluation

**Date**: 2026-06-10
**Scope**: Methodology review of `docs/kv-cache-cross-vendor-2026-06-10.md`
**Verdict**: Data is internally consistent and the per-disk ranking is robust,
but several parameter choices mean **the test is not measuring realistic
production LLM inference KV cache traffic**. The headline result (Biwin wins)
is correct; the absolute numbers should not be cited as production predictions.

---

## P0 — Critical methodological issues

### Issue 1: `--gpu-mem-gb 0 --cpu-mem-gb 0` skips the tier cascade

**What we did**: Disabled GPU and CPU tiers entirely, forcing 100 % of reads
and writes to land on NVMe.

**Why it's wrong**: In real LLM inference the KV cache waterfall is
**GPU HBM → CPU DRAM → NVMe**, and only the *spillover* touches NVMe. By
disabling the upper tiers we measure the NVMe as if it were the *only*
storage tier in the system. Real-world NVMe traffic would be:

- **Much lower volume** — maybe 5–20 % of total cache touches (the rest hit
  HBM or DRAM)
- **Much more skewed** — long-tail reads of old conversations, large
  sequential spills during prefill of big prompts
- **Different I/O shape** — fewer small random reads, more large sequential
  writes during prefill

**Impact**: Our read P99 numbers (~14 ms for Biwin K1) are likely *better*
than production (because we always do cold reads with no in-memory cache),
and our throughput numbers (7,157 tok/s Biwin K4) are likely *worse* than
production (because we have no HBM to absorb the hot path).

**Fix**: Set `--gpu-mem-gb 80 --cpu-mem-gb 80` for an 80 GB H100 + 80 GB
DRAM tier, which matches a single-H100 inference box. Re-run K2 and K4.

### Issue 2: `--trace-speedup 1000` compresses 33 hours of trace into 120 s

**What we did**: Replayed the BurstGPT trace at 1000× wall-clock speed.

**Why it's wrong**: At 1000×, every 120 s run represents ~33 hours of
realistic user traffic. This means:

- Each disk is asked to handle ~33 h of requests in 2 minutes
- Request rate per "wall second" is 1000× higher than real production
- The trace's *natural* request spacing is destroyed — burst patterns are
  preserved but inter-arrival times collapse

The 98 % cache hit rate we see is suspicious under this regime — at real
time the same trace would have lower hit rate because there'd be time
for cache eviction pressure to build up.

**Impact**: The KV cache is "hot" because all the data fits in the
unbounded cache dir and the trace replays fast enough that nothing ages
out. Real production hit rate with bounded cache dir + realistic time
would be lower, and the bottleneck would shift to *eviction policy* not
storage throughput.

**Fix**: Drop `--trace-speedup` to **1.0–10×**. At 10×, each 120 s run
represents ~20 min of real traffic, which is more realistic.

### Issue 3: `--max-concurrent-allocs 2` limits concurrency to 2

**What we did**: Set concurrent allocations to 2 regardless of `--num-users`.

**Why it's wrong**: With 16 users, the natural concurrent allocation rate
should be ~16 (one per user). Limiting to 2 means:

- The KV cache subsystem queues requests
- Storage traffic is throttled artificially
- We measure storage throughput under *lightly-loaded* queue depth
- High `--num-users` tests become "16 users waiting in a queue of 2"
  rather than "16 users concurrently loading the disk"

**Impact**: This **suppresses the actual stress** we want to apply to
NVMe at high concurrency. WD's K4 P99 of 328 ms is bad — but if we let
it actually run with 16 concurrent allocs it could be much worse (or much
better, if the host-side queue smooths it).

**Fix**: Remove the `--max-concurrent-allocs 2` cap, OR set it to
`--num-users` value (allow full concurrency).

---

## P1 — Important caveats

### Issue 4: `--cache-dir` has no size limit

We never set a max KV cache size, so the cache_dir grew unbounded during
each run. This means:

- Total reads per run reached 200–500 GB
- All disk activity fits comfortably in cache
- "Miss rate" is artificially low because nothing is ever evicted

**Real production** would have a bounded KV cache pool (e.g. 100–500 GB)
and the hit rate would be set by the eviction policy interacting with
the working set size. We didn't measure that interaction.

**Fix**: Use `--storage-capacity-gb 200` to bound the cache.

### Issue 5: `--replay-cycles 0` — single replay only

We replayed the trace once per run. With `trace-speedup=1000` this means
the burst rate *during* the run is huge, but the *total volume* per run
is just one copy of the trace. For GC back-pressure to matter (T3/T4
showed GC is a huge factor), we need to write enough total data to fill
SLC + drive down to TLC. We did ~40 GB writes per Biwin K5 run, which is
*less than Biwin's SLC cache* (T2 found >168 GB SLC).

**Fix**: Either run K5 for longer (600 s = 5 min) or use `--replay-cycles`
to repeat the trace multiple times.

### Issue 6: Test runs are too short for GC effects

T3/T4 of the previous cross-vendor characterization showed GC drift
takes ~5–15 minutes to manifest. Our K1–K4 runs are 120 s (2 min) — far
too short to see GC back-pressure. Only K5 (180 s) starts to approach
the regime where GC matters.

**Impact**: Biwin's *burst* performance dominates the results, while
T3/T4 already showed Biwin's sustained throughput collapses by 30 % under
15-min GC pressure. **In a realistic long-running inference server
scenario, Biwin's lead over ZhiTai would shrink substantially**.

---

## P2 — Minor issues

### Issue 7: BurstGPT trace is single workload

We used only the BurstGPT trace (Azure OpenAI chat). Real LLM inference
serves:
- Code completion (long prefill, short decode)
- Document Q&A (very long prefill, very short decode)
- Multi-turn chat (prefill + decode cycle, prefix cache heavy)
- Batch jobs (prefill-heavy, no decode)

BurstGPT is chat-only. Code/RAG workloads would have very different
storage traffic shape (more prefill writes, fewer decode reads).

**Fix**: Add ShareGPT trace workload (`fio_sharegpt_*.ini` already in
results/kvcache-profile/) and rerun K2/K4 with it.

### Issue 8: No warm-up phase

We ran each scenario directly after `--drop_caches`. Real production
servers have hot caches that have been warming for hours. The first
10–20 s of each run is colder than steady-state.

**Fix**: Add a 30 s warm-up, exclude its metrics from the summary (use
`--enable-latency-tracing` already supports this via trace timestamps).

### Issue 9: `direct=1` is implicit (we didn't set it)

KV cache benchmark likely uses buffered I/O by default. With page cache
hot, reads may be served from DRAM not from disk. Combined with
`--cache-dir` unbounded, this can hide actual NVMe load.

**Fix**: Force O_DIRECT for the storage tier reads (need to check if
kv-cache.py supports this).

### Issue 10: Single seed

We ran with `--seed 42` only. BurstGPT trace replay is deterministic
given the trace + speedup + seed, so this is actually fine — but a
second seed would catch any seed-dependent pathology.

---

## What the data DOES tell us reliably

Despite the above issues, several conclusions are **robust**:

1. **Biwin X570 has the best storage controller for small random R/W at
   high concurrency** — visible in K3/K4 with 48 ms / 60 ms read P99.
   This ranking matches T5 (4K random IOPS at QD=64) where Biwin was
   also the best DRAM-equipped drive. The lead is real and not a
   measurement artifact.

2. **ZhiTai's write tail collapses under 70B** — 1,073 ms write P99
   in K5 vs Biwin's 28 ms is so extreme (38×) that even with realistic
   5× improvement from page cache, ZhiTai would still be ~7× worse than
   Biwin on write tail. The conclusion "avoid ZhiTai for large models"
   stands.

3. **WD SN570 saturates under concurrency** — 3,500 tok/s plateau from
   K2 to K4 is a real bottleneck, not a measurement artifact. Even with
   HBM tier absorbing some load, DRAM-less WD would still trail DRAM-
   equipped drives.

4. **Seagate FC530 is the strongest 70B alternative to Biwin** — 28 ms
   write P99 ties Biwin, and 2,012 tok/s is within 25 % of Biwin's
   2,521 tok/s. The T6 mixed R/W lead transfers to KV cache large
   models.

5. **Cache hit rate ~98 % across all drives** — this is robust because
   it depends on the *trace*, not the disk. The 2–3 % miss path is
   where the disk differentiation lives, and that's exactly where the
   tail latency differences show up.

---

## Recommended follow-up runs

A v2 test should add (in priority order):

| Priority | Change | Estimated wall time |
|---|---|---|
| P0 #1 | Add GPU + CPU tiers (`--gpu-mem-gb 80 --cpu-mem-gb 80`) | +36 min |
| P0 #2 | Drop `--trace-speedup` to 10× | +30 min (longer wall = more trace per run) |
| P0 #3 | Remove `--max-concurrent-allocs` cap | +36 min |
| P1 #4 | Bound `--storage-capacity-gb` to 200 GB | +36 min |
| P1 #5 | Extend K5 to 600 s for GC effects | +12 min |
| P2 #7 | Add ShareGPT trace | +30 min |
| **Total** | v2 with all P0 + P1 fixes | **~3 hours** |

The v1 results in `docs/kv-cache-cross-vendor-2026-06-10.md` should be
**retained for the burst-characterization use case** (which is what they
actually measured), but should be **rebranded** to make this scope
explicit, and a v2 run with the fixes should supersede them for any
production-capacity claims.

---

## Bottom line

**The relative ranking is correct**: Biwin > Seagate ≥ ZhiTai > WD for
KV cache workloads is the right call.

**The absolute numbers are inflated**: tok/s numbers are likely
*lower* than production (no HBM tier), and tail latency is likely
*better* than production (cold reads are easier than mixed hit/miss
traffic).

**Don't cite these numbers as production predictions** without running
the v2 test with realistic tier configuration.