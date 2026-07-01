# Codex Task v2: Update Three-Way I/O Comparison Report with Real Default Baseline

**Good news:** I've already created the missing summary JSON files for sharegpt and burstgpt (they didn't exist before). The chart script reads hardcoded values from a `WL` dict, not from JSON files, so you only need to update those numbers. No file path changes needed.

The chart script `scripts/io_three_way_comparison.py` has hardcoded values in a `WL` dict (around lines 50-80). Replace the `default-kvcache` entry with the new real mixed-mode numbers.

---

## Step 1: Replace default-kvcache values in `WL` dict

Open `scripts/io_three_way_comparison.py` and find the `WL` dict (around line 50-80). Update the `default-kvcache` entry to use the NEW real-mixed-mode numbers:

```python
'default-kvcache': {
    'events': 4090543,           # was 2487310
    'reads': 3613662,            # was 2068812
    'writes': 476881,            # was 418498
    'iops': 30806,               # was 21832
    'bw_gib_s': 3.75,            # was 2.47
    'lba_span_gib': 389.38,      # was 389.35 (basically same)
    'read_write_ratio': 7.58,    # was 4.9
    'read_jump_ge_100mib_pct': 79.16,  # was 95.07
    'read_exact_contiguous_pct': 0.0,  # was 2.49
    'write_exact_contiguous_pct': 0.9, # was 75.07 (note: this was misleading from two-stage)
    'read_abs_delta_p50_mib': 5033,    # was 56997
    'read_abs_delta_p95_mib': 88607,   # was 181721
    'write_abs_delta_p50_mib': 0.125,  # was 0.0
    'write_abs_delta_p95_mib': 0.125,  # was 12964
    'dominant_size_share_pct': 99.6,   # was 91.7
    'trace_duration_s': 132.78,  # was 113.93
}
```

Also update:
- The hardcoded text strings in render_card() around lines 100-130 that mention "default-kvcache 113.9s" → "132.78s", "default 4.9:1" → "7.58:1", "default 91.7%" → "99.6%"
- The axhline labels around lines 145, 157 that mention "10s 窗" — the new default baseline has 1s time-series now, so change to "1s 窗" and use `WL['default-kvcache']['iops']`
- The text annotation around line 167 that says "default-kvcache 来自 10s 窗" — change to "default 来自 1s 窗 (跟 sharegpt/burstgpt 同一粒度)"

---

## Step 2: Regenerate the 5 PNG charts

```bash
cd ~/llm/storage
~/llm/.venv/bin/python3 scripts/io_three_way_comparison.py
ls -la docs/assets/io-three-way-comparison/0*.png
# All 5 PNGs should be regenerated with new default data
```

Verify the byte sizes differ from the previous run:
```bash
# Compare to commit 969817f state
git show 969817f --stat -- docs/assets/io-three-way-comparison/ 2>&1 | head -10
```

---

## Step 3: Update the report text

`docs/kv-cache-io-three-way-comparison-2026-06-29.md` (247 lines) needs these changes:

1. **Main signal dashboard table (around line 40-52):** replace all default-kvcache column values with the new numbers from Step 1. The new column header should be just "default" (not "default-kvcache (morning)").

2. **"数据源说明" table (around line 19-23):** update the default-kvcache row to:
   - Data source: `results/kvcache-profile/default_baseline/lba_trace_summary.json`
   - Command: `kv-cache.py --num-users 8 --duration 120 --model llama3.1-8b --tensor-parallel 1 --gpu-mem-gb 0 --cpu-mem-gb 0` (no `--prefill-only`, no `--decode-only`)
   - Block events: 4,090,543
   - Duration: 132.78s

3. **"重要区别" section (around line 25-28):** REWRITE this. The old version says "default-kvcache is two-stage". The new version should say: "default is on the same methodology as sharegpt/burstgpt (TP=1, 8u, 120s, llama3.1-8b, forced NVMe). No more methodology mismatch."

4. **IOPS / BW timeline section (around line 64-81):** update the default row. Remove the "缺时间序列" caveat. The new default has 1s time-series data. The default IOPS = 30,806; default BW = 3.75 GiB/s.

5. **LBA jump CDF section (around line 90-122):** update both Read and Write sub-tables with new adjacent-jump numbers. Specifically:
   - default Read: ≥100 MiB jump = 79.16% (was 95.07%), exact contiguous = 0.0% (was 2.49%), p50 = 5,033 MiB (was 56,997), p95 = 88,607 MiB (was 181,721)
   - default Write: exact contiguous = 0.9% (was 75.07%), p95 = 0.125 MiB (was 12,964)
   - Update the explanations below the table to reflect the new data. The "为什么 default-kvcache 写连续率最低 (75%):" explanation should be DELETED — that was an artifact of the two-stage run. New explanation: "default write jump p50 is 0.125 MiB (effectively sequential) because mixed prefill+decode does sequential KV cache appends."

6. **Block size distribution section (around line 130-143):** update the 128 KiB share from 91.7% to 99.6%. Update the explanation to remove the "default 块大小分布最分散 (4k 也有 4.3%)" claim — new default is also 99.6% pure 128K, similar to burstgpt.

7. **Pressure heatmap section (around line 152-162):** update default row to: IOPS 30.8K, BW 3.75, Read% 88, jump% 79.16.

8. **跨报告结论 section (around line 167-178):** update the description of default to mention "real mixed-mode TP=1 baseline" instead of "morning synthetic".

9. **Appendix code blocks (around line 210-237):** REPLACE the two `--prefill-only` and `--decode-only` commands with a single mixed-mode command:
   ```bash
   # 跑 default (mixed prefill+decode, TP=1)
   ~/llm/storage/kv_cache_benchmark/.venv/bin/python3 \
     ~/llm/storage/kv_cache_benchmark/kv-cache.py \
     --num-users 8 --duration 120 \
     --model llama3.1-8b --tensor-parallel 1 \
     --gpu-mem-gb 0 --cpu-mem-gb 0 \
     --cache-dir ~/llm/storage/results/kvcache-profile/ext4_kvcache_default_baseline \
     --storage-capacity-gb 40
   ```

**Preserve the report's overall structure** — same headings, same section order, same length (247 ± 10 lines). Don't add or remove sections.

---

## Step 4: Update the PPT plan

`docs/kv-cache-io-three-way-comparison-PPT-plan-2026-06-29.md` (12 slides, 10KB). Update default-kvcache numbers in:
- Slide 3 (Signal Dashboard) — use new numbers
- Slide 4 (Methodology) — change "TP=8 two-stage" to "TP=1 mixed"
- Slide 6 (LBA CDF) — new jump percentages
- Slide 8 (Pressure heatmap) — new IOPS/BW

Preserve the 12-slide structure.

---

## Step 5: Verify

```bash
cd ~/llm/storage
grep -E "4,090,543|30806|30,806|3.75" docs/kv-cache-io-three-way-comparison-2026-06-29.md
# At least 3 hits
grep "per_io_lba_ext4_rw_20260629_032924" docs/kv-cache-io-three-way-comparison-2026-06-29.md
# 0 hits
grep "缺时间序列" docs/kv-cache-io-three-way-comparison-2026-06-29.md
# 0 hits
grep "methodology mismatch\|方法学不一致" docs/kv-cache-io-three-way-comparison-2026-06-29.md
# 0 hits
ls -la docs/assets/io-three-way-comparison/0*.png
# 5 PNGs, all today
```

---

## Step 6: Commit and push

```bash
cd ~/llm/storage
git add scripts/io_three_way_comparison.py \
        docs/kv-cache-io-three-way-comparison-2026-06-29.md \
        docs/kv-cache-io-three-way-comparison-PPT-plan-2026-06-29.md \
        docs/assets/io-three-way-comparison/01_signal_dashboard.png \
        docs/assets/io-three-way-comparison/02_iops_bw_timeline.png \
        docs/assets/io-three-way-comparison/03_lba_delta_cdf.png \
        docs/assets/io-three-way-comparison/04_block_size_distribution.png \
        docs/assets/io-three-way-comparison/05_pressure_heatmap.png
git commit -m "三路 IO 对比 v3: 替换 morning 两段拼装的 default-kvcache → 真实 mixed-mode (TP=1)

- 新 default: 4,090,543 events, 30,806 IOPS, 3.75 GiB/s, TP=1 mixed
- default 与 sharegpt/burstgpt 同方法学 (TP=1, 8u, 120s, llama3.1-8b)
- 删除 '方法学不一致' 声明, 修复 '缺时间序列' 注释
- 5 张 chart 全部重画反映新数据
- 附录跑法命令改为单一 mixed-mode"
git push origin main
```

---

## What NOT to do

- ❌ Do NOT modify any test/benchmark code or run new benchmarks
- ❌ Do NOT change chart style/colors
- ❌ Do NOT add/remove report sections
- ❌ Do NOT touch `docs/kv-cache-sharegpt-vs-burstgpt-io-2026-06-29.md` (reference)
- ❌ Do NOT touch `docs/codex-default-baseline-prompt.md` (task spec)
- ❌ Do NOT touch the default_baseline results (inputs, not output)
- ❌ Do NOT create new files in `learn/`, `learns/`, `lmcache-learning/`, or repo root

---

## Expected duration

- Edit chart script + regen PNGs: 3 min
- Update report: 8 min
- Update PPT plan: 3 min
- Verify + commit + push: 2 min
- Total: ~16 minutes

---

## Final report

Print:
1. Verification check results
2. New commit SHA + push confirmation
3. `git log --oneline -3`
4. `git show --stat HEAD` (file diff stat)
5. New default row from the updated signal dashboard table