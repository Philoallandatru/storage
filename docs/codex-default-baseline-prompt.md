# Codex Task Prompt: Default KV-Cache Baseline (mixed prefill+decode)

**Target:** Run a single `kv-cache.py` benchmark that represents the **actual default mixed prefill+decode** behavior (no `--prefill-only` / no `--decode-only` flags), then capture the per-I/O block trace via bpftrace, and produce a small comparison-ready summary CSV.

This baseline will replace the misleading "default-kvcache" row in the three-way I/O comparison report (`docs/kv-cache-io-three-way-comparison-2026-06-29.md`). The current row was incorrectly synthesized from two separate runs (`--prefill-only 35s` + `--decode-only 60s`). The user has decided that the **real default mixed workload** is what we need.

---

## Exact command to run (DO NOT CHANGE the workload knobs — keep methodology aligned with the existing ShareGPT/BurstGPT runs in `docs/kv-cache-sharegpt-vs-burstgpt-io-2026-06-29.md`)

```bash
# 0. Activate the kv-cache venv (kv-cache.py requires this exact venv)
source ~/llm/storage/kv_cache_benchmark/.venv/bin/activate

# 1. Find python's PID FIRST (must happen before trace starts, otherwise bpftrace misses early I/O)
KV_PID=$(pgrep -f "kv-cache.py.*default-baseline" | head -1)
echo "kv-cache.py PID will be: $KV_PID"

# 2. Start bpftrace on parent device /dev/nvme0n1 (matches reference report, dev_t=271581194)
sudo /usr/bin/bpftrace ~/llm/storage/scripts/trace_block_lba.bt 271581194 > /tmp/bt-default-baseline.log 2>&1 &
BTPID=$!
sleep 1

# 3. Run kv-cache.py — DEFAULT mixed prefill+decode, NO --prefill-only, NO --decode-only
mkdir -p ~/llm/storage/results/kvcache-profile/default_baseline
~/llm/storage/kv_cache_benchmark/.venv/bin/python3 \
    ~/llm/storage/kv_cache_benchmark/kv-cache.py \
    --output ~/llm/storage/results/kvcache-profile/default_baseline/results.json \
    --model llama3.1-8b \
    --tensor-parallel 1 \
    --num-users 8 \
    --duration 120 \
    --gpu-mem-gb 0 \
    --cpu-mem-gb 0 \
    --cache-dir ~/llm/storage/results/kvcache-profile/ext4_kvcache_default_baseline \
    --storage-capacity-gb 40 \
    --xlsx-output ~/llm/storage/results/kvcache-profile/default_baseline/results.xlsx \
    > ~/llm/storage/results/kvcache-profile/default_baseline/stdout.log 2>&1
KVRUN_EXIT=$?

# 4. Stop bpftrace
sleep 2
kill -INT $BTPID 2>/dev/null
wait $BTPID 2>/dev/null

echo "kv-cache.py exit code: $KVRUN_EXIT"
ls -la /tmp/bt-default-baseline.log
```

### Why these exact knobs (do NOT change)

- **`--model llama3.1-8b --tensor-parallel 1`** — matches the ShareGPT/BurstGPT runs. Do NOT use TP=8; that's a different methodology.
- **`--num-users 8 --duration 120`** — matches ShareGPT/BurstGPT (same duration flag + same user count).
- **`--gpu-mem-gb 0 --cpu-mem-gb 0`** — forces NVMe tier; no in-GPU/CPU cache. Same as reference runs.
- **`--storage-capacity-gb 40`** — storage cap, matches reference.
- **NO `--prefill-only` and NO `--decode-only`** — this is the critical change. Default mixed mode.
- **NO `--disable-multi-turn`** — it triggers a dataset-mode bug in this checkout (per the existing report). Leave multi-turn enabled.

If `llama3.1-8b` is rejected as an unknown model, report that and stop. Do not substitute another model.

---

## Step 2: Post-process the bpftrace log into the same CSV format as the reference runs

The existing reference data lives in:
- `~/llm/storage/results/kvcache-profile/sharegpt_kvcache_20260629_140729/block_lba_trace.csv`
- `~/llm/storage/results/kvcache-profile/burstgpt_kvcache_20260629_141010/block_lba_trace.csv`

Inspect one of them first to confirm the schema (it's `timestamp_ns,dev,sector,bytes,rwbs,comm,pid`).

Then write `~/llm/storage/scripts/parse_bpftrace_to_csv.py` (small, idempotent) that:

1. Reads `/tmp/bt-default-baseline.log` (bpftrace text output)
2. Filters rows that are valid block_rq_issue entries
3. Writes `~/llm/storage/results/kvcache-profile/default_baseline/block_lba_trace.csv` with the same columns
4. Prints a sanity-check summary: total event count, read/write split, duration span, dev_t values

You can borrow the IO-kind parsing logic from `~/llm/storage/scripts/analyze_sharegpt_burstgpt_io.py` (function `io_kind()` around line 34).

---

## Step 3: Produce the same summary stats as the reference runs

Use `~/llm/storage/scripts/analyze_sharegpt_burstgpt_io.py` as the template. Write `~/llm/storage/scripts/analyze_default_baseline_io.py` that ingests the new CSV and computes:

| Metric | Source |
|---|---|
| Block events | total CSV rows |
| Trace duration (s) | `(ts_max - ts_min) / 1e9` |
| Read events / Write events | by rwbs |
| Read/Write ratio | read_events / write_events |
| Block read bytes (GiB) | sum |
| Block write bytes (GiB) | sum |
| IOPS | events / duration |
| Read IOPS / Write IOPS | per-kind |
| Bandwidth (GiB/s) | bytes / duration |
| Read BW / Write BW | per-kind |
| LBA span (GiB) | max(MAX_LBA, MIN_LBA) delta |
| Dominant request size | mode of `bytes` column |
| Dominant size share | pct |
| Adjacent read jump % (≥100 MiB) | per-pid, sorted by ts, abs(sector[t]-sector[t-1])*512 |
| Adjacent read exact-contiguous % | same with delta == 0 |
| Adjacent write exact-contiguous % | same for writes |
| Adjacent read p50 / p95 abs delta | percentile of abs delta |
| Adjacent write p50 / p95 abs delta | same for writes |

Output:
- JSON summary at `~/llm/storage/results/kvcache-profile/default_baseline/lba_trace_summary.json`
- Print the summary as a table on stdout

---

## Step 4: Time-series IOPS/BW data (optional but valuable)

If the per-second time-series is straightforward to compute (1-second bin), add it to the JSON summary as `iops_per_sec` and `bw_per_sec_giB`. If it's not, skip — the per-second data isn't strictly required for the three-way comparison update.

---

## Step 5: Commit your work

After all four steps complete:

```bash
cd ~/llm/storage
git add scripts/parse_bpftrace_to_csv.py scripts/analyze_default_baseline_io.py
git add results/kvcache-profile/default_baseline/lba_trace_summary.json results/kvcache-profile/default_baseline/results.json
git add results/kvcache-profile/default_baseline/block_lba_trace.csv
git commit -m "default-kvcache baseline: real mixed prefill+decode 8u 120s TP=1

- Default mode (no --prefill-only / --decode-only) benchmark
- llama3.1-8b TP=1 8 users 120s, --gpu-mem-gb 0 --cpu-mem-gb 0
- For comparison with ShareGPT and BurstGPT runs (same methodology)
- Replaces the misleading 'default-kvcache' row in three-way report
- bpftrace block_rq_issue on /dev/nvme0n1 (271581194)"
git push origin main
```

Do NOT commit `stdout.log` (too large) or raw bpftrace log (in /tmp anyway). Add a `.gitignore` entry for `stdout.log` if needed in `results/kvcache-profile/default_baseline/`.

---

## Verification (DO ALL before declaring done)

1. **`codex` exit code** is 0 from the kv-cache.py run (or you understand the error)
2. **CSV row count > 500,000** — if it's tiny, bpftrace missed the run
3. **dev_t = 271581194** in the CSV — if you see other dev_t values, the tracepoint was wrong
4. **comm column is dominated by `python3`** (≥95%) — if not, bpftrace caught noise
5. **Summary JSON has all 17+ fields populated**
6. **Git log shows your commit** on `origin/main`

Print all six checks as a final report. If any check fails, fix it and rerun the relevant step. Do not stop until all six pass.

---

## What NOT to do

- ❌ Do NOT use `--prefill-only` or `--decode-only` — that's what we're replacing
- ❌ Do NOT use `--tensor-parallel 8` — keep TP=1 to match the reference runs
- ❌ Do NOT modify `kv-cache.py` itself — it's the workload runner under test
- ❌ Do NOT touch `docs/kv-cache-io-three-way-comparison-2026-06-29.md` — that update is a separate task for me after you finish
- ❌ Do NOT generate charts — only raw CSVs and JSON. Charting is a separate step
- ❌ Do NOT run multiple benchmark configurations — exactly ONE default baseline run
- ❌ Do NOT use a different model — `llama3.1-8b` only

---

## Expected duration

- kv-cache.py run: ~120s
- bpftrace teardown: ~5s
- Post-processing: ~30s
- Total: ~3 minutes wall clock + analysis

If anything takes > 10 minutes, something is wrong. Stop and report.

---

## When you finish

Print a final report with:

1. The exact kv-cache.py exit code
2. The CSV row count and the 6 verification check results
3. The full summary table (17+ metrics)
4. The git commit SHA you created and confirmation of `git push origin main` succeeding
5. Path to the JSON summary file