# SSD SLC Cache Characterization Report

Generated: 2026-06-09T10:11:51

## Target

- Target directory: `/home/ficus/llm/storage/results/ssd-characterization`
- Test file: `/home/ficus/llm/storage/results/ssd-characterization/ssd_slc_post_precond_immediate_20260609_101031/fio_slc_test.dat`
- Filesystem device: `/dev/nvme1n1p3`
- Mountpoint: `/`
- lsblk: `nvme1n1  389.6G ext4`

## fio Configuration

- Size: `200.00 GiB`
- Block size: `1M`
- iodepth: `32`
- Workload: sequential write, direct=1, libaio

## Result

- Total written: `200.00 GiB`
- Runtime: `80.02 s`
- Average write speed: `2559.49 MiB/s`
- Initial/cache-in speed: `5073.07 MiB/s`
- Post-cache speed: `1824.82 MiB/s`
- Steady tail speed: `1757.38 MiB/s`
- P50/P95/P99 per-second speed: `1874.50` / `5076.12` / `5080.69` MiB/s
- Estimated SLC cache size: `~ 94.67 GiB`
- Media tendency from sustained write: `strong TLC-like sustained write behavior`

## Interpretation

- This test estimates SLC cache behavior from the write-speed cliff.
- It cannot definitively prove TLC vs QLC. Use official specs, controller/NAND inspection, or vendor data for confirmation.
- If no cliff appears, increase `--size-gb` until the write curve drops or the device reaches steady state.
- For AI SSD product evaluation, use the post-cache and steady-tail speeds, not only the initial cache-in speed.

## Files

- fio JSON: `fio_output.json`
- fio stderr: `fio_stderr.txt`
- bandwidth samples: `bandwidth_samples.csv`
