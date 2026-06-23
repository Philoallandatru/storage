#!/usr/bin/env python3
"""Summarize historical benchmark results and redraw IO analysis charts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "results/history-summary"
DEFAULT_DOC = REPO / "docs/test-history-and-io-summary-2026-06-24-zh.md"
DEFAULT_ASSETS = REPO / "docs/assets/test-history-io-summary"


VENDOR_LABELS = {
    "wd_sn570": "WD SN570",
    "biwin_x570": "Biwin X570",
    "zhitai_ti600": "ZhiTai Ti600",
    "seagate_fc530": "Seagate FC530",
}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], preferred: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for key in preferred:
        if any(key in row for row in rows) and key not in keys:
            keys.append(key)
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: format_value(row.get(k, "")) for k in keys})


def format_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.6g}"
    return value


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    text = re.sub(r"[*`%]", "", text)
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


def get_path(data: dict[str, Any], *path: str) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def status_from_health(cache_stats: dict[str, Any]) -> str:
    health = cache_stats.get("storage_health") or {}
    return health.get("overall_status") or ""


def passed_from_health(cache_stats: dict[str, Any]) -> str:
    health = cache_stats.get("storage_health") or {}
    if "passed_count" in health and "total_count" in health:
        return f"{health['passed_count']}/{health['total_count']}"
    return ""


def parse_kv_json(path: Path, family: str, source_kind: str) -> dict[str, Any]:
    data = json.loads(path.read_text())
    summary = data.get("summary") or {}
    cs = summary.get("cache_stats") or {}
    meta_path = path.with_name("metadata.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    parent_parts = path.relative_to(REPO).parts

    vendor = meta.get("vendor")
    if not vendor:
        for part in parent_parts:
            if part in VENDOR_LABELS:
                vendor = part
                break

    scenario = meta.get("scenario") or path.parent.name
    users = meta.get("users")
    if users is None:
        m = re.search(r"(?:users|_)(\d+)u?", path.parent.name)
        users = int(m.group(1)) if m else None

    model = meta.get("model")
    if not model:
        if "70b" in str(path).lower():
            model = "llama3.1-70b-instruct"
        elif "8b" in str(path).lower():
            model = "llama3.1-8b"

    duration_s = meta.get("duration_actual_s") or summary.get("elapsed_time")

    return {
        "category": "KV Cache",
        "family": family,
        "source_kind": source_kind,
        "test_id": path.parent.name,
        "vendor": VENDOR_LABELS.get(str(vendor), vendor or ""),
        "scenario": scenario,
        "model": model or "",
        "users": users,
        "duration_s": duration_s,
        "status": status_from_health(cs),
        "passed": passed_from_health(cs),
        "requests": summary.get("total_requests"),
        "tokens": summary.get("total_tokens"),
        "tok_s": summary.get("avg_throughput_tokens_per_sec"),
        "req_s": summary.get("requests_per_second"),
        "cache_hit_pct": (cs.get("cache_hit_rate") or 0) * 100 if cs else "",
        "e2e_p95_ms": get_path(summary, "end_to_end_latency_ms", "p95"),
        "io_p95_ms": get_path(summary, "storage_io_latency_ms", "p95"),
        "read_p95_ms": cs.get("storage_read_p95_ms"),
        "read_p99_ms": cs.get("storage_read_p99_ms"),
        "write_p95_ms": cs.get("storage_write_p95_ms"),
        "write_p99_ms": cs.get("storage_write_p99_ms"),
        "read_dev_p95_ms": cs.get("storage_read_device_p95_ms"),
        "read_dev_p99_ms": cs.get("storage_read_device_p99_ms"),
        "write_dev_p95_ms": cs.get("storage_write_device_p95_ms"),
        "write_dev_p99_ms": cs.get("storage_write_device_p99_ms"),
        "read_bw_gbps": cs.get("tier_storage_read_bandwidth_gbps"),
        "write_bw_gbps": cs.get("tier_storage_write_bandwidth_gbps"),
        "total_read_gb": cs.get("total_read_gb"),
        "total_write_gb": cs.get("total_write_gb"),
        "read_iops": cs.get("read_iops"),
        "write_iops": cs.get("write_iops"),
        "prefill_writes": cs.get("prefill_writes"),
        "decode_reads": cs.get("decode_reads"),
        "source": rel(path),
    }


def collect_cross_vendor_kv() -> list[dict[str, Any]]:
    base = REPO / "results/cross_vendor"
    rows = []
    for path in sorted(base.glob("**/kv_cache_summary.json")):
        family = path.relative_to(base).parts[0]
        rows.append(parse_kv_json(path, family, "kv_cache_summary.json"))
    return rows


def collect_profile_json() -> list[dict[str, Any]]:
    base = REPO / "results/kvcache-profile"
    rows = []
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "summary" not in data:
            continue
        row = parse_kv_json(path, "kvcache-profile", "profile_json")
        row["vendor"] = row.get("vendor") or "Single-device profile"
        row["scenario"] = row.get("scenario") or "profile"
        rows.append(row)
    return rows


def collect_fio() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sources = [
        ("FIO KV emulation", "fresh", REPO / "results/kvcache-profile/fio_sweep/sweep_summary.csv"),
        ("FIO KV emulation", "preconditioned", REPO / "results/kvcache-profile/fio_sweep_precond/sweep_precond_summary.csv"),
    ]
    for category, state, path in sources:
        for r in read_csv(path):
            read_bw = as_float(r.get("read_bw_MiBs"))
            write_bw = as_float(r.get("write_bw_MiBs"))
            rows.append({
                "category": category,
                "family": state,
                "source_kind": "fio_summary_csv",
                "test_id": f"{r.get('workload')}_qd{r.get('iodepth')}_{state}",
                "scenario": r.get("workload"),
                "iodepth": r.get("iodepth"),
                "read_mix_pct": r.get("rwmixread_pct"),
                "duration_s": r.get("runtime_s"),
                "read_iops": r.get("read_iops"),
                "write_iops": r.get("write_iops"),
                "read_bw_gbps": read_bw / 1024 if read_bw is not None else "",
                "write_bw_gbps": write_bw / 1024 if write_bw is not None else "",
                "read_dev_p99_ms": (as_float(r.get("lat_read_p99_us")) or 0) / 1000,
                "write_dev_p99_ms": (as_float(r.get("lat_write_p99_us")) or 0) / 1000,
                "read_dev_p95_ms": (as_float(r.get("lat_read_p95_us")) or 0) / 1000,
                "write_dev_p95_ms": (as_float(r.get("lat_write_p95_us")) or 0) / 1000,
                "source": rel(path),
            })
    return rows


def collect_ssd_characterization() -> list[dict[str, Any]]:
    path = REPO / "results/cross_vendor/_compiled.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    rows = []
    metric_map = [
        ("seq_read", "t1_seq_read_bw_MBps", "t1_seq_read_iops", "t1_seq_read_lat_us"),
        ("seq_write", "t1_seq_write_bw_MBps", "t1_seq_write_iops", "t1_seq_write_lat_us"),
        ("randread_qd64", None, "t5_randread_qd64_iops", "t5_randread_qd64_lat_us"),
        ("randwrite_qd64", None, "t5_randwrite_qd64_iops", "t5_randwrite_qd64_lat_us"),
        ("mixed_90r10w", "t6_r90_read_bw", None, "t6_r90_read_lat"),
        ("mixed_50r50w", "t6_r50_read_bw", None, "t6_r50_read_lat"),
        ("pagecache_warm", "t7_buffered_warm_bw", None, None),
        ("pagecache_evict", "t7_buffered_evict_bw", None, None),
        ("slc_probe", "t2_probe_mean_MBps", None, None),
    ]
    for vendor, metrics in data.items():
        for scenario, bw_key, iops_key, lat_key in metric_map:
            bw = metrics.get(bw_key) if bw_key else None
            rows.append({
                "category": "SSD characterization",
                "family": "cross_vendor",
                "source_kind": "compiled_json",
                "test_id": f"{vendor}_{scenario}",
                "vendor": VENDOR_LABELS.get(vendor, vendor),
                "scenario": scenario,
                "read_bw_gbps": bw / 1024 if bw and "write" not in scenario else "",
                "write_bw_gbps": bw / 1024 if bw and "write" in scenario else "",
                "read_iops": metrics.get(iops_key) if iops_key and "read" in scenario else "",
                "write_iops": metrics.get(iops_key) if iops_key and "write" in scenario else "",
                "read_dev_p95_ms": (metrics.get(lat_key) / 1000) if lat_key and metrics.get(lat_key) and "write" not in scenario else "",
                "write_dev_p95_ms": (metrics.get(lat_key) / 1000) if lat_key and metrics.get(lat_key) and "write" in scenario else "",
                "source": rel(path),
            })
    return rows


def collect_mlperf_summary() -> list[dict[str, Any]]:
    path = REPO / "results/cross_vendor/mlperf_summary.csv"
    rows = []
    for r in read_csv(path):
        rows.append({
            "category": "Checkpointing",
            "family": "cross_vendor",
            "source_kind": "mlperf_summary_csv",
            "test_id": f"{r.get('vendor')}_{r.get('model')}",
            "vendor": VENDOR_LABELS.get(r.get("vendor", ""), r.get("vendor", "")),
            "model": r.get("model"),
            "scenario": "save_load",
            "read_bw_gbps": as_float(r.get("load_throughput_gibs")) * 8 if as_float(r.get("load_throughput_gibs")) is not None else "",
            "write_bw_gbps": as_float(r.get("save_throughput_gibs")) * 8 if as_float(r.get("save_throughput_gibs")) is not None else "",
            "duration_s": r.get("save_duration_s"),
            "note": f"load_duration_s={r.get('load_duration_s')}; mount={r.get('mount')}",
            "source": rel(path),
        })
    return rows


def collect_markdown_highlights() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    docs = {
        "tests/Flux_test_results.md": "Flux training",
        "tests/DLRM_test_results.md": "DLRM training",
        "tests/RetinaNet_test_results.md": "RetinaNet training",
        "tests/Checkpoint_test_results.md": "Checkpointing",
        "docs/DLRM_NP_Scaling_Results.md": "DLRM NP scaling",
        "docs/UNet3D_NP_Scaling_Results.md": "UNet3D NP scaling",
        "docs/RetinaNet_NP_Scaling_Results.md": "RetinaNet NP scaling",
        "docs/Flux_NP_ReadThreads_Scaling_Results.md": "Flux NP/read_threads scaling",
        "docs/Object_Storage_Test_Results.md": "Object storage library",
    }
    for name, family in docs.items():
        path = REPO / name
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        for match in re.finditer(r"\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|", text):
            left = match.group(1).strip(" *`")
            right = match.group(2).strip(" *`")
            if left.lower() in {"metric", "parameter", "field", "test", "---", "-------"}:
                continue
            if any(k in left.lower() for k in ["accelerator utilization", "training throughput", "i/o throughput", "write throughput", "read throughput", "au%", "samples/s", "derived io", "duration"]):
                rows.append({
                    "category": "Markdown reported result",
                    "family": family,
                    "source_kind": "markdown_table_metric",
                    "test_id": f"{family}:{left}",
                    "scenario": left,
                    "note": right,
                    "source": rel(path),
                })
    return rows


def collect_iostat_analysis() -> list[dict[str, Any]]:
    path = REPO / "results/cross_vendor/kv_cache_k4_gc_drift/_analysis/iostat_analysis.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    rows = []
    for disk, r in data.items():
        rows.append({
            "disk": VENDOR_LABELS.get(disk, disk),
            "samples": r.get("samples"),
            "cliff_s": r.get("cliff_s"),
            "cliff_min": (r.get("cliff_s") or 0) / 60 if r.get("cliff_s") else "",
            "read_req_median_kb": get_path(r, "rareq_sz", "rareq_median"),
            "read_req_p99_kb": get_path(r, "rareq_sz", "rareq_p99"),
            "write_req_median_kb": get_path(r, "wareq_sz", "wareq_median"),
            "write_req_p99_kb": get_path(r, "wareq_sz", "wareq_p99"),
            "rrqm_median_pct": get_path(r, "pct_rrqm", "pct_rrqm_median"),
            "rrqm_p99_pct": get_path(r, "pct_rrqm", "pct_rrqm_p99"),
            "wrqm_median_pct": get_path(r, "pct_wrqm", "pct_wrqm_median"),
            "wrqm_p99_pct": get_path(r, "pct_wrqm", "pct_wrqm_p99"),
            "r_await_median_ms": get_path(r, "r_await", "r_await_median"),
            "r_await_p99_ms": get_path(r, "r_await", "r_await_p99"),
            "w_await_median_ms": get_path(r, "w_await", "w_await_median"),
            "w_await_p99_ms": get_path(r, "w_await", "w_await_p99"),
            "aqu_median": get_path(r, "aqu_sz", "aqu_median"),
            "aqu_p95": get_path(r, "aqu_sz", "aqu_p95"),
            "aqu_p99": get_path(r, "aqu_sz", "aqu_p99"),
            "r_bw_first_mb_s": r.get("r_bw_first_5min"),
            "r_bw_last_mb_s": r.get("r_bw_last_5min"),
            "w_bw_first_mb_s": r.get("w_bw_first_5min"),
            "w_bw_last_mb_s": r.get("w_bw_last_5min"),
            "source": rel(path),
        })
    return rows


def collect_profile_csv() -> list[dict[str, Any]]:
    rows = []
    for path in [
        REPO / "docs/assets/kvcache-io-profiling/io_profile_summary.csv",
        REPO / "results/kvcache-profile/visualizations/io_profile_summary.csv",
    ]:
        for r in read_csv(path):
            row = dict(r)
            row["source"] = rel(path)
            rows.append(row)
    # Deduplicate by file name, keeping docs copy first.
    out = {}
    for row in rows:
        key = row.get("file") or f"{row.get('group')}:{row.get('case')}"
        out.setdefault(key, row)
    return list(out.values())


def plot_charts(master: list[dict[str, Any]], io_rows: list[dict[str, Any]], profile_rows: list[dict[str, Any]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({
        "figure.dpi": 120,
        "savefig.dpi": 160,
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
    })
    made: list[Path] = []

    # Chart 1: K4/K5 and long-run read bandwidth.
    kv = [r for r in master if r.get("category") == "KV Cache" and r.get("vendor")]
    scenarios = ["K4", "K5"]
    vendors = ["Biwin X570", "Seagate FC530", "ZhiTai Ti600", "WD SN570"]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    x = np.arange(len(vendors))
    width = 0.22
    labels = [
        ("K4 16u 8B 120s", lambda r: r.get("family") in {"kv_cache", "kv_cache_k4_only"} and str(r.get("scenario")).startswith("K4") and str(r.get("duration_s")).startswith("12")),
        ("K4 16u 8B 1200s", lambda r: r.get("family") == "kv_cache_k4_gc_drift"),
        ("K5 4u 70B 180s", lambda r: r.get("family") in {"kv_cache", "kv_cache_k5_only"} and str(r.get("scenario")).startswith("K5")),
    ]
    colors = ["#4c78a8", "#f58518", "#54a24b"]
    for j, (label, pred) in enumerate(labels):
        vals = []
        for vendor in vendors:
            candidates = [r for r in kv if r.get("vendor") == vendor and pred(r)]
            vals.append(max([as_float(r.get("read_bw_gbps")) or 0 for r in candidates] or [0]))
        bars = ax.bar(x + (j - 1) * width, vals, width, label=label, color=colors[j])
        for b in bars:
            if b.get_height() > 0:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{b.get_height():.1f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(vendors, rotation=12, ha="right")
    ax.set_ylabel("Read bandwidth (GB/s)")
    ax.set_title("KV cache cross-vendor read bandwidth")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "01_kvcache_read_bw_summary.png"
    fig.savefig(p)
    plt.close(fig)
    made.append(p)

    # Chart 2: IO randomness and service time.
    if io_rows:
        vendors_io = [r["disk"] for r in io_rows]
        read_req = [as_float(r.get("read_req_median_kb")) or 0 for r in io_rows]
        write_req = [as_float(r.get("write_req_median_kb")) or 0 for r in io_rows]
        r_await = [as_float(r.get("r_await_p99_ms")) or 0 for r in io_rows]
        w_await = [as_float(r.get("w_await_p99_ms")) or 0 for r in io_rows]
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        xi = np.arange(len(vendors_io))
        axes[0].bar(xi - 0.18, read_req, 0.36, label="read req median", color="#4c78a8")
        axes[0].bar(xi + 0.18, write_req, 0.36, label="write req median", color="#f58518")
        axes[0].set_xticks(xi)
        axes[0].set_xticklabels(vendors_io, rotation=15, ha="right")
        axes[0].set_ylabel("Request size (kB)")
        axes[0].set_title("KV request size is application-locked")
        axes[0].legend()
        axes[1].bar(xi - 0.18, r_await, 0.36, label="read await p99", color="#4c78a8")
        axes[1].bar(xi + 0.18, w_await, 0.36, label="write await p99", color="#e45756")
        axes[1].set_yscale("log")
        axes[1].set_xticks(xi)
        axes[1].set_xticklabels(vendors_io, rotation=15, ha="right")
        axes[1].set_ylabel("Device service time p99 (ms, log)")
        axes[1].set_title("Controller behavior separates drives")
        axes[1].legend()
        fig.tight_layout()
        p = out_dir / "02_io_pattern_randomness_summary.png"
        fig.savefig(p)
        plt.close(fig)
        made.append(p)

    # Chart 3: Profile workload storage p95 by users.
    prof = []
    for r in profile_rows:
        users = as_float(r.get("users"))
        read_p95 = as_float(r.get("read_dev_p95_ms"))
        write_p95 = as_float(r.get("write_dev_p95_ms"))
        case = r.get("case", "")
        if users and (read_p95 or write_p95) and "trace-mode" not in case:
            prof.append((str(r.get("group")), case, users, read_p95, write_p95))
    if prof:
        prof = sorted(prof, key=lambda x: (x[0], x[2], x[1]))
        fig, ax = plt.subplots(figsize=(12, 6))
        labels2 = [f"{g}\n{c[:18]}" for g, c, *_ in prof[-18:]]
        xi = np.arange(len(labels2))
        ax.plot(xi, [x[3] or np.nan for x in prof[-18:]], marker="o", label="read device p95", color="#4c78a8")
        ax.plot(xi, [x[4] or np.nan for x in prof[-18:]], marker="o", label="write device p95", color="#e45756")
        ax.set_yscale("log")
        ax.set_xticks(xi)
        ax.set_xticklabels(labels2, rotation=55, ha="right", fontsize=8)
        ax.set_ylabel("Device p95 latency (ms, log)")
        ax.set_title("KV cache IO profile: hardware-backed runs")
        ax.legend()
        fig.tight_layout()
        p = out_dir / "03_profile_latency_summary.png"
        fig.savefig(p)
        plt.close(fig)
        made.append(p)

    # Chart 4: FIO preconditioning effect at QD=1024.
    fio = [r for r in master if r.get("category") == "FIO KV emulation" and str(r.get("iodepth")) == "1024"]
    workloads = sorted({str(r.get("scenario")) for r in fio})
    if workloads:
        fig, ax = plt.subplots(figsize=(10, 5.5))
        xi = np.arange(len(workloads))
        fresh = []
        pre = []
        for w in workloads:
            fresh.append(next((as_float(r.get("read_dev_p99_ms")) for r in fio if r.get("scenario") == w and r.get("family") == "fresh"), np.nan))
            pre.append(next((as_float(r.get("read_dev_p99_ms")) for r in fio if r.get("scenario") == w and r.get("family") == "preconditioned"), np.nan))
        ax.bar(xi - 0.18, fresh, 0.36, label="fresh", color="#bab0ac")
        ax.bar(xi + 0.18, pre, 0.36, label="preconditioned", color="#59a14f")
        ax.set_xticks(xi)
        ax.set_xticklabels(workloads, rotation=20, ha="right")
        ax.set_ylabel("Read p99 latency (ms)")
        ax.set_title("FIO KV emulation: preconditioning reduces deep-QD tail")
        ax.legend()
        fig.tight_layout()
        p = out_dir / "04_fio_preconditioning_qd1024.png"
        fig.savefig(p)
        plt.close(fig)
        made.append(p)

    return made


def md_table(rows: list[dict[str, Any]], cols: list[str], limit: int | None = None) -> str:
    selected = rows[:limit] if limit else rows
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in selected:
        out.append("| " + " | ".join(str(format_value(row.get(c, ""))) for c in cols) + " |")
    return "\n".join(out)


def write_doc(path: Path, master: list[dict[str, Any]], io_rows: list[dict[str, Any]], profile_rows: list[dict[str, Any]], charts: list[Path], out_dir: Path) -> None:
    kv = [r for r in master if r.get("category") == "KV Cache" and r.get("vendor")]
    fio = [r for r in master if r.get("category") == "FIO KV emulation"]
    ssd = [r for r in master if r.get("category") == "SSD characterization"]

    k4_long = [r for r in kv if r.get("family") == "kv_cache_k4_gc_drift"]
    best_long = max(k4_long, key=lambda r: as_float(r.get("read_bw_gbps")) or 0) if k4_long else {}
    best_wtail = min(io_rows, key=lambda r: as_float(r.get("w_await_p99_ms")) or float("inf")) if io_rows else {}

    lines = [
        "# 测试历史总表与 IO 重新分析",
        "",
        "**生成日期:** 2026-06-24",
        "",
        "## 产物",
        "",
        f"- 总表 CSV: `{rel(out_dir / 'test_history_master.csv')}`",
        f"- IO 明细 CSV: `{rel(out_dir / 'io_analysis_summary.csv')}`",
        f"- KV profile 去重 CSV: `{rel(out_dir / 'io_profile_runs.csv')}`",
        f"- Excel 工作簿: `{rel(out_dir / 'test_history_master.xlsx')}`",
        "",
        "## 总览",
        "",
        f"- 总表共收录 **{len(master)}** 行历史结果，覆盖 KV cache、FIO KV 仿真、SSD 跨盘表征、checkpoint、训练/object-store Markdown 报告摘要。",
        f"- 结构化 KV cache 结果 **{len(kv)}** 行；FIO KV 仿真 **{len(fio)}** 行；SSD 表征 **{len(ssd)}** 行。",
        f"- K4 16-user 1200s 长稳态中，按 KV summary 的应用层 storage read bandwidth 最高的是 **{best_long.get('vendor', '')}**（{format_value(best_long.get('read_bw_gbps'))} GB/s）。",
        f"- 设备侧写入 p99 最好的是 **{best_wtail.get('disk', '')}**（w_await p99={format_value(best_wtail.get('w_await_p99_ms'))} ms）。",
        "",
        "## 重画图",
        "",
    ]
    for chart in charts:
        lines.append(f"![{chart.stem}]({rel(chart).replace('docs/', '') if rel(chart).startswith('docs/') else rel(chart)})")
        lines.append("")

    lines.extend([
        "## IO 重新总结",
        "",
        "KV cache offload 的块设备行为不是顺序流式读写，而是 **约 115-125 kB 的稀疏大块随机 IO**。判断依据是 `%rrqm` 中位数为 0，读请求大小在四块盘上几乎一致，说明请求形状由 KV entry 大小决定，而不是由 SSD 决定。",
        "",
        "真正拉开差距的是设备如何处理随机写和深队列：Seagate FC530 的写 p99 明显低，队列深度也更浅；Biwin X570 峰值读带宽强，但 GC cliff 来得早；ZhiTai Ti600 和 WD SN570 在长稳态中队列堆积和写尾延迟更明显。",
        "",
        "下面的 `*_mb_s` 来自 `iostat -dx -m`，单位是 MB/s；KV summary 表中的 `read_bw_gbps/write_bw_gbps` 来自 benchmark summary，口径是应用层 storage bandwidth。",
        "",
        "### K4 GC-drift IO 指标",
        "",
        md_table(io_rows, ["disk", "cliff_min", "read_req_median_kb", "write_req_median_kb", "rrqm_median_pct", "r_await_p99_ms", "w_await_p99_ms", "aqu_p99"]),
        "",
        "### 代表性 KV cache 长稳态",
        "",
        md_table(sorted(k4_long, key=lambda r: as_float(r.get("read_bw_gbps")) or 0, reverse=True), ["vendor", "scenario", "model", "users", "duration_s", "read_bw_gbps", "write_bw_gbps", "read_dev_p99_ms", "write_dev_p99_ms", "status"]),
        "",
        "### FIO QD=1024 preconditioning 对比",
        "",
        md_table([r for r in fio if str(r.get("iodepth")) == "1024"], ["family", "scenario", "read_mix_pct", "read_bw_gbps", "write_bw_gbps", "read_dev_p99_ms", "write_dev_p99_ms"]),
        "",
        "## 结合真实 LMCache / SGLang HiCache 预研的补充结论",
        "",
        "参考 `/home/ficus/llm/infer/ai_ssd_prestudy` 中的 `AI_SSD_BOSS_REPORT.md`、`REPORT.md`、`REPORT_LMCACHE.md`、`reports/ai-ssd-real-offloading-investigation-report-2026-06-17.md` 和 `docs/p5-hicache-write-policy.md`，这里的 KV cache 模拟测试应被定位为 **storage microbenchmark / trace replay**，而不是完整替代真实 LMCache 或 SGLang HiCache 端到端测试。",
        "",
        "### 1. 模拟测试回答的是“盘能不能扛住 KV-like IO”",
        "",
        "本仓库的 `kv-cache.py` / FIO / iostat 数据把复杂 serving 系统拆开，重点压测 SSD 面对 KV-cache-like large-block random IO 时的能力：读写带宽、p95/p99、队列深度、GC cliff、preconditioning 效果。它适合做盘型筛选和控制器行为分析。",
        "",
        "但真实 LMCache / HiCache 端到端还包含 prefix lookup、GPU/CPU/L3 分层命中、prefetch、write-through/write-back、eviction、文件系统、page cache、pin_memory L2、推理 scheduler 等因素。真实用户感知的 TTFT/ITL 不等于裸盘 IO 数字。",
        "",
        "### 2. LMCache 证明“缓存机制有价值”，但不直接给盘型排名",
        "",
        "`REPORT_LMCACHE.md` 中 7000-token prompt 的早期 LMCache 测试显示：cold TTFT 约 0.779s，warm TTFT 约 0.034-0.035s，加速约 22-23x；单请求约 0.95GB KV chunk 落盘。这说明 KV cache offload / external prefix cache 方向成立。",
        "",
        "同时该报告也说明：LMCache 默认有 local CPU tier，warm 请求可能优先命中 CPU L1，而不是每次都从 SSD reload。因此 LMCache 单 prompt cold/warm 测试更适合证明缓存机制收益，不适合直接作为 AI SSD 盘型排名。要比较盘，必须强制 L2 miss / cold-from-device，并用 iostat/bpftrace 验证目标盘真有读写。",
        "",
        "### 3. HiCache 证明“盘差只在 L3 reload 暴露”",
        "",
        "`REPORT.md` 和 Boss 报告的核心结论是：常规 cold/warm 或 L2 host DRAM 命中时，4 盘 TTFT spread 只有毫秒级；只有多 prompt 填满 L2、回放早期 prompt 触发 L2 miss / L3 reload 时，盘差才明显。",
        "",
        "Phase7 v3 中，20 prompts × 7K tokens 后 replay p0 的 L3 reload 结果约为：BIWIN 1.66s，Seagate 2.43s，ZhiTai 2.55s，WDC 2.64s，spread 约 980ms / 1.59x。这个结论比单轮 cold/warm 更接近 AI SSD 选型问题：**真正关键的是 L3 reload latency 和稳定性，而不是普通缓存命中路径。**",
        "",
        "### 4. 真实框架会强烈改变 SSD 可见 IO",
        "",
        "HiCache 预研发现几个会改变结论的工程因素：",
        "",
        "- `drop_caches` 清 OS page cache，但不清 SGLang pin_memory 自管 L2；所以只看 drop_caches 后 warm TTFT 可能仍是 L2 hit。",
        "- `write_through`、`write_back`、`write_through_selective` 改变 prefill 是否被写盘阻塞，也改变 OOM 风险。",
        "- `write_back` 平均冷启动 TTFT 低约 31ms / 2.2%，但 WDC/ZhiTai 这类慢盘在 20 prompt async flush 下出现 OOM。",
        "- `write_through_selective` 虽然少写盘，但在 NTFS 上可能因为碎片化读取更慢，WDC 上 replay 比 write_through 慢约 22%。",
        "- 文件系统和挂载路径很关键；ext4、NTFS、系统盘 page cache、mount 误配都会掩盖或扭曲盘差。",
        "",
        "因此，模拟测试里的“Seagate 写尾延迟最好 / Biwin 短 burst 强 / ZhiTai 和 WD 长稳态风险大”应该作为底层盘能力判断；真实部署时还要叠加 framework policy 和 cache hierarchy 的行为。",
        "",
        "### 5. 推荐的证据链",
        "",
        "后续做 AI SSD 结论时，建议把三类测试串起来，而不是互相替代：",
        "",
        "| 层级 | 工具 | 回答的问题 | 不能回答的问题 |",
        "| --- | --- | --- | --- |",
        "| SSD 微基准 | fio / direct IO | 盘的顺序、随机、precondition、SLC/GC 上限 | 真实 KV cache 命中和调度 |",
        "| KV-like trace replay | `kv-cache.py` + iostat/bpftrace | 盘面对 KV-like 大块随机 IO 的 p99、GC cliff、跨盘差异 | LMCache/HiCache 的真实 TTFT 收益 |",
        "| 真实系统 | LMCache / SGLang HiCache | cache 命中、L2 miss、L3 reload、write policy 对 TTFT 的影响 | 单独隔离 SSD 控制器能力较难 |",
        "",
        "最小闭环应同时满足：1) multiprompt 或容量压力触发 L2 miss；2) iostat 目标盘 `rMB/s/wMB/s` 明确非零；3) 记录 TTFT/ITL 与 block IO p95/p99；4) 分离 page cache hit 与 cold-from-device；5) 至少跑 20-30 分钟长稳态观察 GC cliff。",
        "",
        "## 结合生产 KVCache 架构的修正",
        "",
        "阿里云 Tair KVCache 的两篇生产环境文章把这个问题进一步拉到分布式系统层面：",
        "",
        "- [3FS 工程化落地 KVCache](https://developer.aliyun.com/article/1695651)：生产 L3 KVCache 不是单机 SSD 目录，而是面向长上下文、多轮对话/RAG、高并发低延迟 SLA 的共享存储底座。文章给出的典型特征是单次推理 KVCache 可达 GB 到数十 GB，读写比通常大于 10:1，写多为顺序追加，读多为随机跳转/检索，端到端 P99 目标可到 50ms 甚至 10ms 级，并要求节点级带宽能力。",
        "- [Tair KVCache-HiSim](https://developer.aliyun.com/article/1704428)：生产优化不能只靠真实集群压测，需要能建模请求生命周期、调度、prefill/decode、L3→L2 预取、L2→L1 加载、缓存命中/驱逐和 SLO 约束的仿真器。文章强调 KVCache 已从“显存内缓存”升级为可存储、可共享、可调度的系统级状态管理。",
        "",
        "更完整的文章解读见 [阿里云 Tair KVCache 两篇文章解读](aliyun-tair-kvcache-articles-interpretation-2026-06-24-zh.md)。",
        "",
        "这对本预研有三点修正。",
        "",
        "### 1. AI SSD 不是孤立硬件，而是 L3 KVCache 底座的一层",
        "",
        "本预研中的本地 SSD 测试仍然必要，因为它揭示了单盘控制器在 KV-like large-block random IO 下的 p99、GC cliff 和写尾延迟。但生产环境更关心的是 **L3 层整体服务能力**：容量池化、跨节点读写、故障切换、负载均衡、租户隔离、监控运维和成本。阿里云 3FS 方案中的 RDMA、USRBIO、CRAQ 读任一副本、GDR 零拷贝、Kubernetes Operator 等能力，说明最终产品形态更像“KVCache storage appliance / service”，不是单块消费级 NVMe。",
        "",
        "### 2. 我们的 block IO 结论和生产特征一致，但粒度要扩展",
        "",
        "阿里云文章明确生产 KVCache 是读多写少，读多为随机，写多为追加；这和我们在 `kv-cache.py` / iostat 中看到的 **约 115-125 kB 大块随机读写、读写比约 9-12:1、%rrqm≈0** 是一致的。差别在于生产系统还会把这个模式叠加到分布式文件、RDMA 网络、元数据服务、复制协议和调度策略上。因此后续报告不应只写“SSD 随机读写性能”，而应写成：**AI SSD 需要在 KVCache L3 服务中稳定提供随机读尾延迟、追加写吸收能力和长稳态 GC 可控性。**",
        "",
        "### 3. 选型指标要从“盘排名”升级为“SLO 下的容量-延迟-成本前沿”",
        "",
        "HiSim 文章强调在 SLO 约束下搜索时延、吞吐、成本的 Pareto frontier。对应到本预研，单盘排名只能回答局部问题；更完整的选型应给出在目标 TTFT/TPOT/P99 下，GPU HBM、Host DRAM、local SSD、remote KVCache/3FS 各层容量和带宽如何配置。也就是说，AI SSD 报告的下一版应从“哪块盘最快”升级为“在特定业务 workload 和 SLO 下，哪种分层配置最省钱且足够快”。",
        "",
        "### 对现有结论的更新",
        "",
        "| 原结论 | 生产 KVCache 修正后 |",
        "| --- | --- |",
        "| 看 SSD 顺序/随机性能 | 继续看，但要把读多写少、随机读取、追加写和长稳态 GC 纳入同一模型 |",
        "| 看 LMCache/HiCache 端到端 TTFT | 继续看，但必须记录 L3→L2 预取是否隐藏 IO，以及调度策略是否等待 cache ready |",
        "| 看单盘 4 盘排名 | 扩展为本地 SSD、远程 3FS/RDMA、CPU DRAM、GPU HBM 的层级配置比较 |",
        "| 用 fio/kv-cache.py 做复现 | 作为组件级校验；还需要 HiSim 类仿真，把真实 workload trace、SLO、驱逐/TTL/预取策略放进去 |",
        "| AI SSD 是高性能硬盘 | 更准确地说，AI SSD 是生产 KVCache L3 的硬件组件，需要和文件系统、RDMA/GDR、调度和运维体系一起定义 |",
        "",
        "### 下一步建议",
        "",
        "1. **增加 production trace 维度**：采集或构造多轮对话/RAG/agent workload，包含 prefix 复用率、上下文长度、并发、TTL、eviction 分布。",
        "2. **补 L3 service 模型**：在本地 SSD 之外，加入 remote KVCache / 3FS-like 参数：网络 RTT、RDMA 带宽、复制因子、metadata 开销、GDR/zero-copy 开关。",
        "3. **把指标改成 SLO-driven**：用 TTFT p95/p99、TPOT p95/p99、cache hit rate、L3 reload p99、$/1M tokens，而不是单独的 GB/s 排名。",
        "4. **保留组件级长稳态**：继续跑 20-30 分钟以上 GC cliff、preconditioning、write-back 压力，因为生产 L3 的尾延迟最终仍会落到 SSD 控制器和 NAND 稳态能力上。",
        "5. **验证预取是否真的隐藏 IO**：对比 `best_effort / wait_complete / timeout` 等策略下，L3→L2 预取窗口、队列等待和实际 TTFT/TPOT 的关系。",
        "",
        "## 结论",
        "",
        "1. **AI SSD 选择不能只看顺序带宽。** KV cache 的关键指标是随机大块读写下的 p99/p999、队列深度和 GC cliff 后的稳态带宽。",
        "2. **短 burst 与长稳态结论不同。** Biwin X570 的短时读带宽很强；长会话/持续 eviction 更看重 Seagate FC530 的写尾延迟和 cliff 延后能力。",
        "3. **preconditioning 后深队列尾延迟改善明显。** QD=1024 下多个 workload 的读/写 p99 都下降，说明 fresh-device 数据会高估实际部署风险或低估稳态差异，具体取决于测试目标。",
        "4. **训练/object-store 历史结果仍需保留但不应混入块设备 IO 结论。** 那些结果更多反映 s3dlio、loopback/s3-ultra、DLIO 参数和 co-located 资源竞争；本次总表把来源分开，便于后续按类别过滤。",
        "",
        "## 来源说明",
        "",
        "本报告优先使用 JSON/CSV 结构化结果；Markdown 历史报告仅抽取明确表格项作为补充，不从自由文本中推断新数值。",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def maybe_write_xlsx(path: Path, sheets: dict[str, list[dict[str, Any]]]) -> None:
    try:
        import pandas as pd
    except Exception:
        return
    with pd.ExcelWriter(path) as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name[:31], index=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    ap.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.assets_dir.mkdir(parents=True, exist_ok=True)

    master: list[dict[str, Any]] = []
    master.extend(collect_cross_vendor_kv())
    master.extend(collect_profile_json())
    master.extend(collect_fio())
    master.extend(collect_ssd_characterization())
    master.extend(collect_mlperf_summary())
    master.extend(collect_markdown_highlights())

    io_rows = collect_iostat_analysis()
    profile_rows = collect_profile_csv()

    master_cols = [
        "category", "family", "source_kind", "test_id", "vendor", "scenario", "model",
        "users", "iodepth", "read_mix_pct", "duration_s", "status", "passed",
        "requests", "tokens", "tok_s", "req_s", "cache_hit_pct", "e2e_p95_ms",
        "io_p95_ms", "read_p95_ms", "read_p99_ms", "write_p95_ms", "write_p99_ms",
        "read_dev_p95_ms", "read_dev_p99_ms", "write_dev_p95_ms", "write_dev_p99_ms",
        "read_bw_gbps", "write_bw_gbps", "read_iops", "write_iops",
        "total_read_gb", "total_write_gb", "prefill_writes", "decode_reads", "note", "source",
    ]
    io_cols = [
        "disk", "samples", "cliff_s", "cliff_min", "read_req_median_kb", "read_req_p99_kb",
        "write_req_median_kb", "write_req_p99_kb", "rrqm_median_pct", "rrqm_p99_pct",
        "wrqm_median_pct", "wrqm_p99_pct", "r_await_median_ms", "r_await_p99_ms",
        "w_await_median_ms", "w_await_p99_ms", "aqu_median", "aqu_p95", "aqu_p99",
        "r_bw_first_mb_s", "r_bw_last_mb_s", "w_bw_first_mb_s", "w_bw_last_mb_s", "source",
    ]

    write_csv(args.out_dir / "test_history_master.csv", master, master_cols)
    write_csv(args.out_dir / "io_analysis_summary.csv", io_rows, io_cols)
    write_csv(args.out_dir / "io_profile_runs.csv", profile_rows, [])
    maybe_write_xlsx(args.out_dir / "test_history_master.xlsx", {
        "master": master,
        "io_analysis": io_rows,
        "io_profile_runs": profile_rows,
    })

    charts = plot_charts(master, io_rows, profile_rows, args.assets_dir)
    write_doc(args.doc, master, io_rows, profile_rows, charts, args.out_dir)

    print(f"master_rows={len(master)}")
    print(f"io_rows={len(io_rows)}")
    print(f"profile_rows={len(profile_rows)}")
    print(f"charts={len(charts)}")
    print(f"wrote={args.out_dir / 'test_history_master.csv'}")
    print(f"wrote={args.doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
