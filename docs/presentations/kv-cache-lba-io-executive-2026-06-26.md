# KV Cache LBA / IO Executive PPT

Generated deck: `docs/presentations/kv-cache-lba-io-executive-2026-06-26.pptx`

## Key numbers

- ShareGPT profile: `1,678` requests, `439,231` tokens, `1460` tokens/s.
- Cache hit rate: `97.9%`; read/write volume ratio: `19.5x`.
- Device IO shape: `62%` reads and `82%` writes are 128-256 KiB.
- Device D2C latency: read p50/p99 `32/256 us`; write p50/p99 `128/512 us`.
- LBA last-touch: `969` unique `(dev, sector)` entries; nonzero range `564.3-952.6 GiB`.
- Key locality: `83.4%` rereads are intra-token `<10ms`; inter-request cold rereads are `8.1%`.

## Generated charts

- `dashboard`: `docs/assets/kvcache-boss-ppt/01_signal_dashboard.png`
- `lba`: `docs/assets/kvcache-boss-ppt/02_lba_density.png`
- `locality`: `docs/assets/kvcache-boss-ppt/03_locality_donut.png`
- `device`: `docs/assets/kvcache-boss-ppt/04_device_shape_latency.png`
- `vendor`: `docs/assets/kvcache-boss-ppt/05_cross_vendor_randomness.png`
- `evidence`: `docs/assets/kvcache-boss-ppt/06_evidence_stack.png`

## Validation note

`@d[dev, sector] = nsecs` is a bpftrace last-touch map, not a complete per-IO LBA log. The deck deliberately treats gap/direction/run metrics as exploratory last-touch-derived signals only.
