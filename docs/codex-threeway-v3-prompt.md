# Codex Task: Update Three-Way I/O Comparison Report with Real Default Baseline

**Background (do NOT modify anything outside scope):** Commit `969817f` already added the real default mixed-mode baseline (no `--prefill-only`, no `--decode-only`). The current three-way comparison report at `docs/kv-cache-io-three-way-comparison-2026-06-29.md` is still showing a *misleading* "default-kvcache" row that was synthesized from two separate runs (`--prefill-only 35s` + `--decode-only 60s`, TP=8, 2,487,310 events). Your job is to replace that row with the real data and regenerate all five charts.

This is a **report + chart regeneration** task. You do **NOT** need to run any new benchmark or capture any new bpftrace trace. All data already exists in:
- `results/kvcache-profile/default_baseline/lba_trace_summary.json` (the new default baseline, 4,090,543 events, TP=1)
- `results/kvcache-profile/sharegpt_kvcache_20260629_140729/lba_trace_summary.json` (1,981,685 events, TP=1)
- `results/kvcache-profile/burstgpt_kvcache_20260629_141010/lba_trace_summary.json` (4,566,627 events, TP=1)

---

## Step 1: Read the existing report and the existing chart script to understand the schema

```bash
cd ~/llm/storage
head -50 docs/kv-cache-io-three-way-comparison-2026-06-29.md
echo "==="
wc -l docs/kv-cache-io-three-way-comparison-2026-06-29.md
echo "==="
wc -l scripts/io_three_way_comparison.py
head -50 scripts/io_three_way_comparison.py
```

You should see:
- The existing report mentions `default-kvcache (morning)` in row 1 of the main table. It says: "Block events 2,487,310 | Block IOPS 21,832 | Block BW 2.47 GiB/s | Read events 2,068,812 (83%)" etc.
- The chart script reads from `lba_trace_summary.json` files and renders 5 PNGs into `docs/assets/io-three-way-comparison/`.

Read the full existing report (it's 247 lines, manageable) and the full existing chart script (15KB). Understand:
- The 17+ fields the report references (you can see them in `lba_trace_summary.csv` headers)
- Which colors are used for which workload (default / sharegpt / burstgpt)
- How the report text is structured (one main table + sub-tables per chart)

---

## Step 2: Update the chart generation script

`scripts/io_three_way_comparison.py` currently reads a path for "default-kvcache" that points to the morning two-stage run. Replace the path with the new default baseline.

**The critical change:** in the script, find the `DEFAULT_PATH` or similar variable pointing to `per_io_lba_ext4_rw_20260629_032924/lba_trace_summary.json` (the morning two-stage data) and change it to point to `default_baseline/lba_trace_summary.json` instead.

Verify by running the script and checking the 5 PNGs are regenerated. Use the same dark-dashboard style and color palette that the existing script already uses — do NOT redesign the charts. The goal is to **swap the data source**, not redesign the visualizations.

```bash
cd ~/llm/storage
~/llm/.venv/bin/python3 scripts/io_three_way_comparison.py
# Should overwrite 5 PNGs in docs/assets/io-three-way-comparison/
ls -la docs/assets/io-three-way-comparison/0*.png
```

Compare new vs old PNGs using `du -b` or `file` — the byte sizes should differ noticeably because the data changed (default IOPS went from 21.8K to 30.8K, total events 2.49M → 4.09M, etc.).

---

## Step 3: Update the report text

**Replace the misleading "default-kvcache" column in every table** with the new default baseline data. The full new default baseline numbers are:

```
block_events: 4,090,543
trace_duration_s: 132.78
read_events: 3,613,662 (88.3%)
write_events: 476,881 (11.7%)
read_write_ratio: 7.58
block_read_bytes_gib: 440.33
block_write_bytes_gib: 57.33
iops: 30,806
bandwidth_gib_s: 3.75
read_bw_gib_s: 3.32
write_bw_gib_s: 0.43
lba_span_gib: 389.38
dominant_request_size_bytes: 131,072 (128 KiB)
dominant_size_share_pct: 99.6%
adjacent_read_jump_ge_100mib_pct: 79.16%
adjacent_read_exact_contiguous_pct: 0.0%
adjacent_write_exact_contiguous_pct: 0.9%
adjacent_read_abs_delta_mib_p50: 5,033
adjacent_read_abs_delta_mib_p95: 88,607
adjacent_write_abs_delta_mib_p50: 0.125
adjacent_write_abs_delta_mib_p95: 0.125
```

**What to change in the report:**

1. **Row 1 of the main signal dashboard table** — replace all default-kvcache numbers with the new values above. The new column header should be just "default" (not "default-kvcache (morning)").

2. **The "数据源说明" table** at the top — update the default-kvcache row to reflect the new run:
   - Data source: `results/kvcache-profile/default_baseline/lba_trace_summary.json`
   - Command: `kv-cache.py --num-users 8 --duration 120 --model llama3.1-8b --tensor-parallel 1 --gpu-mem-gb 0 --cpu-mem-gb 0` (no `--prefill-only`, no `--decode-only`)
   - Block events: 4,090,543
   - Duration: 132.78s
   - Methodology: **TP=1 mixed mode** (NOT TP=8 two-stage)

3. **The "重要区别" section** under that table — rewrite to acknowledge that default is now on the same methodology as sharegpt/burstgpt (all TP=1, all 8 users, all 120s, all forced NVMe). The previous claim that "default was two-stage" is no longer true.

4. **The IOPS / BW timeline section** — update the default row with the actual time-series from `default_baseline/lba_trace_summary.json`'s `iops_per_sec` and `bw_per_sec_giB` fields. The previous "缺时间序列" note is no longer true since the new run was captured with the same 1s-bin format as sharegpt/burstgpt.

5. **The LBA jump CDF section** — update both Read and Write sub-tables with the new adjacent-jump numbers.

6. **The block size distribution section** — update the 128 KiB share from 91.7% to 99.6% (4,074,111 of 4,090,543).

7. **The pressure heatmap section** — update IOPS / BW / Read% / jump% row for default.

8. **The "六、跨报告结论" section** — update the description of default to be the actual mixed-mode baseline, not the morning two-stage synthetic.

9. **The appendix "跑法" code blocks** — replace the two `--prefill-only` and `--decode-only` commands with a single default mixed-mode command.

10. **The "已知方法学不一致" caveat that was supposed to be added** — REMOVE that caveat entirely. With the new default data, all three workloads use the same methodology (TP=1, 8 users, 120s, llama3.1-8b, forced NVMe). The caveat is no longer needed.

**Preserve the report's overall structure** — don't add new sections, don't reorder sections, don't change the heading hierarchy. The report should still be 247 ± 10 lines.

**Use the new data for default** but keep sharegpt and burstgpt numbers exactly as they are in the existing report (you can verify them by re-running `analyze_sharegpt_burstgpt_io.py` if needed, or just reading the existing report — they should match).

---

## Step 4: Update the PPT plan

`docs/kv-cache-io-three-way-comparison-PPT-plan-2026-06-29.md` (12 slides, 10KB) references default-kvcache numbers in slide 3 (Signal Dashboard), slide 4 (Methodology), slide 6 (LBA CDF), and slide 8 (Pressure heatmap).

For each of those slides, update the default column to use the new numbers from Step 3. The slide structure should stay the same.

---

## Step 5: Verify everything renders correctly

```bash
cd ~/llm/storage
# 1. Confirm the report mentions the new default block event count
grep -E "4,090,543|4090543" docs/kv-cache-io-three-way-comparison-2026-06-29.md
# Should find at least 2 hits (table + data source row)

# 2. Confirm the report no longer references the old morning data path
grep "per_io_lba_ext4_rw_20260629_032924" docs/kv-cache-io-three-way-comparison-2026-06-29.md
# Should find 0 hits

# 3. Confirm the report no longer says "缺时间序列" for default
grep "缺时间序列" docs/kv-cache-io-three-way-comparison-2026-06-29.md
# Should find 0 hits

# 4. Confirm charts are regenerated
ls -la docs/assets/io-three-way-comparison/0*.png
# 5 PNGs, all dated today, all > 50KB

# 5. Confirm PPT plan mentions the new default
grep -E "4,090,543|4090543|30,806|30806" docs/kv-cache-io-three-way-comparison-PPT-plan-2026-06-29.md
# Should find at least 2 hits
```

If any of these checks fail, fix and rerun.

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
git status --short
# Should show 8 files staged, nothing else
git commit -m "三路 IO 对比 v3: 替换 morning 两段拼装的 default-kvcache → 真实 mixed-mode (TP=1)

- 新 default 数据: 4,090,543 events, 30,806 IOPS, 3.75 GiB/s
- default 与 sharegpt/burstgpt 现在用同一方法学 (TP=1, 8u, 120s, llama3.1-8b)
- 删除 '已知方法学不一致' 声明 (不再需要)
- 修复 IOPS/BW 时间序列 '缺数据' 注释 (新 default 用 1s bin 跟 sharegpt/burstgpt 一致)
- 5 张 chart 全部重画, 反映新 default 数据
- 修复附录跑法命令 (单一 mixed-mode 命令替代 prefill+decode 两段)"
git push origin main
```

After push, verify with:
```bash
git log --oneline -3
# Should show your new commit on top of 969817f
git status --short
# Should be empty (clean)
```

---

## What NOT to do

- ❌ Do NOT modify `kv-cache.py` or any test/benchmark code
- ❌ Do NOT run new bpftrace captures or new benchmarks
- ❌ Do NOT change the chart style/colors (only the data feeding them)
- ❌ Do NOT add new sections to the report
- ❌ Do NOT create new files in `learn/` / `learns/` / `lmcache-learning/` / root (FORMAT files)
- ❌ Do NOT touch `docs/kv-cache-sharegpt-vs-burstgpt-io-2026-06-29.md` (it's the reference)
- ❌ Do NOT touch `docs/codex-default-baseline-prompt.md` (it's the task spec)
- ❌ Do NOT touch the default_baseline results files (they're inputs, not your output)
- ❌ Do NOT delete any of the untracked FORMAT/SKILL files in repo root

---

## Expected duration

- Reading existing files: 2 minutes
- Updating the chart script + regenerating PNGs: 3 minutes
- Updating the report text: 10 minutes
- Updating the PPT plan: 3 minutes
- Verification + commit + push: 2 minutes
- Total: ~20 minutes wall clock

If it takes > 40 minutes, something's wrong. Stop and report.

---

## When you finish

Print a final report with:

1. The 5 verification check results (from Step 5)
2. The new commit SHA and confirmation of `git push origin main` succeeding
3. `git log --oneline -3` output
4. A diff stat of files changed in your commit (`git show --stat HEAD`)
5. The new default column values that now appear in the report (copy the row from the updated table)

Be precise. If any number is wrong, the comparison is wrong. If any chart is stale, the report is wrong. Re-run until everything matches.