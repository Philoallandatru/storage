#!/usr/bin/env python3
"""
cross_vendor_analyze.py
Aggregate results from cross-vendor test scripts and emit comparison tables.

Run after all 7 tests are complete:
    python3 scripts/cross_vendor_analyze.py

Reads:
    results/cross_vendor/{t1,t2,t3,t4,t5,t6,t7}/*/

Writes:
    results/cross_vendor/SUMMARY.md
"""
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "cross_vendor"

VENDORS = ["wd_sn570", "biwin_x570", "zhitai_ti600", "seagate_fc530"]
TIER = {
    "wd_sn570": "Entry-level (DRAM-less)",
    "biwin_x570": "Mainstream (DRAM, prior subject)",
    "zhitai_ti600": "Domestic (YMTC NAND)",
    "seagate_fc530": "High-end (Phison E18)",
}
VENDOR_MODEL = {
    "wd_sn570": "WD SN570 1TB",
    "biwin_x570": "Biwin X570 1TB",
    "zhitai_ti600": "ZhiTai Ti600 1TB",
    "seagate_fc530": "Seagate FC530 1TB",
}


def safe_load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"_error": str(e)}


def get_job(j):
    return j["jobs"][0] if "jobs" in j and j["jobs"] else {}


def fmt_bw(kibps):
    """Convert KiB/s to MB/s (decimal)."""
    return f"{kibps/1024:.0f} MB/s" if kibps is not None else "-"


def fmt_iops(iops):
    return f"{iops:,.0f}" if iops is not None else "-"


def fmt_lat_us(ns):
    if ns is None:
        return "-"
    return f"{ns/1000:.1f} μs"


def latest_dir(pattern):
    """Return latest result dir matching glob pattern, or None."""
    matches = sorted(RES.glob(pattern), key=lambda p: p.name, reverse=True)
    return matches[0] if matches else None


# ---------- per-test extractors ----------

def t1_extract(vendor):
    """Sequential burst R/W: peak BW, mean IOPS, latency."""
    d = latest_dir(f"t1_seqburst/{vendor}_*")
    if not d:
        return {"_missing": str(d)}
    out = {}
    for op in ["seq_read", "seq_write"]:
        j = safe_load_json(d / f"{op}.json")
        job = get_job(j)
        if "_error" in j or not job:
            out[op] = {"_error": "no data"}
            continue
        side = job["read"] if op == "seq_read" else job["write"]
        out[op] = {
            "bw_mbs": side["bw"] / 1024,
            "iops": side["iops"],
            "lat_mean_us": side["lat_ns"]["mean"] / 1000,
            "lat_p99_us": side["lat_ns"]["percentile"]["99.000000"] / 1000
                if "percentile" in side["lat_ns"] else None,
        }
    return out


def t5_extract(vendor):
    """4K random read/write IOPS at multiple QDs."""
    d = latest_dir(f"t5_random4k/{vendor}_*")
    if not d:
        return {"_missing": str(d)}
    out = {"randread": {}, "randwrite": {}}
    for op in ["randread", "randwrite"]:
        for qd in [1, 4, 16, 64, 256]:
            path = d / f"{op}_qd{qd}.json"
            j = safe_load_json(path)
            job = get_job(j)
            if "_error" in j or not job:
                out[op][qd] = None
                continue
            side = job["read"] if op == "randread" else job["write"]
            out[op][qd] = {
                "iops": side["iops"],
                "bw_mbs": side["bw"] / 1024,
                "lat_mean_us": side["lat_ns"]["mean"] / 1000,
            }
    return out


def t6_extract(vendor):
    """Mixed R/W."""
    d = latest_dir(f"t6_mixed_rw/{vendor}_*")
    if not d:
        return {"_missing": str(d)}
    out = {}
    for mix in [90, 50]:
        path = d / f"randrw_r{mix}w{100-mix}.json"
        j = safe_load_json(path)
        job = get_job(j)
        if "_error" in j or not job:
            out[f"r{mix}_w{100-mix}"] = None
            continue
        out[f"r{mix}_w{100-mix}"] = {
            "read_bw_mbs": job["read"]["bw"] / 1024,
            "write_bw_mbs": job["write"]["bw"] / 1024,
            "read_iops": job["read"]["iops"],
            "write_iops": job["write"]["iops"],
            "read_lat_mean_us": job["read"]["lat_ns"]["mean"] / 1000,
        }
    return out


def t7_extract(vendor):
    """Page cache sensitivity: warm vs evict."""
    d = latest_dir(f"t7_pagecache/{vendor}_*")
    if not d:
        return {"_missing": str(d)}
    out = {}
    for cond in ["buffered_warm", "buffered_evict"]:
        path = d / f"{cond}.json"
        j = safe_load_json(path)
        job = get_job(j)
        if "_error" in j or not job:
            out[cond] = None
            continue
        out[cond] = {
            "bw_mbs": job["read"]["bw"] / 1024,
            "iops": job["read"]["iops"],
            "lat_mean_us": job["read"]["lat_ns"]["mean"] / 1000,
        }
    return out


def t4_extract(vendor):
    """Long steady-state: GC drift."""
    d = latest_dir(f"t4_gc_drift/{vendor}_*")
    if not d:
        return {"_missing": str(d)}
    j = safe_load_json(d / "long_steady.json")
    job = get_job(j)
    if "_error" in j or not job:
        return {"_error": "no data"}
    return {
        "bw_mbs": job["read"]["bw"] / 1024,
        "iops": job["read"]["iops"],
        "lat_mean_us": job["read"]["lat_ns"]["mean"] / 1000,
        "runtime_s": job["job_runtime"],
    }


# ---------- markdown writer ----------

def write_summary_md(data):
    out = RES / "SUMMARY.md"
    with open(out, "w") as f:
        f.write("# Cross-Vendor NVMe SSD Comparison Summary\n\n")
        f.write("Comparison of 4 consumer NVMe SSDs (1TB class) under a unified "
                "test suite. See `scripts/cross_vendor_*.sh` for methodology.\n\n")
        f.write("## Vendor lineup\n\n")
        f.write("| ID | Model | Tier |\n|---|---|---|\n")
        for vid in VENDORS:
            f.write(f"| {vid} | {VENDOR_MODEL[vid]} | {TIER[vid]} |\n\n")

        # ----- Test 1 -----
        f.write("## Test 1: Sequential Burst R/W (10 GB file, bs=128k, QD=32)\n\n")
        f.write("Vendor datasheet ceiling check.\n\n")
        f.write("| Vendor | Seq Read | Seq Write | Read lat |\n|---|---:|---:|---:|\n")
        for vid in VENDORS:
            d = data[vid]["t1"]
            if "_missing" in d or "seq_read" not in d:
                f.write(f"| {vid} | - | - | - |\n")
                continue
            r = d["seq_read"]; w = d["seq_write"]
            f.write(f"| {vid} | {fmt_bw(r['bw_mbs']*1024)} | {fmt_bw(w['bw_mbs']*1024)} | "
                    f"{fmt_lat_us(r['lat_mean_us']*1000)} |\n")
        f.write("\n")

        # ----- Test 5: 4K IOPS at QD=1 and QD=64 -----
        f.write("## Test 5: 4K Random IOPS (key QDs)\n\n")
        f.write("| Vendor | R QD=1 | R QD=64 | W QD=1 | W QD=64 |\n|---|---:|---:|---:|---:|\n")
        for vid in VENDORS:
            d = data[vid]["t5"]
            if "_missing" in d:
                f.write(f"| {vid} | - | - | - | - |\n")
                continue
            cells = []
            for op, qd in [("randread",1),("randread",64),("randwrite",1),("randwrite",64)]:
                c = d[op].get(qd) if op in d else None
                cells.append(fmt_iops(c["iops"]) if c else "-")
            f.write(f"| {vid} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |\n")
        f.write("\n")

        # ----- Test 6: Mixed R/W -----
        f.write("## Test 6: Mixed R/W (4k, QD=32, time-based 90s)\n\n")
        f.write("| Vendor | 90/10 R | 90/10 W | 50/50 R | 50/50 W |\n|---|---:|---:|---:|---:|\n")
        for vid in VENDORS:
            d = data[vid]["t6"]
            if "_missing" in d:
                f.write(f"| {vid} | - | - | - | - |\n")
                continue
            n90 = d.get("r90_w10"); n50 = d.get("r50_w50")
            f.write(f"| {vid} | "
                    f"{fmt_bw(n90['read_bw_mbs']*1024) if n90 else '-'} | "
                    f"{fmt_bw(n90['write_bw_mbs']*1024) if n90 else '-'} | "
                    f"{fmt_bw(n50['read_bw_mbs']*1024) if n50 else '-'} | "
                    f"{fmt_bw(n50['write_bw_mbs']*1024) if n50 else '-'} |\n")
        f.write("\n")

        # ----- Test 7: Page cache -----
        f.write("## Test 7: Page Cache Sensitivity (4k buffered read, 12 GB file)\n\n")
        f.write("`warm` = first read after `drop_caches`, OS caches the file. "
                "`evict` = `invalidate=1`, OS evicts after each block.\n\n")
        f.write("| Vendor | Warm BW | Evict BW | Speedup | Warm P99 | Evict P99 |\n|---|---:|---:|---:|---:|---:|\n")
        for vid in VENDORS:
            d = data[vid]["t7"]
            if "_missing" in d:
                f.write(f"| {vid} | - | - | - | - | - |\n")
                continue
            w = d.get("buffered_warm"); e = d.get("buffered_evict")
            if not w or not e:
                f.write(f"| {vid} | - | - | - | - | - |\n")
                continue
            speedup = w["bw_mbs"] / e["bw_mbs"] if e["bw_mbs"] > 0 else 0
            f.write(f"| {vid} | {fmt_bw(w['bw_mbs']*1024)} | {fmt_bw(e['bw_mbs']*1024)} | "
                    f"{speedup:.2f}x | - | - |\n")
        f.write("\n")

        # ----- Test 4 -----
        f.write("## Test 4: GC Drift (15 min sustained randread 16k)\n\n")
        f.write("End-of-run stats (BW, mean latency, total runtime).\n\n")
        f.write("| Vendor | End BW | Mean lat | Runtime |\n|---|---:|---:|---:|\n")
        for vid in VENDORS:
            d = data[vid]["t4"]
            if "_missing" in d:
                f.write(f"| {vid} | - | - | - |\n")
                continue
            if "_error" in d:
                f.write(f"| {vid} | - | - | - |\n")
                continue
            f.write(f"| {vid} | {fmt_bw(d['bw_mbs']*1024)} | {fmt_lat_us(d['lat_mean_us']*1000)} | "
                    f"{d['runtime_s']:.0f}s |\n")
        f.write("\n")

        f.write("---\n\n_Generated by `scripts/cross_vendor_analyze.py`._\n")

    print(f"Wrote {out}")


def main():
    data = defaultdict(dict)
    for vid in VENDORS:
        print(f"Extracting {vid}...")
        data[vid]["t1"] = t1_extract(vid)
        data[vid]["t5"] = t5_extract(vid)
        data[vid]["t6"] = t6_extract(vid)
        data[vid]["t7"] = t7_extract(vid)
        data[vid]["t4"] = t4_extract(vid)
    write_summary_md(data)


if __name__ == "__main__":
    main()