# SSD SLC Cache Characterization Report

Generated: 2026-06-09T11:17:28

## Target

- Target directory: `/home/ficus/llm/storage/results/ssd-characterization`
- Test file: `/home/ficus/llm/storage/results/ssd-characterization/ssd_slc_mixed_rw_50_50_20260609_111358/fio_slc_test.dat`
- Filesystem device: `/dev/nvme1n1p3`
- Mountpoint: `/`
- lsblk: `nvme1n1  389.6G ext4`

## fio Configuration

- Size: `200.00 GiB`
- Block size: `1M`
- iodepth: `32`
- Workload: sequential write, direct=1, libaio

## Result

- Total written: `99.92 GiB`
- Runtime: `79.43 s`
- Average write speed: `1288.20 MiB/s`
- Initial/cache-in speed: `1312.00 MiB/s`
- Post-cache speed: `n/a`
- Steady tail speed: `1311.31 MiB/s`
- P50/P95/P99 per-second speed: `1306.31` / `1358.81` / `1373.88` MiB/s
- Estimated SLC cache size: `>= 99.92 GiB (no sustained cliff detected)`
- Media tendency from sustained write: `insufficient-write-volume: run at least 200-600GiB for NAND inference`

## Interpretation

- This test estimates SLC cache behavior from the write-speed cliff.
- It cannot definitively prove TLC vs QLC. Use official specs, controller/NAND inspection, or vendor data for confirmation.
- If no cliff appears, increase `--size-gb` until the write curve drops or the device reaches steady state.
- For AI SSD product evaluation, use the post-cache and steady-tail speeds, not only the initial cache-in speed.

## Files

- fio JSON: `fio_output.json`
- fio stderr: `fio_stderr.txt`
- bandwidth samples: `bandwidth_samples.csv`
